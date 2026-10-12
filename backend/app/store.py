"""Tiny in-memory conversation store.

Kept deliberately simple: this is a demo slice. Swap for Redis/DB for multi-process or
persistent deployments (noted in the README).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Session:
    id: str
    need: str = ""
    restated_need: str = ""
    answers: dict[str, str] = field(default_factory=dict)
    # Set once a recommendation is made, so /run knows what to execute.
    chosen_source_id: Optional[str] = None
    chosen_source_name: Optional[str] = None
    chosen_detail: dict[str, Any] = field(default_factory=dict)
    form: dict[str, Any] = field(default_factory=dict)
    display: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, need: str) -> Session:
        sid = uuid.uuid4().hex[:12]
        sess = Session(id=sid, need=need)
        self._sessions[sid] = sess
        return sess

    def get(self, sid: str) -> Session:
        sess = self._sessions.get(sid)
        if not sess:
            raise KeyError(sid)
        return sess


store = SessionStore()
