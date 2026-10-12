"""Deterministic validators — pure functions, no LLM, no network.

Two jobs:
  1. Validate *input* data at the API boundary (the need text, the run form values) before we
     spend any LLM or Apify call on it.
  2. Validate *output* data from the LLM steps (the generated form and the results display) so
     a malformed or hallucinated result is caught and retried, and never reaches the user or a
     downstream Apify call. (The agent's recommendation is validated in agent/discovery.py.)

Each validator returns a list of human-readable error strings; an empty list means valid.
Keeping these deterministic (and cheap) is what lets us retry only when necessary and fall
back without another model call.
"""
from __future__ import annotations

from typing import Any

MAX_NEED_LEN = 500
MIN_NEED_LEN = 3


# --------------------------- input validation ---------------------------
def clean_need(need: str) -> str:
    return " ".join((need or "").split()).strip()


def validate_need(need: str) -> list[str]:
    errors: list[str] = []
    n = clean_need(need)
    if len(n) < MIN_NEED_LEN:
        errors.append("Please describe what data you're looking for.")
    if len(n) > MAX_NEED_LEN:
        errors.append(f"That's a bit long — please keep it under {MAX_NEED_LEN} characters.")
    return errors


def schema_props(detail: dict) -> dict:
    return (detail.get("inputSchema") or {}).get("properties") or {}


def required_keys(detail: dict) -> set[str]:
    return set((detail.get("inputSchema") or {}).get("required") or [])


def validate_run_input(values: dict, detail: dict) -> list[str]:
    """Flag required inputs the user genuinely left blank. Returns the schema keys that are
    missing (caller maps them to friendly labels).

    We deliberately do NOT flag a required field that the schema gives a default or prefill:
    the source supplies that value itself, so blocking the run would second-guess what the
    source (and the agent's form design) already handle. Only a required input with no value
    and no fallback is a real problem.
    """
    props = schema_props(detail)
    required = required_keys(detail)
    missing: list[str] = []
    for key in required:
        spec = props.get(key)
        if not spec:
            continue
        if values.get(key) not in (None, "", [], {}):
            continue  # user provided it
        if spec.get("default") is not None or spec.get("prefill") is not None:
            continue  # the source fills it in
        missing.append(key)
    return missing


# --------------------------- output validation ---------------------------
# Note: the agent's terminal action is validated by `_validate_submit` in agent/discovery.py,
# next to the graph it guards.
def validate_form(out: Any, props: dict) -> list[str]:
    """The generated form must have at least one field bound to a REAL input key."""
    fields = getattr(out, "fields", None) or []
    if not fields:
        return ["form has no fields"]
    bound = [f for f in fields if getattr(f, "schema_key", None) in props]
    if not bound:
        return ["no form field maps to a real input"]
    return []


def validate_display(out: Any, keys: list[str]) -> list[str]:
    """Display must summarise results and, where it names fields, name real ones."""
    errors: list[str] = []
    if not (getattr(out, "summary", None) or "").strip():
        errors.append("missing results summary")
    valid = set(keys)
    for attr in ("title_field", "subtitle_field", "image_field", "link_field", "rating_field"):
        v = getattr(out, attr, None)
        if v and v not in valid:
            errors.append(f"{attr} points to a non-existent field")
    return errors


def sanitize_items(items: Any) -> list[dict]:
    """Output-data guard: keep only well-formed record dicts."""
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]
