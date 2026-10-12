"""Clarify step: an LLM-as-judge decides whether clarification is needed at all, and only
then asks the few questions that genuinely change the choice.

The key discipline is restraint — the model first JUDGES whether anything needs clarifying;
if the request is already specific enough to choose a source, it asks nothing. When it does
ask, only questions whose answer would change which source we recommend (or how we'd run it),
and never anything it can reasonably infer itself.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import structured
from ..models import ClarifyOption, ClarifyQuestion


class _ClarifyOut(BaseModel):
    restated_need: str = Field(
        ..., description="One sentence restating what the user actually wants, in plain language."
    )
    # LLM-as-judge: is any clarification actually needed to choose/run the best source?
    needs_clarification: bool = Field(
        ..., description="True only if an answer would change which source is best or how to run it."
    )
    judge_reason: str = Field(
        "", description="One short sentence explaining the clarify/skip decision."
    )
    questions: list[ClarifyQuestion] = Field(default_factory=list)


SYSTEM = """You help a non-technical marketer turn a vague data request into a precise one.

You act as a JUDGE first, then (only if the judgment calls for it) an interviewer.

You will be given what the user typed. Produce:
1) restated_need: one plain sentence of what they actually want.
2) needs_clarification: your judgment — true ONLY if an answer would change WHICH data source
   is best, or how we would run it, AND you cannot reasonably infer it yourself. Dimensions that
   sometimes matter: geography/region, language, how fresh the data must be, how much they need
   (a few vs thousands), the specific platform or site, and what they'll DO with it.
3) judge_reason: one short sentence explaining your decision.
4) questions: if needs_clarification is false, return an EMPTY list. If true, the few questions
   that truly matter — at most 3.

How to judge:
- Default to NOT asking. If the request is already specific enough to pick a source, set
  needs_clarification=false and ask nothing. Do not invent questions to have some.
- Only set true when a real ambiguity would change the chosen source or the run.

Hard rules:
- NEVER ask something you can reasonably infer. Do not ask for technical details.
- No jargon. Never say API, scraper, dataset, actor, endpoint, or schema.
- Plain words a marketer uses. Each question must be answerable in a few seconds.
- Prefer "choice" questions with 2-5 concrete options when the dimension is well-known
  (e.g. region, freshness). Use "text" only when options can't be enumerated.
- Every choice question MUST include options. Always allow a custom answer.
- Phrase options as human labels (value can equal the label)."""


def _clarify_fallback(need: str) -> _ClarifyOut:
    # Reliability fallback: if the model can't be reached, skip clarifying rather than fail —
    # the discovery step can still run on the raw need.
    return _ClarifyOut(restated_need=need, needs_clarification=False,
                       judge_reason="Model unavailable; proceeding without clarification.",
                       questions=[])


async def generate_clarifying_questions(need: str) -> _ClarifyOut:
    out = await structured(
        _ClarifyOut,
        system=SYSTEM,
        user=f'The user typed: "{need}"',
        temperature=0.3,
        label="clarify",
        validate=lambda o: ([] if (o.restated_need or "").strip() else ["missing restated need"]),
        fallback=lambda: _clarify_fallback(need),
    )
    # Enforce the judge's verdict: no questions unless it decided clarification is needed.
    if not out.needs_clarification:
        out.questions = []
        return out
    # Safety net: cap questions and guarantee IDs/options are well-formed.
    cleaned: list[ClarifyQuestion] = []
    for i, q in enumerate(out.questions[:3]):
        if not q.id:
            q.id = f"q{i+1}"
        if q.kind == "choice" and not q.options:
            q.kind = "text"
        # de-dup empty option labels
        q.options = [ClarifyOption(value=o.value or o.label, label=o.label or o.value)
                     for o in q.options if (o.label or o.value)]
        cleaned.append(q)
    out.questions = cleaned
    return out
