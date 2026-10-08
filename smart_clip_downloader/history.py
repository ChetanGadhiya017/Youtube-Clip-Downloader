"""Download history persisted as JSON in the user's app-data folder."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def default_history_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "SmartClipDownloader" / "history.json"


class History:
    def __init__(self, path: Path | None = None, limit: int = 500):
        self.path = Path(path) if path else default_history_path()
        self.limit = limit

    def load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def add(self, **entry) -> dict:
        entry.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S"))
        items = [entry] + self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items[: self.limit], indent=2), encoding="utf-8")
        return entry

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
