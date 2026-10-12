"""Apify access — exclusively through Apify's hosted MCP server.

The product never calls the Apify REST API directly and never exposes Apify to the
browser. Everything (discovery, actor details, running an actor) goes through MCP tools,
with the token attached as a server-side Authorization header.

Tool names are resolved dynamically from the server's own tools/list so we don't hard-code
Apify's naming conventions.
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from typing import Any, Optional

from mcp import ClientSession

try:  # mcp >= 2.x
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
except ImportError:  # mcp < 2.x
    from mcp.client.streamable_http import streamablehttp_client

from .config import get_settings


class ApifyMCPError(RuntimeError):
    pass


def _authed_url() -> str:
    """Apify MCP accepts the token as a query param. We attach it server-side only — it never
    reaches the browser. (mcp 2.x dropped the headers= kwarg from the transport.)"""
    s = get_settings()
    url = s.apify_mcp_url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}token={s.apify_token}"


@asynccontextmanager
async def _session():
    # mcp 2.x: transport yields a (read, write) pair; auth travels in the URL.
    async with streamablehttp_client(_authed_url()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _parse_tool_result(result: Any) -> Any:
    """Normalize an MCP tool result into plain Python (dict/list/str)."""
    # Prefer structured content when the server provides it (mcp 2.x: structured_content).
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured:
        return structured

    out: list[Any] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            out.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            out.append(text)

    if not out:
        return None
    if len(out) == 1:
        return out[0]
    return out


_TOOL_CACHE: dict[str, str] = {}


async def _resolve_tool(session: ClientSession, *keywords: str) -> str:
    """Find a tool whose name contains all given keywords (case-insensitive)."""
    cache_key = "|".join(keywords)
    if cache_key in _TOOL_CACHE:
        return _TOOL_CACHE[cache_key]

    tools = (await session.list_tools()).tools
    names = [t.name for t in tools]
    for name in names:
        low = name.lower()
        if all(k in low for k in keywords):
            _TOOL_CACHE[cache_key] = name
            return name
    raise ApifyMCPError(
        f"No Apify MCP tool matched keywords {keywords}. Available: {names}"
    )


async def list_tool_names() -> list[str]:
    async with _session() as session:
        return [t.name for t in (await session.list_tools()).tools]


def _coerce_items(parsed: Any) -> list[dict]:
    """Pull a list of record dicts out of whatever shape a tool returned."""
    if parsed is None:
        return []
    if isinstance(parsed, list):
        # Could be a list of records, or a list with a single wrapper object.
        if len(parsed) == 1 and isinstance(parsed[0], dict) and "items" in parsed[0]:
            return _coerce_items(parsed[0])
        return [p for p in parsed if isinstance(p, dict)]
    if isinstance(parsed, dict):
        for key in ("items", "data", "results", "actors"):
            val = parsed.get(key)
            if isinstance(val, list):
                return [v for v in val if isinstance(v, dict)]
        # dict that itself looks like a record
        return [parsed]
    return []


def _result_text(result: Any) -> str:
    """Join all text blocks of a tool result into one string (Apify's human-readable tools
    return Markdown, which is ideal for the agent to read directly)."""
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# `username/name` ids appear in the search Markdown inside backticks.
_ID_RE = re.compile(r"`([a-z0-9][\w.-]*/[\w.-]+)`", re.IGNORECASE)


async def search_actors(query: str, limit: int = 8) -> dict:
    """Search the Apify Store. Returns {"markdown": <human-readable results for the agent>,
    "ids": [source ids found]}. (The MCP tool now returns Markdown, not JSON.)"""
    async with _session() as session:
        tool = await _resolve_tool(session, "search", "actor")
        result = await session.call_tool(tool, {"keywords": query, "limit": min(limit, 10)})
        text = _result_text(result)
        ids: list[str] = []
        for m in _ID_RE.finditer(text):
            if m.group(1) not in ids:
                ids.append(m.group(1))
        return {"markdown": text, "ids": ids}


# Default detail sections shown to the agent — concise, no raw input schema.
_DETAIL_OUTPUT = {"description": True, "pricing": True, "rating": True,
                  "stats": True, "metadata": True, "inputSchema": True}


async def fetch_actor_details(actor_id: str, output: dict | None = None) -> str:
    """Get a single source's details as Markdown (for the agent to read)."""
    async with _session() as session:
        tool = await _resolve_tool(session, "fetch", "details")
        result = await session.call_tool(
            tool, {"actor": actor_id, "output": output or _DETAIL_OUTPUT})
        return _result_text(result)


_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


