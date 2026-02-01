# Task Planner Service

Standalone FastAPI microservice for generating workflow plans using the Azure OpenAI
GPT-5.2 Thinking model. The service accepts a chat-style conversation and uploaded
file references, performs file extraction + OCR, and returns a structured plan JSON
for user approval.

## Key Capabilities

- Conversation-first planning (`POST /planner/chat`)
- Intent classification (TASK vs NON_TASK)
- File extraction for CSV/XLSX/PDF/images/text
- OCR for scanned PDFs and images via Azure OpenAI Vision
- Structured plan JSON output with tool mapping
- SQL persistence for messages + plans
- Redis cache for active planning state
- Redis cache for extracted file text (optional)

## Quick Start

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure environment variables (see `.env.example`). For local SQLite, use:
   `SQL_DATABASE_URL=sqlite+aiosqlite:///./planner.db`
   Optionally set `PLANNING_MAX_OUTPUT_TOKENS` and omit `PLANNING_TEMPERATURE`
   for GPT-5.2 thinking models.

3. Run the service:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

## Tests

Run unit and integration tests with:
```bash
pytest
```

## Redis File Content Cache (Optional)

The planner can cache extracted file text + metadata in Redis to avoid repeat
parsing/OCR. Configure TTL and size limits with:

- `REDIS_FILE_CACHE_ENABLED`
- `REDIS_FILE_CACHE_TTL_SECONDS`
- `REDIS_FILE_CACHE_MAX_CHARS`

## Planner Endpoint

`POST /planner/chat`

Example request:
```json
{
  "task_id": "optional",
  "messages": [
    {"role": "user", "content": "Summarize this spreadsheet and draft a report."}
  ],
  "uploaded_files": ["sample.xlsx"]
}
```

Example response:
```json
{
  "task_id": "123",
  "assistant_message": "Here is a proposed workflow plan...",
  "plan_json": {
    "plan_id": "plan-123",
    "task_summary": "Summarize spreadsheet and draft a report",
    "mode": "TASK",
    "steps": [
      {
        "step_id": "1",
        "name": "Extract file content",
        "description": "Parse uploaded spreadsheet into structured rows",
        "tool_used": "azure-blob-storage",
        "inputs": ["uploaded_files"],
        "outputs": ["structured_rows"],
        "dependencies": [],
        "success_criteria": "Rows loaded successfully"
      }
    ],
    "requires_user_approval": true,
    "status": "awaiting_user_approval"
  },
  "status": "awaiting_user_approval",
  "intent": "TASK"
}
```