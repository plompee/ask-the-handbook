# Ask the Handbook

Ask questions about your own documents — staff handbooks, policies, manuals, lecture notes — and get short answers where **every claim links to the exact passage it came from**. If the answer isn't in your files, it says so instead of guessing.

Built with Python, FastAPI, SQLite, a hand-written BM25 search and [Claude's citations](https://platform.claude.com/docs/en/build-with-claude/citations) (retrieval-augmented generation, without an embeddings service).

## What it does

- **Upload** PDFs (with selectable text), `.txt` and `.md` files — or load three sample documents (staff handbook, tenant guide, landlord fees).
- **Ask** in plain language, in any language. Answers come with numbered citation markers; click one to jump to the quoted passage, with the document and page (PDF) or section heading (Markdown).
- **Honest by design** — the model only sees the retrieved passages and is told to say when they don't cover the question. If nothing in your library matches, it answers "not in your documents" without calling the API at all.
- **Follow-ups** — short questions like "and for part-time staff?" are searched together with the previous question.

## Run it

Requires [uv](https://docs.astral.sh/uv/) and an [Anthropic API key](https://console.anthropic.com/settings/keys).

```bash
cp .env.example .env      # then paste your key into .env
uv run python -m app      # http://127.0.0.1:8200
```

```bash
uv run pytest             # PDF/Markdown ingest, search ranking, citations -> sources, API (with a fake model)
```

## How it works

1. **Ingest** (`app/ingest.py`) — PDFs are read page by page with `pypdf`; Markdown is split by heading. Text is packed into ~900-character passages on paragraph/sentence boundaries, each starting with its section heading so it stands on its own.
2. **Retrieve** (`app/search.py`) — Okapi BM25 over all passages with a small stemmer (so "cancelled", "cancelling" and "cancel" match). The top 8 passages are used.
3. **Answer** (`app/ai.py`) — each passage is sent as a plain-text `document` block with `citations: {enabled: true}` and a title like "Staff Handbook - Holidays". Claude's `char_location` citations are mapped back to the passage, document and page, and numbered for the UI. Model: `claude-opus-5-5`, with server-side refusal fallback enabled.
4. **Store** (`app/db.py`) — SQLite for documents, passages and question history.

## License

MIT
