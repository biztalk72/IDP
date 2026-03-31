# IDP — 지능형 문서 처리 시스템: PRD
## 1. 개요
PDF를 수집하고, 문서 특성에 따라 최적의 추출 전략(OCR / OCR+LLM / OCR+VLM)을 자동 선택하며, 벡터 스토어에 색인하고, 멀티턴 RAG 챗봇(멀티모달 출력 + 영속적 대화 메모리)을 제공하는 로컬 LLM 기반 문서 처리 시스템.
## 2. 현재 상태
* **추출**: PyMuPDF 네이티브 텍스트 → Tesseract OCR 폴백 (임계값 기반)
* **색인**: 청킹 → Ollama 임베딩 → ChromaDB
* **LLM**: 단일 모델 (`qwen2.5:7b`) Ollama 경유, 대화 메모리 없음
* **채팅**: Streamlit UI, 세션 기반 채팅 기록만 지원 (새로고침 시 소실)
* **문서 관리**: 목록 조회, 삭제만 가능; 정렬·버전 관리 미지원
* **배포**: Docker Compose + Colima 호환
* **차단 이슈**: ChromaDB 0.6.3이 Python 3.14와 비호환 (Pydantic v1 문제)
## 3. 요구사항
### F1. 적응형 추출 파이프라인
페이지별 콘텐츠 특성에 따라 추출 전략을 자동 선택:
* **네이티브 텍스트** — 텍스트 밀도가 충분한 페이지 (현재 PyMuPDF 경로)
* **OCR** — 텍스트가 없거나 적은 스캔 페이지; 현재와 동일한 Tesseract 추출
* **OCR + LLM** — OCR 출력을 LLM으로 후처리하여 오류 수정, 서식 복원, 텍스트 구조화 (예: 표 재구성, 끊어진 문장 수정)
* **OCR + VLM** — 페이지 이미지를 Vision-Language Model(예: `minicpm-v`, `llava`)에 직접 전송하여 OCR이 처리하기 어려운 콘텐츠 추출: 복잡한 레이아웃, 다이어그램, 차트, 손글씨
선택 로직 (페이지별):
1. 네이티브 텍스트 밀도 ≥ 임계값 → **네이티브 텍스트**
2. OCR 텍스트 밀도 ≥ 임계값 → **OCR** (선택적으로 + LLM 보정)
3. OCR 텍스트 밀도 < 임계값 (이미지, 다이어그램, 복잡한 레이아웃) → **OCR + VLM**
멀티 LLM 지원:
* 역할별로 다른 Ollama 모델 지정 가능: 텍스트 LLM, VLM, 임베딩
* `config.py`에 추가: `VLM_MODEL`, `OCR_LLM_MODEL` (미설정 시 `LLM_MODEL` 기본값)
### F2. 장기 메모리 및 멀티턴 채팅
세션 간 대화를 영속적으로 유지:
* **대화 저장소** — SQLite 테이블 `conversations`: `id`, `title`, `created_at`, `updated_at`
* **메시지 저장소** — SQLite 테이블 `messages`: `id`, `conversation_id`, `role`, `content`, `sources_json`, `created_at`
* 백엔드 `/query/` 엔드포인트가 `conversation_id`를 수신; 이전 메시지를 로드하여 LLM 프롬프트에 대화 이력으로 포함
* 컨텍스트 윈도우 관리: 최근 N개 메시지 슬라이딩 윈도우 + 오래된 컨텍스트 요약
* **API 추가**:
    * `POST /conversations/` — 새 대화 생성
    * `GET /conversations/` — 대화 목록 조회
    * `GET /conversations/{id}/messages` — 대화 메시지 조회
    * `DELETE /conversations/{id}` — 대화 삭제
