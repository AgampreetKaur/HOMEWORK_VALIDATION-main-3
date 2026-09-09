"""
Disk storage for report-card uploads.

Files are written under UPLOAD_DIR/report_cards/<student_id>/<uuid><ext>. The
path is stored on the ReportCard row and streamed back later by the download
endpoint. Kept separate from submission storage (services/storage.py) because
report cards are just files to keep — they don't go through the OCR/PDF-to-PNG
pipeline homework pages do; they're sent to Gemini as-is (image or PDF) for
analysis instead.
"""

import os
import uuid

from fastapi import UploadFile

from app.config import settings


REPORT_CARD_DIR = os.path.join(settings.UPLOAD_DIR, "report_cards")

os.makedirs(REPORT_CARD_DIR, exist_ok=True)

# Only allow image + PDF report cards, capped at 15 MB.
ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}
MAX_BYTES = 15 * 1024 * 1024


def save_report_card(student_id: str, file: UploadFile) -> dict:
    """
    Save an uploaded report card for a child and return metadata:
    {file_path, mime_type, file_size, original_filename}.

    Raises ValueError on an unsupported type or oversized file.
    """

    ext = os.path.splitext(file.filename or "")[1].lower()

    if ext not in ALLOWED_EXTS:
        raise ValueError(
            "Unsupported file type. Please upload a PDF or an image "
            "(PNG, JPG, WEBP, HEIC)."
        )

    data = file.file.read()

    if not data:
        raise ValueError("The uploaded file was empty.")

    if len(data) > MAX_BYTES:
        raise ValueError("File is too large. Maximum size is 15 MB.")

    student_dir = os.path.join(REPORT_CARD_DIR, student_id)
    os.makedirs(student_dir, exist_ok=True)

    stored_path = os.path.join(student_dir, f"{uuid.uuid4()}{ext}")

    with open(stored_path, "wb") as f:
        f.write(data)

    mime_type = file.content_type or _guess_mime(ext)

    return {
        "file_path": stored_path,
        "mime_type": mime_type,
        "file_size": len(data),
        "original_filename": file.filename or f"report_card{ext}",
    }


def delete_report_card_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _guess_mime(ext: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }.get(ext, "application/octet-stream")
