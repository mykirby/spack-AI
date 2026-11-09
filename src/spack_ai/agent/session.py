"""Session transcripts: one JSONL file per conversation under data/sessions/.

Transcripts are the raw material for the ML pipeline: spack_ai.ml.data.collector turns
tool calls, results, and user feedback into training examples.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spack_ai.config import Settings


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


class Session:
    def __init__(self, settings: Settings, session_id: str | None = None):
        self.id = session_id or new_session_id()
        self.path = settings.sessions_dir / f"{self.id}.jsonl"
        self.workspace = settings.output_dir / self.id

    def log(self, event: str, **fields: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now(UTC).isoformat(), "event": event, **fields}
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        with path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]

    @classmethod
    def record_feedback(
        cls, settings: Settings, session_id: str, outcome: str, note: str | None = None
    ) -> Path:
        session = cls(settings, session_id)
        if not session.path.exists():
            raise FileNotFoundError(f"no session {session_id} in {settings.sessions_dir}")
        session.log("feedback", outcome=outcome, note=note)
        return session.path
