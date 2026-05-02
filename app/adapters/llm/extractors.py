"""
LLM extraction pipeline for client check-ins.

Two calls per check-in:
  1. extract_checkin()  → CheckInExtraction  (structured JSON via Instructor)
  2. render_digest()    → str                (≤6-line markdown for the coach)

Provider: OpenRouter → google/gemini-2.5-flash
          Escalate to google/gemini-2.5-pro on Instructor retry failure.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from tenacity import retry, stop_after_attempt, wait_exponential

from app.adapters.llm.openrouter import LLMClient
from app.domain.checkin.schema import CheckInExtraction

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    autoescape=False,
)


def _render_template(name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(name).render(**kwargs)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def extract_checkin(
    llm: LLMClient,
    raw_text: str,
    lift_catalog: list[str],
    prior_profile: str,
) -> CheckInExtraction:
    """
    Extract structured data from a free-form client check-in.

    Retries up to 3 times with back-off, feeding Pydantic validation errors
    back into the next prompt so the model can self-correct.
    """
    system_prompt = _render_template(
        "checkin_extract.j2",
        lift_catalog=lift_catalog,
        prior_profile=prior_profile,
    )

    last_error: Optional[str] = None
    for attempt in range(3):
        user_content = raw_text
        if last_error:
            user_content = (
                f"{raw_text}\n\n"
                f"[PREVIOUS ATTEMPT FAILED VALIDATION — fix these errors and retry]\n"
                f"{last_error}"
            )

        raw_response = llm.complete(
            system=system_prompt,
            user=user_content,
            temperature=0.1,
        )

        # Strip accidental markdown fences
        content = raw_response.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3].rstrip()

        try:
            data = json.loads(content)
            extraction = CheckInExtraction.model_validate(data)
            extraction.derive_coach_review_flag()
            return extraction
        except Exception as exc:
            last_error = str(exc)
            logger.warning("extract_checkin attempt %d failed: %s", attempt + 1, exc)

    raise ValueError(f"extract_checkin failed after 3 attempts. Last error: {last_error}")


def render_digest(
    llm: LLMClient,
    raw_text: str,
    extraction: CheckInExtraction,
    client_name: str,
    week_number: int,
) -> str:
    """Render a ≤6-line coach digest from the extraction."""
    prompt = _render_template(
        "checkin_digest.j2",
        client_name=client_name,
        week_number=week_number,
        raw_text=raw_text,
        extraction_json=extraction.model_dump_json(indent=2),
    )
    return llm.complete(system="", user=prompt, temperature=0.3)
