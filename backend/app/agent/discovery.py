"""The discovery agent — an AUTONOMOUS LangGraph tool-calling agent with hard guardrails.

The LLM drives its own loop: each turn it decides whether to search again, inspect a candidate
in more depth, or conclude. The graph is message-driven (agent ⇄ tools), the real LangGraph
agent pattern. Apify's MCP search/detail tools return human-readable Markdown, which the agent
reads directly; deterministic code only extracts what it must (candidate ids, and the chosen
source's input schema for the form).

    ┌─────────────────────────── loop ───────────────────────────┐
    │                                                             │
    ▼                                                             │
  agent ──has tool calls?──▶ tools ──(search / inspect)───────────┘
    │  │                       │
    │  │                       └──(valid submit, or budget hit)──▶ build_form ──▶ END
    │  └──plain text──▶ nudge once ──▶ agent
    │
    └──(step/time/tool budget exceeded)──▶ build_form (deterministic fallback) ──▶ END

Autonomy is bounded by HARD guardrails enforced in the control flow, not just the prompt:
  • Tool whitelist — only search_sources, get_source_details, submit_recommendation.
    There is deliberately NO tool to run a source, so the agent cannot incur scrape cost;
    running stays behind the explicit, capped /run endpoint.
  • Budgets — max agent steps, max total tool calls, max searches, max detail look-ups, and an
    overall wall-clock deadline. A tool call over budget is refused with a message to wrap up.
  • Validated termination — the agent must finish via submit_recommendation; its arguments are
    deterministically validated (chosen id must be real, reasons required). Invalid submissions
    are bounced back once; if it never submits validly, a deterministic fallback is used.
  • Every model/MCP call is wrapped with per-attempt timeout + retries (reliability layer).
"""
from __future__ import annotations

import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from ..config import get_settings
from ..llm import agent_llm
from ..reliability import StepFailed, run_step
from .. import mcp_client

S = get_settings()


# ----------------------------- tools (schema only; executed by the graph) -----------------------------
@tool
def search_sources(keywords: str) -> str:
    """Search the marketplace of ready-made data sources by keywords (use 2-4 word queries).
    Returns up to 5 candidate sources with their id, description, pricing, rating and usage.
    Keep searches few and focused."""
    return ""


@tool
def get_source_details(source_id: str) -> str:
    """Look up ONE source by its exact id to see the real inputs it accepts, its pricing,
    rating and description. Inspect your most promising candidates before deciding."""
    return ""


@tool
def submit_recommendation(
    found: bool,
    message: str = "",
    source_id: str = "",
    name: str = "",
    headline: str = "",
    reasons: list[str] = None,  # type: ignore[assignment]
    evidence: list[str] = None,  # type: ignore[assignment]
    alternatives: list[str] = None,  # type: ignore[assignment]
) -> str:
    """Finish the task — call this EXACTLY ONCE as your final action.
    If a source fits: found=true, source_id (the EXACT id from search results), a short name,
    a one-sentence headline, 2-4 plain-language reasons, 2-4 concrete evidence facts, and up to
    2 alternatives each written as "Name: why it lost".
    If nothing fits: found=false and explain plainly in message what to try instead.
    Never use jargon (no API, scraper, endpoint, schema)."""
    return ""


TOOLS = [search_sources, get_source_details, submit_recommendation]
_MODEL = agent_llm(temperature=0.3).bind_tools(TOOLS)


# ----------------------------- state -----------------------------
class DiscoveryState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    need: str
    answers: dict[str, str]
    steps: int
    tool_calls_used: int
    searches_used: int
    details_used: int
    nudges: int
    deadline: float
    candidates: dict[str, dict]   # id -> {} (ids seen in search results)
    details: dict[str, dict]      # id -> {} inspected, later the chosen one's input schema
    recommendation: dict
    event: str


# ----------------------------- helpers -----------------------------
def _answers_text(answers: dict[str, str]) -> str:
    if not answers:
        return "(no clarifying answers provided)"
    return "\n".join(f"- {k}: {v}" for k, v in answers.items())


