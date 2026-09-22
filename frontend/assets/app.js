/* UZ Finance Reviews dashboard */

const state = {
  dashboard: null,
  apps: [],
  reviewsOffset: 0,
  reviewsLimit: 40,
  charts: {},
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3500);
}

function fmt(n, digits = 1) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const x = Number(n);
  if (Math.abs(x) >= 1_000_000) return (x / 1_000_000).toFixed(1) + "M";
  if (Math.abs(x) >= 1_000) return (x / 1_000).toFixed(1) + "K";
  return Number.isInteger(x) ? String(x) : x.toFixed(digits);
}

function stars(n) {
  const r = Math.round(Number(n) || 0);
  return "★".repeat(Math.max(0, Math.min(5, r))) + "☆".repeat(Math.max(0, 5 - r));
}

function storeBadge(store) {
  if (store === "play") return `<span class="badge play">Play</span>`;
  if (store === "ios") return `<span class="badge ios">iOS</span>`;
  if (store === "huawei") return `<span class="badge play">Huawei</span>`;
  if (store === "xiaomi") return `<span class="badge ios">Xiaomi</span>`;
  return "";
}

const TASHKENT_OFFSET_MS = 5 * 3600 * 1000;

function tashkentDay(daysAgo = 0) {
  return new Date(Date.now() + TASHKENT_OFFSET_MS - daysAgo * 86400000).toISOString().slice(0, 10);
}

function tashkentDate(iso) {
  const t = Date.parse(iso || "");
  return Number.isNaN(t) ? (iso || "").slice(0, 10) : new Date(t + TASHKENT_OFFSET_MS).toISOString().slice(0, 10);
}

function periodRange(prefix) {
  switch ($(`#${prefix}Period`).value) {
    case "today": return [tashkentDay(0), tashkentDay(0)];
    case "yesterday": return [tashkentDay(1), tashkentDay(1)];
    case "7d": return [tashkentDay(6), tashkentDay(0)];
    case "30d": return [tashkentDay(29), tashkentDay(0)];
    case "custom": return [$(`#${prefix}From`).value, $(`#${prefix}To`).value];
    default: return ["", ""];
  }
}

function filterParams(prefix) {
  const params = new URLSearchParams();
  const app = $(`#${prefix}App`).value;
  const store = $(`#${prefix}Store`).value;
  const [from, to] = periodRange(prefix);
  if (app) params.set("app", app);
  if (store) params.set("store", store);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  return params;
}

