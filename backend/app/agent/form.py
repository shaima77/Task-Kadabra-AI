"""Generate the 'Use' form from the chosen source's REAL input schema.

The form is not generic: the model is given the source's actual input fields and the user's
need, and must (a) keep only the fields that matter for this need, (b) relabel them in plain
language, (c) pre-fill sensible defaults derived from the need, and (d) keep each field bound
to a real schema key so /run can send valid input. We validate the binding before trusting it.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..llm import structured
from ..models import ClarifyOption, FormField, UsageForm
from .. import validation as V


# Keys that control how many results a run returns — capped in /run regardless.
LIMIT_KEYS = {
    "maxitems", "maxresults", "resultslimit", "maxitemsperquery", "maxpagesperquery",
    "limit", "maxrequestretries", "resultsperpage", "maxposts", "maxcomments",
}


def _schema_properties(detail: dict) -> dict:
    return (detail.get("inputSchema") or {}).get("properties") or {}


def _required_keys(detail: dict) -> set[str]:
    return set((detail.get("inputSchema") or {}).get("required") or [])


def _compact_schema(detail: dict) -> list[dict]:
    props = _schema_properties(detail)
    required = _required_keys(detail)
    out = []
    for key, spec in props.items():
        out.append({
            "key": key,
            "type": spec.get("type"),
            "editor": spec.get("editor"),
            "title": spec.get("title"),
            "description": (spec.get("description") or "")[:180],
            "enum": spec.get("enum"),
            "enumTitles": spec.get("enumTitles"),
            "default": spec.get("default"),
            "prefill": spec.get("prefill"),
            "required": key in required,
        })
    return out


class _FormFieldOut(BaseModel):
    schema_key: str = Field(..., description="The EXACT input key this field maps to.")
    label: str
    help: str | None = None
    kind: str = Field("text", description="text|textarea|number|select|multiselect|toggle|tags")
    options: list[str] = Field(default_factory=list, description="Option labels for select/multiselect.")
    default: Any = None
    placeholder: str | None = None
    required: bool = False


class _FormOut(BaseModel):
    title: str
    subtitle: str | None = None
    run_button_label: str = "Get the data"
    fields: list[_FormFieldOut] = Field(default_factory=list)


SYSTEM = """You design a short, friendly form that lets a non-technical marketer run ONE data
source correctly, without seeing any technical detail.

You are given the source's real input fields and the user's need. Produce a form that:
- Includes ONLY the fields that matter for this need. Omit advanced/technical/auth/proxy
  fields and anything the user wouldn't understand or need. 2-6 fields is ideal.
- Relabels every field in plain language (what a marketer would call it). No jargon.
- Pre-fills sensible defaults, derived from the user's need where possible (e.g. put their
  topic/handle/city straight into the main field's default).
- Keeps each field bound to the EXACT original input key via schema_key.
- Chooses a sensible kind: text, textarea, number, toggle, tags (a list of words/handles/URLs),
  select or multiselect (use the source's allowed values as options).
- Marks a field required only if it truly is.
Always include the one or two fields the source needs to return anything useful (e.g. a search
term, handle, or URL). Keep labels short. Keep it usable."""


_KIND_BY_EDITOR = {
    "textfield": "text",
    "textarea": "textarea",
    "javascript": "textarea",
    "python": "textarea",
    "number": "number",
    "datepicker": "text",
    "stringList": "tags",
    "select": "select",
}
_VALID_KINDS = {"text", "textarea", "number", "select", "multiselect", "toggle", "tags"}


def _infer_kind(spec: dict) -> str:
    editor = spec.get("editor")
    if editor in _KIND_BY_EDITOR:
        return _KIND_BY_EDITOR[editor]
    t = spec.get("type")
    if t == "boolean":
        return "toggle"
    if t == "integer" or t == "number":
        return "number"
    if t == "array":
        return "multiselect" if spec.get("items", {}).get("enum") else "tags"
    if spec.get("enum"):
        return "select"
    return "text"


def _fallback_form(source_name: str, detail: dict) -> _FormOut:
    """Deterministic form used if the model can't produce a valid one: expose the required
    fields plus a couple of simple ones, using the schema's own titles — no model call."""
    props = _schema_properties(detail)
    required = _required_keys(detail)
    simple_types = {"string", "integer", "number", "boolean", "array"}

    chosen: list[str] = [k for k in required if k in props]
    for k, spec in props.items():
        if len(chosen) >= 4:
            break
        if k in chosen:
            continue
        if spec.get("type") in simple_types and spec.get("editor") not in ("json", "hidden"):
            chosen.append(k)

    fields = []
    for k in chosen:
        spec = props[k]
        fields.append(_FormFieldOut(
            schema_key=k,
            label=spec.get("title") or k,
            help=(spec.get("description") or None),
            kind=_infer_kind(spec),
            default=spec.get("prefill", spec.get("default")),
            required=k in required,
        ))
    return _FormOut(title=f"Use {source_name}",
                    subtitle="Fill in what you need and run it.",
                    fields=fields)


async def generate_usage_form(need: str, answers: dict, source_name: str, detail: dict) -> UsageForm:
    props = _schema_properties(detail)
    if not props:
        # Nothing to configure — give a single free-text field as a safe fallback.
        return UsageForm(
            title=f"Use {source_name}",
            subtitle="Describe what you want and run it.",
            fields=[FormField(id="searchStringsArray", label="What are you looking for?",
                              kind="text", required=True)],
        )

    out = await structured(
        _FormOut,
        system=SYSTEM,
        user=(
            f"Need: {need}\nAnswers: {answers}\nSource: {source_name}\n\n"
            f"Real input fields:\n{_compact_schema(detail)}"
        ),
        temperature=0.2,
        use_agent_model=True,
        label="build_form",
        validate=lambda o: V.validate_form(o, props),
        fallback=lambda: _fallback_form(source_name, detail),
    )

    fields: list[FormField] = []
    seen: set[str] = set()
    for f in out.fields:
        key = f.schema_key
        if key not in props or key in seen:
            continue  # only trust bindings to real, unique keys
        seen.add(key)
        spec = props[key]
        kind = f.kind if f.kind in _VALID_KINDS else _infer_kind(spec)

        # Build options for select/multiselect from the real enum when available.
        options: list[ClarifyOption] = []
        enum = spec.get("enum")
        enum_titles = spec.get("enumTitles") or []
        if kind in ("select", "multiselect"):
            if enum:
                options = [
                    ClarifyOption(value=str(v), label=str(enum_titles[i]) if i < len(enum_titles) else str(v))
                    for i, v in enumerate(enum)
                ]
            elif f.options:
                options = [ClarifyOption(value=o, label=o) for o in f.options]
            else:
                kind = "text"  # no real options -> safer as text

        default = f.default if f.default is not None else spec.get("prefill", spec.get("default"))
        fields.append(FormField(
            id=key,
            label=f.label or spec.get("title") or key,
            help=f.help or (spec.get("description") or None),
            kind=kind,
            options=options,
            default=default,
            placeholder=f.placeholder,
            required=f.required or (key in _required_keys(detail)),
        ))

    if not fields:  # absolute fallback: expose the first simple field
        k, spec = next(iter(props.items()))
        fields = [FormField(id=k, label=spec.get("title") or k, kind=_infer_kind(spec))]

    return UsageForm(
        title=out.title or f"Use {source_name}",
        subtitle=out.subtitle,
        run_button_label=out.run_button_label or "Get the data",
        fields=fields,
    )
