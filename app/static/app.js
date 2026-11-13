"use strict";

const state = {
  searches: [],
  items: [],
  liveItems: null,
  liveQuery: "",
  channels: [],
  alerts: [],
  auctions: [],
};

const CHANNEL_SCHEMAS = {
  discord: [
    { key: "webhook_url", label: "Discord Webhook URL *", type: "url", placeholder: "https://discord.com/api/webhooks/..." },
  ],
  slack: [
    { key: "webhook_url", label: "Slack Incoming Webhook URL *", type: "url", placeholder: "https://hooks.slack.com/services/..." },
  ],
  webhook: [
    { key: "webhook_url", label: "Target Webhook URL *", type: "url", placeholder: "https://example.com/webhook" },
    { key: "headers_json", label: "Custom Headers (JSON object, optional)", type: "text", placeholder: '{"Authorization": "Bearer ..."}' },
  ],
  email: [
    { key: "host", label: "SMTP Host *", type: "text", placeholder: "smtp.gmail.com" },
    { key: "port", label: "SMTP Port *", type: "number", placeholder: "587", default: 587 },
    { key: "username", label: "SMTP Username", type: "text", placeholder: "you@gmail.com" },
    { key: "password", label: "SMTP Password / App Password", type: "password", placeholder: "••••••••" },
    { key: "from_email", label: "From Email *", type: "text", placeholder: "alerts@example.com" },
    { key: "to_email", label: "To Email(s, comma-separated) *", type: "text", placeholder: "you@example.com" },
    { key: "use_tls", label: "Use STARTTLS", type: "checkbox", default: true },
    { key: "use_ssl", label: "Use SSL (port 465)", type: "checkbox", default: false },
  ],
  ntfy: [
    { key: "server_url", label: "ntfy Server URL", type: "url", placeholder: "https://ntfy.sh", default: "https://ntfy.sh" },
    { key: "topic", label: "Topic *", type: "text", placeholder: "my-equipbid-alerts" },
    { key: "token", label: "Access Token (optional)", type: "password", placeholder: "" },
    { key: "priority", label: "Priority (min, low, default, high, urgent)", type: "text", placeholder: "default", default: "default" },
  ],
  gotify: [
    { key: "server_url", label: "Gotify Server URL *", type: "url", placeholder: "https://gotify.example.com" },
    { key: "app_token", label: "Gotify App Token *", type: "password", placeholder: "" },
    { key: "priority", label: "Priority (0-10)", type: "number", placeholder: "5", default: 5 },
  ],
  pushover: [
    { key: "user_key", label: "Pushover User Key *", type: "text", placeholder: "" },
    { key: "api_token", label: "Pushover API Token *", type: "password", placeholder: "" },
    { key: "priority", label: "Priority (-2 to 2)", type: "number", placeholder: "0", default: 0 },
  ],
  telegram: [
    { key: "bot_token", label: "Telegram Bot Token *", type: "password", placeholder: "123456:ABC-DEF..." },
    { key: "chat_id", label: "Telegram Chat ID *", type: "text", placeholder: "123456789" },
  ],
};

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function fmtMoney(val) {
  const num = Number(val || 0);
  return "$" + num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtIsoShort(iso) {
  if (!iso) return "Never";
  return iso.replace("T", " ").replace("Z", " UTC");
}

function hoursUntil(iso) {
  if (!iso) return null;
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return null;
  return (dt.getTime() - Date.now()) / 3600000;
}

function toast(msg, kind = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data && data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  return resp.json();
}

function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Stats & Data Loading
// ---------------------------------------------------------------------------

async function refreshStats() {
  try {
    const stats = await api("/api/stats");
    document.getElementById("stat-unread").textContent = stats.unread_count;
    document.getElementById("stat-closing").textContent = stats.closing_soon_count;
    document.getElementById("stat-watched").textContent = stats.watched_count;
    document.getElementById("stat-searches").textContent = stats.active_searches;
    const badge = document.getElementById("nav-unread-badge");
    badge.textContent = stats.unread_count;
    badge.classList.toggle("zero", stats.unread_count === 0);
  } catch (err) {
    console.error("Failed to refresh stats", err);
  }
}

async function loadSearches() {
  state.searches = await api("/api/searches");
  const select = document.getElementById("filter-search-id");
  const prev = select.value;
  select.innerHTML = '<option value="">All Saved Searches</option>';
  state.searches.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = String(s.id);
    opt.textContent = s.name;
    select.appendChild(opt);
  });
  if (prev) select.value = prev;
  renderSearches();
}

