"""FastAPI app: upload documents, ask questions, get cited answers."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import ai, db
from .ingest import MAX_FILE, ingest
from .search import index_for, tokenize

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
MAX_FILES = 20
TOP_K = 8

app = FastAPI(title="Ask the Handbook")


@app.exception_handler(ai.AIError)
def _ai_error(_, exc: ai.AIError):
    return JSONResponse({"error": str(exc)}, status_code=exc.status)


@app.exception_handler(HTTPException)
def _http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
def _validation_error(_, exc):
    first = exc.errors()[0]
    field = ".".join(str(x) for x in first["loc"] if x not in ("body", "query", "path"))
    return JSONResponse({"error": f"{field}: {first['msg']}" if field else first["msg"]}, status_code=400)


class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@app.get("/api/status")
def status():
    return {"api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))}


@app.get("/api/documents")
def documents():
    return db.list_documents()


def _add(name: str, data: bytes) -> dict:
    kind, pages, chunks = ingest(name, data)
    return db.add_document(name[:200], kind, pages, chunks)


@app.post("/api/documents")
async def upload(files: list[UploadFile] = File(...)):
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Upload at most {MAX_FILES} files at a time")
    added, skipped = [], []
    for f in files:
        data = await f.read(MAX_FILE + 1)
        try:
            added.append(_add(f.filename or "document", data))
        except ValueError as e:
            skipped.append(f"{f.filename}: {e}")
    return {"added": added, "skipped": skipped}


@app.post("/api/samples")
def samples():
    existing = {d["name"] for d in db.list_documents()}
    added = [_add(p.name, p.read_bytes()) for p in sorted(SAMPLES.glob("*.md")) if p.name not in existing]
    return {"added": added}


@app.delete("/api/documents/{did}")
def delete_document(did: str):
    if not db.delete_document(did):
        raise HTTPException(404, "Document not found")
    return {"deleted": True}


@app.post("/api/ask")
def ask(body: Ask):
    question = body.question.strip()
    chunks = db.all_chunks()
    if not chunks:
        raise HTTPException(409, "Upload a document (or load the samples) first")
    history = db.list_questions(limit=2)
    query = question
    if len(tokenize(question)) < 4 and history:  # short follow-up like "and for pets?" - search with the last question too
        query = f"{history[0]['question']} {question}"
    hits = [c for c, _ in index_for(chunks).search(query, TOP_K)]
    if not hits:  # nothing relevant: say so without spending an API call
        result = {"text": "I couldn't find anything about that in your documents.", "parts": [], "sources": [], "cited": False, "no_match": True}
    else:
        result = ai.answer(question, hits, history)
    return db.add_question(question, result)


@app.get("/api/history")
def history():
    return db.list_questions()


@app.delete("/api/history")
def clear_history():
    db.clear_questions()
    return {"cleared": True}


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