def _known_ids(candidates: dict, details: dict) -> set[str]:
    return set(candidates) | set(details)


def _parse_alternatives(items: list[str] | None) -> list[dict]:
    out = []
    for raw in (items or [])[:2]:
        text = str(raw)
        name, tradeoff = text, ""
        for sep in (":", " — ", " - ", "—", "|"):
            if sep in text:
                name, tradeoff = text.split(sep, 1)
                break
        out.append({"source_id": "", "name": name.strip(), "tradeoff": tradeoff.strip()})
    return out


def _validate_submit(args: dict, known: set[str]) -> list[str]:
    """Deterministic guardrail on the agent's terminal action."""
    errors: list[str] = []
    if args.get("found"):
        sid = (args.get("source_id") or "").strip()
        if not sid or sid not in known:
            errors.append("source_id must be one of the ids returned by search_sources")
        if not (args.get("name") or "").strip():
            errors.append("name is required")
        if not (args.get("headline") or "").strip():
            errors.append("headline is required")
        if not (args.get("reasons") or []):
            errors.append("at least one reason is required")
    else:
        if not (args.get("message") or "").strip():
            errors.append("message explaining why nothing fits is required")
    return errors


def _normalize_submit(args: dict) -> dict:
    return {
        "found": bool(args.get("found")),
        "message": (args.get("message") or None),
        "source_id": (args.get("source_id") or None),
        "name": (args.get("name") or None),
        "headline": (args.get("headline") or None),
        "reasons": list(args.get("reasons") or []),
        "evidence": list(args.get("evidence") or []),
        "alternatives": _parse_alternatives(args.get("alternatives")),
    }


def _fallback_recommendation(state: DiscoveryState) -> dict:
    """Deterministic recommendation used if the agent exhausts its budget or never submits a
    valid choice. Picks a source it actually looked at; build_form fills in the display name."""
    candidates = state.get("candidates", {})
    details = state.get("details", {})
    inspected = [i for i in details if i in candidates]
    pool = inspected or list(candidates)
    if not pool:
        return {"found": False, "reasons": [], "evidence": [], "alternatives": [],
                "message": "I couldn't find a source that clearly fits. Try describing the data "
                           "a little differently."}
    return {
        "found": True,
        "source_id": pool[0],
        "name": None,  # build_form derives a readable name from the source's schema
        "headline": f"The closest match we found for '{state.get('need', 'your request')}'.",
        "reasons": ["Best overall match among the sources we reviewed for your request."],
        "evidence": [],
        "alternatives": [],
    }


SYSTEM = """You are an autonomous researcher who finds the single best ready-made data source
for a non-technical marketer, then hands off a recommendation.

You work by yourself using these tools — never ask the user anything:
  • search_sources(keywords, limit): find candidate sources (results come back as a short
    report you read).
  • get_source_details(source_id): inspect one promising source in depth.
  • submit_recommendation(...): your FINAL action, called exactly once.

How to work (be fast and economical — do NOT over-research):
1. Do ONE search with your best keywords. It returns up to 5 candidates. Only search a second
   time if the first results clearly miss the need — never search more than twice total.
2. Inspect only your 2-3 most promising candidates with get_source_details.
3. Then STOP searching and call submit_recommendation with the winner, honest reasons and
   evidence you actually gathered, and up to two alternatives with honest trade-offs.

Hard limits you must respect: at most 2 searches and a few look-ups — submit before the budget
runs out. You CANNOT run any source or fetch live data — you only research and recommend.
Always use the EXACT source id (looks like "username/name") shown in the search results. If
nothing fits, submit with found=false and say what to try instead. No technical jargon."""


