# Diagnosis Note
**AI Builder Task — Find the Best Data Source**

*Originally written before building; updated to reflect what was actually delivered.*

### 1. User and Actual Need
The target users are non-technical marketing professionals who know what information they want
but do not know where or how to retrieve it.

Their actual need is not simply to find an API, but to obtain relevant, reliable, and
actionable data through an intuitive interface without dealing with technical complexity.

### 2. Main Challenges
The main challenge is translating natural-language requests into the user's actual data
requirements, especially when requests are ambiguous or do not clearly match an available data
source.

Another challenge is selecting the most suitable source based on real evidence, rather than
relying only on the LLM's assumptions, while ensuring reliable execution and meaningful results.

### 3. Solution (as built)
An end-to-end application consisting of a React frontend, a Python FastAPI backend, and a single
Gemini-powered **autonomous agent** (built with LangGraph) integrated with **Apify through its
hosted MCP server** — never the raw REST API, and never exposed to the browser.

The agent uses a well-defined system prompt and a real tool-calling loop to search available
sources, inspect the most promising candidates, compare them, and produce an evidence-based
recommendation with honest alternatives. A lightweight **LLM-as-judge** first decides whether
any clarifying question is even needed, and asks only when an answer would change the choice.

The system dynamically generates a user-friendly input form from the selected source's **actual
input schema** and displays results in a readable card format.

I implemented a **Deterministic Validator** for input/output structure, required fields, and
real source ids/keys, alongside bounded **Retry, Timeout, and Fallback** mechanisms to handle
failures and unsuitable sources. The agent's autonomy is held inside **hard guardrails** (a
tool whitelist with no "run" tool, step/tool/search budgets, a wall-clock deadline, and a
validated terminal action), and runs are cost-capped (return at the result cap, then abort).

### 4. Scope and Trade-offs
Given the two-hour constraint, I focused on one complete working flow with real Apify data.

One scope decision changed during the build: I **added a small LLM-as-judge** for the clarify
step, because it was cheap and directly improved the experience (no needless questions on
already-specific requests).

I deliberately excluded a **multi-agent architecture**, persistent storage / auth / billing,
recurring or scheduled pulls, and observability
tooling (e.g. LangSmith). Since the task is focused on a single domain, one agent with multiple
tools is sufficient.

### 5. Success Criteria
Success means a non-technical user can describe a need, understand why a source was recommended,
run it, and receive relevant, readable results without writing code.

The system also handles invalid inputs, failed executions, and missing results gracefully.

### 6. With Another Week
- **More reliable, cost-optimised flow:** cache source metadata/schemas, reuse one MCP session,
  route cheap vs. strong models per step, estimate run cost before a scrape, and use real
  test-runs of the top candidates as stronger evidence.
- **Richer web UI:** editable clarify answers, save/compare recommendations, tweak-and-rerun,
  result filtering/sorting and table↔card views, CSV export, and a run-cost meter.
- **Observability (LangSmith):** trace tokens, latency, and tool calls per step to tune budgets
  from data.
- **More LLM-as-judge checks** (recommendation evidence, form fit, result quality) and a
  benchmark of other agent setups (`create_react_agent`, planner/executor, multi-agent).
- **Prompt iteration:** version each prompt, add few-shot good/bad examples, and score changes
  against the eval suite.

**Evaluation process (how I'd know it's good).** A repeatable suite run on every change:
1. A **golden set** of ~15-20 needs across categories, each with expectations (should-clarify,
   acceptable source ids, required form fields).
2. **Deterministic checks:** the clarify judge asks only when ambiguous; the recommendation
   names a real source with reasons; the form binds to real keys and covers required inputs; a
   run returns well-formed rows within the cap and time budget.
3. **LLM-as-judge scoring** on the task's 1-4 rubric: reasoning grounded in evidence, form
   usability, result relevance.
4. **Operational metrics** (via LangSmith): tokens, cost, latency, retry rate, fallback rate.
5. A **regression gate** that ships a change only if quality holds or improves without a cost
   blow-up, plus a few hand spot-checks.
