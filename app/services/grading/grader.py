import json
import logging
from typing import List, Dict, Optional

from google import genai
from google.genai import types

from app.config import settings
from app.services.grading.prompts import SYSTEM_PROMPT, build_grading_prompt

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def grade_submission(questions: List[Dict], answer_text: str, subject: Optional[str] = None) -> List[Dict]:
    """
    questions: list of dicts with keys question_number, question_text, max_marks, rubric
    answer_text: concatenated, approved OCR text for the whole submission
    subject: optional, e.g. "Mathematics" — passed straight through to the prompt for
             grading context; does not change the response schema.

    Returns a list of dicts matching GradingResult fields, ready to persist.
    """
    if not questions:
        raise ValueError("No questions provided to grade against.")

    client = _get_client()
    prompt = build_grading_prompt(questions, answer_text, subject=subject)

    response = client.models.generate_content(
        model=settings.GRADING_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",  # forces valid JSON output
            max_output_tokens=8000,
        ),
    )

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
        results = parsed["results"]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(
            "Failed to parse grading response as JSON (finish_reason=%s): %s\nRaw (first 2000 chars): %s",
            finish_reason, e, raw_text[:2000],
        )
        if str(finish_reason) in ("MAX_TOKENS", "FinishReason.MAX_TOKENS"):
            raise ValueError(
                "Grading response was cut off before finishing (hit the output "
                "length limit) — this usually means the submission has a lot of "
                "questions/answer text to grade. Try again; if it keeps "
                "happening, the output limit may need to be raised further."
            ) from e
        raise ValueError("Grading model returned an unparseable response.") from e

    # basic validation / clamping so a model quirk can't corrupt scores
    for r in results:
        r["score"] = max(0.0, min(float(r["score"]), float(r["max_score"])))
        r.setdefault("deductions", [])
        r.setdefault("flagged_illegible", False)
        r.setdefault("attempted", True)  # tolerate an older-style response that omits it

        # An unattempted question must score 0 regardless of what the
        # model returned — the explanation in "feedback" is kept so the
        # student can still learn from it (see prompts.py rule 7), but
        # the score itself is enforced here.
        if r["attempted"] is False and r["score"] != 0:
            logger.info(
                "Question %s marked unattempted but model returned score=%s — forcing score to 0.",
                r.get("question_number"), r["score"],
            )
            r["score"] = 0.0

        r["raw_model_response"] = raw_text

    return results