function wirePeriod(prefix, onChange) {
  const range = $(`#${prefix}Range`);
  const from = $(`#${prefix}From`);
  const to = $(`#${prefix}To`);
  from.max = to.max = tashkentDay(0);
  // Browsers may restore a "custom" selection on reload
  range.hidden = $(`#${prefix}Period`).value !== "custom";
  $(`#${prefix}Period`).addEventListener("change", (e) => {
    const custom = e.target.value === "custom";
    range.hidden = !custom;
    if (custom && !from.value && !to.value) {
      from.value = tashkentDay(6);
      to.value = tashkentDay(0);
    }
    onChange?.();
  });
  [from, to].forEach((el) => el.addEventListener("change", () => onChange?.()));
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    credentials: "include",
    headers: {
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    location.replace("/login");
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

function setView(name) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  const titles = {
    overview: ["Overview", "Ratings & reviews for UZ finance category leaders"],
    apps: ["Apps", "Catalog of tracked finance apps in Uzbekistan"],
    reviews: ["Reviews", "Browse and filter scraped store reviews"],
    themes: ["Themes", "What users talk about — positives & pain points"],
  };
  const [t, s] = titles[name] || ["Dashboard", ""];
  $("#pageTitle").textContent = t;
  $("#pageSub").textContent = s;
}

function destroyChart(key) {
  if (state.charts[key]) {
    state.charts[key].destroy();
    delete state.charts[key];
  }
}

function chartDefaults() {
  Chart.defaults.color = "#93a0bd";
  Chart.defaults.borderColor = "rgba(148,163,184,0.12)";
  Chart.defaults.font.family = "DM Sans";
}

function renderKPIs(d) {
  const t = d.totals || {};
  const total = t.total_reviews || 0;
  const neg = t.negative_count || 0;
  const pos = t.positive_count || 0;
  const negPct = total ? ((neg / total) * 100).toFixed(1) : "0.0";
  const posPct = total ? ((pos / total) * 100).toFixed(1) : "0.0";

  $("#kpiGrid").innerHTML = `
    <div class="kpi">
      <div class="label">Tracked apps</div>
      <div class="value">${fmt(d.app_count, 0)}</div>
      <div class="hint">Finance catalog (UZ)</div>
    </div>
    <div class="kpi accent">
      <div class="label">Scraped reviews</div>
      <div class="value">${fmt(total, 0)}</div>
      <div class="hint">Play ${fmt(t.play_count, 0)} · iOS ${fmt(t.ios_count, 0)} · HW ${fmt(t.huawei_count, 0)} · Mi ${fmt(t.xiaomi_count, 0)}</div>
    </div>
    <div class="kpi">
      <div class="label">Avg rating (sample)</div>
      <div class="value">${t.avg_rating != null ? Number(t.avg_rating).toFixed(2) : "—"}</div>
      <div class="hint">${posPct}% positive (4–5★)</div>
    </div>
    <div class="kpi danger">
      <div class="label">Negative share</div>
      <div class="value">${negPct}%</div>
      <div class="hint">${fmt(neg, 0)} reviews ≤ 2★</div>
    </div>
  `;
}

function renderRatingChart(d) {
  destroyChart("rating");
  const dist = d.rating_distribution || [];
  const labels = [1, 2, 3, 4, 5];
  const map = Object.fromEntries(dist.map((x) => [x.rating, x.count]));
  const data = labels.map((r) => map[r] || 0);
  const ctx = $("#ratingChart");
  state.charts.rating = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels.map((r) => `${r}★`),
      datasets: [{
        label: "Reviews",
        data,
        backgroundColor: [
          "rgba(255,107,138,0.75)",
          "rgba(255,140,120,0.75)",
          "rgba(255,200,87,0.75)",
          "rgba(120,200,255,0.75)",
          "rgba(61,214,140,0.75)",
        ],
        borderRadius: 8,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  });
}

function renderTimelineChart(d) {
  destroyChart("timeline");
  const tl = d.timeline || [];
  const ctx = $("#timelineChart");
  state.charts.timeline = new Chart(ctx, {
    type: "line",
    data: {
      labels: tl.map((x) => x.day),
      datasets: [{
        label: "Reviews",
        data: tl.map((x) => x.count),
        borderColor: "#5b8cff",
        backgroundColor: "rgba(91,140,255,0.15)",
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxTicksLimit: 8 },
        },
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  });
}

function renderLeaderboard(d) {
  const tbody = $("#leaderboardTable tbody");
  const rows = (d.by_app || []).slice().sort((a, b) => {
    const ar = (a.play_rating || 0) + (a.ios_rating || 0);
    const br = (b.play_rating || 0) + (b.ios_rating || 0);
    return br - ar;
  });
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty">No data yet — run Sync stores</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((a) => {
      const sample = a.scraped_reviews || 0;
      const neg = a.negatives || 0;
      const negPct = sample ? ((neg / sample) * 100).toFixed(0) + "%" : "—";
      return `<tr>
        <td><strong>${escapeHtml(a.name)}</strong><div class="muted tiny">${escapeHtml(a.brand || "")}</div></td>
        <td class="mono">${a.play_rating != null ? Number(a.play_rating).toFixed(2) : "—"}</td>
        <td class="mono">${a.ios_rating != null ? Number(a.ios_rating).toFixed(2) : "—"}</td>
        <td class="mono">${fmt(sample, 0)}</td>
        <td class="mono">${negPct}</td>
      </tr>`;
    })
    .join("");
}

function reviewCard(r) {
  const date = tashkentDate(r.review_date || r.scraped_at);
  return `<article class="review-item">
    <div class="review-meta">
      <strong style="color:var(--text)">${escapeHtml(r.app_name || r.app_slug)}</strong>
      ${storeBadge(r.store)}
      <span class="stars" title="${r.rating}★">${stars(r.rating)}</span>
      <span>${escapeHtml(r.author || "Anonymous")}</span>
      <span class="mono">${escapeHtml(date)}</span>
      ${r.version ? `<span class="mono">v${escapeHtml(r.version)}</span>` : ""}
    </div>
    ${r.title ? `<div class="review-title">${escapeHtml(r.title)}</div>` : ""}
    <div class="review-body">${escapeHtml(r.body || "")}</div>
  </article>`;
}