async def fetch_input_schema(actor_id: str) -> dict:
    """Fetch and parse a source's real input schema (structured), for building the usage form.
    The detail tool embeds the schema as a ```json``` block; we extract and parse it."""
    async with _session() as session:
        tool = await _resolve_tool(session, "fetch", "details")
        result = await session.call_tool(tool, {"actor": actor_id, "output": {"inputSchema": True}})
        text = _result_text(result)
    for block in _JSON_BLOCK_RE.findall(text):
        try:
            schema = json.loads(block)
            if isinstance(schema, dict) and schema.get("properties"):
                return schema
        except json.JSONDecodeError:
            continue
    return {}


_TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT"}


def flatten_record(obj: Any, prefix: str = "") -> dict:
    """Flatten nested dicts into dot-notation keys so the frontend can render uniformly.
    Lists and scalars are kept as-is (a list of strings/objects stays under one key)."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten_record(v, key))
            else:
                out[key] = v
    else:
        out[prefix or "value"] = obj
    return out


async def _get_dataset_items(session: ClientSession, dataset_id: str, limit: int) -> list[dict]:
    tool = await _resolve_tool(session, "get-dataset", "items")
    result = await session.call_tool(tool, {"datasetId": dataset_id, "limit": limit, "clean": True})
    items = _coerce_items(_parse_tool_result(result))[:limit]
    return [flatten_record(it) for it in items]


async def _poll_run(session: ClientSession, run_id: str, deadline_secs: int) -> dict:
    """Wait for a run to reach a terminal state, within an overall budget."""
    import time as _time

    tool = await _resolve_tool(session, "get-actor-run")
    start = _time.monotonic()
    last: dict = {}
    while _time.monotonic() - start < deadline_secs:
        remaining = deadline_secs - (_time.monotonic() - start)
        wait = max(1, min(int(remaining), 30))
        res = _parse_tool_result(await session.call_tool(tool, {"runId": run_id, "waitSecs": wait}))
        if isinstance(res, list):
            res = next((p for p in res if isinstance(p, dict)), {})
        last = res or last
        if (last.get("status") or "").upper() in _TERMINAL:
            break
    return last


async def call_actor(actor_id: str, run_input: dict, timeout: Optional[int] = None) -> dict:
    """Run a source and return {status, status_message, items, item_count}.

    `call-actor` returns a run summary (status + dataset id), not the rows, so we then
    fetch the rows from the run's dataset — capped to MAX_RESULTS to keep cost bounded.
    """
    import asyncio as _asyncio
    import time as _time

    s = get_settings()
    deadline_secs = timeout or s.actor_run_timeout_secs

    def _dataset_of(obj: dict) -> Optional[str]:
        return (obj.get("defaultDatasetId")
                or (obj.get("storages", {}) or {}).get("datasets", {}).get("default", {}).get("id"))

    async with _session() as session:
        call_tool_name = await _resolve_tool(session, "call", "actor")
        run_tool = await _resolve_tool(session, "get-actor-run")
        # Short initial wait, then poll for ITEMS — we only need up to MAX_RESULTS, so there's
        # no reason to wait for a broad scrape to finish.
        summary = _parse_tool_result(await session.call_tool(
            call_tool_name,
            {"actor": actor_id, "input": run_input, "waitSecs": min(deadline_secs, 15)}))
        if isinstance(summary, list):
            summary = next((p for p in summary if isinstance(p, dict)), {})
        summary = summary or {}

        status = (summary.get("status") or "UNKNOWN").upper()
        status_message = summary.get("statusMessage", "")
        run_id = summary.get("runId")
        dataset_id = _dataset_of(summary)

        start = _time.monotonic()
        items: list[dict] = []
        while True:
            if dataset_id:
                items = await _get_dataset_items(session, dataset_id, s.max_results)
            if len(items) >= s.max_results:
                break                                   # we have enough — stop early
            if status in _TERMINAL:
                if not items and status == "SUCCEEDED":  # dataset can lag a beat
                    await _asyncio.sleep(1.5)
                    if dataset_id:
                        items = await _get_dataset_items(session, dataset_id, s.max_results)
                break
            if _time.monotonic() - start >= deadline_secs or not run_id:
                break
            remaining = deadline_secs - (_time.monotonic() - start)
            res = _parse_tool_result(await session.call_tool(
                run_tool, {"runId": run_id, "waitSecs": max(1, min(int(remaining), 10))}))
            if isinstance(res, list):
                res = next((p for p in res if isinstance(p, dict)), {})
            res = res or {}
            status = (res.get("status") or status).upper()
            status_message = res.get("statusMessage", status_message)
            dataset_id = dataset_id or _dataset_of(res)

        # Cost cap: if the run is still going but we already have what we need (or ran out of
        # time), abort it so it stops charging.
        if status not in _TERMINAL and run_id:
            try:
                abort_tool = await _resolve_tool(session, "abort", "actor", "run")
                await session.call_tool(abort_tool, {"runId": run_id})
                status_message = status_message or "Stopped early after collecting enough results."
            except Exception:
                pass

        return {
            "status": status,
            "status_message": status_message,
            "items": items,
            "item_count": len(items),
        }
