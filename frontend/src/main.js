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
function briefSourceLabel(source) {
  if (source === "llm") return "AI 의견 초안";
  if (source === "template_fallback") return "규칙 기반 초안";
  if (source === "graph" || source === "knowledge_graph") return "지식그래프 정리";
  if (!source || source === "template") return "시스템 초안";
  return String(source);
}

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
          <span class="chip accent">${esc(briefSourceLabel(brief.source))}</span>
          ${fallback.confidence != null ? `<span class="chip">신뢰도 ${(fallback.confidence * 100).toFixed(1)}%</span>` : ""}
        </div>
      </div>
      <div class="brief-section"><h4>추천 코드</h4>
        <p><span class="brief-code">${esc(rec.hs || "")}</span>${rec.title ? ` — ${esc(rec.title)}` : ""}</p></div>
      <div class="brief-section"><h4>선정 사유</h4><p>${esc(rec.why_selected || brief.narrative_ko || "")}</p></div>
      <div class="brief-section"><h4>GIR 근거</h4><p>${esc(rec.gir_basis || "-")}</p></div>
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

function showChatWelcome() {
  const box = document.getElementById("chat-messages");
  box.innerHTML = `
    <div class="bubble-row theirs">
      <div class="bubble assistant welcome">
        <div class="bubble-text">상품명·재질·용도를 입력해 주세요. AI가 HS 추천 초안과 검토 포인트를 의견서 형식으로 정리합니다. 최종 확정은 관세사 검토 화면에서 진행합니다.</div>
      </div>
    </div>`;
}

async function loadChatMessages(sessionId) {
  const rows = await api(`/chat/sessions/${sessionId}/messages`);
  const box = document.getElementById("chat-messages");
  box.innerHTML = "";
  if (!rows.length) {
    showChatWelcome();
    return;
  }
  rows.forEach(appendChatMessage);
}

async function refreshChatSessions() {
  const rows = await api("/chat/sessions");
  const el = document.getElementById("chat-session-list");
  if (!rows.length) {
    el.innerHTML = `<p class="muted">의뢰 이력이 없습니다. 새 의뢰를 시작해 주세요.</p>`;
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
      body: JSON.stringify({ title: "신규 분류 의뢰" }),
    });
    state.chatSessionId = created.id;
  }
  await loadChatMessages(state.chatSessionId);
  await refreshChatSessions();
}

