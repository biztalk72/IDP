# IDP — Intelligent Document Processing

Local LLM-powered document processing system with OCR, RAG Q&A, and multimodal chatbot.

## Features

- **PDF ingestion** with native text extraction + Tesseract OCR fallback
- **Automatic indexing**: chunking → embedding → vector store (ChromaDB)
- **LLM-generated** document titles and summaries (Ollama `qwen2.5:7b`)
- **RAG Q&A** chat with source citations and page thumbnails
- **Multimodal output**: markdown tables, code blocks, LaTeX math rendering
- **Export**: download conversations as Markdown or PDF reports
- **Docker Compose** deployment (Colima-compatible)

## Prerequisites

- [Ollama](https://ollama.ai) with models pulled:
  ```bash
  ollama pull qwen2.5:7b
  ollama pull mxbai-embed-large
  ```
- Python 3.11+ (for local dev) or Docker
- Tesseract OCR (`brew install tesseract` on macOS)
- Poppler (`brew install poppler` on macOS)

## Quick Start (Local)

```bash
# Install dependencies
pip install -r requirements.txt

# Ensure Ollama is running
ollama serve &

# Start FastAPI backend
uvicorn app.main:app --reload --port 8000

# In another terminal — start Streamlit UI
streamlit run ui/streamlit_app.py
```

Open http://localhost:8501 for the UI, or http://localhost:8000/docs for the API.

## Quick Start (Docker Compose)

```bash
# Make sure Ollama is running on the host
ollama serve &

# Build and run
docker compose up --build
```

- API: http://localhost:8000
- UI: http://localhost:8501

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents/upload` | Upload a PDF |
| GET | `/documents/` | List all documents |
| GET | `/documents/{id}` | Get document metadata |
| DELETE | `/documents/{id}` | Delete a document |
| GET | `/documents/{id}/page/{n}/thumbnail` | Page thumbnail PNG |
| POST | `/query/` | RAG Q&A query |
| POST | `/query/export/markdown` | Export answer as .md |
| POST | `/query/export/pdf` | Export answer as .pdf |

## AWS Deployment

### Option A: EC2 with Docker Compose

1. Launch an EC2 instance (recommended: `g4dn.xlarge` for GPU, or `c5.2xlarge` for CPU-only)
2. Install Docker + Docker Compose
3. Install and start Ollama, pull models
4. Clone repo and run `docker compose up -d`

```bash
# On EC2
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:7b && ollama pull mxbai-embed-large

git clone https://github.com/biztalk72/IDP.git
cd IDP
docker compose up -d --build
```

### Option B: ECS Fargate (CPU-only, use external Ollama)

1. Push Docker images to ECR
2. Create ECS task definition with `api` and `ui` containers
3. Run Ollama on a separate GPU EC2 instance
4. Set `OLLAMA_BASE_URL` to the Ollama instance's private IP

### Security Notes

- Use an ALB with HTTPS in front of the services
- Restrict security groups to your IP range
- Store sensitive config in AWS Secrets Manager

## Project Structure

```
IDP/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── config.py            # Settings
│   ├── models.py            # Schemas + DB
│   ├── services/
│   │   ├── extractor.py     # PDF text + OCR
│   │   ├── chunker.py       # Text chunking
│   │   ├── embedder.py      # Ollama embeddings
│   │   ├── vectorstore.py   # ChromaDB
│   │   ├── indexer.py       # Pipeline orchestrator
│   │   ├── llm.py           # LLM client
│   │   └── exporter.py      # Markdown/PDF export
│   └── routers/
│       ├── documents.py     # Document CRUD
│       └── query.py         # RAG + export
├── ui/
│   └── streamlit_app.py     # Streamlit frontend
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.ui
└── requirements.txt
```

## License

MIT
