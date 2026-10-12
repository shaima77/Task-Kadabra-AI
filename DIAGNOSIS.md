# Diagnosis note

*(Written before building. Demo need used throughout: **"recent customer reviews of
coffee shops in a given city"** — a stand-in for the marketing need given at the start.)*

## Who the user is
A marketer. They know the *outcome* they want ("what are people saying about coffee shops
in Chicago?") but not where that data lives, which tool returns it, what inputs it needs, or
what its output looks like. They will never read JSON, pick between two scrapers, or fill in a
field called `startUrls`.

## What they say vs. what they actually need
- **Say:** "I want reviews of coffee shops in Chicago."
- **Need:** recent, readable reviews with ratings and text, from a source that (a) covers the
  right *place* and *platform*, (b) can filter by *freshness*, and (c) returns *enough but not
  a flood*. The decision hinges on dimensions they didn't state: which platform (Google vs
  Yelp), how far back, and whether this is a one-off or a recurring pull.

## The real difficulty
It is **not** the UI and **not** running a scraper. It is **choosing well and making the
result usable**:
1. **Discovery is a judgment call, not a search.** The marketplace has thousands of
   overlapping tools. "Best" depends on the *specific* need — a globally-scoped scraper with a
   great rating can still be the wrong answer if the user needs US-only, newest-first. The
   agent must gather evidence (description, inputs, pricing, reputation) and defend a pick.
2. **The chosen tool's inputs are technical and arbitrary.** Every source has a different,
   jargon-filled input schema. Turning that into a 3-field form a marketer fills correctly —
   with the right value shapes (e.g. a URL list of objects, not strings) — is where "no code"
   is won or lost.
3. **Raw output is unreadable.** Each source emits differently-shaped rows. They must become
   cards with a title, rating, and link — tailored to *this* source's fields.

## What I will build (a thin vertical slice, end-to-end, real)
Describe → Clarify → live Search → Recommend (with reasons + honest alternatives) → a
**generated** usage form → readable result cards. One full journey runs against **real** Apify
sources via Apify's **MCP** server; Gemini supplies all judgment and language.

- **Deterministic code** does what must be exact: all Apify (MCP) calls, input-schema parsing,
  type coercion, result caps/timeouts, and validation of every LLM output against a schema.
- **The LLM** does what needs judgment: which questions change the answer, which tool wins and
  why, which input fields matter and their plain-language labels, and how to lay out results.

## What I will cut (on purpose)
- No auth, accounts, billing, persistence (in-memory sessions), or multi-user concerns.
- No recurring/scheduled pulls — I detect the intent in clarify but build the one-off path.
- No exhaustive source coverage — one refinement loop, a capped shortlist, one source run.
- No test-run-as-evidence during recommendation (cost/latency); I justify from description,
  inputs, pricing, rating and usage, and note this as a deliberate trade-off.

## How I'll know it's good
The clarify questions, the comparison, and the form must visibly change with the need — a
different need produces different questions, a different winner, and a different form. And a
non-technical person must be able to go from a sentence to real, readable rows without ever
seeing a technical word.
