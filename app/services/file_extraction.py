import io
import json
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import anyio
import fitz
import pandas as pd
from redis.asyncio import Redis

from app.core.azure_openai import AzureOpenAIClient
from app.core.config import Settings


@dataclass
class FileExtractionResult:
    blob_ref: str
    filename: str
    content_type: str
    text: str
    truncated: bool
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None
    cached: bool = False
    cache_truncated: bool = False
    original_length: Optional[int] = None
    cached_at: Optional[str] = None


@dataclass
class FileContext:
    context_text: str
    summaries: List[Dict[str, Any]]


class FileExtractionService:
    def __init__(self, settings: Settings, azure_openai: Optional[AzureOpenAIClient]) -> None:
        self._settings = settings
        self._azure_openai = azure_openai

    async def build_file_context(
        self,
        uploaded_files: List[str],
        redis_client: Optional[Redis] = None,
    ) -> FileContext:
        if not uploaded_files:
            return FileContext(context_text="", summaries=[])

        results: List[Optional[FileExtractionResult]] = [None] * len(uploaded_files)

        async def worker(index: int, blob_ref: str) -> None:
            cached_result = await self._load_cached(redis_client, blob_ref)
            if cached_result:
                results[index] = cached_result
                return
            result = await self._process_blob(blob_ref)
            results[index] = result
            await self._store_cached(redis_client, blob_ref, result)

        async with anyio.create_task_group() as task_group:
            for index, blob_ref in enumerate(uploaded_files):
                task_group.start_soon(worker, index, blob_ref)

        resolved_results: List[FileExtractionResult] = [
            result for result in results if result is not None
        ]

        context_text = self._assemble_context(resolved_results)
        summaries = [
            {
                "blob_ref": result.blob_ref,
                "filename": result.filename,
                "content_type": result.content_type,
                "truncated": result.truncated,
                "notes": result.notes,
                "error": result.error,
                "cached": result.cached,
                "cache_truncated": result.cache_truncated,
                "original_length": result.original_length,
                "cached_at": result.cached_at,
            }
            for result in resolved_results
        ]
        return FileContext(context_text=context_text, summaries=summaries)

    async def _process_blob(self, blob_ref: str) -> FileExtractionResult:
        try:
            data, filename, content_type = await anyio.to_thread.run_sync(
                self._download_blob, blob_ref
            )
            text, truncated, notes = await self._extract_text(
                data=data, filename=filename, content_type=content_type
            )
            return FileExtractionResult(
                blob_ref=blob_ref,
                filename=filename,
                content_type=content_type,
                text=text,
                truncated=truncated,
                notes=notes,
            )
        except Exception as exc:  # noqa: BLE001 - capture extraction failures
            return FileExtractionResult(
                blob_ref=blob_ref,
                filename=blob_ref.split("/")[-1],
                content_type="unknown",
                text="",
                truncated=False,
                notes=[],
                error=str(exc),
            )

    def _download_blob(self, blob_ref: str) -> Tuple[bytes, str, str]:
        if blob_ref.startswith(("http://", "https://")):
            raise RuntimeError(
                "Remote blob references are disabled. "
                "Provide a file:// path or ensure the extracted content is cached in Redis."
            )

        path = blob_ref
        if blob_ref.startswith("file://"):
            path = blob_ref[len("file://") :]

        with open(path, "rb") as handle:
            data = handle.read()
        content_type, _ = mimetypes.guess_type(path)
        return data, path.split("/")[-1], content_type or "application/octet-stream"

    def _cache_key(self, blob_ref: str) -> str:
        key_source = blob_ref
        if blob_ref.startswith("https://"):
            parts = urlsplit(blob_ref)
            key_source = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        elif blob_ref.startswith("file://"):
            key_source = blob_ref[len("file://") :]
        digest = sha256(key_source.encode("utf-8")).hexdigest()
        return f"planner:file:{digest}"

    async def _load_cached(
        self, redis_client: Optional[Redis], blob_ref: str
    ) -> Optional[FileExtractionResult]:
        if not redis_client or not self._settings.redis_file_cache_enabled:
            return None
        key = self._cache_key(blob_ref)
        cached_raw = await redis_client.get(key)
        if not cached_raw:
            return None
        try:
            payload = json.loads(cached_raw)
        except json.JSONDecodeError:
            return None

        notes = payload.get("notes") or []
        cache_truncated = bool(payload.get("cache_truncated"))
        if cache_truncated:
            max_chars = payload.get("cache_max_chars")
            notes = list(notes) + [f"Cached content truncated to {max_chars} characters."]

        return FileExtractionResult(
            blob_ref=payload.get("blob_ref", blob_ref),
            filename=payload.get("filename", blob_ref.split("/")[-1]),
            content_type=payload.get("content_type", "unknown"),
            text=payload.get("text", ""),
            truncated=bool(payload.get("truncated", False)),
            notes=notes,
            error=payload.get("error"),
            cached=True,
            cache_truncated=cache_truncated,
            original_length=payload.get("original_length"),
            cached_at=payload.get("cached_at"),
        )

    async def _store_cached(
        self,
        redis_client: Optional[Redis],
        blob_ref: str,
        result: FileExtractionResult,
    ) -> None:
        if not redis_client or not self._settings.redis_file_cache_enabled:
            return
        if result.error:
            return

        cache_max_chars = self._settings.redis_file_cache_max_chars
        cache_truncated = False
        original_length = len(result.text)
        cache_text = result.text
        if cache_max_chars > 0 and original_length > cache_max_chars:
            cache_text = result.text[:cache_max_chars]
            cache_truncated = True

        payload = {
            "blob_ref": blob_ref,
            "filename": result.filename,
            "content_type": result.content_type,
            "text": cache_text,
            "truncated": result.truncated,
            "notes": result.notes,
            "error": result.error,
            "cache_truncated": cache_truncated,
            "cache_max_chars": cache_max_chars,
            "original_length": original_length,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        }
        key = self._cache_key(blob_ref)
        ttl_seconds = self._settings.redis_file_cache_ttl_seconds
        if ttl_seconds and ttl_seconds > 0:
            await redis_client.setex(key, ttl_seconds, json.dumps(payload))
        else:
            await redis_client.set(key, json.dumps(payload))

    async def _extract_text(
        self, data: bytes, filename: str, content_type: str
    ) -> Tuple[str, bool, List[str]]:
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        notes: List[str] = []
        truncated = False

        if ext in {"csv"}:
            text, truncated = await anyio.to_thread.run_sync(self._extract_table, data, "csv")
            return text, truncated, notes
        if ext in {"xlsx", "xls"}:
            text, truncated = await anyio.to_thread.run_sync(self._extract_table, data, "excel")
            return text, truncated, notes
        if ext in {"txt", "md", "log", "json"}:
            text = await anyio.to_thread.run_sync(self._decode_text, data)
            return text, False, notes
        if ext in {"pdf"} or content_type == "application/pdf":
            text, ocr_used = await self._extract_pdf_text(data)
            if ocr_used:
                notes.append("OCR used for scanned PDF pages.")
            return text, False, notes
        if ext in {"png", "jpg", "jpeg"} or content_type.startswith("image/"):
            text = await self._extract_image_text(data, content_type)
            notes.append("OCR used for image.")
            return text, False, notes

        try:
            text = await anyio.to_thread.run_sync(self._decode_text, data)
            return text, False, notes
        except UnicodeDecodeError:
            notes.append("Binary file could not be decoded.")
            return "", False, notes

    def _extract_table(self, data: bytes, file_type: str) -> Tuple[str, bool]:
        max_rows = self._settings.max_file_rows
        truncated = False
        buffer = io.BytesIO(data)
        if file_type == "csv":
            frame = pd.read_csv(buffer)
        else:
            frame = pd.read_excel(buffer)
        if len(frame) > max_rows:
            frame = frame.head(max_rows)
            truncated = True
        return frame.to_csv(index=False), truncated

    async def _extract_pdf_text(self, data: bytes) -> Tuple[str, bool]:
        ocr_enabled = bool(
            self._azure_openai and self._settings.azure_openai_vision_deployment
        )
        combined, ocr_images = await anyio.to_thread.run_sync(
            self._extract_pdf_sync,
            data,
            self._settings.min_pdf_text_chars,
            ocr_enabled,
            self._settings.max_ocr_pages,
        )

        ocr_used = False
        if ocr_images and self._azure_openai:
            ocr_chunks: List[str] = []
            for image_bytes in ocr_images:
                ocr_text = await self._azure_openai.vision_ocr(image_bytes, "image/png")
                if ocr_text:
                    ocr_chunks.append(ocr_text)
            if ocr_chunks:
                ocr_used = True
                combined = "\n".join([combined, "\n".join(ocr_chunks)]).strip()

        return combined, ocr_used

    async def _extract_image_text(self, data: bytes, content_type: str) -> str:
        if not self._azure_openai:
            raise RuntimeError("Azure OpenAI client is not configured for OCR.")
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return await self._azure_openai.vision_ocr(data, content_type)

    @staticmethod
    def _extract_pdf_sync(
        data: bytes,
        min_chars: int,
        ocr_enabled: bool,
        max_pages: int,
    ) -> Tuple[str, List[bytes]]:
        text_chunks: List[str] = []
        ocr_images: List[bytes] = []
        doc = fitz.open(stream=data, filetype="pdf")
        for page in doc:
            page_text = page.get_text("text")
            if page_text:
                text_chunks.append(page_text)
        combined = "\n".join(text_chunks).strip()

        if ocr_enabled and len(combined) < min_chars:
            page_count = min(max_pages, doc.page_count)
            for page_index in range(page_count):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(dpi=200)
                ocr_images.append(pix.tobytes("png"))
        doc.close()
        return combined, ocr_images

    @staticmethod
    def _decode_text(data: bytes) -> str:
        return data.decode("utf-8", errors="replace")

    def _assemble_context(self, results: List[FileExtractionResult]) -> str:
        chunks: List[str] = []
        for result in results:
            header = f"File: {result.filename} ({result.content_type})"
            chunks.append(header)
            if result.error:
                chunks.append(f"[Extraction error] {result.error}")
            else:
                chunks.append(result.text.strip() or "[No extractable text]")
            if result.truncated:
                chunks.append("[Truncated to max row limit]")
            if result.notes:
                chunks.append(f"[Notes] {'; '.join(result.notes)}")
            chunks.append("---")

        combined = "\n".join(chunks).strip()
        max_chars = self._settings.max_file_context_chars
        if len(combined) > max_chars:
            return combined[:max_chars] + "\n[File context truncated]"
        return combined
