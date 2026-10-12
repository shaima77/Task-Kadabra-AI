"""Pydantic models shared across the API. These are the contract the React app relies on."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------- /describe ----------
class DescribeRequest(BaseModel):
    need: str = Field(..., description="The user's data need, in their own words.")


class ClarifyOption(BaseModel):
    value: str
    label: str


class ClarifyQuestion(BaseModel):
    id: str
    question: str
    help: Optional[str] = None
    # "choice" renders chips/radios, "text" renders a short input.
    kind: Literal["choice", "text"] = "choice"
    options: list[ClarifyOption] = []
    allow_custom: bool = True


class DescribeResponse(BaseModel):
    session_id: str
    need: str
    restated_need: str
    questions: list[ClarifyQuestion]


# ---------- /recommend (SSE) ----------
class RecommendRequest(BaseModel):
    session_id: str
    answers: dict[str, str] = {}


class FormField(BaseModel):
    """A single field of the generated, plain-language usage form."""
    id: str                      # maps to a real key in the actor input schema
    label: str                   # plain language, no jargon
    help: Optional[str] = None
    kind: Literal["text", "textarea", "number", "select", "multiselect", "toggle", "tags"] = "text"
    options: list[ClarifyOption] = []
    default: Any = None
    placeholder: Optional[str] = None
    required: bool = False


class UsageForm(BaseModel):
    title: str
    subtitle: Optional[str] = None
    run_button_label: str = "Get the data"
    fields: list[FormField] = []


class Alternative(BaseModel):
    source_id: str
    name: str
    tradeoff: str                # honest reason it was NOT chosen


class Recommendation(BaseModel):
    found: bool
    # When found is False, `message` explains why nothing fit.
    message: Optional[str] = None
    source_id: Optional[str] = None
    name: Optional[str] = None
    headline: Optional[str] = None       # one-line why-it-fits
    reasons: list[str] = []              # evidence-backed bullet points
    evidence: list[str] = []            # raw facts gathered (stats, pricing, inputs)
    alternatives: list[Alternative] = []
    form: Optional[UsageForm] = None


# ---------- /run ----------
class RunRequest(BaseModel):
    session_id: str
    values: dict[str, Any] = {}


class DisplaySpec(BaseModel):
    """Tells the frontend how to turn this source's rows into human cards."""
    layout: Literal["cards", "table"] = "cards"
    title_field: Optional[str] = None
    subtitle_field: Optional[str] = None
    image_field: Optional[str] = None
    link_field: Optional[str] = None
    rating_field: Optional[str] = None
    badge_fields: list[str] = []
    detail_fields: list[dict[str, str]] = []   # [{"key":..., "label":...}]


class RunResponse(BaseModel):
    ok: bool
    count: int
    summary: Optional[str] = None
    display: DisplaySpec
    items: list[dict[str, Any]] = []
    message: Optional[str] = None           # set on empty/odd/failed runs
