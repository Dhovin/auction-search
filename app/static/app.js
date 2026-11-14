"use strict";

const state = {
  searches: [],
  items: [],
  liveItems: null,
  liveQuery: "",
  channels: [],
  alerts: [],
  auctions: [],
  settings: {
    default_zip_code: "",
    default_distance_radius: -1,
    global_exclude_words: "",
    default_check_interval_minutes: 30,
    default_closing_soon_hours: 4,
    include_shippable_out_of_range: true,
    alert_batch_minutes: 15,
  },
};

const PLATFORM_GUIDES = {
  email: {
    title: "Email (SMTP) Setup Guide",
    steps: [
      "For Gmail, enable 2-Step Verification on your Google account and create a 16-character App Password (your regular password will fail).",
      "Common settings: smtp.gmail.com port 587 with STARTTLS checked, or port 465 for SSL.",
      "Enter your email address in SMTP Username, From Address, and Recipient Emails.",
    ],
    links: [
      { label: "Google App Passwords", url: "https://myaccount.google.com/apppasswords" },
      { label: "Gmail SMTP Docs", url: "https://support.google.com/mail/answer/7126229" },
      { label: "Fastmail App Passwords", url: "https://www.fastmail.help/hc/en-us/articles/360058753834-App-passwords" },
    ],
  },
  discord: {
    title: "Discord Webhook Setup Guide",
    steps: [
      "Open your Discord server -> Channel Settings (gear icon) -> Integrations -> Webhooks.",
      "Click New Webhook, choose the target text channel, and click Copy Webhook URL.",
      "Paste the https://discord.com/api/webhooks/... URL below and test delivery.",
    ],
    links: [
      { label: "Discord Webhooks Guide", url: "https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks" },
    ],
  },
  slack: {
    title: "Slack Webhook Setup Guide",
    steps: [
      "Open Slack API Apps and click Create New App -> From scratch.",
      "Under Features, open Incoming Webhooks and toggle Activate Incoming Webhooks on.",
      "Click Add New Webhook to Workspace, pick a channel, and paste the https://hooks.slack.com/services/... URL.",
    ],
    links: [
      { label: "Slack Incoming Webhooks Docs", url: "https://api.slack.com/messaging/webhooks" },
      { label: "Create a Slack App", url: "https://api.slack.com/apps" },
    ],
  },
  telegram: {
    title: "Telegram Bot Setup Guide",
    steps: [
      "Message @BotFather on Telegram and send /newbot to generate your Bot Token.",
      "Send /start in a direct chat with your new bot (or add it to a group chat).",
      "Find your numeric Chat ID using @userinfobot or https://api.telegram.org/bot<TOKEN>/getUpdates.",
    ],
    links: [
      { label: "Telegram Bot Tutorial", url: "https://core.telegram.org/bots/tutorial" },
      { label: "Open @BotFather", url: "https://t.me/BotFather" },
    ],
  },
  pushover: {
    title: "Pushover Setup Guide",
    steps: [
      "Sign in to your Pushover dashboard and copy your User Key (shown at the top right).",
      "Create a new Application / API Token for Equip-Bid Alerts and copy the API Token.",
      "Optional: enter a Device Name to notify a single device, or leave blank for all devices.",
    ],
    links: [
      { label: "Pushover Dashboard", url: "https://pushover.net/" },
      { label: "Create Pushover App Token", url: "https://pushover.net/apps/build" },
      { label: "Pushover API Docs", url: "https://pushover.net/api" },
    ],
  },
  pushbullet: {
    title: "Pushbullet Setup Guide",
    steps: [
      "Open Pushbullet Account Settings and scroll to Access Tokens.",
      "Click Create Access Token and paste the token (o....) below.",
      "Optional: enter a Device Iden or Channel Tag to restrict or broadcast pushes.",
    ],
    links: [
      { label: "Pushbullet Account Settings", url: "https://www.pushbullet.com/#settings/account" },
      { label: "Pushbullet API Docs", url: "https://docs.pushbullet.com/" },
    ],
  },
  ntfy: {
    title: "ntfy Push Setup Guide",
    steps: [
      "Choose a unique, hard-to-guess Topic Name (e.g. equipbid-kc-deals-9482) since public ntfy.sh topics have no password by default.",
      "Subscribe to that exact topic name in the ntfy mobile app or web app.",
      "For a private or self-hosted server, set your Server URL and Access Token (tk_...).",
    ],
    links: [
      { label: "ntfy Official Docs", url: "https://docs.ntfy.sh/" },
      { label: "ntfy.sh Web App", url: "https://ntfy.sh/app" },
    ],
  },
  gotify: {
    title: "Gotify Setup Guide",
    steps: [
      "Open your self-hosted Gotify web UI -> Apps -> Create Application.",
      "Enter your base Server URL (e.g. https://gotify.yourdomain.com) and copy the App Token.",
      "Priority defaults to 5 (range 1-10); higher priority triggers urgent phone notifications.",
    ],
    links: [
      { label: "Gotify Docs", url: "https://gotify.net/docs/index" },
      { label: "Gotify Push Messages", url: "https://gotify.net/docs/pushmsg" },
    ],
  },
  webhook: {
    title: "Custom Webhook Setup Guide",
    steps: [
      "Provide any HTTP/HTTPS endpoint accepting JSON POST requests.",
      "Payloads include alert_type, title, item (title, current_bid, next_required_bid, closing_at, url), search, and sent_at.",
      "Optionally provide Custom Headers as JSON, e.g. {\"Authorization\": \"Bearer TOKEN\"}.",
    ],
    links: [
      { label: "Home Assistant Webhook Docs", url: "https://www.home-assistant.io/docs/automation/trigger/#webhook-trigger" },
      { label: "n8n Webhook Node Docs", url: "https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/" },
    ],
  },
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
  pushbullet: [
    { key: "access_token", label: "Pushbullet Access Token *", type: "password", placeholder: "o.xxxxxxxxxxxxxxxx" },
    { key: "device_iden", label: "Target Device ID (optional, blank = all devices)", type: "text", placeholder: "" },
    { key: "channel_tag", label: "Channel Tag (optional)", type: "text", placeholder: "" },
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

function confirmAction({ title = "Confirm Action", message = "Are you sure?", confirmText = "Confirm" } = {}) {
  const modal = document.getElementById("confirm-modal");
  if (!modal) {
    return Promise.resolve(window.confirm(message));
  }

  document.getElementById("confirm-modal-title").textContent = title;
  document.getElementById("confirm-modal-message").textContent = message;
  const okBtn = document.getElementById("confirm-modal-ok");
  const cancelBtn = document.getElementById("confirm-modal-cancel");
  const closeBtn = document.getElementById("confirm-modal-close");
  const backdrop = document.getElementById("confirm-modal-backdrop");
  okBtn.textContent = confirmText;

  return new Promise((resolve) => {
    const finish = (result) => {
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      closeBtn.removeEventListener("click", onCancel);
      backdrop.removeEventListener("click", onCancel);
      document.removeEventListener("keydown", onKeyDown);
      closeModal("confirm-modal");
      resolve(result);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finish(false);
      }
    };

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    closeBtn.addEventListener("click", onCancel);
    backdrop.addEventListener("click", onCancel);
    document.addEventListener("keydown", onKeyDown);
    openModal("confirm-modal");
    cancelBtn.focus();
  });
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
  select.innerHTML = '<option value="">All Saved Searches</option><option value="manual">Manually Added Links</option>';
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
  if (searchId === "manual") {
    params.set("manual_only", "true");
  } else if (searchId) {
    params.set("search_id", searchId);
  }
  if (q) params.set("q", q);
  if (maxBid) params.set("max_bid", maxBid);
  if (sort) params.set("sort", sort);
  if (document.getElementById("filter-unread").checked) params.set("unread_only", "true");
  if (document.getElementById("filter-watched").checked) params.set("watched_only", "true");
  if (document.getElementById("filter-closing").checked) params.set("closing_soon_only", "true");

  state.items = await api(`/api/items?${params.toString()}`);
  renderItems();
}

async function addManualItemByUrl(rawUrl, watch = true) {
  const url = (rawUrl || "").trim();
  if (!url) {
    toast("Paste an Equip-Bid item URL first", "error");
    return;
  }
  const btn = document.getElementById("btn-add-item-url");
  const prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Fetching Lot...";
  try {
    const res = await api("/api/items/from-url", {
      method: "POST",
      body: JSON.stringify({ url, watch }),
    });
    const urlInput = document.getElementById("manual-item-url");
    if (urlInput) urlInput.value = "";
    await Promise.all([loadItems(), refreshStats()]);
    toast(`Listed ${res.count} item(s) from Equip-Bid link`, "ok");
  } finally {
    btn.disabled = false;
    btn.textContent = prevText;
  }
}

async function runAdhocLiveSearch() {
  const q = document.getElementById("filter-q").value.trim();
  if (!q) {
    toast("Type a keyword in the search box first (e.g. workstation)", "info");
    return;
  }
  if (/\/auction\/\d+\/item\/\d+/i.test(q)) {
    try {
      await addManualItemByUrl(q, true);
      document.getElementById("filter-q").value = "";
    } catch (err) {
      toast(`Failed to add item link: ${err.message}`, "error");
    }
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

function renderSiteSettings() {
  const s = state.settings || {};
  const zipEl = document.getElementById("global-zip");
  const distEl = document.getElementById("global-distance");
  const excEl = document.getElementById("global-exclude");
  const intEl = document.getElementById("global-interval");
  const closeEl = document.getElementById("global-closing-hours");
  const shipEl = document.getElementById("global-include-shippable");
  const batchEl = document.getElementById("global-alert-batch-minutes");
  if (zipEl) zipEl.value = s.default_zip_code || "";
  if (distEl) distEl.value = String(s.default_distance_radius ?? -1);
  if (excEl) excEl.value = s.global_exclude_words || "";
  if (intEl) intEl.value = s.default_check_interval_minutes ?? 30;
  if (closeEl) closeEl.value = s.default_closing_soon_hours ?? 4;
  if (shipEl) shipEl.checked = s.include_shippable_out_of_range !== false;
  if (batchEl) batchEl.value = s.alert_batch_minutes ?? 15;
  const badgeEl = document.getElementById("sidebar-defaults-badge");
  if (badgeEl) {
    const zip = (s.default_zip_code || "").trim();
    const dist = Number(s.default_distance_radius ?? -1);
    if (zip && dist > 0) badgeEl.textContent = `${zip} · ${dist}mi`;
    else if (zip) badgeEl.textContent = `${zip} · Any`;
    else badgeEl.textContent = dist > 0 ? `${dist}mi` : "Default";
  }

  const aucZipEl = document.getElementById("auctions-zip");
  const aucDistEl = document.getElementById("auctions-distance");
  const aucShipEl = document.getElementById("auctions-include-shippable");
  if (aucZipEl && !aucZipEl.dataset.touched && !aucZipEl.value) {
    aucZipEl.value = s.default_zip_code || "";
  }
  if (aucDistEl && !aucDistEl.dataset.touched) {
    aucDistEl.value = String(s.default_distance_radius ?? -1);
  }
  if (aucShipEl && !aucShipEl.dataset.touched) {
    aucShipEl.checked = s.include_shippable_out_of_range !== false;
  }
}

async function loadSettings() {
  state.settings = await api("/api/settings");
  renderSiteSettings();
}

async function saveSiteSettings() {
  const closingRaw = document.getElementById("global-closing-hours").value.trim();
  const batchEl = document.getElementById("global-alert-batch-minutes");
  const batchRaw = batchEl ? batchEl.value.trim() : "";
  const payload = {
    default_zip_code: document.getElementById("global-zip").value.trim(),
    default_distance_radius: Number(document.getElementById("global-distance").value),
    global_exclude_words: document.getElementById("global-exclude").value.trim(),
    default_check_interval_minutes: Number(document.getElementById("global-interval").value || 30),
    default_closing_soon_hours: closingRaw === "" ? 0 : Number(closingRaw),
    include_shippable_out_of_range: document.getElementById("global-include-shippable").checked,
    alert_batch_minutes: batchRaw === "" ? 15 : Number(batchRaw),
  };
  state.settings = await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  const aucZipEl = document.getElementById("auctions-zip");
  const aucDistEl = document.getElementById("auctions-distance");
  const aucShipEl = document.getElementById("auctions-include-shippable");
  if (aucZipEl && !aucZipEl.dataset.touched) aucZipEl.value = state.settings.default_zip_code || "";
  if (aucDistEl && !aucDistEl.dataset.touched) aucDistEl.value = String(state.settings.default_distance_radius ?? -1);
  if (aucShipEl && !aucShipEl.dataset.touched) aucShipEl.checked = state.settings.include_shippable_out_of_range !== false;
  renderSiteSettings();
  renderSearches();
  toast("Site-wide defaults saved", "ok");
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

      const hasShipping = (item.shipping_info || "").toLowerCase().includes("shipping available");
      const badgesHtml = isLive
        ? `<span class="pill unread">LIVE EQUIP-BID RESULT</span>
           ${hasShipping ? '<span class="pill ok">SHIPPING AVAILABLE</span>' : ""}
           ${isClosingSoon ? '<span class="pill warn">CLOSING SOON</span>' : ""}`
        : `${!item.is_read ? '<span class="pill unread">NEW</span>' : ""}
           ${item.is_watched ? '<span class="pill ok">WATCHED</span>' : ""}
           ${hasShipping ? '<span class="pill ok">SHIPPING AVAILABLE</span>' : ""}
           ${isClosingSoon ? '<span class="pill warn">CLOSING SOON</span>' : ""}
           ${isEnded ? '<span class="pill danger">ENDED</span>' : ""}
           ${item.search_name ? `<span class="pill">${esc(item.search_name)}</span>` : (!item.search_id ? '<span class="pill">MANUAL LINK</span>' : "")}`;

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
           <button class="btn btn-ghost btn-sm" data-action="dismiss" data-id="${item.id}" data-watched="${item.is_watched ? "true" : "false"}">Dismiss</button>`;

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
      const defZip = (state.settings.default_zip_code || "").trim();
      const defDist = Number(state.settings.default_distance_radius ?? -1);
      const effDist = s.distance_radius > 0 ? s.distance_radius : defDist;
      const shipSuffix = effDist > 0 && s.include_shippable_out_of_range !== false ? " + Shipping" : "";
      const distLabel = effDist > 0 ? `${effDist} mi${shipSuffix}` : "Any distance";
      let locText = "All locations";
      if (s.zip_code) {
        locText = `${esc(s.zip_code)} (${distLabel})`;
      } else if (defZip) {
        locText = `Site default: ${esc(defZip)} (${distLabel})`;
      } else if (effDist > 0) {
        locText = `Site default distance (${effDist} mi${shipSuffix})`;
      }
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
              ${(a.shipping_info || "").toLowerCase().includes("shipping available")
                ? `<span class="pill ok">${esc(a.shipping_info)}</span>`
                : (a.shipping_info ? `<span class="pill">${esc(a.shipping_info)}</span>` : "")}
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
    list.innerHTML = `<div class="empty-state">No external alert channels saved yet. Use the form above to set up Email (SMTP), Discord, Slack, Telegram, Pushover, ntfy, Gotify, or a Webhook.</div>`;
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
          <button class="btn btn-secondary btn-sm" data-channel-toggle="${c.id}" data-enabled="${!c.enabled}">
            ${c.enabled ? "Disable" : "Enable"}
          </button>
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
  const settings = state.settings || {};
  const defZip = (settings.default_zip_code || "").trim();
  const defDist = Number(settings.default_distance_radius ?? -1);
  const defInterval = settings.default_check_interval_minutes ?? 30;
  const defClosing = settings.default_closing_soon_hours;

  document.getElementById("search-modal-title").textContent = existing ? "Edit Saved Search" : "New Saved Search";
  document.getElementById("search-id").value = existing ? existing.id : "";
  document.getElementById("search-name").value = existing ? existing.name : (prefill.name || "");
  document.getElementById("search-keywords").value = existing ? existing.keywords : (prefill.keywords || "");
  document.getElementById("search-must-include").value = existing ? existing.must_include : "";
  document.getElementById("search-exclude").value = existing ? existing.exclude_words : "";
  document.getElementById("search-min-bid").value = existing && existing.min_bid != null ? existing.min_bid : "";
  document.getElementById("search-max-bid").value = existing && existing.max_bid != null ? existing.max_bid : "";

  const zipInput = document.getElementById("search-zip");
  zipInput.value = existing ? existing.zip_code : "";
  zipInput.placeholder = defZip ? `Site default: ${defZip}` : "e.g. 64101";

  const distSelect = document.getElementById("search-distance");
  const defaultDistOption = distSelect.querySelector('option[value="-1"]');
  if (defaultDistOption) {
    defaultDistOption.textContent = defDist > 0
      ? `Use Site Default (${defDist} miles)`
      : "Use Site Default / Any Distance";
  }
  distSelect.value = existing ? String(existing.distance_radius) : "-1";

  document.getElementById("search-auction-id").value = existing ? existing.auction_id : (prefill.auction_id || "");
  document.getElementById("search-sort").value = existing ? existing.sort_field : "close";
  document.getElementById("search-interval").value = existing ? existing.check_interval_minutes : defInterval;
  document.getElementById("search-pages").value = existing ? existing.max_pages : 2;
  const newClosingVal = defClosing && Number(defClosing) > 0 ? String(defClosing) : "";
  document.getElementById("search-closing-hours").value =
    existing ? (existing.closing_soon_hours != null ? existing.closing_soon_hours : "") : newClosingVal;
  document.getElementById("search-include-shippable").checked = existing
    ? existing.include_shippable_out_of_range !== false
    : settings.include_shippable_out_of_range !== false;
  document.getElementById("search-alert-new").checked = existing ? existing.alert_on_new : true;
  document.getElementById("search-enabled").checked = existing ? existing.enabled : true;

  const runWrap = document.getElementById("search-run-now-wrap");
  runWrap.style.display = existing ? "none" : "flex";
  document.getElementById("preview-box").classList.add("hidden");
  document.getElementById("preview-results").innerHTML = "";

  const activeChannels = state.channels.filter((c) => c.enabled);
  const summaryEl = document.getElementById("search-modal-channels-summary");
  if (summaryEl) {
    summaryEl.textContent = activeChannels.length
      ? `Active alert platforms: ${activeChannels.map((c) => `${c.name} (${c.channel_type})`).join(", ")}`
      : "No Email or external platforms configured yet (alerts show in web dashboard only).";
  }

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
    include_shippable_out_of_range: document.getElementById("search-include-shippable").checked,
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
// Channel Inline & Modal Dynamic Fields
// ---------------------------------------------------------------------------

function renderChannelFields(type, existingConfig = {}, containerId = "inline-channel-dynamic-fields") {
  const container = document.getElementById(containerId);
  if (!container) return;
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

function readChannelConfigFromForm(type, containerSelector = "#inline-channel-dynamic-fields") {
  const cfg = {};
  const fields = CHANNEL_SCHEMAS[type] || [];
  fields.forEach((f) => {
    const el = document.querySelector(`${containerSelector} [data-cfg-key="${f.key}"]`);
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

function renderPlatformGuide(type) {
  const container = document.getElementById("inline-platform-guide");
  if (!container) return;
  const guide = PLATFORM_GUIDES[type];
  if (!guide) {
    container.innerHTML = "";
    return;
  }
  const linksHtml = (guide.links || [])
    .map(
      (lnk) =>
        `<a class="platform-guide-link" href="${esc(lnk.url)}" target="_blank" rel="noopener noreferrer">${esc(lnk.label)} &nearr;</a>`
    )
    .join("");
  const stepsHtml = (guide.steps || [])
    .map((step) => `<li>${esc(step)}</li>`)
    .join("");
  container.innerHTML = `
    <div class="platform-guide-header">
      <span class="platform-guide-title">${esc(guide.title)}</span>
      <div class="platform-guide-links">${linksHtml}</div>
    </div>
    <ol class="platform-guide-steps">${stepsHtml}</ol>
  `;
}

function setInlinePlatform(type, existingConfig = {}) {
  document.getElementById("inline-channel-type").value = type;
  document.querySelectorAll("#inline-platform-pills .platform-pill").forEach((pill) => {
    pill.classList.toggle("active", pill.dataset.platform === type);
  });
  const nameInput = document.getElementById("inline-channel-name");
  if (!document.getElementById("inline-channel-id").value && !nameInput.dataset.touched) {
    const labelMap = {
      email: "Email Alerts",
      discord: "Discord Alerts",
      slack: "Slack Alerts",
      telegram: "Telegram Alerts",
      pushover: "Pushover Alerts",
      pushbullet: "Pushbullet Alerts",
      ntfy: "ntfy Push Alerts",
      gotify: "Gotify Alerts",
      webhook: "Custom Webhook",
    };
    nameInput.placeholder = `e.g. ${labelMap[type] || "My Alert Channel"}`;
  }
  renderPlatformGuide(type);
  renderChannelFields(type, existingConfig, "inline-channel-dynamic-fields");
}

function resetInlineChannelForm() {
  document.getElementById("inline-channel-id").value = "";
  const nameInput = document.getElementById("inline-channel-name");
  nameInput.value = "";
  delete nameInput.dataset.touched;
  document.getElementById("inline-channel-enabled").checked = true;
  document.getElementById("btn-inline-save-channel").textContent = "Save Channel";
  document.getElementById("btn-inline-reset-channel").classList.add("hidden");
  setInlinePlatform("email", {});
}

function editChannelInline(ch) {
  document.getElementById("inline-channel-id").value = ch.id;
  const nameInput = document.getElementById("inline-channel-name");
  nameInput.value = ch.name;
  nameInput.dataset.touched = "1";
  document.getElementById("inline-channel-enabled").checked = ch.enabled;
  document.getElementById("btn-inline-save-channel").textContent = "Update Channel";
  document.getElementById("btn-inline-reset-channel").classList.remove("hidden");
  setInlinePlatform(ch.channel_type, ch.config || {});
  document.getElementById("inline-channel-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function saveInlineChannel(andTest = false) {
  const id = document.getElementById("inline-channel-id").value;
  const type = document.getElementById("inline-channel-type").value;
  const name = document.getElementById("inline-channel-name").value.trim();
  if (!name) {
    toast("Please enter a Channel Label (e.g. Personal Email)", "error");
    document.getElementById("inline-channel-name").focus();
    return;
  }
  const config = readChannelConfigFromForm(type, "#inline-channel-dynamic-fields");
  const payload = {
    name,
    channel_type: type,
    config,
    enabled: document.getElementById("inline-channel-enabled").checked,
  };
  let saved;
  if (id) {
    saved = await api(`/api/channels/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    toast("Alert channel updated", "ok");
  } else {
    saved = await api("/api/channels", { method: "POST", body: JSON.stringify(payload) });
    toast("Alert channel saved", "ok");
  }
  resetInlineChannelForm();
  await Promise.all([loadChannels(), refreshStats()]);
  if (andTest && saved && saved.id) {
    await api(`/api/channels/${saved.id}/test`, { method: "POST" });
    toast(`Test notification delivered via ${saved.name}!`, "ok");
  }
}

async function switchTab(target) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === target);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === `tab-${target}`);
  });
  if (target === "alerts") await loadAlerts();
  if (target === "auctions" && !state.auctions.length) {
    document.getElementById("live-auctions-form").dispatchEvent(new Event("submit"));
  }
}

