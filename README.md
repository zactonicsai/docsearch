# DocMS — Classified Document Management System

Full-stack document management with classification-based ACL, full-text search
via Elasticsearch, and a real Temporal.io workflow pipeline for document-to-text
extraction.

## Architecture

```
                          ┌──────────────────┐
                          │   Temporal UI    │
                          │   :8088          │
                          └────────┬─────────┘
                                   │
┌─────────────┐  ┌────────────┐  ┌┴───────────┐  ┌────────────────┐
│  Frontend   │─▶│ Go Backend │─▶│  Temporal   │─▶│ Python Worker  │
│  HTML/TW/JS │  │  REST API  │  │  Server     │  │ doc-to-text +  │
│  Nginx:3000 │  │  :8080     │  │  :7233      │  │ ES indexing    │
└─────────────┘  └─────┬──────┘  └─────────────┘  └───────┬────────┘
                       │                                    │
                ┌──────┴──────┐  ┌──────────────┐  ┌───────┴────────┐
                │ SQLite Auth │  │ PostgreSQL   │  │ Elasticsearch  │
                │ + Doc Store │  │ (Temporal)   │  │ :9200          │
                └─────────────┘  └──────────────┘  └───────┬────────┘
                                                           │
                                                    ┌──────┴────────┐
                                                    │ Kibana :5601  │
                                                    └───────────────┘
```

## Two Processing Paths

| Path | Toggle | How it works |
|------|--------|-------------|
| **Static** | Default | Go stub converters → direct ES index (fast, mock text) |
| **Temporal** | Toggle ON in UI | File → Temporal workflow → Python worker extracts real text → indexes to ES |

The Python worker supports real extraction for: `.txt`, `.md`, `.csv`, `.tsv`,
`.json`, `.xml`, `.html`, `.docx`, `.pdf`, `.xlsx`, `.png/.jpg/.tiff` (OCR via Tesseract).

## Services (8 containers)

| Service | Port | Description |
|---------|------|-------------|
| frontend | 3000 | Nginx serving HTML/Tailwind/JS SPA |
| backend | 8080 | Go REST API (auth, upload, search, Temporal client) |
| worker | — | Python Temporal worker (text extraction + ES indexing) |
| temporal | 7233 | Temporal server (workflow orchestration) |
| temporal-ui | 8088 | Temporal Web UI (workflow monitoring) |
| temporal-postgresql | 5432 | PostgreSQL (Temporal persistence) |
| elasticsearch | 9200 | Full-text search index |
| kibana | 5601 | Elasticsearch dashboard |

## Users & ACL

| Username | Password | Permissions |
|----------|----------|-------------|
| public_reader | reader123 | public_search_read |
| public_editor | editor123 | public_search_read, public_upload |
| private_reader | private123 | public_search_read, private_search_read |
| admin | admin123 | All (search + upload, public + private) |

## Quick Start

```bash
# Start everything (first build takes ~2 min)
docker compose up --build -d

# Watch logs
docker compose logs -f worker backend

# Run integration tests
docker compose --profile test up --build test-runner
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/login | No | Login → JWT |
| POST | /api/register | No | Create user |
| GET | /api/health | No | Health + Temporal status |
| GET | /api/me | JWT | Current user |
| POST | /api/upload | JWT | Upload file (add `use_temporal=true` for workflow) |
| POST | /api/search | JWT | Search (ACL-filtered) |
| POST | /api/temporal/start | JWT | Start workflow for existing doc |
| GET | /api/temporal/status | JWT | Poll workflow status |
| POST | /internal/update-status | Internal | Worker → backend status callback |

## Temporal Workflow

```
DocumentProcessingWorkflow
  ├── Activity: extract_text      (Python: real file parsing)
  ├── Activity: index_to_elasticsearch  (Python: ES client)
  └── Activity: update_document_status  (HTTP callback to backend)
```

Monitor workflows at http://localhost:8088 (Temporal UI).
