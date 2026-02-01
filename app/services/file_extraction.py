import io
import mimetypes
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import anyio
import fitz
import pandas as pd
from azure.storage.blob import BlobClient, BlobServiceClient

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


@dataclass
class FileContext:
    context_text: str
    summaries: List[Dict[str, Any]]


class FileExtractionService:
    def __init__(self, settings: Settings, azure_openai: Optional[AzureOpenAIClient]) -> None:
        self._settings = settings
        self._azure_openai = azure_openai
        self._blob_service_client: Optional[BlobServiceClient] = None
        if settings.azure_blob_connection_string:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                settings.azure_blob_connection_string
            )

    async def build_file_context(self, uploaded_files: List[str]) -> FileContext:
        results: List[FileExtractionResult] = []
        for blob_ref in uploaded_files:
            result = await self._process_blob(blob_ref)
            results.append(result)

        context_text = self._assemble_context(results)
        summaries = [
            {
                "blob_ref": result.blob_ref,
                "filename": result.filename,
                "content_type": result.content_type,
                "truncated": result.truncated,
                "notes": result.notes,
                "error": result.error,
            }
            for result in results
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
        if blob_ref.startswith("file://"):
            path = blob_ref[len("file://") :]
            with open(path, "rb") as handle:
                data = handle.read()
            content_type, _ = mimetypes.guess_type(path)
            return data, path.split("/")[-1], content_type or "application/octet-stream"

        if blob_ref.startswith("https://"):
            credential = self._settings.azure_blob_sas_token or self._settings.azure_blob_account_key
            blob_client = BlobClient.from_blob_url(blob_ref, credential=credential)
        else:
            if not self._blob_service_client:
                raise RuntimeError("Azure Blob connection string is not configured.")
            if not self._settings.azure_blob_container:
                raise RuntimeError("Azure Blob container is not configured.")
            blob_client = self._blob_service_client.get_blob_client(
                container=self._settings.azure_blob_container,
                blob=blob_ref,
            )

        props = blob_client.get_blob_properties()
        content_type = props.content_settings.content_type or "application/octet-stream"
        data = blob_client.download_blob().readall()
        filename = blob_ref.split("/")[-1]
        return data, filename, content_type

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
