const API =
  window.HSCODE_API ||
  (location.port === "5173"
    ? `${location.protocol}//${location.hostname}:8000/api/v1`
    : "/api/v1");

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function fmt(n) {
  if (typeof n !== "number") return "-";
  return n.toFixed(3);
}

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
    .map(
      ([label, value]) =>
        `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`
    )
    .join("");
}

async function refreshClassifications() {
  const rows = await api("/classifications?limit=12");
  const el = document.getElementById("class-list");
  if (!rows.length) {
    el.innerHTML = `<p class="muted">아직 분류 결과가 없습니다. 시드 적재 후 일괄 실증을 실행하세요.</p>`;
    return;
  }
  el.innerHTML = rows
    .map((r) => {
      const badge =
        r.status === "corrected"
          ? `<span class="badge warn">corrected</span>`
          : r.status === "blocked"
            ? `<span class="badge fail">blocked</span>`
            : `<span class="badge">auto</span>`;
      return `<article class="card-lite">
        ${badge}<strong>#${r.id} → ${r.final_hs}</strong>
        <div class="muted">추천 ${r.recommended_hs} · 신뢰도 ${fmt(r.confidence)} · ${r.review_tier} · ${r.routing_mode}</div>
      </article>`;
    })
    .join("");
}

async function refreshWorkOrders() {
  const rows = await api("/work-orders");
  const el = document.getElementById("wo-list");
  if (!rows.length) {
    el.innerHTML = `<p class="muted">총괄 에이전트 파이프라인 실행 후 작업지시가 표시됩니다.</p>`;
    return;
  }
  el.innerHTML = rows
    .map((r) => {
      const badge =
        r.status === "verified" || r.status === "completed"
          ? `<span class="badge">${r.status}</span>`
          : r.status === "failed"
            ? `<span class="badge fail">${r.status}</span>`
            : `<span class="badge warn">${r.status}</span>`;
      return `<article class="card-lite">
        ${badge}<strong>${r.agent_role}: ${r.title}</strong>
        <div class="muted">${r.order_id}${r.verification_notes ? " · " + r.verification_notes : ""}</div>
      </article>`;
    })
    .join("");
}

async function refreshAll() {
  await Promise.all([refreshMetrics(), refreshClassifications(), refreshWorkOrders()]);
}

document.getElementById("btn-seed").addEventListener("click", async () => {
  try {
    const out = await api("/admin/seed", { method: "POST" });
    alert(`시드 적재: ${out.seeded}건`);
    await refreshAll();
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("btn-batch").addEventListener("click", async () => {
  try {
    const out = await api("/classify/batch", {
      method: "POST",
      body: JSON.stringify({ closed_loop: true, limit: 100 }),
    });
    alert(`일괄 분류 ${out.processed}건 완료`);
    await refreshAll();
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("classify-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const description = document.getElementById("description").value.trim();
  const ground_truth_hs = document.getElementById("gt").value.trim() || null;
  const closed_loop = document.getElementById("closed-loop").checked;
  const resultEl = document.getElementById("classify-result");
  try {
    const out = await api("/classify", {
      method: "POST",
      body: JSON.stringify({ description, ground_truth_hs, closed_loop }),
    });
    resultEl.hidden = false;
    resultEl.textContent = JSON.stringify(out, null, 2);
    await refreshAll();
  } catch (e) {
    resultEl.hidden = false;
    resultEl.textContent = e.message;
  }
});

refreshAll().catch((e) => console.warn(e));
