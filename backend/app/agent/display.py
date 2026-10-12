"""Turn a source's raw rows into a human card layout.

Given the actual keys present in the returned rows (and a couple of sample values), the model
chooses which fields become the card title, subtitle, image, link, rating and a few detail
fields — tailored to THIS source's output and THIS user's need. We validate every chosen key
against the real data so the UI never references a field that doesn't exist.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..llm import structured
from ..models import DisplaySpec
from .. import validation as V


class _DisplayOut(BaseModel):
    summary: str = Field(..., description="One plain sentence summarising what came back.")
    layout: str = Field("cards", description="cards or table")
    title_field: str | None = None
    subtitle_field: str | None = None
    image_field: str | None = None
    link_field: str | None = None
    rating_field: str | None = None
    badge_fields: list[str] = Field(default_factory=list)
    detail_fields: list[str] = Field(default_factory=list, description="A few extra keys worth showing.")


def _sample(items: list[dict], n: int = 3) -> list[dict]:
    out = []
    for it in items[:n]:
        trimmed = {}
        for k, v in it.items():
            if isinstance(v, str) and len(v) > 160:
                v = v[:160] + "…"
            trimmed[k] = v
        out.append(trimmed)
    return out


def _all_keys(items: list[dict]) -> list[str]:
    keys: list[str] = []
    for it in items:
        for k in it.keys():
            if k not in keys:
                keys.append(k)
    return keys


def _fallback_display(keys: list[str], count: int) -> _DisplayOut:
    """Deterministic display chosen by key-name heuristics — used if the model fails."""
    def first(*cands):
        return next((c for c in cands if c in keys), None)
    return _DisplayOut(
        summary=f"Found {count} results.",
        layout="cards",
        title_field=first("title", "name", "fullName", "username", "searchResult.title", "metadata.title"),
        subtitle_field=first("subtitle", "address", "description", "metadata.description"),
        image_field=first("image", "imageUrl", "pictureUrl", "thumbnail", "reviewerPhotoUrl"),
        link_field=first("url", "link", "reviewUrl", "postUrl", "metadata.url"),
        rating_field=first("rating", "stars", "score"),
        detail_fields=[k for k in ("text", "description", "snippet") if k in keys][:3],
    )


async def build_display_spec(need: str, source_name: str, items: list[dict]) -> tuple[DisplaySpec, str]:
    keys = _all_keys(items)
    out = await structured(
        _DisplayOut,
        system=(
            "You lay out data as readable cards for a non-technical marketer. Using ONLY the keys "
            "present in the data, choose: a title field (short, identifying), an optional subtitle, "
            "an image field if any key holds an image URL, a link field if any key holds a URL to the "
            "original, a rating/score field if present, up to 3 badge fields (small facts like counts "
            "or dates), and up to 5 detail fields worth showing. Prefer fields relevant to the need. "
            "Use the EXACT key strings. Also write a one-sentence plain summary of what came back."
        ),
        user=f"Need: {need}\nSource: {source_name}\nAvailable keys: {keys}\nSample rows: {_sample(items)}",
        temperature=0.2,
        label="display",
        validate=lambda o: V.validate_display(o, keys),
        fallback=lambda: _fallback_display(keys, len(items)),
    )

    valid = set(keys)

    def ok(k: str | None) -> str | None:
        return k if (k and k in valid) else None

    spec = DisplaySpec(
        layout="table" if out.layout == "table" else "cards",
        title_field=ok(out.title_field),
        subtitle_field=ok(out.subtitle_field),
        image_field=ok(out.image_field),
        link_field=ok(out.link_field),
        rating_field=ok(out.rating_field),
        badge_fields=[k for k in out.badge_fields if k in valid][:3],
        detail_fields=[{"key": k, "label": k.split(".")[-1].replace("_", " ").title()}
                       for k in out.detail_fields if k in valid][:5],
    )
    # Guarantee at least a title so cards are never blank.
    if not spec.title_field:
        for cand in ("title", "name", "fullName", "username", "searchResult.title", "metadata.title"):
            if cand in valid:
                spec.title_field = cand
                break
        if not spec.title_field and keys:
            spec.title_field = keys[0]
    return spec, out.summary
