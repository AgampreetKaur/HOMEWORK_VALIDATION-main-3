import os
import uuid
from typing import List

from pdf2image import convert_from_path
from fastapi import UploadFile

from app.config import settings


os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


def _submission_dir(submission_id: str) -> str:
    path = os.path.join(settings.UPLOAD_DIR, submission_id)
    os.makedirs(path, exist_ok=True)
    return path


def save_upload(submission_id: str, file: UploadFile) -> List[str]:
    """
    Saves an uploaded file.

    PDFs are converted into one PNG image per page.
    Images are saved directly.

    Returns a list of saved file paths.
    """

    directory = _submission_dir(submission_id)

    ext = os.path.splitext(file.filename or "")[1].lower()

    temp_path = os.path.join(
        directory,
        f"{uuid.uuid4()}{ext}",
    )

    with open(temp_path, "wb") as f:
        f.write(file.file.read())

    # ---------------------------------------------------------
    # PDF
    # ---------------------------------------------------------

    if ext == ".pdf":
        images = convert_from_path(
            temp_path,
            dpi=300,
        )

        saved_paths = []

        for i, img in enumerate(images):
            img_path = os.path.join(
                directory,
                f"{uuid.uuid4()}_p{i + 1}.png",
            )

            img.save(
                img_path,
                "PNG",
            )

            saved_paths.append(img_path)

        os.remove(temp_path)

        return saved_paths

    # ---------------------------------------------------------
    # Image
    # ---------------------------------------------------------

    return [temp_path]


def write_temp_copy(page) -> str:
    """
    Writes the page.file_data BLOB to a temporary file.

    The OCR pipeline passes a Page object directly.
    """

    directory = _submission_dir(
        str(page.submission_id)
    )

    filename = page.original_filename or "page"

    ext = os.path.splitext(filename)[1].lower()

    if not ext:
        ext = ".bin"

    temp_path = os.path.join(
        directory,
        f"{uuid.uuid4()}_ocr{ext}",
    )

    with open(temp_path, "wb") as f:
        f.write(page.file_data)

    return temp_path


def delete_temp_copy(path: str) -> None:
    """
    Deletes a temporary OCR file if it exists.
    """

    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass