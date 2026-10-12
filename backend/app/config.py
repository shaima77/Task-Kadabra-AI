"""Central configuration. Secrets are read from the environment only — never hard-coded,
never sent to the browser."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env regardless of where uvicorn is launched from.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    def __init__(self) -> None:
        self.apify_token: str = os.environ.get("APIFY_TOKEN", "").strip()
        self.gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "").strip()
        self.apify_mcp_url: str = os.environ.get("APIFY_MCP_URL", "https://mcp.apify.com").strip()

        self.agent_model: str = os.environ.get("GEMINI_AGENT_MODEL", "gemini-2.5-flash").strip()
        self.utility_model: str = os.environ.get("GEMINI_UTILITY_MODEL", "gemini-2.5-flash").strip()

        # Cost/abuse guardrails.
        self.max_results: int = int(os.environ.get("MAX_RESULTS", "20"))
        self.actor_run_timeout_secs: int = int(os.environ.get("ACTOR_RUN_TIMEOUT_SECS", "90"))
        self.max_candidates: int = int(os.environ.get("MAX_CANDIDATES_TO_INSPECT", "6"))

        # Reliability: retries per step and per-attempt timeouts (seconds).
        self.step_max_retries: int = int(os.environ.get("STEP_MAX_RETRIES", "3"))
        self.search_timeout_secs: int = int(os.environ.get("SEARCH_TIMEOUT_SECS", "30"))
        self.reasoning_timeout_secs: int = int(os.environ.get("REASONING_TIMEOUT_SECS", "45"))

        # Autonomous agent hard guardrails.
        self.agent_max_steps: int = int(os.environ.get("AGENT_MAX_STEPS", "12"))
        self.agent_max_tool_calls: int = int(os.environ.get("AGENT_MAX_TOOL_CALLS", "14"))
        self.agent_max_searches: int = int(os.environ.get("AGENT_MAX_SEARCHES", "2"))
        self.search_results_per_query: int = int(os.environ.get("SEARCH_RESULTS_PER_QUERY", "5"))
        self.agent_timeout_secs: int = int(os.environ.get("AGENT_TIMEOUT_SECS", "150"))

    def require(self) -> None:
        missing = [k for k, v in {
            "APIFY_TOKEN": self.apify_token,
            "GEMINI_API_KEY": self.gemini_api_key,
        }.items() if not v]
        if missing:
            raise RuntimeError(
                f"Missing required env vars: {', '.join(missing)}. "
                f"Copy backend/.env.example to backend/.env and fill them in."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
