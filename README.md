# Data Finder

A no-code product that lets a **marketer describe a data need in plain words** and walks them
to **real, readable data** — without ever seeing an API, scraper, token, or JSON. An AI agent
does the discovery; a clean interface delivers the result.

> The words *Apify*, *actor*, *API*, *endpoint*, *token* and *schema* never appear in the UI.

---

## The journey

**Describe** → **Clarify** (optional — an LLM judge asks only when an answer would change the
choice) → **Search** (live, human-readable progress) → **Recommend** (best source + why, with
honest alternatives) → **Use** (a form auto-generated from that source's real inputs) →
**Results** (cards, not JSON).

## Stack

| Part | Choice | Why |
|------|--------|-----|
| Agent | **LangGraph** autonomous tool-calling agent | A message-driven agent ⇄ tools loop where the LLM decides its own next action (search again, inspect, or conclude) — bounded by hard guardrails (see below). Not a fixed pipeline, not one prompt returning a list. |
| LLM | **Google Gemini** (`gemini-3.8-flash`) | Fast + cheap; the agent makes several tool-driven calls per request, so latency and cost compound. (Gemini 3.x needs `langchain-google-genai` 4.x — see `requirements.txt`.) |
| Data engine | **Apify, via its MCP server** (`https://mcp.apify.com`) | The backend is an MCP client; Apify is invisible and server-side only. No direct REST, no other providers. |
| Backend | **FastAPI** | Holds session state, streams progress over SSE, enforces caps. |
| Frontend | **React + Vite** | The five-screen journey with loading / empty / error states. |

## Architecture

```
Browser (React)                     FastAPI                          Apify MCP     Gemini
   │  POST /api/describe  ───────────▶ clarify: LLM-as-judge ──────────────────────▶ (ask only if needed)
   │  POST /api/recommend (SSE) ─────▶ autonomous LangGraph agent (agent ⇄ tools loop):
   │        ◀─ progress events ─────── LLM decides: search → inspect → … → submit
   │                                        │  search-actors / fetch-actor-details ──▶ Apify
   │                                        └  decisions + language ────────────────▶ Gemini
   │        ◀─ result (recommendation + generated form)
   │  POST /api/run ─────────────────▶ coerce + cap inputs → call-actor → poll dataset
   │                                   → return at the cap, then abort the run ─────▶ Apify
   │        ◀─ normalized rows + a display spec (title/rating/image/link/…) ───────▶ Gemini
```

The autonomous LangGraph loop (`backend/app/agent/discovery.py`) — the LLM drives it:

```
          ┌───────────────── loop ─────────────────┐
          ▼                                         │
   agent ──tool calls?──▶ tools ──search / inspect──┘
     │  │                   │
     │  │                   └─(valid submit · or budget hit)─▶ build_form ─▶ END
     │  └─plain text─▶ nudge once ─▶ agent
     └─(step/time/tool budget exceeded)─▶ build_form (deterministic fallback) ─▶ END
```

**Hard guardrails** (enforced in the graph's control flow, not just the prompt):
- **Tool whitelist** — the agent only has `search_sources`, `get_source_details`,
  `submit_recommendation`. There is **no tool to run a source**, so it cannot incur scrape cost
  on its own; running stays behind the explicit, capped `/run`.
- **Budgets** — `AGENT_MAX_STEPS` (12), `AGENT_MAX_TOOL_CALLS` (14), `AGENT_MAX_SEARCHES` (2,
  `SEARCH_RESULTS_PER_QUERY`=5 each), `MAX_CANDIDATES_TO_INSPECT` (6), and an overall
  `AGENT_TIMEOUT_SECS` (150) wall-clock deadline. A tool call over budget is refused with a
  message telling the agent to wrap up.
- **Validated termination** — the agent must finish via `submit_recommendation`; its arguments
  are deterministically validated (chosen id must be a real source it saw; reasons required).
  Invalid → bounced back once; if it never submits validly or runs out of budget, a
  deterministic fallback recommendation is used.
- Every model/MCP call carries the retry + timeout from the reliability layer.

Apify's MCP search/detail tools return **Markdown**, which the agent reads directly; the only
structured extraction is the candidate ids (for validation) and the chosen source's input
schema (for the form).

---

## Run it (< 5 minutes)

Everything lives in **one conda env, `Kadabra-AI`** (Python 3.12 **and** Node 22 — Node is
installed into the env via conda-forge, so you don't need a separate Node install).

### 0 — One-time setup (skip if the env already exists)
```bash
# create the env with Python + Node together
conda create -n Kadabra-AI python=3.12 -y
conda install -n Kadabra-AI -c conda-forge nodejs=22 -y

conda activate Kadabra-AI

# backend deps
cd backend
pip install -r requirements.txt

# keys: copy the template and paste in your two keys
cp .env.example .env            # edit .env → APIFY_TOKEN=... and GEMINI_API_KEY=...

# frontend deps
cd ../frontend
npm install
```

### Run (two terminals, both in the env)

**Terminal 1 — backend (FastAPI on :8000)**
```bash
conda activate Kadabra-AI
cd backend
uvicorn app.main:app --port 8000
```

**Terminal 2 — frontend (Vite on :5173)**
```bash
conda activate Kadabra-AI      # Node lives in this same env
cd frontend
npm run dev
```

Then open **http://localhost:5173**.

- The Vite dev server proxies `/api` to the backend, so the browser only ever talks to one
  origin and never sees a key.
- Sanity check: `curl http://localhost:8000/api/health` → `{"ok":true}`.
- If `conda` / `uvicorn` / `npm` aren't found: make sure the env is **activated** (the prompt
  shows `(Kadabra-AI)`). On Windows PowerShell, run `conda init powershell` once, then reopen
  the shell. `uvicorn` and `npm` are provided by the env — no global install needed.

> **Windows note:** the env was built on Windows; the same commands work in PowerShell, Git
> Bash, or the Anaconda Prompt. Use forward slashes or quote paths that contain spaces.

---


**Real (end-to-end, no mocks):**
- Source discovery, comparison and the recommendation — live Apify Store search + per-source
  detail (inputs, pricing, rating, usage) over MCP.
- The usage form is generated from the chosen source's **actual** input schema and bound to
  real keys.
- `POST /api/run` actually runs the chosen source over MCP and returns its real rows. Verified
  against e.g. *Google Maps Reviews Scraper* (20 live review cards) and *TikTok Video Search
  Scraper*.



## Key decisions

- **Apify through MCP, not REST.** The agent treats Apify as a set of MCP tools
  (`search-actors`, `fetch-actor-details`, `call-actor`, `get-dataset-items`). Tool names are
  resolved dynamically so we're robust to naming changes.
- **Deterministic / LLM split.** Everything that must be exact is code: MCP calls, schema
  parsing, input **type coercion** (e.g. wrapping URL strings into `{"url": …}` objects where
  the schema expects it), caps, and Pydantic-validated structured outputs. The LLM only does
  judgment and language, and we never trust it to invent a source id or input key — both are
  validated against real data.
- **Cost awareness.** The agent has no tool to run a source, so discovery never scrapes. On
  `/run`, every result-count input is auto-capped to `MAX_RESULTS` (20); the run returns as soon
  as it has that many rows and then **aborts** the job so it stops charging. One click can't
  trigger a huge run.
- **Non-generic by construction.** Whether to clarify (and what to ask), the chosen source, the
  form fields, and the results layout are all derived from *this* need and *this* source. Change
  the need and they all change.

## Reliability: validator + retry + timeout + fallback

Every fallible step runs through one wrapper, `reliability.run_step` (`backend/app/reliability.py`):

- **3 retries per step** (`STEP_MAX_RETRIES`, default 3) with brief backoff.
- **Per-attempt timeouts** — `SEARCH_TIMEOUT_SECS` (30s) for Apify search/inspect,
  `REASONING_TIMEOUT_SECS` (45s) for every Gemini call — so a slow call can't hang a request.
- **Deterministic fallback** — when attempts are exhausted the step degrades to a cheap,
  no-LLM result instead of erroring.

A **deterministic validator** (`backend/app/validation.py`, pure functions, no LLM / no
network) guards both ends. It checks **structure and facts only — never the agent's judgment**
(it verifies a chosen id is real, not whether it's the *best* choice):

- **Inputs**, before we spend anything: the need text (length) at `/describe`; required run
  fields at `/run` that have no value *and* no schema default (rejected with friendly labels,
  not schema keys).
- **Outputs**: the generated form (≥1 field bound to a real input key), the results display
  (summary present; any named card field exists in the data), and result rows (only well-formed
  records survive). The agent's recommendation is validated next to the graph by
  `_validate_submit` in `discovery.py` — chosen id must be a real source it saw, and
  name/headline/reasons must be present.

A failed output check **triggers a retry**, and once retries are spent we switch to the
deterministic fallback — so we **stop calling the model** rather than loop on bad output. Cheap
checks gate expensive calls; fallbacks replace a model call instead of adding more.

Fallbacks by step: clarify → skip questions · agent (budget hit / never submits / model
error) → a deterministic recommendation built from the candidates it actually looked at ·
invalid `submit` → bounced back once with the validation errors · form → required + simple
fields from the schema · display → field layout by key-name heuristics.

Note: the actual **run** (`call-actor`) is intentionally **not** auto-retried — re-running a
scraper costs money — but keeps its own wait-clamp + poll budget and reports status honestly.

## Failure handling (user-facing)
- **Nothing fits** → the agent returns `found:false` with a plain explanation (no fake pick).
- **Run fails / times out / empty** → distinct, friendly messages with "adjust & retry".
- **Apify or LLM errors** mid-search → surfaced as a single human error event, journey
  recoverable; a one-sentence banner, never a stack trace.

## With another week

- **More reliable, cost-optimised data flow.** Cache source metadata and input schemas so we
  don't re-fetch per request; reuse a single MCP session instead of opening one per call; add
  model-tier routing (a cheap model for search/clarify, a stronger one only for the final
  decision); estimate and show run cost *before* a scrape; dedupe identical runs; and run the
  top-2 candidates with tiny caps as *real* evidence for the recommendation when the budget
  allows.
- **A much better, richer web UI.** More polish and more options: editable clarify answers,
  save/compare multiple recommendations side-by-side, tweak-and-rerun the form, results
  filtering/sorting and table↔card views, export (CSV), a visible run-cost meter, and clearer
  loading/empty/error states with the agent's live reasoning.
- **LangSmith tracing.** Instrument the whole flow with LangSmith to track tokens, latency and
  tool calls per step — so we can see where cost and time actually go and tune budgets from
  data instead of guesswork.
- **More LLM-as-judge checks.** Extend the judge pattern beyond clarify: a judge that scores the
  final recommendation's evidence, a judge that sanity-checks the generated form against the
  need, and a judge that rates result quality (empty/odd/good) — each with a deterministic
  fallback.
- **Evaluate other agent setups.** Benchmark alternatives for this task — `create_react_agent`,
  a planner/executor split, or a multi-agent (searcher + evaluator) team — against the current
  single-loop agent on cost, latency and choice quality, and keep whichever wins.
- **Improve the prompts.** Treat each prompt (agent system prompt, clarify judge, form,
  display) as something to iterate on, not set once: tighten wording, add few-shot examples of
  good vs. bad behaviour, version them, and score each change against the eval harness and
  LangSmith traces so prompt tweaks are measured, not vibes.
### Evaluation process (how I'd know it's good)

A repeatable suite run on every prompt/code change, so quality is measured, not vibed:

1. **Golden set.** ~15-20 representative needs across categories (social, reviews, ads,
   contacts, products, trends), each with expectations: should-clarify or not, a set of
   acceptable source ids, and required form fields.
2. **Deterministic stage checks** (cheap, pass/fail, no LLM):
   - *Clarify judge* asks only when the golden need is ambiguous (precision/recall on ask-vs-skip).
   - *Recommendation* names a real, non-deprecated source; reasons and alternatives are present.
   - *Form* fields all bind to real schema keys; every required input is covered.
   - *Run* returns non-empty, well-formed rows within the cap and time budget.
3. **LLM-as-judge scoring** (offline, a stronger model) on the task's own 1-4 rubric:
   recommendation reasoning grounded in gathered evidence, form usability, and result relevance.
4. **Operational metrics** from LangSmith per run: tokens, $ cost, latency, tool-call count,
   retry rate, and fallback rate (a rising fallback rate means the agent is failing silently).
5. **Regression gate.** Compare scores *and* cost/latency against the last baseline; a change
   ships only if quality holds or improves without a cost blow-up. A few cases are spot-checked
   by hand each run.

## Layout
```
backend/app/
  main.py            FastAPI: /describe, /recommend (SSE), /run
  mcp_client.py      Apify via MCP (markdown search/details for the agent; input-schema +
                     run/dataset extraction for the deterministic paths; caps + polling)
  reliability.py     run_step: retry (3) + per-attempt timeout + deterministic fallback
  validation.py      deterministic validators for inputs and every LLM output
  llm.py             Gemini access + schema-validated structured output (wrapped by run_step)
  agent/
    clarify.py       LLM-as-judge: ask only when an answer changes the choice
    discovery.py     the autonomous LangGraph agent (agent ⇄ tools loop) + hard guardrails
    form.py          usage form from the real input schema
    display.py       rows → human card layout
frontend/src/        React journey (Describe · Clarify · Progress · Recommendation · Results)
DIAGNOSIS.md         the pre-build thinking
```

## AI usage trail
Built with Claude Code (Opus) driving the implementation — see the attached chat export /
screen recording. API keys live only in `backend/.env` (git-ignored) and are never sent to the
browser.