* **UI**: 사이드바에 과거 대화 세션 표시, 클릭으로 이어서 대화
### F3. 멀티모달 채팅 출력
풍부한 콘텐츠로 채팅 경험 강화:
* **문맥 기반 이미지 표시** — 대화 맥락상 관련된 PDF 내 이미지(차트, 도표, 사진 등)를 자동으로 인라인 표시하고 개별 다운로드 버튼 제공
* **마크다운 테이블 생성** — LLM이 문서 데이터를 기반으로 마크다운 표를 생성; **Excel(.xlsx) / CSV 내보내기** 버튼 제공
* **그래프 시각화** — LLM이 데이터를 분석하여 2D/3D 그래프 생성 (Plotly 활용)
    * 2D: 선형, 막대, 산점도, 히스토그램, 파이 차트
    * 3D: 표면, 산점도, 등고선
    * 대화 중 "그래프로 보여줘" 등의 요청 시 자동 생성
    * 그래프 이미지 PNG/SVG 다운로드 지원
* **LaTeX 수식** — `st.latex` 또는 KaTeX를 통한 수식 렌더링
* **페이지 이미지** — 출처 인용 옆에 PDF 페이지 썸네일 인라인 표시 + 다운로드
* 출처 참조를 클릭 가능한 확장 섹션으로 페이지 미리보기와 함께 표시
### F4. 문서 관리
기본 목록+삭제를 넘어 문서 관리 기능 확장:
* **정렬** — 제목, 파일명, 업로드 일시, 페이지 수, 상태별 정렬
* **버전 관리** — 동일 파일명 재업로드 시 교체 대신 새 버전 생성
    * SQLite 스키마 추가: `version INTEGER DEFAULT 1`, `parent_id TEXT` (원본 문서 참조)
    * API에서 버전 정보 반환; UI에서 문서별 버전 이력 표시
    * 벡터 스토어 항목에 `doc_id:version` 태그 → 구버전 포함/제외 가능
* **필터링** — 상태별 필터 (ready / processing / error)
* **일괄 작업** — 여러 문서 선택 후 삭제 또는 재색인
* **API 추가**:
    * `GET /documents/?sort_by=title&order=desc&status=ready` — 정렬 + 필터 파라미터
    * `GET /documents/{id}/versions` — 문서 버전 목록
    * `POST /documents/{id}/reindex` — 기존 문서 재색인
### F5. 배포 (Docker / Colima)
현재 Docker Compose 구성을 유지하고 Colima에서 정상 동작 보장:
* Dockerfile에서 Python 3.12 고정 (3.14 Pydantic 이슈 회피)
* Python 3.12 호환 최신 안정 버전 `chromadb`로 업그레이드
* API 및 UI 컨테이너 헬스체크
* `./data`, `./db` 볼륨 마운트로 데이터 영속성 확보
* `OLLAMA_BASE_URL` 기본값 `host.docker.internal:11434`
## 4. 기술 스택
* **Python** 3.12 (호환성을 위해 고정)
* **FastAPI** + Uvicorn — 백엔드 API
* **Streamlit** — 프론트엔드 UI
* **Plotly** — 2D/3D 그래프 시각화
* **openpyxl** — Excel 내보내기
* **Ollama** — 로컬 LLM 추론 (텍스트, 비전, 임베딩)
* **ChromaDB** — 벡터 스토어
* **SQLite** (aiosqlite) — 메타데이터, 대화, 메시지
* **PyMuPDF** — PDF 파싱
* **Tesseract + pdf2image** — OCR
* **Docker Compose** — 배포 (Colima 호환)
## 5. 모델 (기본값)
* 텍스트 LLM: `qwen2.5:7b`
* VLM: `minicpm-v` (또는 `llava`)
* 임베딩: `mxbai-embed-large`
* OCR 보정 LLM: 텍스트 LLM과 동일 (설정 변경 가능)
## 6. 프로젝트 구조 (목표)
```warp-runnable-command
IDP/
├── app/
│   ├── main.py
│   ├── config.py                  # + VLM_MODEL, OCR_LLM_MODEL
│   ├── models.py                  # + conversations, messages, versioning
│   ├── services/
│   │   ├── extractor.py           # + 적응형 파이프라인 (OCR/LLM/VLM)
│   │   ├── vlm.py                 # 신규 — VLM 추론
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── vectorstore.py
│   │   ├── indexer.py
│   │   ├── llm.py                 # + 대화 컨텍스트, OCR 보정
│   │   ├── conversation.py        # 신규 — 대화 CRUD
│   │   └── exporter.py            # + Excel/CSV/그래프 내보내기
│   └── routers/
│       ├── documents.py           # + 정렬, 필터링, 버전 관리
│       ├── query.py               # + conversation_id, 멀티턴
│       └── conversations.py       # 신규 — 대화 엔드포인트
├── ui/
│   └── streamlit_app.py           # + 대화 사이드바, 그래프, 향상된 출력
├── docker-compose.yml
├── Dockerfile                     # Python 3.12
├── Dockerfile.ui
└── requirements.txt
```
## 7. 우선순위
1. **런타임 수정** — Python 3.12 고정, ChromaDB/Pydantic 호환성 해결
2. **F4** — 문서 관리 (정렬, 버전 관리, 필터링)
3. **F1** — 적응형 추출 파이프라인 (OCR → OCR+LLM → OCR+VLM)
4. **F2** — 장기 메모리 및 멀티턴 채팅
5. **F3** — 멀티모달 채팅 출력 강화
6. **F5** — Docker/Colima 배포 안정화
***
# IDP — Intelligent Document Processing: PRD (English)
## 1. Overview
Local LLM-powered document processing system that ingests PDFs, automatically selects the optimal extraction strategy (OCR / OCR+LLM / OCR+VLM), indexes content into a vector store, and provides a multi-turn RAG chatbot with multimodal output and persistent conversation memory.
## 2. Current State
* **Extraction**: PyMuPDF native text → Tesseract OCR fallback (threshold-based)
* **Indexing**: chunking → Ollama embeddings → ChromaDB
* **LLM**: single model (`qwen2.5:7b`) via Ollama, no conversation memory
* **Chat**: Streamlit UI with session-only chat history (lost on reload)
* **Documents**: list, delete; no sorting or versioning
* **Deployment**: Docker Compose + Colima-compatible
* **Blockers**: ChromaDB 0.6.3 incompatible with Python 3.14 (Pydantic v1 issue)
## 3. Requirements
### F1. Adaptive Extraction Pipeline
Automatically select extraction strategy per page based on content characteristics:
* **Native Text** — pages with sufficient text density (current PyMuPDF path)
* **OCR** — scanned pages with no/low text; Tesseract extraction as today
* **OCR + LLM** — OCR output is post-processed by an LLM to correct errors, fix formatting, and structure the text (e.g. reconstruct tables, fix broken sentences)
* **OCR + VLM** — page image is sent directly to a Vision-Language Model (e.g. `minicpm-v`, `llava`) to extract content that OCR cannot handle well: complex layouts, diagrams, charts, handwriting
Selection logic (per page):
1. If native text density ≥ threshold → **Native Text**
2. If OCR text density ≥ threshold → **OCR** (optionally + LLM correction)
3. If OCR text density < threshold (images, diagrams, complex layouts) → **OCR + VLM**
Multi-LLM support:
* Config allows specifying different Ollama models for each role: text LLM, VLM, embedding
* `config.py` adds: `VLM_MODEL`, `OCR_LLM_MODEL` (default to `LLM_MODEL` if unset)
### F2. Long Memory & Multi-Turn Chat
Persist conversations across sessions with full context:
* **Conversation store** — SQLite table `conversations`: `id`, `title`, `created_at`, `updated_at`
* **Message store** — SQLite table `messages`: `id`, `conversation_id`, `role`, `content`, `sources_json`, `created_at`
* Backend `/query/` endpoint accepts `conversation_id`; loads prior messages and includes them in the LLM prompt as conversation history
* Context window management: sliding window of recent N messages + summarized older context
* **API additions**:
    * `POST /conversations/` — create new conversation
    * `GET /conversations/` — list conversations
    * `GET /conversations/{id}/messages` — get messages for a conversation
    * `DELETE /conversations/{id}` — delete conversation
* **UI**: conversation sidebar showing past sessions, click to resume
### F3. Multimodal Chat Output
Enhance the chat experience with rich content:
* **Context-aware image display** — automatically show relevant images from PDFs (charts, diagrams, photos) inline in the conversation, with individual download buttons
* **Markdown table generation** — LLM generates markdown tables from document data; **Excel (.xlsx) / CSV export** buttons provided
* **Graph visualization** — LLM analyzes data and generates 2D/3D graphs (using Plotly)
    * 2D: line, bar, scatter, histogram, pie charts
    * 3D: surface, scatter, contour
    * Auto-generated when user requests (e.g. "show me a graph")
    * Graph image download in PNG/SVG