document.getElementById("btn-new-chat").addEventListener("click", async () => {
  const created = await api("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "신규 분류 의뢰" }),
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
  btn.textContent = "검토 중…";
  const box = document.getElementById("chat-messages");
  if (box.querySelector(".bubble.welcome")) box.innerHTML = "";
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
    btn.textContent = "의뢰";
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
      `의견 확정 · 학습 반영 완료 (HS 변경 ${out.hs_changed ? "예" : "아니오"} · 가중치 ${(out.learning_artifact?.weight_updates || []).length}건)`;
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
    el.innerHTML = `<p class="muted">검토 대기 건이 없습니다. HS 분류 상담에서 의뢰를 진행해 주세요.</p>`;
    return;
  }
  el.innerHTML = rows
    .map(
      (r) => `<article class="card-lite">
      <span class="badge warn">검토 대기</span>
      <strong>#${r.classification_id} 시스템 추천 ${esc(r.recommended_hs)}</strong>
      <div class="muted">${esc(r.description)}</div>
      <pre class="opinion-preview">${esc((r.system_opinion || "").slice(0, 360))}${
        (r.system_opinion || "").length > 360 ? "…" : ""
      }</pre>
      <button class="btn" data-open="${r.classification_id}">의견서 검토</button>
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
    const extract = doc.extract || doc.analysis?.extract || {};
    if (extract.ok === false) {
      msg.textContent = `업로드 #${doc.id} · 추출 실패 — ${extract.warning || "형식을 확인해 주세요"}`;
    } else {
      msg.textContent = `업로드 완료 #${doc.id} · ${extract.format || "파일"} 추출 ${extract.char_count ?? ""}자`;
    }
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
      } · overlay=${doc.office_model?.phrase_overlay ?? doc.learning_artifact?.office_model?.phrase_overlay ?? "-"}`;
    await refreshDocuments();
    refreshPending();
    refreshWeights();
  } catch (ex) {
    document.getElementById("doc-upload-msg").textContent = ex.message;
  }
});

/* ---------- Admin analytics dashboard ---------- */
const dashCharts = {};

function pct(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function fmtCi(ci) {
  if (!ci || ci[0] == null || ci[1] == null) return "—";
  return `${(ci[0] * 100).toFixed(1)}–${(ci[1] * 100).toFixed(1)}%`;
}

function destroyChart(key) {
  if (dashCharts[key]) {
    dashCharts[key].destroy();
    delete dashCharts[key];
  }
}

function chartColors() {
  return {
    accent: "#1b4f72",
    accent2: "#2f6b5a",
    soft: "#2a6f97",
    warn: "#8a5a12",
    muted: "#5b6b7c",
    grid: "rgba(20, 32, 51, 0.08)",
    fills: ["#1b4f72", "#2f6b5a", "#2a6f97", "#5b6b7c", "#8a5a12", "#4a6fa5", "#3d7a6a", "#6b7280"],
  };
}

function makeChart(key, canvasId, config) {
  const el = document.getElementById(canvasId);
  if (!el || typeof Chart === "undefined") return;
  destroyChart(key);
  dashCharts[key] = new Chart(el, config);
}

function renderKpis(m, paper) {
  const acc = paper.accuracy || {};
  const ops = paper.operations || {};
  const learn = paper.learning || {};
  const tiles = [
    {
      label: "표본 N",
      value: String(m.n ?? 0),
      sub: `라벨 ${acc.n_labeled ?? m.n_labeled ?? 0}건`,
    },
    {
      label: "Top-1",
      value: pct(acc.top1?.rate ?? m.top1),
      sub: `95% CI ${fmtCi(acc.top1?.ci95)}`,
      cls: "accent-ok",
    },
    {
      label: "Prefix-4",
      value: pct(acc.prefix4?.rate ?? m.prefix4),
      sub: `P6 ${pct(acc.prefix6?.rate ?? m.prefix6)} · Ch ${pct(acc.chapter?.rate ?? m.chapter_hit)}`,
      cls: "accent-ok",
    },
    {
      label: "ESA",
      value: pct(acc.esa?.rate ?? m.esa),
      sub: `RVR ${pct(acc.rvr?.rate ?? m.rvr)}`,
    },
    {
      label: "CIR",
      value: pct(acc.cir?.rate ?? m.cir),
      sub: `수정 ${acc.cir?.n_overrides ?? 0} → 재현 ${acc.cir?.incorporated ?? 0}`,
    },
    {
      label: "Escalation",
      value: pct(ops.escalation_rate ?? m.escalation_rate),
      sub: `Override ${pct(ops.override_rate ?? m.override_rate)}`,
      cls: "accent-warn",
    },
    {
      label: "Avg Confidence",
      value: fmt(ops.avg_confidence ?? m.avg_confidence),
      sub: `mode-collapse ${ops.mode_collapse_flags ?? m.mode_collapse_flags ?? 0}`,
    },
    {
      label: "학습 가중치",
      value: String(learn.weight_pairs ?? 0),
      sub: `의견서 수정률 ${pct(learn.hs_change_rate)}`,
    },
  ];
  document.getElementById("dash-kpi").innerHTML = tiles
    .map(
      (t) => `<div class="kpi-tile ${t.cls || ""}">
      <div class="kpi-label">${esc(t.label)}</div>
      <div class="kpi-value">${esc(t.value)}</div>
      <div class="kpi-sub">${esc(t.sub)}</div>
    </div>`
    )
    .join("");
}

function renderCiTable(acc) {
  const rows = [
    ["Top-1", acc.top1],
    ["Prefix-4", acc.prefix4],
    ["Prefix-6", acc.prefix6],
    ["Chapter", acc.chapter],
    ["ESA", acc.esa],
    ["RVR", acc.rvr],
  ];
  document.getElementById("dash-ci-table").innerHTML = `<table>
    <thead><tr><th>지표</th><th>비율</th><th>n</th><th>95% CI</th></tr></thead>
    <tbody>
      ${rows
        .map(([name, b]) => {
          const block = b || {};
          return `<tr>
            <td>${esc(name)}</td>
            <td>${pct(block.rate)}</td>
            <td>${block.n ?? "—"}</td>
            <td>${fmtCi(block.ci95)}</td>
          </tr>`;
        })
        .join("")}
    </tbody>
  </table>`;
}

function renderDefinitions(defs) {
  const el = document.getElementById("dash-definitions");
  const entries = Object.entries(defs || {});
  el.innerHTML = entries.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

function renderDashCharts(paper) {
  const c = chartColors();
  const ts = paper.timeseries?.daily || [];
  const labels = ts.map((d) => d.date.slice(5));
  makeChart("timeseries", "chart-timeseries", {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Top-1",
          data: ts.map((d) => (d.top1 == null ? null : d.top1 * 100)),
          borderColor: c.accent2,
          backgroundColor: "rgba(47,107,90,0.12)",
          tension: 0.25,
          yAxisID: "y",
          spanGaps: true,
        },
        {
          label: "Avg Confidence ×100",
          data: ts.map((d) => (d.avg_confidence == null ? null : d.avg_confidence * 100)),
          borderColor: c.accent,
          backgroundColor: "rgba(27,79,114,0.08)",
          tension: 0.25,
          yAxisID: "y",
          borderDash: [5, 4],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: {
        y: { min: 0, max: 100, grid: { color: c.grid }, ticks: { callback: (v) => `${v}%` } },
        x: { grid: { display: false } },
      },
    },
  });

  const acc = paper.accuracy || {};
  const prefixKeys = [
    ["Top-1", acc.top1],
    ["P4", acc.prefix4],
    ["P6", acc.prefix6],
    ["Ch", acc.chapter],
    ["ESA", acc.esa],
  ];
  makeChart("prefix", "chart-prefix", {
    type: "bar",
    data: {
      labels: prefixKeys.map(([k]) => k),
      datasets: [
        {
          label: "Hit rate %",
          data: prefixKeys.map(([, b]) => (b?.rate == null ? 0 : b.rate * 100)),
          backgroundColor: [c.accent2, c.accent, c.soft, c.muted, c.warn],
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { min: 0, max: 100, grid: { color: c.grid }, ticks: { callback: (v) => `${v}%` } },
        x: { grid: { display: false } },
      },
    },
  });

  const hist = paper.distributions?.confidence_histogram || [];
  makeChart("confidence", "chart-confidence", {
    type: "bar",
    data: {
      labels: hist.map((h) => h.bin),
      datasets: [
        {
          label: "건수",
          data: hist.map((h) => h.count),
          backgroundColor: c.accent,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: c.grid }, ticks: { precision: 0 } },
        x: { grid: { display: false } },
      },
    },
  });

  const chapters = (paper.distributions?.chapter_top || []).slice(0, 8);
  makeChart("chapter", "chart-chapter", {
    type: "doughnut",
    data: {
      labels: chapters.map((x) => `류 ${x.chapter}`),
      datasets: [
        {
          data: chapters.map((x) => x.count),
          backgroundColor: c.fills.slice(0, chapters.length),
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "right", labels: { boxWidth: 10, font: { size: 10 } } } },
    },
  });

  const status = paper.distributions?.status || [];
  makeChart("status", "chart-status", {
    type: "bar",
    data: {
      labels: status.map((s) => s.key),
      datasets: [
        {
          label: "건수",
          data: status.map((s) => s.count),
          backgroundColor: status.map((_, i) => c.fills[i % c.fills.length]),
          borderRadius: 4,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, grid: { color: c.grid }, ticks: { precision: 0 } },
        y: { grid: { display: false } },
      },
    },
  });
}

async function refreshMetrics() {
  const m = await api("/metrics");
  const paper = m.paper || {};
  const stamp = document.getElementById("dash-updated");
  if (stamp) {
    const t = paper.generated_at ? new Date(paper.generated_at) : new Date();
    stamp.textContent = `갱신 ${t.toLocaleString("ko-KR")}`;
  }
  renderKpis(m, paper);
  renderCiTable(paper.accuracy || {});
  renderDefinitions(paper.definitions || {});
  // Charts need Chart.js; retry briefly if CDN still loading
  const paint = () => renderDashCharts(paper);
  if (typeof Chart !== "undefined") paint();
  else setTimeout(paint, 400);

  const rows = await api("/classifications?limit=12");
  document.getElementById("class-list").innerHTML =
    rows
      .map(
        (r) => `<article class="card-lite"><span class="badge">${esc(r.status)}</span>
      <strong>#${r.id} ${esc(r.final_hs)}</strong>
      <div class="muted">추천 ${esc(r.recommended_hs)} · conf ${fmt(r.confidence)} · ${esc(r.review_tier)}</div></article>`
      )
      .join("") || `<p class="muted">분류 결과 없음</p>`;

  // Prefer paper learning top weights when present
  const learnRows = paper.learning?.top_weights;
  if (learnRows?.length) {
    document.getElementById("weights-list").innerHTML = learnRows
      .map(
        (r) => `<article class="card-lite"><strong>${esc(r.keyword)} → ${esc(r.hs_code)}</strong>
      <div class="muted">weight=${fmt(r.weight)} · evidence=${r.evidence_count}</div></article>`
      )
      .join("");
  }

  const exps = paper.experiments || [];
  const blindEl = document.getElementById("blind-eval-list");
  if (blindEl && exps.length) {
    blindEl.innerHTML = exps
      .map(
        (r) => `<article class="card-lite">
        <span class="badge">${esc(r.status)}</span>
        <strong>#${r.id} ${esc(r.name)}</strong>
        <div class="muted">${esc(r.type)} · Q ${fmt(r.quality_score)} · P4 ${fmt(r.prefix4_hit_rate)}${
          r.delta_score != null ? ` · Δ ${fmt(r.delta_score)}` : ""
        }</div>
      </article>`
      )
      .join("");
  }
}

async function refreshWeights() {
  const rows = await api("/learning/weights");
  const el = document.getElementById("weights-list");
  if (!el) return;
  // Keep paper top_weights if already richer; still refresh from API when empty
  if (!rows.length && el.querySelector(".card-lite")) return;
  el.innerHTML = rows.length
    ? rows
        .slice(0, 12)
        .map(
          (r) => `<article class="card-lite"><strong>${esc(r.keyword)} → ${esc(r.hs_code)}</strong>
      <div class="muted">weight=${fmt(r.weight)} · evidence=${r.evidence_count}</div></article>`
        )
        .join("")
    : `<p class="muted">아직 학습 가중치가 없습니다. 의견서/업무자료를 반영하세요.</p>`;
}

async function refreshBlindEvals() {
  const el = document.getElementById("blind-eval-list");
  if (!el) return;
  // If metrics already filled experiments, skip overwrite unless empty
  if (el.querySelector(".card-lite") && !el.dataset.force) return;
  try {
    const out = await api("/agents/blind-eval/latest?limit=5");
    const runs = out.runs || [];
    el.innerHTML = runs.length
      ? runs
          .map((r) => {
            const ev = r.metrics?.evaluation || {};
            const plan = r.metrics?.plan || {};
            return `<article class="card-lite">
          <span class="badge ${r.status === "completed" ? "" : "warn"}">${esc(r.status)}</span>
          <strong>#${r.id} ${esc(r.name)}</strong>
          <div class="muted">품질 ${fmt(ev.quality_score)} · prefix4 ${fmt(ev.metrics?.prefix4_hit_rate)} · ${esc(
              (plan.actions || [])[0] || ""
            )}</div>
        </article>`;
          })
          .join("")
      : `<p class="muted">아직 블라인드 검증 이력이 없습니다.</p>`;
  } catch {
    el.innerHTML = `<p class="muted">블라인드 검증 이력을 불러오지 못했습니다.</p>`;
  }
}

document.getElementById("btn-dash-refresh")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-dash-refresh");
  btn.disabled = true;
  try {
    await refreshMetrics();
    await refreshWeights();
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-retrain")?.addEventListener("click", async () => {
  const box = document.getElementById("agent-status");
  box.hidden = false;
  box.textContent = "사무실 모델 재학습 중…";
  try {
    const out = await api("/learning/retrain", { method: "POST", body: "{}" });
    box.textContent = JSON.stringify(out.office_model || out, null, 2);
    refreshWeights();
    refreshMetrics();
  } catch (ex) {
    box.textContent = ex.message;
  }
});

document.getElementById("btn-blind-eval")?.addEventListener("click", async () => {
  const box = document.getElementById("agent-status");
  const btn = document.getElementById("btn-blind-eval");
  box.hidden = false;
  box.textContent = "블라인드 테스터 → 평가 → 총괄 사이클 실행 중…";
  btn.disabled = true;
  try {
    const out = await api("/agents/blind-eval/run", {
      method: "POST",
      body: JSON.stringify({ limit: 8, auto_remediate: true }),
    });
    const summary = {
      status: out.status,
      quality_score: out.evaluation?.quality_score,
      passed: out.evaluation?.passed,
      metrics: out.evaluation?.metrics,
      remediations: out.remediations,
      plan: out.plan,
      learning_stats: out.learning_stats,
    };
    box.textContent = JSON.stringify(summary, null, 2);
    document.getElementById("blind-eval-list").dataset.force = "1";
    await refreshBlindEvals();
    delete document.getElementById("blind-eval-list").dataset.force;
    refreshWeights();
    refreshMetrics();
  } catch (ex) {
    box.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-sia-harness")?.addEventListener("click", async () => {
  const box = document.getElementById("agent-status");
  const btn = document.getElementById("btn-sia-harness");
  box.hidden = false;
  box.textContent = "SIA harness 루프 실행 중 (블라인드×의견서×scaffold 패치)…";
  btn.disabled = true;
  try {
    const out = await api("/agents/sia-harness/run", {
      method: "POST",
      body: JSON.stringify({ rounds: 3, apply_opinions: true, reset: true }),
    });
    box.textContent = JSON.stringify(
      {
        summary: out.summary,
        improved: out.improved,
        delta_score: out.delta_score,
        baseline: out.baseline,
        final: out.final,
        interpretation: out.interpretation,
        rounds: out.rounds,
        harness: out.harness,
        experiment_run_id: out.experiment_run_id,
      },
      null,
      2
    );
    document.getElementById("blind-eval-list").dataset.force = "1";
    await refreshBlindEvals();
    delete document.getElementById("blind-eval-list").dataset.force;
    refreshWeights();
    refreshMetrics();
  } catch (ex) {
    box.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
});

async function refreshAll() {
  await Promise.allSettled([
    refreshPending(),
    refreshMetrics(),
    refreshWeights(),
    refreshDocuments(),
    refreshBlindEvals(),
  ]);
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
