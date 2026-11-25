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
    if not key:
        try:  # Streamlit Community Cloud keeps keys in st.secrets
            import streamlit as st
            key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            key = None
    key = (key or "").strip().strip('"').strip("'")
    return key or None


def _client():
    key = get_api_key()
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=30.0, max_retries=1)


def _model() -> str:
    model = os.environ.get("CLAUDE_MODEL")
    if not model:
        try:
            import streamlit as st
            model = st.secrets.get("CLAUDE_MODEL")
        except Exception:
            model = None
    return (model or "").strip() or DEFAULT_MODEL


# The reason the last AI call failed, in words the user can act on (None = no failure).
last_error: str | None = None


def _explain(e: Exception) -> str:
    import anthropic
    text = str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return "the API key was rejected. Check that ANTHROPIC_API_KEY is copied in full, starting with sk-ant-."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "this API key is not allowed to use the model. Check the key's workspace in the Claude Console."
    if isinstance(e, anthropic.NotFoundError):
        return f"the model '{_model()}' was not found. Set CLAUDE_MODEL to a current model, e.g. claude-haiku-5-5."
    if isinstance(e, anthropic.RateLimitError):
        return "too many requests right now (rate limit). Wait a minute and press Retry."
    if isinstance(e, anthropic.BadRequestError) and "credit" in text.lower():
        return "the Anthropic account has no credit left. Add credit under Billing in the Claude Console."
    if isinstance(e, anthropic.APIConnectionError):
        return "the app could not reach the Anthropic API (network problem)."
    return f"{type(e).__name__}: {text[:200]}"


def _ask_tool(system: str, user: str, tool: dict, max_tokens: int = 2000) -> dict | None:
    """Ask Claude to answer by filling in a tool's input schema.

    Forcing a tool call makes Claude reply with structured data that matches the
    schema, instead of free text that we would have to parse.
    """
    global last_error
    if not get_api_key():
        last_error = ("no API key found. Add ANTHROPIC_API_KEY in Streamlit's Settings > Secrets, "
                      "or in the .env file when running on a laptop.")
        return None
    try:
        msg = _client().messages.create(
            model=_model(), max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool], tool_choice={"type": "tool", "name": tool["name"]})
    except Exception as e:
        last_error = _explain(e)
        return None
    for block in msg.content:
        if getattr(block, "type", "") == "tool_use" and isinstance(block.input, dict):
            last_error = None
            return block.input
    if getattr(msg, "stop_reason", "") == "max_tokens":
        last_error = "Claude's answer was cut off because it was too long."
    else:
        last_error = "Claude replied, but not in the expected format."
    return None


# ---------- Job 1: categories for merchants the rules could not place ----------

CATEGORY_SYSTEM = (
    "You sort Canadian bank and credit-card transaction descriptions into spending categories for a "
    "budgeting tool. Descriptions often include a store number, a city and province, and a card-processor "
    "prefix such as 'SQ *' (Square, usually a small cafe, shop or restaurant), 'TST*' (Toast, a restaurant), "
    "'DD *' (DoorDash) or 'PAYPAL *'. Use your knowledge of Canadian businesses. "
    "Pick 'Miscellaneous' only when you genuinely cannot tell what kind of business it is."
)
CATEGORY_TOOL = {
    "name": "record_categories",
    "description": "Record one category for each numbered transaction description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The number of the description."},
                        "category": {"type": "string", "enum": SPENDING_CATEGORIES},
                    },
                    "required": ["id", "category"],
                },
            }
        },
        "required": ["results"],
    },
}
BATCH = 60


def suggest_categories(descriptions: list[str]) -> dict[str, str] | None:
    """Return {description: category} for the descriptions Claude placed.

    Sends the descriptions in batches so long lists are not cut off. Returns None
    only if no batch could be answered (AI unavailable).
    """
    if not descriptions:
        return {}
    out: dict[str, str] = {}
    answered = False
    for start in range(0, min(len(descriptions), 600), BATCH):
        batch = descriptions[start:start + BATCH]
        lines = "\n".join(f"{i}. {d}" for i, d in enumerate(batch))
        data = _ask_tool(CATEGORY_SYSTEM, "Categorize these descriptions:\n" + lines, CATEGORY_TOOL,
                         max_tokens=40 * len(batch) + 300)
        if not data or not isinstance(data.get("results"), list):
            continue
        answered = True
        for item in data["results"]:
            try:
                i, cat = int(item["id"]), item["category"]
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= i < len(batch) and cat in SPENDING_CATEGORIES:
                out[batch[i]] = cat
    return out if answered else None


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
    "Record your answer with the record_insights tool."
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


INSIGHT_TOOL = {
    "name": "record_insights",
    "description": "Record the spending insights and the reworded saving suggestion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "insights": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4,
                         "description": "3 or 4 insights, one or two sentences each."},
            "suggestion": {"type": "string",
                           "description": "The saving suggestion in one or two encouraging sentences, "
                                          "keeping its dollar figures. Empty if there is no suggestion."},
        },
        "required": ["insights", "suggestion"],
    },
}


def write_insights(facts: dict, allowed: set[float]) -> dict | None:
    """Return {"insights": [...], "suggestion": str|None, "dropped": int} or None if AI is unavailable."""
    data = _ask_tool(INSIGHT_SYSTEM, json.dumps(facts, indent=1), INSIGHT_TOOL, max_tokens=1500)
    if data is None or not isinstance(data.get("insights"), list):
        global last_error
        last_error = last_error or "Claude replied, but not in the expected format."
        return None
    raw = [str(x) for x in data["insights"]][:4]
    kept = [t for t in raw if safe(t, allowed)]
    sugg = data.get("suggestion")
    sugg = str(sugg) if sugg and safe(str(sugg), allowed) else None
    return {"insights": kept, "suggestion": sugg, "dropped": len(raw) - len(kept)}