function renderRecent(d) {
  const list = d.recent_reviews || [];
  $("#recentList").innerHTML = list.length
    ? list.map(reviewCard).join("")
    : `<div class="empty">No reviews yet. Click “Sync stores”.</div>`;
}

function renderThemes(d) {
  destroyChart("themes");
  destroyChart("negThemes");

  const themes = d.themes || [];
  const neg = d.themes_negative || [];

  state.charts.themes = new Chart($("#themesChart"), {
    type: "doughnut",
    data: {
      labels: themes.map((t) => t.theme),
      datasets: [{
        data: themes.map((t) => t.count),
        backgroundColor: [
          "#5b8cff", "#3dd6c6", "#ffc857", "#ff6b8a", "#a78bfa",
          "#34d399", "#fb7185", "#38bdf8", "#fbbf24", "#c084fc",
        ],
        borderWidth: 0,
      }],
    },
    options: {
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } },
    },
  });

  state.charts.negThemes = new Chart($("#negThemesChart"), {
    type: "bar",
    data: {
      labels: neg.map((t) => t.theme),
      datasets: [{
        label: "Mentions in 1–2★",
        data: neg.map((t) => t.count),
        backgroundColor: "rgba(255,107,138,0.75)",
        borderRadius: 8,
      }],
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, ticks: { precision: 0 } },
        y: { grid: { display: false } },
      },
    },
  });

  const chip = (items, cls = "") =>
    (items || [])
      .slice(0, 30)
      .map((k) => `<span class="chip ${cls}">${escapeHtml(k.word)}<b>${k.count}</b></span>`)
      .join("") || `<div class="empty">No data</div>`;

  $("#kwAll").innerHTML = chip(d.keywords);
  $("#kwNeg").innerHTML = chip(d.keywords_negative, "neg");
  $("#kwPos").innerHTML = chip(d.keywords_positive, "pos");
}

const STORE_ID_FIELD = { play: "play_id", ios: "ios_id", huawei: "huawei_id", xiaomi: "xiaomi_id" };

const rating2 = (v) => (v != null ? Number(v).toFixed(2) : "—");

function appMetrics(a, store) {
  switch (store) {
    case "play":
      return [
        ["Play rating", rating2(a.play_rating)],
        ["Play ratings #", fmt(a.play_ratings_count, 0), true],
        ["Installs", escapeHtml(a.play_installs || "—"), true],
        ["Play reviews", fmt(a.play_review_count, 0), true],
      ];
    case "ios":
      return [
        ["iOS rating", rating2(a.ios_rating)],
        ["iOS ratings #", fmt(a.ios_ratings_count, 0), true],
        ["iOS reviews", fmt(a.ios_review_count, 0), true],
      ];
    case "huawei":
      return [
        ["Huawei rating", rating2(a.huawei_rating)],
        ["Huawei reviews", fmt(a.huawei_review_count, 0), true],
      ];
    case "xiaomi":
      return [
        ["Xiaomi rating", rating2(a.xiaomi_rating)],
        ["Xiaomi reviews", fmt(a.xiaomi_review_count, 0), true],
      ];
    default:
      return [
        ["Play rating", rating2(a.play_rating)],
        ["iOS rating", rating2(a.ios_rating)],
        ["Play ratings #", fmt(a.play_ratings_count, 0), true],
        ["iOS ratings #", fmt(a.ios_ratings_count, 0), true],
        ["Installs", escapeHtml(a.play_installs || "—"), true],
        ["Scraped reviews", fmt(a.review_count, 0), true],
      ];
  }
}

