"""SQLite storage: agents, rooms, members, messages, notes, jobs, approvals and an audit trail."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY, persona TEXT NOT NULL DEFAULT '', tier TEXT NOT NULL DEFAULT 'auto',
    tools TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rooms (
    name TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'room', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS members (
    room TEXT NOT NULL, member TEXT NOT NULL, PRIMARY KEY (room, member));
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL, sender TEXT NOT NULL,
    text TEXT NOT NULL, ts REAL NOT NULL, hops INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS messages_room ON messages(room, id);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, room TEXT NOT NULL, cron TEXT NOT NULL,
    prompt TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_run_minute INTEGER);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, room TEXT NOT NULL, tool TEXT NOT NULL,
    args TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', ts REAL NOT NULL,
    decided_by TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, agent TEXT, event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '');
"""


class Database:
    """One shared connection guarded by a lock: the server, the scheduler and agent runs all use it."""

    def __init__(self, path: Path | str) -> None:
        self.lock = threading.RLock()
        Path(path).touch(mode=0o600)  # created private before SQLite (and its -wal/-shm files) copy the mode
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a write; returns the last inserted row id."""
        with self.lock:
            cursor = self.conn.execute(sql, params)
            self.conn.commit()
            return cursor.lastrowid

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self.lock:
            self.conn.close()