async function loadItems() {
  state.liveItems = null;
  state.liveQuery = "";
  const params = new URLSearchParams();
  const searchId = document.getElementById("filter-search-id").value;
  const q = document.getElementById("filter-q").value.trim();
  const maxBid = document.getElementById("filter-max-bid").value.trim();
  const sort = document.getElementById("filter-sort").value;
  if (searchId) params.set("search_id", searchId);
  if (q) params.set("q", q);
  if (maxBid) params.set("max_bid", maxBid);
  if (sort) params.set("sort", sort);
  if (document.getElementById("filter-unread").checked) params.set("unread_only", "true");
  if (document.getElementById("filter-watched").checked) params.set("watched_only", "true");
  if (document.getElementById("filter-closing").checked) params.set("closing_soon_only", "true");

  state.items = await api(`/api/items?${params.toString()}`);
  renderItems();
}

async function runAdhocLiveSearch() {
  const q = document.getElementById("filter-q").value.trim();
  if (!q) {
    toast("Type a keyword in the search box first (e.g. workstation)", "info");
    return;
  }
  const btn = document.getElementById("btn-live-search-bar");
  const maxBid = document.getElementById("filter-max-bid").value.trim();
  const sortMap = {
    closing_asc: "close",
    bid_asc: "bidlow",
    bid_desc: "bidhigh",
    newest: "relevancy",
  };
  const sortField = sortMap[document.getElementById("filter-sort").value] || "close";

  btn.disabled = true;
  btn.textContent = "Searching...";
  try {
    const qs = new URLSearchParams({
      keywords: q,
      sort_field: sortField,
      max_pages: "2",
    });
    if (maxBid) qs.set("max_bid", maxBid);
    state.liveItems = await api(`/api/live-search?${qs.toString()}`);
    state.liveQuery = q;
    renderItems();
    toast(`Found ${state.liveItems.length} live lot(s) for "${q}"`, "ok");
  } catch (err) {
    toast(`Live search failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Search Equip-Bid Live";
  }
}

async function loadChannels() {
  state.channels = await api("/api/channels");
  renderChannels();
}

async function loadAlerts() {
  state.alerts = await api("/api/alerts");
  renderAlerts();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderItems() {
  const grid = document.getElementById("items-grid");
  const isLive = Array.isArray(state.liveItems);
  const itemsToRender = isLive ? state.liveItems : state.items;
  const currentQ = document.getElementById("filter-q").value.trim();

  if (!itemsToRender.length) {
    if (isLive) {
      grid.innerHTML = `
        <div class="empty-state">
          <h3>No live lots found for "${esc(state.liveQuery)}"</h3>
          <p>Try broader keywords, or save this as an alert rule so you're notified when one is listed.</p>
          <div style="margin-top:14px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-primary btn-sm" data-action="save-live-search">+ Save Alert Rule for "${esc(state.liveQuery)}"</button>
            <button type="button" class="btn btn-secondary btn-sm" data-action="clear-live-search">Back to Saved Matches</button>
          </div>
        </div>`;
      return;
    }
    grid.innerHTML = `
      <div class="empty-state">
        <h3>${currentQ ? `No saved matches for "${esc(currentQ)}"` : "No matching items yet"}</h3>
        <p>${currentQ
          ? "Click below to search live Equip-Bid listings directly, or save this query as an automated alert rule."
          : 'Create a Saved Search or click "Run All Searches Now" to scan equip-bid.com.'}</p>
        ${currentQ ? `
          <div style="margin-top:14px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
            <button type="button" class="btn btn-primary btn-sm" data-action="run-live-search">Search Equip-Bid Live for "${esc(currentQ)}"</button>
            <button type="button" class="btn btn-secondary btn-sm" data-action="save-live-search">+ Save as Alert Rule</button>
          </div>` : ""}
      </div>`;
    return;
  }

  const headerBanner = isLive
    ? `<div class="row-card" style="grid-column:1/-1;align-items:center;">
         <div class="row-card-main">
           <strong>Live Equip-Bid Search: "${esc(state.liveQuery)}"</strong>
           <span class="muted"> &mdash; Showing ${itemsToRender.length} live lot(s) directly from equip-bid.com</span>
         </div>
         <div class="row-card-actions">
           <button type="button" class="btn btn-primary btn-sm" data-action="save-live-search">+ Save as Alert Rule</button>
           <button type="button" class="btn btn-secondary btn-sm" data-action="clear-live-search">Back to Saved Matches</button>
         </div>
       </div>`
    : "";

  grid.innerHTML = headerBanner + itemsToRender
    .map((item) => {
      const hrs = hoursUntil(item.closing_at);
      const isClosingSoon = hrs !== null && hrs > 0 && hrs <= 24;
      const isEnded = hrs !== null && hrs <= 0;
      const thumbHtml = item.image_url
        ? `<img class="lot-thumb" src="${esc(item.image_url)}" alt="${esc(item.title)}" loading="lazy" />`
        : `<div class="lot-thumb-placeholder">No Image</div>`;

      const badgesHtml = isLive
        ? `<span class="pill unread">LIVE EQUIP-BID RESULT</span>
           ${isClosingSoon ? '<span class="pill warn">CLOSING SOON</span>' : ""}`
        : `${!item.is_read ? '<span class="pill unread">NEW</span>' : ""}
           ${item.is_watched ? '<span class="pill ok">WATCHED</span>' : ""}
           ${isClosingSoon ? '<span class="pill warn">CLOSING SOON</span>' : ""}
           ${isEnded ? '<span class="pill danger">ENDED</span>' : ""}
           ${item.search_name ? `<span class="pill">${esc(item.search_name)}</span>` : ""}`;

      const actionsHtml = isLive
        ? `<a class="btn btn-primary btn-sm" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">View Lot</a>
           <button type="button" class="btn btn-secondary btn-sm" data-action="save-live-search">+ Save Search Rule</button>`
        : `<a class="btn btn-primary btn-sm" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">View Lot</a>
           <button class="btn btn-secondary btn-sm" data-action="watch" data-id="${item.id}" data-val="${!item.is_watched}">
             ${item.is_watched ? "Unwatch" : "Watch"}
           </button>
           <button class="btn btn-secondary btn-sm" data-action="read" data-id="${item.id}" data-val="${!item.is_read}">
             ${item.is_read ? "Mark Unread" : "Mark Read"}
           </button>
           <div class="spacer"></div>
           <button class="btn btn-ghost btn-sm" data-action="dismiss" data-id="${item.id}">Dismiss</button>`;

      return `
        <article class="lot-card ${!isLive && !item.is_read ? "unread" : ""}">
          <div class="lot-card-top">
            ${thumbHtml}
            <div class="lot-info">
              <div class="lot-badges">${badgesHtml}</div>
              <h3 class="lot-title">
                <a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>
              </h3>
              <div class="lot-meta">
                <span>Lot #${esc(item.lot_number)} &bull; ${esc(item.location || "Location N/A")}</span>
                <span>${esc(item.affiliate || "Equip-Bid")}${item.category ? " &bull; " + esc(item.category) : ""}</span>
                <span>Closes: ${esc(item.closing_time_raw || item.time_remaining_raw || "N/A")}${item.time_remaining_raw ? " (" + esc(item.time_remaining_raw) + ")" : ""}</span>
              </div>
            </div>
          </div>
          <div class="lot-pricing">
            <div>
              <span class="bid-price">${fmtMoney(item.current_bid)}</span>
              ${item.next_required_bid != null ? `<span class="bid-sub"> &bull; Next: ${fmtMoney(item.next_required_bid)}</span>` : ""}
            </div>
            <span class="bid-sub">${item.shipping_info ? esc(item.shipping_info) : ""}</span>
          </div>
          <div class="lot-actions">${actionsHtml}</div>
        </article>
      `;
    })
    .join("");
}

function renderSearches() {
  const list = document.getElementById("searches-list");
  if (!state.searches.length) {
    list.innerHTML = `<div class="empty-state">No saved searches configured yet. Click "+ Add Saved Search" to start monitoring Equip-Bid.</div>`;
    return;
  }

  list.innerHTML = state.searches
    .map((s) => {
      const distLabel = s.distance_radius > 0 ? `${s.distance_radius} mi` : "Any distance";
      const locText = s.zip_code ? `${esc(s.zip_code)} (${distLabel})` : "All locations";
      const bidLimits = [];
      if (s.min_bid != null) bidLimits.push(`Min $${s.min_bid}`);
      if (s.max_bid != null) bidLimits.push(`Max $${s.max_bid}`);
      const closingText = s.closing_soon_hours ? `${s.closing_soon_hours}h before close` : "Disabled";

      return `
        <div class="row-card">
          <div class="row-card-main">
            <div class="row-card-title">
              <h3>${esc(s.name)}</h3>
              <span class="pill ${s.enabled ? "ok" : "danger"}">${s.enabled ? "Enabled" : "Paused"}</span>
              <span class="pill">Every ${s.check_interval_minutes}m</span>
              ${s.auction_id ? `<span class="pill">Auction #${esc(s.auction_id)}</span>` : ""}
            </div>
            <p class="muted">
              <strong>Keywords:</strong> "${esc(s.keywords)}"
              ${s.must_include ? ` &bull; <strong>Must include:</strong> ${esc(s.must_include)}` : ""}
              ${s.exclude_words ? ` &bull; <strong>Exclude:</strong> ${esc(s.exclude_words)}` : ""}
            </p>
            <p class="muted" style="margin-top:4px;">
              <strong>Location:</strong> ${locText}
              &bull; <strong>Bid Filter:</strong> ${bidLimits.length ? bidLimits.join(" / ") : "Any"}
              &bull; <strong>Closing Alert:</strong> ${closingText}
              &bull; <strong>Last Run:</strong> ${fmtIsoShort(s.last_run_at)} (${s.last_match_count} matches)
            </p>
          </div>
          <div class="row-card-actions">
            <button class="btn btn-primary btn-sm" data-search-run="${s.id}">Run Now</button>
            <button class="btn btn-secondary btn-sm" data-search-edit="${s.id}">Edit</button>
            <button class="btn btn-secondary btn-sm" data-search-toggle="${s.id}" data-enabled="${!s.enabled}">
              ${s.enabled ? "Pause" : "Enable"}
            </button>
            <button class="btn btn-danger btn-sm" data-search-delete="${s.id}">Delete</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderAuctions() {
  const list = document.getElementById("live-auctions-list");
  if (!state.auctions.length) {
    list.innerHTML = `<div class="empty-state">Click "Fetch Live Auctions" above to browse current sales from equip-bid.com/auction/list.</div>`;
    return;
  }

  list.innerHTML = state.auctions
    .map((a) => {
      const thumbs = (a.sample_images || [])
        .map((src) => `<img src="${esc(src)}" alt="Preview" loading="lazy" />`)
        .join("");
      return `
        <div class="row-card">
          <div class="row-card-main">
            <div class="row-card-title">
              <h3><a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a></h3>
              <span class="pill ok">${esc(a.status)}</span>
              ${a.item_count_text ? `<span class="pill">${esc(a.item_count_text)}</span>` : ""}
              <span class="pill">ID: ${esc(a.auction_id)}</span>
            </div>
            <p class="muted">
              <strong>Affiliate:</strong> ${esc(a.affiliate || "N/A")}
              &bull; <strong>Location:</strong> ${esc(a.location || "N/A")}
              &bull; <strong>Closes:</strong> ${esc(a.closing_time_raw || "N/A")} ${a.countdown ? "(" + esc(a.countdown) + ")" : ""}
            </p>
            ${thumbs ? `<div class="auction-thumbs">${thumbs}</div>` : ""}
          </div>
          <div class="row-card-actions">
            <button class="btn btn-primary btn-sm" data-auction-search="${esc(a.auction_id)}" data-auction-title="${esc(a.title)}">
              Setup Search in Auction
            </button>
            <a class="btn btn-secondary btn-sm" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">Open on Equip-Bid</a>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderChannels() {
  const list = document.getElementById("channels-list");
  if (!state.channels.length) {
    list.innerHTML = `<div class="empty-state">No external notification channels configured. Alerts still appear in the Matched Items dashboard.</div>`;
    return;
  }

  list.innerHTML = state.channels
    .map((c) => `
      <div class="row-card">
        <div class="row-card-main">
          <div class="row-card-title">
            <h3>${esc(c.name)}</h3>
            <span class="pill">${esc(c.channel_type.toUpperCase())}</span>
            <span class="pill ${c.enabled ? "ok" : "danger"}">${c.enabled ? "Enabled" : "Disabled"}</span>
          </div>
          <p class="muted">Created: ${fmtIsoShort(c.created_at)}</p>
        </div>
        <div class="row-card-actions">
          <button class="btn btn-primary btn-sm" data-channel-test="${c.id}">Send Test Alert</button>
          <button class="btn btn-secondary btn-sm" data-channel-edit="${c.id}">Edit</button>
          <button class="btn btn-danger btn-sm" data-channel-delete="${c.id}">Delete</button>
        </div>
      </div>
    `)
    .join("");
}

function renderAlerts() {
  const tbody = document.getElementById("alerts-tbody");
  if (!state.alerts.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:24px;">No alerts logged yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.alerts
    .map((a) => {
      const statusClass = a.status === "success" ? "ok" : a.status === "error" ? "danger" : a.status === "partial" ? "warn" : "";
      const titleCell = a.item_url
        ? `<a href="${esc(a.item_url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>`
        : esc(a.title);
      return `
        <tr>
          <td>${fmtIsoShort(a.created_at)}</td>
          <td><span class="pill">${esc(a.alert_type)}</span></td>
          <td>
            <div>${titleCell}</div>
            <div class="muted" style="font-size:0.78rem;">${esc(a.message)}</div>
            ${a.error_detail ? `<div style="color:#fca5a5;font-size:0.78rem;">${esc(a.error_detail)}</div>` : ""}
          </td>
          <td>${esc(a.channels_notified || "In-App Only")}</td>
          <td><span class="pill ${statusClass}">${esc(a.status)}</span></td>
        </tr>
      `;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Search Modal & Live Preview
// ---------------------------------------------------------------------------

function openSearchModal(existing = null, prefill = {}) {
  document.getElementById("search-modal-title").textContent = existing ? "Edit Saved Search" : "New Saved Search";
  document.getElementById("search-id").value = existing ? existing.id : "";
  document.getElementById("search-name").value = existing ? existing.name : (prefill.name || "");
  document.getElementById("search-keywords").value = existing ? existing.keywords : (prefill.keywords || "");
  document.getElementById("search-must-include").value = existing ? existing.must_include : "";
  document.getElementById("search-exclude").value = existing ? existing.exclude_words : "";
  document.getElementById("search-min-bid").value = existing && existing.min_bid != null ? existing.min_bid : "";
  document.getElementById("search-max-bid").value = existing && existing.max_bid != null ? existing.max_bid : "";
  document.getElementById("search-zip").value = existing ? existing.zip_code : "";
  document.getElementById("search-distance").value = existing ? String(existing.distance_radius) : "-1";
  document.getElementById("search-auction-id").value = existing ? existing.auction_id : (prefill.auction_id || "");
  document.getElementById("search-sort").value = existing ? existing.sort_field : "close";
  document.getElementById("search-interval").value = existing ? existing.check_interval_minutes : 30;
  document.getElementById("search-pages").value = existing ? existing.max_pages : 2;
  document.getElementById("search-closing-hours").value =
    existing ? (existing.closing_soon_hours != null ? existing.closing_soon_hours : "") : "4";
  document.getElementById("search-alert-new").checked = existing ? existing.alert_on_new : true;
  document.getElementById("search-enabled").checked = existing ? existing.enabled : true;

  const runWrap = document.getElementById("search-run-now-wrap");
  runWrap.style.display = existing ? "none" : "flex";
  document.getElementById("preview-box").classList.add("hidden");
  document.getElementById("preview-results").innerHTML = "";
  openModal("search-modal");
}

function readSearchFormPayload() {
  const minVal = document.getElementById("search-min-bid").value.trim();
  const maxVal = document.getElementById("search-max-bid").value.trim();
  const closingVal = document.getElementById("search-closing-hours").value.trim();
  return {
    name: document.getElementById("search-name").value.trim(),
    keywords: document.getElementById("search-keywords").value.trim(),
    must_include: document.getElementById("search-must-include").value.trim(),
    exclude_words: document.getElementById("search-exclude").value.trim(),
    min_bid: minVal === "" ? null : Number(minVal),
    max_bid: maxVal === "" ? null : Number(maxVal),
    zip_code: document.getElementById("search-zip").value.trim(),
    distance_radius: Number(document.getElementById("search-distance").value),
    auction_id: document.getElementById("search-auction-id").value.trim(),
    sort_field: document.getElementById("search-sort").value,
    check_interval_minutes: Number(document.getElementById("search-interval").value || 30),
    max_pages: Number(document.getElementById("search-pages").value || 2),
    closing_soon_hours: closingVal === "" ? null : Number(closingVal),
    alert_on_new: document.getElementById("search-alert-new").checked,
    enabled: document.getElementById("search-enabled").checked,
    run_immediately: document.getElementById("search-run-now").checked,
  };
}

// ---------------------------------------------------------------------------
// Channel Modal Dynamic Fields
// ---------------------------------------------------------------------------

function renderChannelFields(type, existingConfig = {}) {
  const container = document.getElementById("channel-dynamic-fields");
  const fields = CHANNEL_SCHEMAS[type] || [];
  container.innerHTML = fields
    .map((f) => {
      let val = existingConfig[f.key];
      if (f.key === "headers_json" && existingConfig.headers) {
        val = JSON.stringify(existingConfig.headers);
      }
      if (val === undefined) val = f.default !== undefined ? f.default : "";
      if (f.type === "checkbox") {
        return `
          <label class="checkbox-row">
            <input type="checkbox" data-cfg-key="${f.key}" ${val ? "checked" : ""} />
            <span>${esc(f.label)}</span>
          </label>`;
      }
      return `
        <div class="form-group">
          <label>${esc(f.label)}</label>
          <input type="${f.type}" data-cfg-key="${f.key}" value="${esc(val)}" placeholder="${esc(f.placeholder || "")}" />
        </div>`;
    })
    .join("");
}

function openChannelModal(existing = null) {
  document.getElementById("channel-modal-title").textContent = existing ? "Edit Notification Channel" : "Add Notification Channel";
  document.getElementById("channel-id").value = existing ? existing.id : "";
  document.getElementById("channel-name").value = existing ? existing.name : "";
  const typeSelect = document.getElementById("channel-type");
  typeSelect.value = existing ? existing.channel_type : "discord";
  document.getElementById("channel-enabled").checked = existing ? existing.enabled : true;
  renderChannelFields(typeSelect.value, existing ? existing.config : {});
  openModal("channel-modal");
}

function readChannelConfigFromForm(type) {
  const cfg = {};
  const fields = CHANNEL_SCHEMAS[type] || [];
  fields.forEach((f) => {
    const el = document.querySelector(`#channel-dynamic-fields [data-cfg-key="${f.key}"]`);
    if (!el) return;
    if (f.type === "checkbox") {
      cfg[f.key] = el.checked;
    } else if (f.type === "number") {
      cfg[f.key] = el.value === "" ? (f.default ?? 0) : Number(el.value);
    } else if (f.key === "headers_json") {
      const raw = el.value.trim();
      if (raw) {
        cfg.headers = JSON.parse(raw);
      }
    } else {
      cfg[f.key] = el.value.trim();
    }
  });
  return cfg;
}

// ---------------------------------------------------------------------------
// Event Wiring
// ---------------------------------------------------------------------------

function initEvents() {
  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.tab;
      document.getElementById(`tab-${target}`).classList.add("active");
      if (target === "alerts") await loadAlerts();
      if (target === "auctions" && !state.auctions.length) {
        document.getElementById("live-auctions-form").dispatchEvent(new Event("submit"));
      }
    });
  });

  // Modal close buttons
  document.querySelectorAll("[data-close]").forEach((el) => {
    el.addEventListener("click", () => closeModal(el.dataset.close));
  });

  document.getElementById("btn-new-search-top").addEventListener("click", () => openSearchModal());
  document.getElementById("btn-add-search").addEventListener("click", () => openSearchModal());
  document.getElementById("btn-add-channel").addEventListener("click", () => openChannelModal());
  document.getElementById("btn-refresh-alerts").addEventListener("click", () => loadAlerts());

  document.getElementById("channel-type").addEventListener("change", (e) => {
    renderChannelFields(e.target.value, {});
  });

  // Item filters
  ["filter-search-id", "filter-sort", "filter-unread", "filter-watched", "filter-closing"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadItems());
  });
  let debounceTimer;
  ["filter-q", "filter-max-bid"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => loadItems(), 250);
    });
  });

  document.getElementById("filter-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      clearTimeout(debounceTimer);
      runAdhocLiveSearch();
    }
  });
  document.getElementById("btn-live-search-bar").addEventListener("click", () => runAdhocLiveSearch());
  document.getElementById("btn-save-from-bar").addEventListener("click", () => {
    const q = document.getElementById("filter-q").value.trim();
    openSearchModal(null, { keywords: q, name: q ? `${q} Monitor` : "" });
  });

  // Run all searches / Mark all read
  document.getElementById("btn-mark-all-read").addEventListener("click", async () => {
    const searchId = document.getElementById("filter-search-id").value;
    const url = searchId ? `/api/items/mark-all-read?search_id=${searchId}` : "/api/items/mark-all-read";
    await api(url, { method: "POST" });
    toast("Marked items as read", "ok");
    await Promise.all([loadItems(), refreshStats()]);
  });

  document.getElementById("btn-run-all").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Scanning Equip-Bid...";
    try {
      const res = await api("/api/searches/run-all", { method: "POST" });
      const totalMatched = (res.runs || []).reduce((acc, r) => acc + (r.matched || 0), 0);
      toast(`Scan complete: ${totalMatched} matching lots processed`, "ok");
      await Promise.all([loadItems(), loadSearches(), refreshStats()]);
    } catch (err) {
      toast(`Scan error: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Run All Searches Now";
    }
  });

  // Item card actions
  document.getElementById("items-grid").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const id = btn.dataset.id;
    const action = btn.dataset.action;
    const val = btn.dataset.val === "true";
    try {
      if (action === "run-live-search") {
        await runAdhocLiveSearch();
        return;
      } else if (action === "save-live-search") {
        const q = (state.liveQuery || document.getElementById("filter-q").value).trim();
        openSearchModal(null, { keywords: q, name: q ? `${q} Monitor` : "" });
        return;
      } else if (action === "clear-live-search") {
        await loadItems();
        return;
      } else if (action === "watch") {
        await api(`/api/items/${id}/watch`, { method: "POST", body: JSON.stringify({ value: val }) });
      } else if (action === "read") {
        await api(`/api/items/${id}/read`, { method: "POST", body: JSON.stringify({ value: val }) });
      } else if (action === "dismiss") {
        await api(`/api/items/${id}/dismiss`, { method: "POST", body: JSON.stringify({ value: true }) });
        toast("Item dismissed", "info");
      }
      await Promise.all([loadItems(), refreshStats()]);
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // Search form save & preview
  document.getElementById("btn-preview-search").addEventListener("click", async (e) => {
    const payload = readSearchFormPayload();
    if (!payload.keywords) {
      toast("Enter keywords to preview", "error");
      return;
    }
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Searching...";
    try {
      const qs = new URLSearchParams({
        keywords: payload.keywords,
        must_include: payload.must_include,
        exclude_words: payload.exclude_words,
        zip_code: payload.zip_code,
        distance_radius: String(payload.distance_radius),
        auction_id: payload.auction_id,
        sort_field: payload.sort_field,
        max_pages: "1",
      });
      if (payload.min_bid != null) qs.set("min_bid", String(payload.min_bid));
      if (payload.max_bid != null) qs.set("max_bid", String(payload.max_bid));
      const items = await api(`/api/live-search?${qs.toString()}`);
      const box = document.getElementById("preview-box");
      const list = document.getElementById("preview-results");
      document.getElementById("preview-title").textContent = `Live Preview (${items.length} matching lots on page 1)`;
      list.innerHTML = items.length
        ? items.slice(0, 15).map((it) => `
            <div class="preview-row">
              <a href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>
              <strong>${fmtMoney(it.current_bid)}</strong>
            </div>`).join("")
        : '<div class="muted">No lots matched these criteria.</div>';
      box.classList.remove("hidden");
    } catch (err) {
      toast(`Preview failed: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Preview Results on Equip-Bid";
    }
  });

  document.getElementById("search-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = document.getElementById("search-id").value;
    const payload = readSearchFormPayload();
    const submitBtn = e.target.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    try {
      if (id) {
        delete payload.run_immediately;
        await api(`/api/searches/${id}`, { method: "PUT", body: JSON.stringify(payload) });
        toast("Saved search updated", "ok");
      } else {
        await api("/api/searches", { method: "POST", body: JSON.stringify(payload) });
        toast("Saved search created", "ok");
      }
      closeModal("search-modal");
      await Promise.all([loadSearches(), loadItems(), refreshStats()]);
    } catch (err) {
      toast(`Failed to save search: ${err.message}`, "error");
    } finally {
      submitBtn.disabled = false;
    }
  });

  // Saved searches list actions
  document.getElementById("searches-list").addEventListener("click", async (e) => {
    const runBtn = e.target.closest("[data-search-run]");
    const editBtn = e.target.closest("[data-search-edit]");
    const toggleBtn = e.target.closest("[data-search-toggle]");
    const delBtn = e.target.closest("[data-search-delete]");
    try {
      if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = "Running...";
        const res = await api(`/api/searches/${runBtn.dataset.searchRun}/run`, { method: "POST" });
        toast(`Found ${res.matched} matches (${res.new_alerts} new alerts)`, "ok");
        await Promise.all([loadSearches(), loadItems(), refreshStats()]);
      } else if (editBtn) {
        const s = state.searches.find((x) => x.id === Number(editBtn.dataset.searchEdit));
        if (s) openSearchModal(s);
      } else if (toggleBtn) {
        const enabled = toggleBtn.dataset.enabled === "true";
        await api(`/api/searches/${toggleBtn.dataset.searchToggle}`, {
          method: "PUT",
          body: JSON.stringify({ enabled }),
        });
        await Promise.all([loadSearches(), refreshStats()]);
      } else if (delBtn) {
        await api(`/api/searches/${delBtn.dataset.searchDelete}`, { method: "DELETE" });
        toast("Saved search deleted", "info");
        await Promise.all([loadSearches(), loadItems(), refreshStats()]);
      }
    } catch (err) {
      toast(err.message, "error");
    }
  });

  // Live auctions browser
  document.getElementById("live-auctions-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const list = document.getElementById("live-auctions-list");
    list.innerHTML = `<div class="empty-state">Loading live auctions from equip-bid.com/auction/list...</div>`;
    try {
      const qs = new URLSearchParams({
        zip_code: document.getElementById("auctions-zip").value.trim(),
        distance_radius: document.getElementById("auctions-distance").value,
        sort_field: document.getElementById("auctions-sort").value,
      });
      state.auctions = await api(`/api/live-auctions?${qs.toString()}`);
      renderAuctions();
    } catch (err) {
      list.innerHTML = `<div class="empty-state">Failed to fetch live auctions: ${esc(err.message)}</div>`;
    }
  });

  document.getElementById("live-auctions-list").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-auction-search]");
    if (!btn) return;
    openSearchModal(null, {
      auction_id: btn.dataset.auctionSearch,
      name: `Auction #${btn.dataset.auctionSearch} Monitor`,
    });
  });

  // Channel form save
  document.getElementById("channel-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = document.getElementById("channel-id").value;
    const type = document.getElementById("channel-type").value;
    try {
      const config = readChannelConfigFromForm(type);
      const payload = {
        name: document.getElementById("channel-name").value.trim(),
        channel_type: type,
        config,
        enabled: document.getElementById("channel-enabled").checked,
      };
      if (id) {
        await api(`/api/channels/${id}`, { method: "PUT", body: JSON.stringify(payload) });
        toast("Notification channel updated", "ok");
      } else {
        await api("/api/channels", { method: "POST", body: JSON.stringify(payload) });
        toast("Notification channel added", "ok");
      }
      closeModal("channel-modal");
      await Promise.all([loadChannels(), refreshStats()]);
    } catch (err) {
      toast(`Channel save failed: ${err.message}`, "error");
    }
  });

  // Channel list actions
  document.getElementById("channels-list").addEventListener("click", async (e) => {
    const testBtn = e.target.closest("[data-channel-test]");
    const editBtn = e.target.closest("[data-channel-edit]");
    const delBtn = e.target.closest("[data-channel-delete]");
    try {
      if (testBtn) {
        testBtn.disabled = true;
        testBtn.textContent = "Sending...";
        await api(`/api/channels/${testBtn.dataset.channelTest}/test`, { method: "POST" });
        toast("Test notification delivered!", "ok");
        testBtn.disabled = false;
        testBtn.textContent = "Send Test Alert";
      } else if (editBtn) {
        const ch = state.channels.find((x) => x.id === Number(editBtn.dataset.channelEdit));
        if (ch) openChannelModal(ch);
      } else if (delBtn) {
        await api(`/api/channels/${delBtn.dataset.channelDelete}`, { method: "DELETE" });
        toast("Channel deleted", "info");
        await Promise.all([loadChannels(), refreshStats()]);
      }
    } catch (err) {
      toast(err.message, "error");
      if (testBtn) {
        testBtn.disabled = false;
        testBtn.textContent = "Send Test Alert";
      }
    }
  });
}

async function bootstrap() {
  initEvents();
  await Promise.all([refreshStats(), loadSearches(), loadItems(), loadChannels()]);
  setInterval(() => {
    refreshStats();
  }, 30000);
}

bootstrap();