function renderApps(apps) {
  const q = ($("#appSearch").value || "").toLowerCase();
  const slug = $("#apApp").value;
  const store = $("#apStore").value;
  const filtered = apps.filter(
    (a) =>
      (!slug || a.slug === slug) &&
      (!store || a[STORE_ID_FIELD[store]]) &&
      (!q ||
        (a.name || "").toLowerCase().includes(q) ||
        (a.brand || "").toLowerCase().includes(q) ||
        (a.slug || "").toLowerCase().includes(q))
  );

  $("#appsGrid").innerHTML = filtered
    .map((a) => {
      const icon = a.icon_url
        ? `<img class="app-icon" src="${escapeHtml(a.icon_url)}" alt="" />`
        : `<div class="app-icon"></div>`;
      const metrics = appMetrics(a, store)
        .map(([k, v, mono]) => `<div class="metric"><div class="k">${k}</div><div class="v${mono ? " mono" : ""}">${v}</div></div>`)
        .join("");
      return `<article class="app-card">
        <div class="app-card-top">
          ${icon}
          <div>
            <div class="app-name">${escapeHtml(a.name)}</div>
            <div class="app-brand">${escapeHtml(a.brand || a.slug)}</div>
          </div>
        </div>
        <div class="app-metrics">${metrics}</div>
      </article>`;
    })
    .join("") || `<div class="empty">No apps match</div>`;
}

function fillAppFilters(apps) {
  const options =
    `<option value="">All apps</option>` +
    apps
      .map((a) => `<option value="${escapeHtml(a.slug)}">${escapeHtml(a.name)}</option>`)
      .join("");
  $$(".app-filter").forEach((sel) => {
    const current = sel.value;
    sel.innerHTML = options;
    sel.value = current;
  });
}

// Filters fire a request per change; drop responses superseded by a newer one
const latestRequest = {};
async function latest(key, path) {
  const seq = (latestRequest[key] = (latestRequest[key] || 0) + 1);
  const data = await api(path);
  return seq === latestRequest[key] ? data : null;
}

async function loadOverview() {
  const d = await latest("overview", `/api/dashboard?${filterParams("ov")}`);
  if (!d) return;
  state.dashboard = d;
  renderKPIs(d);
  renderRatingChart(d);
  renderTimelineChart(d);
  renderLeaderboard(d);
  renderRecent(d);
  updateSyncPill(d);
}

async function loadThemes() {
  const d = await latest("themes", `/api/dashboard?${filterParams("th")}`);
  if (d) renderThemes(d);
}

async function loadReviews() {
  const params = filterParams("filter");
  params.set("limit", String(state.reviewsLimit));
  params.set("offset", String(state.reviewsOffset));
  const rating = $("#filterRating").value;
  const q = $("#filterQ").value.trim();
  if (rating) params.set("rating", rating);
  if (q) params.set("q", q);

  const data = await latest("reviews", `/api/reviews?${params}`);
  if (!data) return;
  $("#reviewCount").textContent = `${fmt(data.total, 0)} results`;
  $("#reviewsList").innerHTML = data.items.length
    ? data.items.map(reviewCard).join("")
    : `<div class="empty">No reviews match filters</div>`;

  const page = Math.floor(state.reviewsOffset / state.reviewsLimit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / state.reviewsLimit));
  $("#pageInfo").textContent = `Page ${page} / ${pages}`;
  $("#prevPage").disabled = state.reviewsOffset <= 0;
  $("#nextPage").disabled = state.reviewsOffset + state.reviewsLimit >= data.total;
}

function updateSyncPill(d) {
  const ls = d.last_sync;
  if (!ls) {
    $("#lastSyncPill").textContent = "Never synced";
    $("#syncStatus").textContent = "idle · no data";
    return;
  }
  const when = (ls.finished_at || ls.started_at || "").slice(0, 19).replace("T", " ");
  $("#lastSyncPill").textContent = `Last sync: ${when || "—"} · ${ls.status || ""}`;
  $("#syncStatus").textContent = `${ls.status || "unknown"} · ${when || ""}`;
}

async function applyShareMode() {
  try {
    const st = await api("/api/auth/status");
    const btn = $("#syncBtn");
    if (st.readonly) {
      btn.disabled = true;
      btn.textContent = "Read-only share";
      btn.title = "Sync is disabled on this shared view";
      const pill = $("#lastSyncPill");
      if (pill && !pill.textContent.includes("read-only")) {
        pill.textContent = (pill.textContent || "") + " · read-only";
      }
    }
  } catch {
    /* ignore */
  }
}