// ---------------------------------------------------------------------------
// Event Wiring
// ---------------------------------------------------------------------------

function initEvents() {
  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Modal close buttons
  document.querySelectorAll("[data-close]").forEach((el) => {
    el.addEventListener("click", () => closeModal(el.dataset.close));
  });

  document.getElementById("btn-new-search-top").addEventListener("click", () => openSearchModal());
  const appShell = document.getElementById("app-shell");
  const toggleSidebarBtn = document.getElementById("btn-toggle-sidebar");
  const applySidebarCollapsed = (collapsed) => {
    if (!appShell) return;
    appShell.classList.toggle("sidebar-collapsed", collapsed);
    if (toggleSidebarBtn) {
      toggleSidebarBtn.setAttribute("aria-expanded", String(!collapsed));
      toggleSidebarBtn.textContent = collapsed ? "Show Controls" : "Hide Controls";
    }
  };
  if (appShell) {
    applySidebarCollapsed(localStorage.getItem("equipbid_sidebar_collapsed") === "1");
  }
  if (toggleSidebarBtn) {
    toggleSidebarBtn.addEventListener("click", () => {
      const nextCollapsed = !appShell.classList.contains("sidebar-collapsed");
      applySidebarCollapsed(nextCollapsed);
      localStorage.setItem("equipbid_sidebar_collapsed", nextCollapsed ? "1" : "0");
    });
  }
  document.getElementById("btn-open-alerts-settings").addEventListener("click", () => switchTab("channels"));
  document.getElementById("btn-alerts-tab-configure").addEventListener("click", () => switchTab("channels"));
  document.getElementById("btn-modal-go-channels").addEventListener("click", () => {
    closeModal("search-modal");
    switchTab("channels");
  });
  document.getElementById("btn-add-search").addEventListener("click", () => openSearchModal());
  document.getElementById("btn-refresh-alerts").addEventListener("click", () => loadAlerts());

  document.getElementById("global-defaults-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("btn-save-global-settings");
    btn.disabled = true;
    try {
      await saveSiteSettings();
    } catch (err) {
      toast(`Failed to save defaults: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById("auctions-zip").addEventListener("input", (e) => {
    e.target.dataset.touched = "1";
  });
  document.getElementById("auctions-distance").addEventListener("change", (e) => {
    e.target.dataset.touched = "1";
  });
  document.getElementById("auctions-include-shippable").addEventListener("change", (e) => {
    e.target.dataset.touched = "1";
  });

  document.getElementById("add-item-url-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const rawUrl = document.getElementById("manual-item-url").value.trim();
    const watch = document.getElementById("manual-item-watch").checked;
    try {
      await addManualItemByUrl(rawUrl, watch);
      switchTab("items");
    } catch (err) {
      toast(`Failed to add item link: ${err.message}`, "error");
    }
  });

  // Inline platform selector pills & channel form
  document.getElementById("inline-platform-pills").addEventListener("click", (e) => {
    const pill = e.target.closest("[data-platform]");
    if (!pill) return;
    setInlinePlatform(pill.dataset.platform, {});
  });
  document.getElementById("inline-channel-name").addEventListener("input", (e) => {
    e.target.dataset.touched = "1";
  });
  document.getElementById("inline-channel-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await saveInlineChannel(false);
    } catch (err) {
      toast(`Failed to save alert channel: ${err.message}`, "error");
    }
  });
  document.getElementById("btn-inline-save-test").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Testing...";
    try {
      await saveInlineChannel(true);
    } catch (err) {
      toast(`Test failed: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Save & Send Test Alert";
    }
  });
  document.getElementById("btn-inline-reset-channel").addEventListener("click", () => resetInlineChannelForm());

  // Item filters
  ["filter-search-id", "filter-sort", "filter-unread", "filter-watched", "filter-closing"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => {
      switchTab("items");
      loadItems();
    });
  });
  let debounceTimer;
  ["filter-q", "filter-max-bid"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        switchTab("items");
        loadItems();
      }, 250);
    });
  });

  document.getElementById("filter-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      clearTimeout(debounceTimer);
      switchTab("items");
      runAdhocLiveSearch();
    }
  });
  document.getElementById("btn-live-search-bar").addEventListener("click", () => {
    switchTab("items");
    runAdhocLiveSearch();
  });
  document.getElementById("btn-save-from-bar").addEventListener("click", () => {
    const q = document.getElementById("filter-q").value.trim();
    openSearchModal(null, { keywords: q, name: q ? `${q} Monitor` : "" });
  });

  // Run all searches / Mark all read
  document.getElementById("btn-mark-all-read").addEventListener("click", async () => {
    const searchId = document.getElementById("filter-search-id").value;
    const validSearchId = searchId && searchId !== "manual" ? searchId : "";
    const url = validSearchId ? `/api/items/mark-all-read?search_id=${validSearchId}` : "/api/items/mark-all-read";
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
        const item = state.items.find((x) => x.id === Number(id));
        const isWatched = item ? Boolean(item.is_watched) : btn.dataset.watched === "true";
        if (isWatched) {
          const label = item?.title ? `"${item.title}"` : "this watched lot";
          const confirmed = await confirmAction({
            title: "Dismiss Watched Item?",
            message: `${label} is currently watched. Dismissing it will remove it from your active and watched lists. Are you sure you want to dismiss it?`,
            confirmText: "Dismiss Item",
          });
          if (!confirmed) return;
        }
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
        include_shippable_out_of_range: String(payload.include_shippable_out_of_range),
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
        use_defaults: "false",
        include_shippable_out_of_range: String(document.getElementById("auctions-include-shippable").checked),
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

  // Channel list actions
  document.getElementById("channels-list").addEventListener("click", async (e) => {
    const testBtn = e.target.closest("[data-channel-test]");
    const editBtn = e.target.closest("[data-channel-edit]");
    const toggleBtn = e.target.closest("[data-channel-toggle]");
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
        if (ch) editChannelInline(ch);
      } else if (toggleBtn) {
        const enabled = toggleBtn.dataset.enabled === "true";
        await api(`/api/channels/${toggleBtn.dataset.channelToggle}`, {
          method: "PUT",
          body: JSON.stringify({ enabled }),
        });
        await Promise.all([loadChannels(), refreshStats()]);
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
  setInlinePlatform("email", {});
  await loadSettings();
  await Promise.all([refreshStats(), loadSearches(), loadItems(), loadChannels()]);
  setInterval(() => {
    refreshStats();
    const itemsTabActive = document.getElementById("tab-items")?.classList.contains("active");
    const hasOpenModal = Boolean(document.querySelector(".modal:not(.hidden)"));
    if (itemsTabActive && !state.isLiveMode && !hasOpenModal) {
      loadItems();
    }
  }, 30000);
}

bootstrap();
