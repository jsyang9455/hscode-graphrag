const API =
  window.HSCODE_API ||
  (location.port === "5173"
    ? `${location.protocol}//${location.hostname}:8000/api/v1`
    : "/api/v1");

const state = {
  token: localStorage.getItem("hs_token") || "",
  user: JSON.parse(localStorage.getItem("hs_user") || "null"),
  chatSessionId: null,
  currentDocId: null,
};

function authHeaders(json = true) {
  const h = {};
  if (state.token) h.Authorization = `Bearer ${state.token}`;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: { ...authHeaders(!isForm), ...(options.headers || {}) },
  });
  if (res.status === 401) {
    logout(false);
    throw new Error("로그인이 필요합니다");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showAuth() {
  const auth = document.getElementById("view-auth");
  const app = document.getElementById("view-app");
  auth.hidden = false;
  auth.style.display = "";
  app.hidden = true;
  app.style.display = "none";
}

function showApp() {
  const auth = document.getElementById("view-auth");
  const app = document.getElementById("view-app");
  auth.hidden = true;
  auth.style.display = "none";
  app.hidden = false;
  app.style.display = "";
  document.getElementById("user-label").textContent =
    `${state.user.full_name} · ${state.user.office_name} (${state.user.office_code})`;
  switchView(location.hash.replace("#", "") || "chat");
  refreshAll();
}

function logout(clear = true) {
  if (clear) {
    localStorage.removeItem("hs_token");
    localStorage.removeItem("hs_user");
  }
  state.token = "";
  state.user = null;
  state.chatSessionId = null;
  showAuth();
}

function fmt(n) {
  return typeof n === "number" ? n.toFixed(3) : "-";
}

function switchView(name) {
  const allowed = ["chat", "opinions", "documents", "admin"];
  const view = allowed.includes(name) ? name : "chat";
  document.querySelectorAll(".view-pane").forEach((el) => {
    const on = el.id === `view-${view}`;
    el.hidden = !on;
    el.classList.toggle("active", on);
  });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });
  if (location.hash !== `#${view}`) location.hash = view;
  if (view === "chat") ensureChatSession();
  if (view === "opinions") refreshPending();
  if (view === "documents") refreshDocuments();
  if (view === "admin") {
    refreshMetrics();
    refreshWeights();
  }
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
window.addEventListener("hashchange", () => {
  if (!state.token) return;
  switchView(location.hash.replace("#", "") || "chat");
});

// tabs auth
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    document.getElementById("form-login").hidden = tab !== "login";
    document.getElementById("form-signup").hidden = tab !== "signup";
  });
});

document.getElementById("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("login-error");
  const btn = e.target.querySelector('button[type="submit"]');
  err.hidden = true;
  const prevLabel = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "로그인 중…";
  }
  try {
    const body = {
      email: document.getElementById("login-email").value.trim(),
      password: document.getElementById("login-password").value,
      office_code: document.getElementById("login-office").value.trim() || null,
    };
    const out = await api("/auth/login", { method: "POST", body: JSON.stringify(body) });
    state.token = out.access_token;
    state.user = out.user;
    localStorage.setItem("hs_token", state.token);
    localStorage.setItem("hs_user", JSON.stringify(state.user));
    showApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prevLabel || "로그인";
    }
  }
});

document.getElementById("form-signup").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = document.getElementById("signup-error");
  err.hidden = true;
  try {
    const body = {
      email: document.getElementById("su-email").value.trim(),
      password: document.getElementById("su-password").value,
      full_name: document.getElementById("su-name").value.trim(),
      office_code: document.getElementById("su-office-code").value.trim(),
      office_name: document.getElementById("su-office-name").value.trim(),
    };
    const out = await api("/auth/signup", { method: "POST", body: JSON.stringify(body) });
    state.token = out.access_token;
    state.user = out.user;
    localStorage.setItem("hs_token", state.token);
    localStorage.setItem("hs_user", JSON.stringify(state.user));
    showApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

document.getElementById("btn-logout").addEventListener("click", () => logout());

document.getElementById("btn-data").addEventListener("click", async () => {
  const el = document.getElementById("data-status");
  try {
    const out = await api("/data/status");
    el.hidden = false;
    el.textContent = JSON.stringify(out, null, 2);
  } catch (ex) {
    el.hidden = false;
    el.textContent = ex.message;
  }
});

document.getElementById("btn-ingest").addEventListener("click", async () => {
  try {
    const out = await api("/admin/ingest-hs", { method: "POST" });
    alert(`HS 적재 완료: ${JSON.stringify(out)}`);
  } catch (ex) {
    alert(ex.message);
  }
});

document.getElementById("btn-batch").addEventListener("click", async () => {
  try {
    const out = await api("/classify/batch", {
      method: "POST",
      body: JSON.stringify({ closed_loop: true, limit: 50 }),
    });
    alert(`일괄 분류 ${out.processed}건`);
    refreshAll();
  } catch (ex) {
    alert(ex.message);
  }
});

/* ---------- Chat ---------- */
function renderBriefCard(brief, fallback = {}) {
  const rec = brief.recommended || {
    hs: fallback.recommended_hs,
    title: "",
    why_selected: brief.narrative_ko || "",
    gir_basis: (fallback.gir_applied || []).join(", "),
  };
  const alts = brief.alternatives || [];
  const risks = brief.risks_and_checks || [];
  return `
    <div class="brief chat-brief">
      <div class="brief-head">
        <h3>${esc(brief.headline || `추천 HS ${rec.hs || ""}`)}</h3>
        <div class="brief-meta">
          <span class="chip accent">${esc(brief.source || "template")}</span>
          ${fallback.confidence != null ? `<span class="chip">신뢰도 ${(fallback.confidence * 100).toFixed(1)}%</span>` : ""}
        </div>
      </div>
      <div class="brief-section"><h4>추천 코드</h4>
        <p><span class="brief-code">${esc(rec.hs || "")}</span>${rec.title ? ` — ${esc(rec.title)}` : ""}</p></div>
      <div class="brief-section"><h4>선정 사유</h4><p>${esc(rec.why_selected || brief.narrative_ko || "")}</p></div>
      <div class="brief-section"><h4>GIR</h4><p>${esc(rec.gir_basis || "-")}</p></div>
      ${
        alts.length
          ? `<div class="brief-section"><h4>대안</h4><div class="alt-list">${alts
              .map(
                (a) =>
                  `<div class="alt-item"><strong>${esc(a.hs)} — ${esc(a.title || "")}</strong><span class="muted">${esc(
                    a.why_secondary || ""
                  )}</span></div>`
              )
              .join("")}</div></div>`
          : ""
      }
      ${
        risks.length
          ? `<div class="brief-section"><h4>확인 포인트</h4><ul>${risks
              .map((r) => `<li>${esc(r)}</li>`)
              .join("")}</ul></div>`
          : ""
      }
    </div>`;
}

function appendChatMessage(msg) {
  const box = document.getElementById("chat-messages");
  const mine = msg.role === "user";
  const brief = msg.meta?.broker_brief;
  const el = document.createElement("div");
  el.className = `bubble-row ${mine ? "mine" : "theirs"}`;
  el.innerHTML = `
    <div class="bubble ${mine ? "user" : "assistant"}">
      <div class="bubble-text">${esc(msg.content).replace(/\n/g, "<br>")}</div>
      ${!mine && brief ? renderBriefCard(brief, msg.meta || {}) : ""}
      ${
        !mine && msg.classification_id
          ? `<button type="button" class="btn ghost mini" data-goto-opinion="${msg.classification_id}">의견서에서 검토</button>`
          : ""
      }
    </div>`;
  box.appendChild(el);
  el.querySelector("[data-goto-opinion]")?.addEventListener("click", () => {
    switchView("opinions");
    refreshPending().then(() => {
      const item = window.__pendingRows?.find(
        (x) => String(x.classification_id) === String(msg.classification_id)
      );
      if (item) openOpinionForm(item);
    });
  });
  box.scrollTop = box.scrollHeight;
}

async function loadChatMessages(sessionId) {
  const rows = await api(`/chat/sessions/${sessionId}/messages`);
  const box = document.getElementById("chat-messages");
  box.innerHTML = "";
  rows.forEach(appendChatMessage);
}

async function refreshChatSessions() {
  const rows = await api("/chat/sessions");
  const el = document.getElementById("chat-session-list");
  if (!rows.length) {
    el.innerHTML = `<p class="muted">대화가 없습니다.</p>`;
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `<button type="button" class="session-item ${
        r.id === state.chatSessionId ? "active" : ""
      }" data-sid="${r.id}">${esc(r.title)}</button>`
    )
    .join("");
  el.querySelectorAll("[data-sid]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.chatSessionId = Number(btn.dataset.sid);
      await loadChatMessages(state.chatSessionId);
      refreshChatSessions();
    });
  });
}

async function ensureChatSession() {
  if (state.chatSessionId) {
    await loadChatMessages(state.chatSessionId);
    await refreshChatSessions();
    return;
  }
  const sessions = await api("/chat/sessions");
  if (sessions.length) {
    state.chatSessionId = sessions[0].id;
  } else {
    const created = await api("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "새 HS 분류 대화" }),
    });
    state.chatSessionId = created.id;
  }
  await loadChatMessages(state.chatSessionId);
  await refreshChatSessions();
}

document.getElementById("btn-new-chat").addEventListener("click", async () => {
  const created = await api("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "새 HS 분류 대화" }),
  });
  state.chatSessionId = created.id;
  await loadChatMessages(state.chatSessionId);
  await refreshChatSessions();
});

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.chatSessionId) await ensureChatSession();
  const input = document.getElementById("chat-input");
  const content = input.value.trim();
  if (!content) return;
  const btn = document.getElementById("btn-chat-send");
  btn.disabled = true;
  btn.textContent = "분류 중…";
  appendChatMessage({ role: "user", content });
  input.value = "";
  try {
    const out = await api(`/chat/sessions/${state.chatSessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({
        content,
        material: document.getElementById("chat-material").value.trim() || null,
        function: document.getElementById("chat-usage").value.trim() || null,
        closed_loop: document.getElementById("chat-closed").checked,
      }),
    });
    // remove optimistic duplicate user bubble already shown; reload for consistency
    await loadChatMessages(state.chatSessionId);
    await refreshChatSessions();
    refreshPending();
  } catch (ex) {
    appendChatMessage({ role: "assistant", content: `오류: ${ex.message}` });
  } finally {
    btn.disabled = false;
    btn.textContent = "전송";
  }
});

/* ---------- Opinions ---------- */
function openOpinionForm(item) {
  const form = document.getElementById("opinion-form");
  form.hidden = false;
  document.getElementById("op-class-id").value = item.classification_id;
  document.getElementById("op-system-hs").value = item.recommended_hs;
  document.getElementById("op-broker-hs").value = item.recommended_hs;
  document.getElementById("op-detail").value = "";
  document.getElementById("op-msg").textContent =
    `${item.description}\n\n[시스템 사유]\n${item.system_opinion || item.gir_rationale || ""}`;
  form.scrollIntoView({ behavior: "smooth" });
}

document.getElementById("opinion-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const conditions = [...document.querySelectorAll('input[name="cond"]:checked')].map((x) => x.value);
  try {
    const out = await api("/opinions/broker-review", {
      method: "POST",
      body: JSON.stringify({
        classification_id: Number(document.getElementById("op-class-id").value),
        broker_hs: document.getElementById("op-broker-hs").value.trim(),
        conditions: conditions.length ? conditions : ["hs_accurate"],
        detail_opinion: document.getElementById("op-detail").value.trim(),
      }),
    });
    document.getElementById("op-msg").textContent =
      `학습 반영 완료 · changed=${out.hs_changed} · weights=${(out.learning_artifact?.weight_updates || []).length}`;
    document.getElementById("opinion-form").hidden = true;
    refreshAll();
  } catch (ex) {
    document.getElementById("op-msg").textContent = ex.message;
  }
});

async function refreshPending() {
  const rows = await api("/opinions/pending");
  window.__pendingRows = rows;
  const el = document.getElementById("pending-list");
  if (!rows.length) {
    el.innerHTML = `<p class="muted">대기 중인 의견서가 없습니다. 챗봇에서 분류를 실행하세요.</p>`;
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `<article class="card-lite">
      <span class="badge warn">pending</span>
      <strong>#${r.classification_id} 추천 ${esc(r.recommended_hs)}</strong>
      <div class="muted">${esc(r.description)}</div>
      <pre class="opinion-preview">${esc((r.system_opinion || "").slice(0, 360))}${
        (r.system_opinion || "").length > 360 ? "…" : ""
      }</pre>
      <button class="btn" data-open="${r.classification_id}">검토하기</button>
    </article>`
    )
    .join("");
  el.querySelectorAll("button[data-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = rows.find((x) => String(x.classification_id) === btn.dataset.open);
      if (item) openOpinionForm(item);
    });
  });
}

/* ---------- Documents ---------- */
function fillDocEditor(doc) {
  state.currentDocId = doc.id;
  const a = { ...(doc.analysis || {}), ...(doc.edited_fields || {}) };
  document.getElementById("doc-current").innerHTML =
    `<strong>#${doc.id}</strong> ${esc(doc.filename)} · <span class="badge">${esc(doc.status)}</span>`;
  document.getElementById("doc-edit-form").hidden = false;
  document.getElementById("doc-desc").value = a.product_description || "";
  document.getElementById("doc-material").value = a.material || "";
  document.getElementById("doc-usage").value = a.usage || "";
  document.getElementById("doc-hs").value = a.suggested_hs || "";
  document.getElementById("doc-opinion").value = a.broker_opinion_excerpt || "";
  const prev = document.getElementById("doc-analysis-preview");
  if (doc.analysis && Object.keys(doc.analysis).length) {
    prev.hidden = false;
    prev.textContent = JSON.stringify(doc.analysis, null, 2);
  } else {
    prev.hidden = true;
  }
}

async function refreshDocuments() {
  const rows = await api("/documents");
  const el = document.getElementById("doc-list");
  if (!rows.length) {
    el.innerHTML = `<p class="muted">업로드된 업무자료가 없습니다.</p>`;
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `<article class="card-lite">
      <span class="badge">${esc(r.status)}</span>
      <strong>#${r.id} ${esc(r.filename)}</strong>
      <div class="muted">${esc(r.doc_type)} · ${(r.analysis?.summary_ko || r.raw_text_preview || "").slice(0, 120)}</div>
      <button class="btn" data-doc="${r.id}">선택</button>
    </article>`
    )
    .join("");
  el.querySelectorAll("[data-doc]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const doc = await api(`/documents/${btn.dataset.doc}`);
      fillDocEditor(doc);
    });
  });
}

document.getElementById("btn-doc-upload").addEventListener("click", async () => {
  const fileInput = document.getElementById("doc-file");
  const msg = document.getElementById("doc-upload-msg");
  if (!fileInput.files?.length) {
    msg.textContent = "파일을 선택하세요.";
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("doc_type", document.getElementById("doc-type").value);
  try {
    const doc = await api("/documents/upload", { method: "POST", body: fd });
    msg.textContent = `업로드 완료 #${doc.id}`;
    fillDocEditor(doc);
    await refreshDocuments();
  } catch (ex) {
    msg.textContent = ex.message;
  }
});

document.getElementById("btn-doc-paste").addEventListener("click", async () => {
  const text = document.getElementById("doc-paste").value.trim();
  const msg = document.getElementById("doc-upload-msg");
  if (text.length < 5) {
    msg.textContent = "텍스트를 더 입력하세요.";
    return;
  }
  try {
    const doc = await api("/documents/paste", {
      method: "POST",
      body: JSON.stringify({
        title: "broker-memo.txt",
        text,
        doc_type: document.getElementById("doc-type").value,
      }),
    });
    msg.textContent = `붙여넣기 저장 #${doc.id}`;
    fillDocEditor(doc);
    await refreshDocuments();
  } catch (ex) {
    msg.textContent = ex.message;
  }
});

document.getElementById("btn-doc-analyze").addEventListener("click", async () => {
  if (!state.currentDocId) return;
  const btn = document.getElementById("btn-doc-analyze");
  btn.disabled = true;
  btn.textContent = "분석 중…";
  try {
    const doc = await api(`/documents/${state.currentDocId}/analyze`, { method: "POST" });
    fillDocEditor(doc);
    await refreshDocuments();
  } catch (ex) {
    document.getElementById("doc-upload-msg").textContent = ex.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "분석";
  }
});

document.getElementById("doc-edit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.currentDocId) return;
  try {
    const doc = await api(`/documents/${state.currentDocId}/save`, {
      method: "POST",
      body: JSON.stringify({
        run_classify: document.getElementById("doc-run-classify").checked,
        closed_loop: true,
        edited: {
          product_description: document.getElementById("doc-desc").value.trim(),
          material: document.getElementById("doc-material").value.trim() || null,
          usage: document.getElementById("doc-usage").value.trim() || null,
          suggested_hs: document.getElementById("doc-hs").value.trim() || null,
          broker_opinion_excerpt: document.getElementById("doc-opinion").value.trim() || null,
        },
      }),
    });
    fillDocEditor(doc);
    document.getElementById("doc-upload-msg").textContent =
      `학습 반영 완료 · classification=${doc.classification_id || "-"} · weights=${
        (doc.learning_artifact?.weight_updates || []).length
      }`;
    await refreshDocuments();
    refreshPending();
    refreshWeights();
  } catch (ex) {
    document.getElementById("doc-upload-msg").textContent = ex.message;
  }
});

