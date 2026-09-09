"""
AI overview generation for uploaded report cards.

Sends the report card file (image or PDF) directly to Gemini, which is
multimodal and reads both without a separate OCR pass, and returns a
structured summary (subjects, marks, attendance, remarks). Parent-only —
see routers/report_cards.py for access control.
"""

import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            logger.warning(
                "GEMINI_API_KEY is not set — report card analysis will fail "
                "until it is provided."
            )
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


_ANALYSIS_PROMPT = """
You are an experienced school teacher reading a student's report card
(image or PDF). Read everything on the page(s) and produce a clear,
parent-friendly overview.

Return ONLY valid JSON matching this exact shape — no markdown, no
commentary, no extra keys:

{
  "summary": "2-4 sentence plain-language overview of overall performance",
  "overall_grade_or_percentage": "e.g. '86%' or 'A' or null if not present",
  "subjects": [
    {"subject": "Mathematics", "marks": "42/50", "grade": "A", "remarks": "..."}
  ],
  "attendance": "e.g. '92% (184/200 days)' or null if not present",
  "teacher_remarks": "verbatim or lightly summarized teacher comments, or null",
  "strengths": ["short phrase", "short phrase"],
  "areas_to_improve": ["short phrase", "short phrase"]
}

Rules:
- Only report what is actually on the document. Never invent marks,
  subjects, or remarks that are not present.
- If a field genuinely isn't on the document, use null (or an empty list
  for "subjects" / "strengths" / "areas_to_improve").
- "subjects" should list every subject/marks row you can read, in the
  order they appear.
- Keep "strengths" and "areas_to_improve" short and specific to what the
  marks/remarks actually show — do not pad with generic advice.
""".strip()


def analyze_report_card(file_path: str, mime_type: str) -> dict:
    """
    Reads the stored report card file and returns a parsed overview dict
    (matching the shape in _ANALYSIS_PROMPT above).

    Raises ValueError if the file can't be read or Gemini's response can't
    be parsed as JSON — callers should catch this and leave `overview`
    unset rather than storing garbage.
    """

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except OSError as exc:
        raise ValueError(f"Could not read the stored file: {exc}") from exc

    client = _get_client()

    try:
        response = client.models.generate_content(
            model=settings.GRADING_MODEL,
            contents=[
                _ANALYSIS_PROMPT,
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                max_output_tokens=4000,
            ),
        )
    except Exception as exc:  # network error, bad/missing key, quota, etc.
        logger.error("Report card analysis request failed: %s", exc)
        raise ValueError(f"Analysis request failed: {exc}") from exc

    # A truncated response (hit the token limit) is different from a
    # malformed one — worth distinguishing in the error message.
    finish_reason = None
    try:
        finish_reason = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        pass

    raw_text = (response.text or "").strip()

    # Strip markdown fences defensively even though forced JSON mode
    # should prevent them.
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    # Extract just the outer {...} object in case there's any stray
    # preamble/trailing text around it.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse report card overview as JSON (finish_reason=%s): %s\nRaw (first 2000 chars): %s",
            finish_reason, exc, raw_text[:2000],
        )
        if str(finish_reason) in ("MAX_TOKENS", "FinishReason.MAX_TOKENS"):
            raise ValueError(
                "Analysis response was cut off before finishing (hit the output "
                "length limit) — this usually means the document has a lot of "
                "content to summarize. Try again; if it keeps happening, the "
                "output limit may need to be raised further."
            ) from exc
        raise ValueError("Analysis returned an unparseable response.") from exc

    # Light normalisation so the frontend can render this without guarding
    # against every possible missing key.
    parsed.setdefault("summary", "")
    parsed.setdefault("overall_grade_or_percentage", None)
    parsed.setdefault("subjects", [])
    parsed.setdefault("attendance", None)
    parsed.setdefault("teacher_remarks", None)
    parsed.setdefault("strengths", [])
    parsed.setdefault("areas_to_improve", [])

    return parsed
