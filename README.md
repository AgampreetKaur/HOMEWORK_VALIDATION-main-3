# Homework Validation & Grading Backend

Backend for an AI tutor app: students upload photos/PDFs of handwritten
homework or test answers, the system OCR-scans them, shows the student the
extracted text for approval (rescans if rejected), then sends the approved
text to an AI grader that scores it like a teacher would.

Tested and verified: full lifecycle (upload → OCR → approval → grading
dispatch → graceful failure handling) runs correctly end-to-end using
FastAPI's TestClient + SQLite + the Tesseract fallback engine. Only a real
`GEMINI_API_KEY` is needed to see actual grading output.

## Pipeline

```
[Upload image/PDF] → [OCR extraction] → [Student approval loop] → [AI grading] → [Result]
                                              ↑ reject/rescan ─┘
```

1. **Upload** (`POST /submissions`) — one or more images or PDFs (PDFs are
   split into per-page images automatically).
2. **OCR extraction** runs in the background. Extracted text is stored as an
   immutable, versioned record per page — the student sees it read-only,
   never editable.
3. **Approval loop**:
   - Approve a page (`POST /submissions/{id}/approve`) → locks that page's
     text.
   - Reject → rescan (`POST /submissions/{id}/rescan`) → OCR re-runs with
     progressively heavier image preprocessing (deskew → denoise/contrast →
     adaptive binarization) rather than just repeating the same call, since a
     plain re-run on identical pixels tends to reproduce the same mistake.
     Capped at `OCR_MAX_RESCAN_ATTEMPTS` (default 3) per page — after that,
     the API returns 409 so the frontend can prompt for a fresh photo or
     manual correction instead of looping forever.
4. **Grading**: once every page is approved, grading triggers automatically.
   Questions can come from the scan itself (`question_source=embedded`), be
   attached separately (`POST /submissions/{id}/questions`), or both.
5. **Result** (`GET /submissions/{id}/result`) — per-question score, max
   score, feedback, and any deductions, plus a total.

## OCR engine: Gemini vision (DEFAULT)

The default engine (`OCR_ENGINE=gemini`) sends the whole page image to the
multimodal Gemini API and gets back a transcription — reusing the same
`google-genai` SDK and `GEMINI_API_KEY` already used for grading. It is
markedly stronger on cursive / messy handwriting than Tesseract or TrOCR,
needs **no model download and no line segmentation**, and adds no extra
dependencies.

- Implemented in `services/ocr/gemini_engine.py` behind the same
  `BaseOCREngine` interface as every other engine.
- Model is set by `OCR_GEMINI_MODEL` (default `gemini-2.5-flash`) — a cheap,
  fast "flash" model is plenty for transcription. Same deprecation caveat as
  the grading model: if it 404s, switch to the current flash model.
- Requires a valid `GEMINI_API_KEY`. If Gemini returns nothing, the pipeline
  still falls back to Tesseract (when its system binary is installed).

Switch engines any time with `OCR_ENGINE=gemini|trocr|tesseract` in `.env`.

## OCR engine: TrOCR (optional, self-hosted handwriting model)


The self-hosted engine is **TrOCR** (`microsoft/trocr-large-handwritten`) — an
open-source, free-to-self-host transformer OCR model trained specifically
on handwritten text (IAM dataset). It meaningfully outperforms Tesseract on
messy handwriting, which is the actual hard case here since Tesseract was
built for printed text.

- TrOCR recognizes *lines*, not full pages, so `line_segmentation.py` does a
  lightweight horizontal-projection crop of each page into lines before
  handing them to the model.
- `preprocessing.py` cleans up the photo before OCR (deskew, denoise,
  contrast), escalating aggressiveness on each rescan attempt.
- **Tesseract** is kept as a free fallback for typed/printed pages (e.g. a
  printed question paper uploaded alongside handwritten answers) and as an
  automatic safety net if TrOCR returns nothing on a page.
