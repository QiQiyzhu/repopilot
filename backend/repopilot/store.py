from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import MemoryEntry, TaskRecord, TraceEvent


class SQLiteStore:
    """Short transactions, WAL, and explicit schemas; swap behind the repository protocols."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, created TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, body TEXT);
                CREATE INDEX IF NOT EXISTS event_task ON events(task_id, sequence);
                CREATE TABLE IF NOT EXISTS memory (
                    id TEXT PRIMARY KEY, repository TEXT, commit_sha TEXT, valid INTEGER, body TEXT);
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=15)

    def save_task(self, task: TaskRecord) -> None:
        body = task.model_copy(update={"trace": []}).model_dump_json()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)",
                (task.task_id, task.created_at, body),
            )

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            task = TaskRecord.model_validate_json(row[0])
            task.trace = self.events(task_id)
            return task

    def list_tasks(self) -> list[TaskRecord]:
        with self.connect() as db:
            rows = db.execute("SELECT body FROM tasks ORDER BY created DESC LIMIT 200").fetchall()
        return [TaskRecord.model_validate_json(row[0]) for row in rows]

    def append_event(self, event: TraceEvent) -> TraceEvent:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO events(task_id,body) VALUES (?,?)",
                (event.task_id, event.model_dump_json()),
            )
            event.sequence = int(cur.lastrowid or 0)
            db.execute(
                "UPDATE events SET body=? WHERE sequence=?",
                (event.model_dump_json(), event.sequence),
            )
        return event

    def events(self, task_id: str, after: int = 0) -> list[TraceEvent]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT body FROM events WHERE task_id=? AND sequence>? ORDER BY sequence",
                (task_id, after),
            ).fetchall()
        return [TraceEvent.model_validate_json(row[0]) for row in rows]

    def add_memory(self, entry: MemoryEntry) -> None:
        if entry.trusted and not entry.provenance:
            raise ValueError("Trusted memory requires evidence provenance")
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO memory VALUES (?,?,?,?,?)",
                (
                    entry.id,
                    entry.repository,
                    entry.commit,
                    int(entry.valid),
                    entry.model_dump_json(),
                ),
            )

    def retrieve(self, repository: str, commit: str, query: str) -> list[MemoryEntry]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT body FROM memory WHERE repository=? AND commit_sha=? AND valid=1",
                (repository, commit),
            ).fetchall()
        entries = [MemoryEntry.model_validate_json(row[0]) for row in rows]
        words = set(query.lower().split())
        return sorted(
            [e for e in entries if e.trusted],
            key=lambda e: -len(words & set(e.content.lower().split())),
        )[:5]

    def all_memory(self) -> list[MemoryEntry]:
        with self.connect() as db:
            return [
                MemoryEntry.model_validate_json(r[0])
                for r in db.execute("SELECT body FROM memory").fetchall()
            ]

    def invalidate(self, memory_id: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT body FROM memory WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return False
            body = json.loads(row[0])
            body["valid"] = False
            db.execute(
                "UPDATE memory SET valid=0, body=? WHERE id=?", (json.dumps(body), memory_id)
            )
            return True
