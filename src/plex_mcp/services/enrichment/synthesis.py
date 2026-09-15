"""LLM synthesis of a structured enrichment report from merged source data.

Decoupled from any specific LLM transport: callers supply a ``sample_fn``
async callable of ``(system_prompt: str, user_prompt: str) -> str``. The MCP
tool path adapts FastMCP's ``ctx.sample``; the webapp REST path adapts its own
local+cloud LLM provider registry. This module only owns prompt shape and
response parsing.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from ...utils import get_logger

logger = get_logger(__name__)

REPORT_SECTION_KEYS = (
    "synopsis",
    "critical_overview",
    "why_this_matters",
    "production_notes",
    "reception_at_release",
    "legacy",
    "content_warnings",
    "thematic_tags",
    "director_context",
    "key_cast_notes",
    "awards",
    "trivia",
)

SYSTEM_PROMPT = (
    "You are a thoughtful film/TV critic preparing a dossier on a specific title "
    "for a cinephile's personal media library browser. Be honest and specific, "
    "never generic marketing copy. If the film is mediocre, say so in "
    "why_this_matters. If content warnings are serious, be specific rather than "
    "vague. Return ONLY valid JSON, no markdown fences, no commentary."
)


class SampleFn(Protocol):
    async def __call__(self, system_prompt: str, user_prompt: str) -> str: ...


def build_user_prompt(title: str, year: int | None, media_type: str, merged_sources: dict[str, Any]) -> str:
    source_json = json.dumps(merged_sources, ensure_ascii=False, indent=2)[:12000]
    return f"""TITLE: {title} ({year if year else "unknown year"})
TYPE: {media_type}

SOURCE MATERIAL (raw, may be partial or contradictory - prefer Wikipedia on factual conflicts and note the discrepancy in trivia):
{source_json}

Produce a JSON object with exactly these keys:
- synopsis: 2-3 sentences, non-spoiler
- critical_overview: 3-4 paragraphs on what this work is doing, why it matters, its place in the filmography/genre/movement
- why_this_matters: 1 paragraph, honest case for (or against) watching it tonight
- production_notes: key behind-the-scenes facts, string
- reception_at_release: string
- legacy: string (empty string if not applicable)
- content_warnings: object with keys violence, sexual_content, language, other_triggers (array of strings) - concrete descriptions, not MPAA codes
- thematic_tags: array of 3-7 short phrases describing what this is ABOUT (not genre labels)
- director_context: brief string on the director's other notable work and style
- key_cast_notes: brief string on notable performances or cast connections
- awards: array of strings, brief
- trivia: array of 3-5 genuinely interesting items (not filler)

Return ONLY the JSON object."""


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"```\s*$", "", stripped)
    return stripped.strip()


def parse_report(raw_text: str) -> tuple[dict[str, Any], bool]:
    """Returns (report_sections, parsed_ok). On failure, wraps raw text as critical_overview."""
    cleaned = _strip_code_fences(raw_text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            report = {k: data.get(k, "") for k in REPORT_SECTION_KEYS}
            return report, True
    except (json.JSONDecodeError, TypeError):
        pass

    logger.warning("Enrichment synthesis did not return valid JSON; wrapping raw text")
    report = dict.fromkeys(REPORT_SECTION_KEYS, "")
    report["critical_overview"] = cleaned[:4000]
    report["content_warnings"] = {"violence": "", "sexual_content": "", "language": "", "other_triggers": []}
    report["thematic_tags"] = []
    report["awards"] = []
    report["trivia"] = []
    return report, False


async def synthesise_report(
    title: str,
    year: int | None,
    media_type: str,
    merged_sources: dict[str, Any],
    sample_fn: SampleFn,
) -> tuple[dict[str, Any], bool]:
    """Call the LLM and parse its response. Raises on transport failure (caller decides fallback)."""
    user_prompt = build_user_prompt(title, year, media_type, merged_sources)
    raw_text = await sample_fn(SYSTEM_PROMPT, user_prompt)
    return parse_report(raw_text)