# ----------------------------- nodes -----------------------------
async def agent_node(state: DiscoveryState) -> DiscoveryState:
    steps = state.get("steps", 0) + 1
    over_budget = (
        steps > S.agent_max_steps
        or state.get("tool_calls_used", 0) >= S.agent_max_tool_calls
        or time.monotonic() > state.get("deadline", 0)
    )
    if over_budget:
        return {"steps": steps, "recommendation": _fallback_recommendation(state),
                "_force_end": True, "event": "Finalising the best option within budget…"}

    try:
        ai: AIMessage = await run_step(
            lambda: _MODEL.ainvoke(state["messages"]),
            label="agent", attempts=S.step_max_retries, timeout=S.reasoning_timeout_secs,
        )
    except StepFailed:
        return {"steps": steps, "recommendation": _fallback_recommendation(state),
                "_force_end": True, "event": "Finalising the best option…"}

    return {"messages": [ai], "steps": steps, "event": _describe_intent(ai)}


def _describe_intent(ai: AIMessage) -> str:
    calls = getattr(ai, "tool_calls", None) or []
    names = [c.get("name") for c in calls]
    if "submit_recommendation" in names:
        return "Choosing the best fit…"
    for c in calls:
        if c.get("name") == "search_sources":
            kw = (c.get("args") or {}).get("keywords", "")
            return f'Searching for "{kw}"…'
    if "get_source_details" in names:
        return "Taking a closer look at the strongest candidates…"
    return "Thinking about where to look…"


async def tools_node(state: DiscoveryState) -> DiscoveryState:
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []

    searches = state.get("searches_used", 0)
    details_used = state.get("details_used", 0)
    used = state.get("tool_calls_used", 0)
    candidates = dict(state.get("candidates", {}))
    details = dict(state.get("details", {}))
    out_msgs: list[ToolMessage] = []
    events: list[str] = []
    recommendation: dict | None = None

    for tc in calls:
        name = tc.get("name")
        args = tc.get("args") or {}
        call_id = tc.get("id")
        used += 1

        if name == "search_sources":
            if searches >= S.agent_max_searches:
                out_msgs.append(ToolMessage(
                    content="Search budget reached. Inspect a candidate or submit now.",
                    tool_call_id=call_id))
                continue
            kw = str(args.get("keywords", "")).strip()[:120]
            lim = S.search_results_per_query
            res = await run_step(
                lambda kw=kw, lim=lim: mcp_client.search_actors(kw, limit=lim),
                label=f"search:{kw}", attempts=S.step_max_retries,
                timeout=S.search_timeout_secs, fallback={"markdown": "(search unavailable)", "ids": []})
            searches += 1
            for sid in res.get("ids", []):
                candidates.setdefault(sid, {})
            events.append(f'searched "{kw}" ({len(res.get("ids", []))} found)')
            out_msgs.append(ToolMessage(content=(res.get("markdown") or "")[:6000], tool_call_id=call_id))

        elif name == "get_source_details":
            if details_used >= S.max_candidates:
                out_msgs.append(ToolMessage(
                    content="Look-up budget reached. Submit your recommendation now.",
                    tool_call_id=call_id))
                continue
            sid = str(args.get("source_id", "")).strip()
            md = await run_step(
                lambda sid=sid: mcp_client.fetch_actor_details(sid),
                label=f"inspect:{sid}", attempts=S.step_max_retries,
                timeout=S.search_timeout_secs, fallback="(details unavailable)")
            details_used += 1
            details.setdefault(sid, {})
            events.append(f"checked {sid}")
            out_msgs.append(ToolMessage(content=(md or "")[:6000], tool_call_id=call_id))

        elif name == "submit_recommendation":
            errs = _validate_submit(args, _known_ids(candidates, details))
            if errs:
                out_msgs.append(ToolMessage(
                    content="Recommendation not accepted: " + "; ".join(errs)
                            + ". Please fix and call submit_recommendation again.",
                    tool_call_id=call_id))
            else:
                recommendation = _normalize_submit(args)
                out_msgs.append(ToolMessage(content="Recommendation accepted.", tool_call_id=call_id))

        else:
            out_msgs.append(ToolMessage(content="Unknown tool.", tool_call_id=call_id))

    result: DiscoveryState = {
        "messages": out_msgs,
        "searches_used": searches,
        "details_used": details_used,
        "tool_calls_used": used,
        "candidates": candidates,
        "details": details,
    }
    if events:
        result["event"] = _humanise_events(events)
    if recommendation is not None:
        result["recommendation"] = recommendation
    return result