* **LaTeX math** — render math expressions via `st.latex` or KaTeX in markdown
* **Page images** — inline PDF page thumbnails next to source citations + download
* Source references displayed as clickable expandable sections with page previews
### F4. Document Management
Expand document management beyond basic list+delete:
* **Sorting** — sort document list by: title, filename, date uploaded, page count, status
* **Versioning** — when the same filename is re-uploaded, create a new version instead of replacing
    * SQLite schema adds: `version INTEGER DEFAULT 1`, `parent_id TEXT` (references original doc)
    * API returns version info; UI shows version history per document
    * Vector store entries are tagged with `doc_id:version` so old versions can be excluded/included
* **Filtering** — filter by status (ready / processing / error)
* **Bulk operations** — select multiple documents for delete or re-index
* **API additions**:
    * `GET /documents/?sort_by=title&order=desc&status=ready` — sorting + filtering params
    * `GET /documents/{id}/versions` — list versions of a document
    * `POST /documents/{id}/reindex` — re-run indexing on existing document
### F5. Deployment (Docker / Colima)
Maintain current Docker Compose setup and ensure everything runs on Colima:
* Pin Python to 3.12 in Dockerfiles (avoid 3.14 Pydantic issue)
* Upgrade `chromadb` to latest stable version compatible with Python 3.12
* Health checks for API and UI containers
* Volume mounts for `./data`, `./db` persistence
* `OLLAMA_BASE_URL` defaults to `host.docker.internal:11434`
## 4. Tech Stack
* **Python** 3.12 (pinned for compatibility)
* **FastAPI** + Uvicorn — backend API
* **Streamlit** — frontend UI
* **Plotly** — 2D/3D graph visualization
* **openpyxl** — Excel export
* **Ollama** — local LLM inference (text, vision, embeddings)
* **ChromaDB** — vector store
* **SQLite** (aiosqlite) — metadata, conversations, messages
* **PyMuPDF** — PDF parsing
* **Tesseract + pdf2image** — OCR
* **Docker Compose** — deployment (Colima-compatible)
## 5. Models (Default)
* Text LLM: `qwen2.5:7b`
* VLM: `minicpm-v` (or `llava`)
* Embeddings: `mxbai-embed-large`
* OCR correction LLM: same as text LLM (configurable)
## 6. Project Structure (Target)
```warp-runnable-command
IDP/
├── app/
│   ├── main.py
│   ├── config.py                  # + VLM_MODEL, OCR_LLM_MODEL
│   ├── models.py                  # + conversations, messages, versioning
│   ├── services/
│   │   ├── extractor.py           # + adaptive pipeline (OCR/LLM/VLM)
│   │   ├── vlm.py                 # NEW — VLM inference
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── vectorstore.py
│   │   ├── indexer.py
│   │   ├── llm.py                 # + conversation context, OCR correction
│   │   ├── conversation.py        # NEW — conversation CRUD
│   │   └── exporter.py            # + Excel/CSV/graph export
│   └── routers/
│       ├── documents.py           # + sorting, filtering, versioning
│       ├── query.py               # + conversation_id, multi-turn
│       └── conversations.py       # NEW — conversation endpoints
├── ui/
│   └── streamlit_app.py           # + conversation sidebar, graphs, enhanced output
├── docker-compose.yml
├── Dockerfile                     # Python 3.12
├── Dockerfile.ui
└── requirements.txt
```
## 7. Priority Order
1. **Fix runtime** — pin Python 3.12, resolve ChromaDB/Pydantic compatibility
2. **F4** — Document management (sorting, versioning, filtering)
3. **F1** — Adaptive extraction pipeline (OCR → OCR+LLM → OCR+VLM)
4. **F2** — Long memory & multi-turn chat
5. **F3** — Multimodal chat output enhancements
6. **F5** — Docker/Colima deployment hardening
