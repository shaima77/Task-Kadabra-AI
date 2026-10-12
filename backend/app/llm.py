"""Gemini access. All LLM calls in the product go through here.

Model choice (see README): we default both roles to gemini-2.5-flash. Flash is fast and
cheap, which matters because the discovery phase makes several calls per user request.
The utility model can be pointed at gemini-2.5-pro via env if a need demands deeper
judgment, at higher latency/cost.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from .config import get_settings
from .reliability import run_step

T = TypeVar("T", bound=BaseModel)

_UNSET = object()


def _llm(model: str, temperature: float) -> ChatGoogleGenerativeAI:
    s = get_settings()
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=s.gemini_api_key,
        temperature=temperature,
    )


def agent_llm(temperature: float = 0.3) -> ChatGoogleGenerativeAI:
    return _llm(get_settings().agent_model, temperature)


def utility_llm(temperature: float = 0.1) -> ChatGoogleGenerativeAI:
    return _llm(get_settings().utility_model, temperature)


async def structured(
    schema: Type[T],
    system: str,
    user: str,
    *,
    use_agent_model: bool = False,
    temperature: float = 0.2,
    validate: Optional[Callable[[T], list[str]]] = None,
    fallback: Any = _UNSET,
    label: str = "reasoning",
) -> T:
    """Run one Gemini call that must return an instance of `schema`.

    Structured output keeps the boundary clean: the LLM supplies judgment and language, while
    Pydantic validates the *shape*. On top of that this call is wrapped with a per-attempt
    timeout, up to `STEP_MAX_RETRIES` retries, an optional deterministic `validate` (semantic
    checks beyond Pydantic — a failure triggers a retry), and an optional deterministic
    `fallback` used when every attempt fails, so a flaky or slow model never breaks the journey.
    """
    s = get_settings()
    model = s.agent_model if use_agent_model else s.utility_model
    llm = _llm(model, temperature).with_structured_output(schema)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    return await run_step(
        lambda: llm.ainvoke(messages),
        label=label,
        attempts=s.step_max_retries,
        timeout=s.reasoning_timeout_secs,
        validate=validate,
        fallback=fallback,
    )
