"""FastAPI app: the only thing the browser talks to. Secrets never leave this process.

Endpoints map to the user journey:
  POST /api/describe   -> clarifying questions
  POST /api/recommend  -> Server-Sent Events: live progress, then the recommendation + form
  POST /api/run        -> run the chosen source (capped) and return human-ready results
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .agent.clarify import generate_clarifying_questions
from .agent.discovery import discovery_graph, initial_state
from .agent.display import build_display_spec
from .config import get_settings
from .models import (
    DescribeRequest, DescribeResponse, DisplaySpec, Recommendation,
    RecommendRequest, RunRequest, RunResponse,
)
from .store import store
from . import validation as V

settings = get_settings()
settings.require()

app = FastAPI(title="Data Finder", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/api/describe", response_model=DescribeResponse)
async def describe(req: DescribeRequest) -> DescribeResponse:
    need = V.clean_need(req.need)
    errors = V.validate_need(need)
    if errors:
        raise HTTPException(400, " ".join(errors))
    sess = store.create(need)
    out = await generate_clarifying_questions(need)
    sess.restated_need = out.restated_need
    return DescribeResponse(
        session_id=sess.id,
        need=need,
        restated_need=out.restated_need,
        questions=out.questions,
    )


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    try:
        sess = store.get(req.session_id)
    except KeyError:
        raise HTTPException(404, "Session not found. Please start again.")
    sess.answers = req.answers or {}

    async def gen():
        merged: dict[str, Any] = {}
        initial = initial_state(sess.need, sess.answers)
        # recursion_limit is a backstop; the agent's own step/tool/time budgets stop it first.
        config = {"recursion_limit": 2 * (settings.agent_max_steps + settings.max_candidates) + 10}
        try:
            async for update in discovery_graph.astream(initial, config=config):
                for _node, delta in update.items():
                    if not isinstance(delta, dict):
                        continue
                    # Merge only the scalar/collection keys we care about (ignore message deltas).
                    for key in ("recommendation", "details", "candidates", "event"):
                        if key in delta:
                            merged[key] = delta[key]
                    if delta.get("event"):
                        yield _sse("progress", {"message": delta["event"]})
        except Exception as exc:  # the whole discovery failed
            yield _sse("error", {"message": f"Something went wrong while searching: {exc}"})
            return

        rec = merged.get("recommendation") or {"found": False,
                                               "message": "I couldn't find a matching source."}
        # Persist what /run needs.
        if rec.get("found") and rec.get("source_id"):
            sess.chosen_source_id = rec["source_id"]
            sess.chosen_source_name = rec.get("name") or rec["source_id"]
            sess.chosen_detail = (merged.get("details") or {}).get(rec["source_id"], {})
            sess.form = rec.get("form") or {}
        yield _sse("result", Recommendation(**rec).model_dump())

    return EventSourceResponse(gen())


# ---------------- run ----------------
# Nouns that, combined with max/limit, denote a result-count knob we should cap.
_COUNT_NOUNS = ("result", "review", "item", "post", "comment", "page", "record",
                "tweet", "video", "photo", "listing", "product", "place", "lead")


def _is_result_cap(key: str) -> bool:
    k = key.lower()
    if "limit" in k:
        return True
    if "max" in k and any(n in k for n in _COUNT_NOUNS):
        return True
    if k in ("resultsperpage", "count"):
        return True
    return False


def _coerce(value: Any, spec: dict) -> Any:
    t = spec.get("type")
    try:
        if t == "integer":
            return int(value)
        if t == "number":
            return float(value)
        if t == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if t == "array":
            if isinstance(value, list):
                items = value
            elif value is None or value == "":
                items = []
            else:
                # split a textarea/string into a list
                items = [p.strip() for p in str(value).replace(",", "\n").splitlines() if p.strip()]
            # Many Apify list inputs expect objects like {"url": "..."} rather than bare
            # strings. Wrap strings to match the schema's item shape.
            item_schema = spec.get("items") or {}
            if item_schema.get("type") == "object":
                item_props = item_schema.get("properties") or {}
                target = "url" if "url" in item_props else (next(iter(item_props), None))
                wrapped = []
                for it in items:
                    if isinstance(it, dict):
                        wrapped.append(it)
                    elif target:
                        wrapped.append({target: it})
                return wrapped
            return items
    except (ValueError, TypeError):
        return value
    return value


def _build_run_input(values: dict, detail: dict) -> dict:
    props = (detail.get("inputSchema") or {}).get("properties") or {}
    run_input: dict[str, Any] = {}
    for key, val in (values or {}).items():
        if key in props and val not in (None, "", []):
            run_input[key] = _coerce(val, props[key])

    cap = settings.max_results
    # Ensure every result-count knob the source exposes is capped — even if the user
    # never saw it — so one click can't trigger a huge, expensive run.
    for key, spec in props.items():
        if _is_result_cap(key) and spec.get("type") in ("integer", "number"):
            current = run_input.get(key, spec.get("prefill", spec.get("default")))
            try:
                run_input[key] = min(int(current), cap) if current is not None else cap
            except (ValueError, TypeError):
                run_input[key] = cap
    return run_input


@app.post("/api/run", response_model=RunResponse)
async def run(req: RunRequest) -> RunResponse:
    try:
        sess = store.get(req.session_id)
    except KeyError:
        raise HTTPException(404, "Session not found. Please start again.")
    if not sess.chosen_source_id:
        raise HTTPException(400, "No source selected yet.")

    # Deterministic input validation before we spend an Apify run.
    missing = V.validate_run_input(req.values, sess.chosen_detail)
    if missing:
        labels = {f.get("id"): f.get("label") for f in (sess.form.get("fields") or [])}
        names = [labels.get(k, k) for k in missing]
        raise HTTPException(400, f"Please fill in: {', '.join(names)}.")

    from . import mcp_client  # local import keeps startup light

    run_input = _build_run_input(req.values, sess.chosen_detail)
    try:
        result = await mcp_client.call_actor(sess.chosen_source_id, run_input)
    except Exception as exc:
        return RunResponse(ok=False, count=0, display=DisplaySpec(),
                           message=f"The run couldn't complete: {exc}")

    status = result.get("status", "UNKNOWN")
    items = V.sanitize_items(result.get("items", []))  # output-data guard

    if not items:
        if status in ("FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT"):
            msg = "This source couldn't complete the request. Try different or broader inputs."
        elif status == "RUNNING":
            msg = "This is taking longer than expected. Try again, or narrow your request."
        else:
            msg = "The source ran but found nothing for these inputs. Try broadening your search."
        return RunResponse(ok=status == "SUCCEEDED", count=0, display=DisplaySpec(), message=msg)

    display, summary = await build_display_spec(sess.need, sess.chosen_source_name or "", items)
    return RunResponse(ok=True, count=len(items), summary=summary, display=display, items=items)


# ---------------- static frontend (production build), optional ----------------
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
