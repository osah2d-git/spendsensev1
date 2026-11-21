"""The two AI jobs, both done by Claude through the Anthropic API.

1. suggest_categories: place merchant names the rules could not place.
2. write_insights: turn calculated totals into 3-4 plain-language insights
   and the wording of one saving suggestion.

Safeguards:
- Claude only ever receives merchant names (job 1) or totals and percentages (job 2).
- Every dollar figure and percentage in Claude's text is checked against the
  calculated numbers; any insight with a number that does not match is dropped.
- If there is no API key, or the call fails, the functions return None and the
  app carries on without AI.
"""
from __future__ import annotations

import json
import os
import re

from .categorize import SPENDING_CATEGORIES

DEFAULT_MODEL = "claude-haiku-5-5"
BANNED = re.compile(r"\b(invest|investment|stock|etf|rrsp|tfsa|crypto|bitcoin|mortgage rate|credit score|"
                    r"loan|line of credit|tax|refinanc|consolidat)\w*", re.I)


def get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:  # Streamlit Community Cloud keeps keys in st.secrets
        import streamlit as st
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _client():
    key = get_api_key()
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=30.0, max_retries=1)


def _model() -> str:
    return os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)


def _ask(system: str, user: str, max_tokens: int = 800) -> str | None:
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(model=_model(), max_tokens=max_tokens, temperature=0,
                                     system=system, messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    except Exception:
        return None


def _json_from(text: str | None):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------- Job 1: categories for unplaced merchants ----------

CATEGORY_SYSTEM = (
    "You sort bank transaction descriptions into spending categories for a Canadian budgeting tool. "
    "Answer with JSON only, in the form {\"<description>\": \"<category>\"}. "
    "Use exactly one of these categories: " + ", ".join(SPENDING_CATEGORIES) + ". "
    "If you cannot tell, use \"Other\". Do not add any other text."
)
CATEGORY_EXAMPLES = (
    "Examples:\n"
    "SQ *JOE'S DINER -> Dining Out\n"
    "PRESTO FARE -> Transport\n"
    "DOLLARAMA #123 -> Shopping\n"
)


def suggest_categories(descriptions: list[str]) -> dict[str, str] | None:
    """Return {description: category} for the ones Claude placed, or None if AI is unavailable."""
    if not descriptions:
        return {}
    text = _ask(CATEGORY_SYSTEM, CATEGORY_EXAMPLES + "\nDescriptions:\n" + "\n".join(descriptions[:100]))
    data = _json_from(text)
    if not isinstance(data, dict):
        return None
    return {d: c for d, c in data.items() if d in descriptions and c in SPENDING_CATEGORIES}


# ---------- Job 2: insights and suggestion wording ----------

INSIGHT_SYSTEM = (
    "You write short, friendly spending insights for a young professional in Canada. "
    "You receive monthly spending facts as JSON. Rules:\n"
    "- Write 3 or 4 insights, each one or two sentences, in plain language.\n"
    "- Quote only numbers that appear in the facts. Never calculate new numbers. "
    "Write dollars like $612.00 and percentages like 40.1%.\n"
    "- Be non-judgmental: describe, do not scold. Say 'grew' or 'was your biggest category', not 'wasted'.\n"
    "- Never give investment, credit, debt, loan or tax advice. Talk only about spending habits.\n"
    "- Then rewrite the saving suggestion from the facts as one or two encouraging sentences that keep its dollar figures.\n"
    "Answer with JSON only: {\"insights\": [\"...\", \"...\"], \"suggestion\": \"...\"}"
)

NUM = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(%)?")


def numbers_ok(text: str, allowed: set[float]) -> bool:
    """True if every number in the text matches a calculated number (after rounding)."""
    for m in NUM.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            return False
        if v.is_integer() and v < 32 and not m.group(2) and "$" not in m.group(0):
            continue  # small counts like "3 subscriptions" or a day of the month
        if v in (2025.0, 2026.0, 2027.0):
            continue  # years in month labels
        if not any(abs(v - a) < 0.051 for a in allowed):
            return False
    return True


def safe(text: str, allowed: set[float]) -> bool:
    return bool(text) and numbers_ok(text, allowed) and not BANNED.search(text)


def write_insights(facts: dict, allowed: set[float]) -> dict | None:
    """Return {"insights": [...], "suggestion": str|None, "dropped": int} or None if AI is unavailable."""
    text = _ask(INSIGHT_SYSTEM, json.dumps(facts, indent=1))
    data = _json_from(text)
    if not isinstance(data, dict) or not isinstance(data.get("insights"), list):
        return None
    raw = [str(x) for x in data["insights"]][:4]
    kept = [t for t in raw if safe(t, allowed)]
    sugg = data.get("suggestion")
    sugg = str(sugg) if sugg and safe(str(sugg), allowed) else None
    return {"insights": kept, "suggestion": sugg, "dropped": len(raw) - len(kept)}
