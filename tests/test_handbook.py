from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ai
from app.ingest import ingest
from app.main import app
from app.search import Index, stem, tokenize

client = TestClient(app)


def tiny_pdf(*pages: str) -> bytes:
    """Builds a minimal valid PDF with one line of Helvetica text per page (correct xref offsets)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class FakeClaude:
    """Records requests and returns text blocks with citations pointing at the given document indexes."""

    def __init__(self, blocks, stop_reason="end_turn"):
        self.calls, self.blocks, self.stop_reason = [], blocks, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, content=self.blocks)


def text(t, *cites):
    return SimpleNamespace(type="text", text=t, citations=[SimpleNamespace(type="char_location", document_index=i, cited_text=q) for i, q in cites] or None)


# ---------- ingest & search ----------
def test_pdf_pages_become_cited_chunks():
    kind, pages, chunks = ingest("Policy.pdf", tiny_pdf("Holiday allowance is 25 days.", "Sick pay lasts 10 days."))
    assert (kind, pages) == ("pdf", 2)
    assert chunks[0][0] == 1 and "25 days" in chunks[0][1]
    assert chunks[1][0] == 2 and "Sick pay" in chunks[1][1]


def test_markdown_sections_and_bad_files():
    kind, pages, chunks = ingest("Guide.md", b"# Pets\n\nNo pets.\n\n# Rent\n\nPay monthly.")
    assert kind == "markdown" and pages == 2 and chunks[1] == (2, "Rent:\n\nPay monthly.")
    with pytest.raises(ValueError, match="Only PDF"):
        ingest("photo.jpg", b"x")
    with pytest.raises(ValueError, match="No text"):
        ingest("empty.txt", b"   ")
    with pytest.raises(ValueError, match="Couldn't read"):
        ingest("broken.pdf", b"%PDF-1.4 not really")


def test_search_ranks_the_right_section():
    assert stem("cancelling") == stem("cancelled") == "cancel"
    assert "the" not in tokenize("What is the policy?")
    chunks = [{"id": 1, "doc_name": "Handbook", "text": "Holidays: 25 days of annual leave."},
              {"id": 2, "doc_name": "Handbook", "text": "Mileage is paid at 45p per mile."}]
    idx = Index(chunks)
    assert idx.search("How much annual leave?")[0][0]["id"] == 1
    assert idx.search("mileage rate")[0][0]["id"] == 2
    assert idx.search("football scores") == []


# ---------- API ----------
def test_samples_upload_and_delete():
    added = client.post("/api/samples").json()["added"]
    assert {d["name"] for d in added} == {"Staff Handbook.md", "Tenant Guide.md", "Landlord Fees and Terms.md"}
    assert client.post("/api/samples").json()["added"] == []  # not loaded twice
    r = client.post("/api/documents", files=[("files", ("Policy.pdf", tiny_pdf("Parking is free after 6pm."), "application/pdf")),
                                            ("files", ("notes.docx", b"x", "application/octet-stream"))]).json()
    assert len(r["added"]) == 1 and r["added"][0]["chunk_count"] == 1 and "notes.docx" in r["skipped"][0]
    did = r["added"][0]["id"]
    assert client.delete(f"/api/documents/{did}").json() == {"deleted": True}
    assert all(d["id"] != did for d in client.get("/api/documents").json())


def test_ask_returns_numbered_sources_from_citations():
    fake = FakeClaude([
        SimpleNamespace(type="thinking", thinking=""),
        text("Full-time staff get "),
        text("25 days of annual leave plus bank holidays", (0, "Full-time staff get 25 days of annual leave plus bank holidays.")),
        text(", and up to 5 days can be carried over", (0, "Up to 5 unused days can be carried over to the next year")),
        text("."),
    ])
    ai.set_client_for_tests(fake)
    q = client.post("/api/ask", json={"question": "How much holiday do I get and can I carry it over?"}).json()
    a = q["answer"]
    assert a["text"] == "Full-time staff get 25 days of annual leave plus bank holidays, and up to 5 days can be carried over."
    assert [s["n"] for s in a["sources"]] == [1, 2] and a["cited"] is True
    assert a["sources"][0]["doc_name"] == "Staff Handbook.md" and a["sources"][0]["location"] == "Holidays"
    assert [p["sources"] for p in a["parts"]] == [[], [1], [2], []]

    req = fake.calls[0]  # request shape: citable documents titled with doc + location, then the question
    docs = [b for b in req["messages"][0]["content"] if b["type"] == "document"]
    assert docs and all(d["citations"] == {"enabled": True} and d["source"]["type"] == "text" for d in docs)
    assert docs[0]["title"] == "Staff Handbook.md - Holidays"
    assert req["messages"][0]["content"][-1]["text"].endswith("can I carry it over?")
    assert req["fallbacks"] == "default" and req["model"] == "claude-opus-5-5"
    assert "output_config" in req and "format" not in req["output_config"]  # citations can't be combined with structured outputs


def test_follow_up_uses_previous_question_and_no_match_skips_the_api():
    fake = FakeClaude([text("Yes.", (0, "Up to 5 unused days can be carried over"))])
    ai.set_client_for_tests(fake)
    client.post("/api/ask", json={"question": "and for part-time staff?"})
    assert "Earlier question:" in fake.calls[0]["messages"][0]["content"][-1]["text"]

    fake.calls.clear()
    r = client.post("/api/ask", json={"question": "Who won the World Cup in 1966?"}).json()
    assert r["answer"]["no_match"] is True and fake.calls == []


def test_refusal_and_validation():
    ai.set_client_for_tests(FakeClaude([], stop_reason="refusal"))
    r = client.post("/api/ask", json={"question": "What is the sickness policy?"})
    assert r.status_code == 422
    assert client.post("/api/ask", json={"question": "x"}).status_code == 400
    assert len(client.get("/api/history").json()) >= 2
    assert client.delete("/api/history").json() == {"cleared": True}