- Both implement the same `BaseOCREngine` interface (`services/ocr/base.py`)
  — swap engines via `OCR_ENGINE=trocr|tesseract` in `.env`, or add a new
  engine (e.g. a paid cloud OCR API) by implementing that interface.

**Note on running TrOCR:** the model weights (~1.3GB) download on first use
via HuggingFace, and inference is meaningfully faster on GPU. On CPU-only
hosting, expect a few seconds per line — fine for a homework app's async
flow, but budget for it. If cost/latency becomes an issue at scale, the
pluggable interface means switching to a paid OCR API is a one-file change.

**Note for Intel Mac users:** PyTorch dropped x86_64 macOS wheels after
version 2.2.2, so `requirements.txt` intentionally leaves `torch`/
`torchvision` unpinned to a minor version (`>=2.2.0`) — pip will resolve
2.2.2 automatically on Intel Macs and a current release everywhere else.
`transformers` is deliberately pinned to `4.44.2` (not left open) for the
same reason: newer `transformers` releases added a hard runtime check
requiring `torch>=2.4`, which fails outright on Intel Mac's 2.2.2 cap with
`PyTorch >= 2.4 is required but found 2.2.2`. 4.44.2 predates that check.

## AI grading

Uses the Gemini API directly, via the current `google-genai` SDK
(`services/grading/grader.py`), with a system
prompt (`prompts.py`) instructed to grade like a teacher: award partial
credit, give specific reasons for every deduction, and flag OCR-garbled
(vs. student-error) text as `flagged_illegible` rather than penalizing it.
Output is forced to structured JSON so it's directly storable.

## Setup

```bash
cd homework-grader
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# The default (Gemini) OCR needs no extra deps. To use OCR_ENGINE=trocr,
# uncomment the torch/transformers lines in requirements.txt first.

# System dependency for Tesseract fallback:
#   Ubuntu/Debian: sudo apt install tesseract-ocr poppler-utils
#   (poppler-utils is needed for PDF → image splitting via pdf2image)

cp .env.example .env
# edit .env: set GEMINI_API_KEY, and DATABASE_URL if not using SQLite

uvicorn app.main:app --reload
```

Interactive API docs at `http://localhost:8000/docs`.

## What's stubbed vs. production-ready

- **Storage**: files save to local disk (`services/storage.py`). Swap for
  S3/GCS by changing that one file — nothing else depends on the storage
  backend.
- **Background jobs**: uses FastAPI's built-in `BackgroundTasks` for
  simplicity (no extra infra to run this locally). `celery` + `redis` are
  in `requirements.txt` for when you need durable retries, horizontal
  scaling, or to survive a server restart mid-OCR — swap the
  `background_tasks.add_task(...)` calls in `routers/submissions.py` for
  `.delay(...)` Celery task calls.
- **DB migrations**: `Base.metadata.create_all()` runs on startup for local
  dev. Use Alembic for production so schema changes are tracked.
- **Auth**: none — `student_id` is passed as a plain form field. Add your
  auth layer in front of these routes before going live.

## Project layout

```
app/
  main.py                     FastAPI app entrypoint
  config.py                   Settings (env-driven)
  database.py                 SQLAlchemy engine/session
  models.py                   Submission, Page, ExtractedText, Question, GradingResult
  schemas.py                  Pydantic request/response models
  routers/
    submissions.py            All API endpoints
  services/
    storage.py                File upload handling, PDF→image splitting
    pipeline.py                Orchestrates OCR → approval → grading stages
    ocr/
      base.py                 BaseOCREngine interface
      trocr_engine.py         Primary handwriting engine
      tesseract_engine.py     Fallback engine
      engine_factory.py       Picks engine from settings, handles fallback
      preprocessing.py        Deskew/denoise/contrast/binarize
      line_segmentation.py    Splits a page into lines for TrOCR
    grading/
      grader.py                Calls Gemini API, parses structured output
      prompts.py                Grading system prompt + prompt builder
```
