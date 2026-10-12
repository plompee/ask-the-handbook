"""SQLite storage: documents, their searchable chunks, and the question history."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("HANDBOOK_DB", Path(__file__).resolve().parent.parent / "data" / "handbook.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, pages INTEGER NOT NULL,
    chars INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER,          -- 1-based page for PDFs, section number for text files
    position INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_document(name: str, kind: str, pages: int, chunks: list[tuple[int | None, str]]) -> dict:
    """Stores a document and its chunks in one transaction. chunks = [(page, text), ...]."""
    did, ts = uuid.uuid4().hex, now()
    with connect() as c:
        c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", (did, name, kind, pages, sum(len(t) for _, t in chunks), ts))
        c.executemany("INSERT INTO chunks (doc_id, page, position, text) VALUES (?,?,?,?)",
                      [(did, page, i, text) for i, (page, text) in enumerate(chunks)])
    return get_document(did)


def get_document(did: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT d.*, COUNT(k.id) AS chunk_count FROM documents d LEFT JOIN chunks k ON k.doc_id = d.id WHERE d.id = ? GROUP BY d.id", (did,)).fetchone()
    return dict(r) if r else None


def list_documents() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT d.*, COUNT(k.id) AS chunk_count FROM documents d LEFT JOIN chunks k ON k.doc_id = d.id GROUP BY d.id ORDER BY d.created_at DESC")]


def delete_document(did: str) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM documents WHERE id = ?", (did,)).rowcount > 0


def all_chunks() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT k.id, k.doc_id, k.page, k.position, k.text, d.name AS doc_name, d.kind FROM chunks k JOIN documents d ON d.id = k.doc_id ORDER BY k.doc_id, k.position")]


def add_question(question: str, answer: dict) -> dict:
    qid, ts = uuid.uuid4().hex, now()
    with connect() as c:
        c.execute("INSERT INTO questions VALUES (?,?,?,?)", (qid, question, json.dumps(answer), ts))
    return {"id": qid, "question": question, "answer": answer, "created_at": ts}


def list_questions(limit: int = 50) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM questions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "answer": json.loads(r["answer"])} for r in rows]


def clear_questions() -> None:
    with connect() as c:
        c.execute("DELETE FROM questions")