/* ---------- Metrics / learning ---------- */
async function refreshMetrics() {
  const m = await api("/metrics");
  const grid = document.getElementById("metrics-grid");
  const items = [
    ["N", m.n],
    ["Top-1", fmt(m.top1)],
    ["ESA", fmt(m.esa)],
    ["RVR", fmt(m.rvr)],
    ["CIR", fmt(m.cir)],
    ["Escalation", fmt(m.escalation_rate)],
    ["Override", fmt(m.override_rate)],
    ["Avg Conf", fmt(m.avg_confidence)],
  ];
  grid.innerHTML = items
    .map(([label, value]) => `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`)
    .join("");
  const rows = await api("/classifications?limit=12");
  document.getElementById("class-list").innerHTML =
    rows
      .map(
        (r) => `<article class="card-lite"><span class="badge">${r.status}</span>
      <strong>#${r.id} ${r.final_hs}</strong>
      <div class="muted">추천 ${r.recommended_hs} · conf ${fmt(r.confidence)}</div></article>`
      )
      .join("") || `<p class="muted">분류 결과 없음</p>`;
}

async function refreshWeights() {
  const rows = await api("/learning/weights");
  const el = document.getElementById("weights-list");
  el.innerHTML = rows.length
    ? rows
        .map(
          (r) => `<article class="card-lite"><strong>${esc(r.keyword)} → ${esc(r.hs_code)}</strong>
      <div class="muted">weight=${fmt(r.weight)} · evidence=${r.evidence_count}</div></article>`
        )
        .join("")
    : `<p class="muted">아직 학습 가중치가 없습니다. 의견서/업무자료를 반영하세요.</p>`;
}

async function refreshAll() {
  await Promise.allSettled([refreshPending(), refreshMetrics(), refreshWeights(), refreshDocuments()]);
}

const TEST_ACCOUNT = {
  email: "test@demo-customs.com",
  password: "Test1234!",
  office_code: "DEMO-01",
};

function fillTestAccount() {
  document.getElementById("login-email").value = TEST_ACCOUNT.email;
  document.getElementById("login-password").value = TEST_ACCOUNT.password;
  document.getElementById("login-office").value = TEST_ACCOUNT.office_code;
}

document.getElementById("btn-fill-test")?.addEventListener("click", fillTestAccount);

if (state.token && state.user) showApp();
else {
  showAuth();
  fillTestAccount();
}