async function refreshAll() {
  chartDefaults();
  state.apps = await api("/api/apps");
  fillAppFilters(state.apps);
  renderApps(state.apps);
  await Promise.all([loadOverview(), loadThemes()]);
}

function formatAutoSync(st) {
  const auto = st.auto_sync || {};
  if (!auto.enabled) return "manual only";
  const h = auto.interval_hours;
  const since = auto.hours_since_last_ok;
  if (st.running) return "running…";
  if (since == null) return `every ${h}h · first run soon`;
  const next = auto.next_sync_at ? auto.next_sync_at.slice(11, 16) + " UTC" : "";
  return `every ${h}h · last ${since.toFixed(1)}h ago${next ? " · next " + next : ""}`;
}

async function pollSync() {
  try {
    const st = await api("/api/sync/status");
    const btn = $("#syncBtn");
    if (st.running) {
      btn.disabled = true;
      btn.textContent = "Syncing…";
      $("#syncStatus").textContent = "running…";
      setTimeout(pollSync, 2500);
    } else {
      btn.disabled = false;
      btn.textContent = "Sync now";
      $("#syncStatus").textContent = formatAutoSync(st);
    }
  } catch {
    /* ignore */
  }
}

async function startSync() {
  const btn = $("#syncBtn");
  btn.disabled = true;
  btn.textContent = "Starting…";
  try {
    const res = await api("/api/sync?background=true", { method: "POST" });
    if (res.status === "already_running") toast("Sync already running");
    else toast("Sync started — fetching Play + App Store…");
    pollSync();
    // Refresh when done
    const wait = async () => {
      const st = await api("/api/sync/status");
      if (st.running) {
        setTimeout(wait, 3000);
      } else {
        await refreshAll();
        await loadReviews();
        if (st.last_result?.status === "ok") {
          toast(
            `Synced: Play ${st.last_result.play_reviews || 0} · iOS ${st.last_result.ios_reviews || 0}` +
              ` · HW ${st.last_result.huawei_reviews || 0} · Mi ${st.last_result.xiaomi_reviews || 0}`
          );
        } else if (st.last_result?.status === "error") {
          toast("Sync finished with errors — check API logs");
        }
      }
    };
    setTimeout(wait, 3000);
  } catch (e) {
    toast("Failed to start sync: " + e.message);
    btn.disabled = false;
    btn.textContent = "Sync now";
  }
}

function wire() {
  $$(".nav-item").forEach((btn) =>
    btn.addEventListener("click", () => setView(btn.dataset.view))
  );
  $("#syncBtn").addEventListener("click", startSync);
  $("#appSearch").addEventListener("input", () => renderApps(state.apps));
  ["#apApp", "#apStore"].forEach((sel) =>
    $(sel).addEventListener("change", () => renderApps(state.apps))
  );
  ["#ovApp", "#ovStore"].forEach((sel) =>
    $(sel).addEventListener("change", () => loadOverview().catch((e) => toast(e.message)))
  );
  ["#thApp", "#thStore"].forEach((sel) =>
    $(sel).addEventListener("change", () => loadThemes().catch((e) => toast(e.message)))
  );
  wirePeriod("ov", () => loadOverview().catch((e) => toast(e.message)));
  wirePeriod("th", () => loadThemes().catch((e) => toast(e.message)));
  wirePeriod("filter", null);
  $("#filterBtn").addEventListener("click", () => {
    state.reviewsOffset = 0;
    loadReviews().catch((e) => toast(e.message));
  });
  $("#filterQ").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      state.reviewsOffset = 0;
      loadReviews().catch((err) => toast(err.message));
    }
  });
  $("#prevPage").addEventListener("click", () => {
    state.reviewsOffset = Math.max(0, state.reviewsOffset - state.reviewsLimit);
    loadReviews().catch((e) => toast(e.message));
  });
  $("#nextPage").addEventListener("click", () => {
    state.reviewsOffset += state.reviewsLimit;
    loadReviews().catch((e) => toast(e.message));
  });
}

async function main() {
  wire();
  setView("reviews");
  try {
    await applyShareMode();
    await refreshAll();
    await loadReviews();
    await pollSync();
  } catch (e) {
    if (e.message !== "Unauthorized") toast("Failed to load: " + e.message);
  }
}

main();
