const $ = (s, r = document) => r.querySelector(s);
const KIND_ICON = { pdf: "📕", markdown: "📝", text: "📄" };
const STARTERS = [
  "How many holiday days do I get, and can I carry any over?",
  "What should a tenant do if they smell gas?",
  "How much is business mileage paid at?",
  "What are your fees for a fully managed property?",
  "When will a tenant get their deposit back?",
  "Can tenants keep a cat?",
];
let docs = [], asking = false;

/** Builds a DOM node; all text goes in as text nodes, so document/answer text can't inject markup. */
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
}
async function api(method, url, body, isForm = false) {
  const res = await fetch(url, { method, headers: body && !isForm ? { "content-type": "application/json" } : {}, body: isForm ? body : body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
function toast(msg, kind = "error") {
  const t = $("#toast"); t.textContent = msg; t.className = `toast show ${kind}`;
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 5000);
}

/* ---------- Library ---------- */
async function loadDocs() {
  docs = await api("GET", "/api/documents");
  $("#lib-count").textContent = docs.length ? `· ${docs.length}` : "";
  $("#docs").replaceChildren(...(docs.length ? docs.map((d) => h("li", { class: "doc" },
    h("span", { class: "doc-icon" }, KIND_ICON[d.kind] || "📄"),
    h("div", {}, h("b", { title: d.name }, d.name), h("small", {}, `${d.pages} ${d.kind === "pdf" ? "page" : "section"}${d.pages === 1 ? "" : "s"} · ${d.chunk_count} passages`)),
    h("button", { type: "button", class: "icon-btn", "aria-label": `Remove ${d.name}`, title: "Remove", onclick: () => removeDoc(d) }, "✕"))) : [h("li", { class: "muted small" }, "No documents yet.")]));
  if (!$("#thread").children.length || $(".welcome")) renderWelcome();
}
async function removeDoc(d) {
  try { await api("DELETE", `/api/documents/${d.id}`); await loadDocs(); toast(`Removed ${d.name}.`, "info"); } catch (e) { toast(e.message); }
}
async function upload(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  $("#drop").classList.add("busy");
  try {
    const r = await api("POST", "/api/documents", fd, true);
    await loadDocs();
    toast(`Added ${r.added.length} document${r.added.length === 1 ? "" : "s"}${r.skipped.length ? ` · skipped: ${r.skipped.join("; ")}` : ""}`, r.skipped.length ? "error" : "info");
  } catch (e) { toast(e.message); } finally { $("#drop").classList.remove("busy"); }
}
$("#file").addEventListener("change", (e) => { upload([...e.target.files]); e.target.value = ""; });
$("#drop").addEventListener("dragover", (e) => { e.preventDefault(); $("#drop").classList.add("over"); });
$("#drop").addEventListener("dragleave", () => $("#drop").classList.remove("over"));
$("#drop").addEventListener("drop", (e) => { e.preventDefault(); $("#drop").classList.remove("over"); upload([...e.dataTransfer.files]); });
$("#samples").addEventListener("click", async () => {
  try { const r = await api("POST", "/api/samples"); await loadDocs(); toast(r.added.length ? `Loaded ${r.added.length} sample documents.` : "Samples are already loaded.", "info"); } catch (e) { toast(e.message); }
});

/* ---------- Thread ---------- */
function renderWelcome() {
  $("#thread").replaceChildren(h("li", { class: "welcome" },
    h("span", { class: "welcome-icon" }, "📘"),
    h("h2", {}, docs.length ? "Ask a question" : "Start by adding documents"),
    h("p", { class: "muted" }, docs.length ? "Try one of these:" : "Upload handbooks, policies or manuals — or load the samples to try it."),
    docs.length ? h("div", { class: "starters" }, STARTERS.map((q) => h("button", { type: "button", class: "chip", onclick: () => ask(q) }, q))) : null));
}
function answerNode(entry) {
  const a = entry.answer, id = entry.id;
  const body = h("p", { class: "answer-text" });
  if (a.parts.length) {
    for (const part of a.parts) {
      body.append(part.text);
      for (const n of part.sources) body.append(h("button", { type: "button", class: "cite", "aria-label": `Source ${n}`, onclick: () => focusSource(id, n) }, n));
    }
  } else body.append(a.text);
  return h("li", { class: "turn" },
    h("div", { class: "q" }, h("span", { class: "q-av" }, "You"), h("p", {}, entry.question)),
    h("div", { class: `a${a.cited ? "" : " uncited"}` },
      h("div", { class: "a-head" }, h("span", { class: "a-av" }, "📘"), h("b", {}, "Answer"), !a.cited ? h("span", { class: "pill warn" }, a.no_match ? "Not in your documents" : "No source quoted") : h("span", { class: "pill ok" }, `${a.sources.length} source${a.sources.length === 1 ? "" : "s"}`)),
      body,
      a.sources.length ? h("ol", { class: "sources" }, a.sources.map((s) => h("li", { id: `src-${id}-${s.n}`, class: "source" },
        h("span", { class: "src-n" }, s.n),
        h("div", {}, h("b", {}, `${s.doc_name.replace(/\.(md|txt|pdf)$/i, "")}`, h("small", {}, ` · ${s.location}`)), h("blockquote", {}, s.quote))))) : null));
}
function focusSource(id, n) {
  const el = document.getElementById(`src-${id}-${n}`);
  if (!el) return;
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}
async function loadHistory() {
  const items = await api("GET", "/api/history");
  if (!items.length) return renderWelcome();
  $("#thread").replaceChildren(...items.reverse().map(answerNode));
  $("#thread").lastElementChild?.scrollIntoView({ block: "end" });
}

async function ask(question) {
  question = question.trim();
  if (!question || asking) return;
  if (!docs.length) return toast("Add a document or load the samples first.", "info");
  asking = true;
  $(".welcome")?.remove();
  const pending = h("li", { class: "turn" }, h("div", { class: "q" }, h("span", { class: "q-av" }, "You"), h("p", {}, question)),
    h("div", { class: "a thinking" }, h("span", { class: "a-av" }, "📘"), h("span", { class: "dots" }, h("i"), h("i"), h("i")), h("span", { class: "muted" }, "Searching your documents…")));
  $("#thread").append(pending);
  pending.scrollIntoView({ block: "end", behavior: "smooth" });
  $("#question").value = ""; grow();
  try {
    pending.replaceWith(answerNode(await api("POST", "/api/ask", { question })));
    $("#thread").lastElementChild.scrollIntoView({ block: "end", behavior: "smooth" });
  } catch (e) {
    pending.remove(); toast(e.message); $("#question").value = question;
    if (!$("#thread").children.length) renderWelcome();
  } finally { asking = false; }
}
$("#ask").addEventListener("submit", (e) => { e.preventDefault(); ask($("#question").value); });
const grow = () => { const q = $("#question"); q.style.height = "auto"; q.style.height = `${Math.min(q.scrollHeight, 160)}px`; };
$("#question").addEventListener("input", grow);
$("#question").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask").requestSubmit(); } });
$("#clear").addEventListener("click", async () => { try { await api("DELETE", "/api/history"); renderWelcome(); } catch (e) { toast(e.message); } });

(async () => {
  try {
    const s = await api("GET", "/api/status");
    $("#key-status").replaceChildren(h("span", { class: `dot ${s.api_key_configured ? "ok" : "warn"}` }), s.api_key_configured ? "Claude connected" : "No API key — add it to .env");
    await loadDocs();
    await loadHistory();
  } catch (e) { toast(e.message); }
})();