def _humanise_events(events: list[str]) -> str:
    searched = [e for e in events if e.startswith("searched")]
    checked = [e.split(" ", 1)[1] for e in events if e.startswith("checked")]
    parts = []
    if searched:
        parts.append(searched[-1].capitalize())
    if checked:
        parts.append("Looked closely at " + ", ".join(checked))
    return " · ".join(parts) or "Gathering evidence…"


async def nudge_node(state: DiscoveryState) -> DiscoveryState:
    """The model answered in prose instead of submitting — remind it once to use the tool."""
    return {
        "nudges": state.get("nudges", 0) + 1,
        "messages": [HumanMessage(content="Please finish by calling submit_recommendation with "
                                          "your final choice (or found=false if nothing fits).")],
    }


async def build_form(state: DiscoveryState) -> DiscoveryState:
    from .form import generate_usage_form  # local import avoids a circular import

    rec = dict(state.get("recommendation") or {})
    if not rec.get("found") or not rec.get("source_id"):
        return {"recommendation": rec, "event": "Done."}

    sid = rec["source_id"]
    # Fetch the chosen source's real input schema (structured) to build the form.
    schema = await run_step(
        lambda: mcp_client.fetch_input_schema(sid),
        label=f"schema:{sid}", attempts=S.step_max_retries,
        timeout=S.search_timeout_secs, fallback={})
    detail = {"inputSchema": schema}

    name = rec.get("name") or schema.get("title") or sid
    rec["name"] = name
    form = await generate_usage_form(
        need=state["need"], answers=state.get("answers", {}), source_name=name, detail=detail)
    rec["form"] = form.model_dump()

    details = dict(state.get("details", {}))
    details[sid] = detail  # so /run can read the chosen source's schema
    return {"recommendation": rec, "details": details,
            "event": "Built a simple form tailored to this source."}


# ----------------------------- routing -----------------------------
def _route_after_agent(state: DiscoveryState) -> str:
    if state.get("_force_end"):
        return "build_form"
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "nudge" if state.get("nudges", 0) < 1 else "build_form"


def _route_after_tools(state: DiscoveryState) -> str:
    if state.get("recommendation"):
        return "build_form"
    if state.get("tool_calls_used", 0) >= S.agent_max_tool_calls:
        return "finalize"
    return "agent"


async def finalize(state: DiscoveryState) -> DiscoveryState:
    rec = state.get("recommendation") or _fallback_recommendation(state)
    return {"recommendation": rec, "event": "Finalising the best option…"}


# ----------------------------- graph -----------------------------
def build_discovery_graph():
    g = StateGraph(DiscoveryState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("nudge", nudge_node)
    g.add_node("finalize", finalize)
    g.add_node("build_form", build_form)

    g.set_entry_point("agent")
    g.add_conditional_edges("agent", _route_after_agent,
                            {"tools": "tools", "nudge": "nudge", "build_form": "build_form"})
    g.add_conditional_edges("tools", _route_after_tools,
                            {"agent": "agent", "finalize": "finalize", "build_form": "build_form"})
    g.add_edge("nudge", "agent")
    g.add_edge("finalize", "build_form")
    g.add_edge("build_form", END)
    return g.compile()


discovery_graph = build_discovery_graph()


def initial_state(need: str, answers: dict[str, str]) -> DiscoveryState:
    """Seed the agent with the task and start its guardrail clock."""
    user = f"The user's data need: {need}\n\nClarifying answers:\n{_answers_text(answers)}"
    return {
        "messages": [SystemMessage(content=SYSTEM), HumanMessage(content=user)],
        "need": need,
        "answers": answers,
        "steps": 0,
        "tool_calls_used": 0,
        "searches_used": 0,
        "details_used": 0,
        "nudges": 0,
        "deadline": time.monotonic() + S.agent_timeout_secs,
        "candidates": {},
        "details": {},
    }
