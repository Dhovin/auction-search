"""Multi-channel notification dispatcher and test sender."""

from __future__ import annotations

import asyncio
import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

import httpx

from app import database


def _build_item_summary(item: dict[str, Any]) -> str:
    bid = float(item.get("current_bid") or 0.0)
    parts = [f"Current Bid: ${bid:,.2f}"]
    if item.get("next_required_bid") is not None:
        parts.append(f"Next Bid: ${float(item['next_required_bid']):,.2f}")
    if item.get("location"):
        parts.append(f"Location: {item['location']}")
    if item.get("closing_time_raw"):
        parts.append(f"Closes: {item['closing_time_raw']}")
    elif item.get("time_remaining_raw"):
        parts.append(f"Time Left: {item['time_remaining_raw']}")
    if item.get("auction_title"):
        parts.append(f"Auction: {item['auction_title']}")
    return " | ".join(parts)


def _send_smtp_message(
    cfg: dict[str, Any], subject: str, plain_body: str, html_body: str
) -> None:
    host = cfg.get("host", "").strip()
    port = int(cfg.get("port", 587))
    username = cfg.get("username", "").strip()
    password = cfg.get("password", "")
    use_ssl = bool(cfg.get("use_ssl", False))
    use_tls = bool(cfg.get("use_tls", True))
    from_addr = (cfg.get("from_email") or username).strip()
    to_raw = cfg.get("to_email", "").strip()
    recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    if not host or not from_addr or not recipients:
        raise ValueError("SMTP channel requires host, from_email, and to_email")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20) as server:
            if username:
                server.login(username, password)
            server.sendmail(from_addr, recipients, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            if use_tls:
                server.starttls()
            if username:
                server.login(username, password)
            server.sendmail(from_addr, recipients, msg.as_string())


def _send_smtp_sync(cfg: dict[str, Any], title: str, message: str, item: dict[str, Any]) -> None:
    item_url = item.get("url") or "https://www.equip-bid.com/auction/list"
    image_url = item.get("image_url") or ""
    bid = float(item.get("current_bid") or 0.0)

    plain_body = f"{title}\n\n{message}\n\nView on Equip-Bid: {item_url}\n"
    img_html = (
        f'<p><img src="{html.escape(image_url)}" alt="Lot Image" '
        f'style="max-width:280px;border-radius:8px;border:1px solid #ddd;"></p>'
        if image_url
        else ""
    )
    html_body = f"""
    <html>
      <body style="font-family:Segoe UI,Arial,sans-serif;color:#1e293b;line-height:1.5;">
        <h2 style="color:#0f172a;margin-bottom:8px;">{html.escape(title)}</h2>
        <p style="font-size:15px;">{html.escape(message)}</p>
        {img_html}
        <p><strong>Current Bid:</strong> ${bid:,.2f}</p>
        <p>
          <a href="{html.escape(item_url)}"
             style="display:inline-block;padding:10px 18px;background:#2563eb;color:#fff;
                    text-decoration:none;border-radius:6px;font-weight:600;">
            View Lot on Equip-Bid
          </a>
        </p>
      </body>
    </html>
    """
    _send_smtp_message(cfg, title, plain_body, html_body)


def _format_batch_metadata(entries: list[dict[str, Any]]) -> dict[str, Any]:
    types = {e.get("alert_type") or "new_item" for e in entries}
    new_count = sum(1 for e in entries if e.get("alert_type") == "new_item")
    closing_count = sum(1 for e in entries if e.get("alert_type") == "closing_soon")
    batch_type = next(iter(types)) if len(types) == 1 else "digest"

    first_title = (entries[0]["item"].get("title") or "Equip-Bid Lot").strip()
    if len(first_title) > 55:
        first_title = first_title[:52] + "..."
    extra = len(entries) - 1

    if batch_type == "closing_soon":
        batch_title = f"[{len(entries)} Closing Soon Alerts] {first_title} (+{extra} more)"
    elif batch_type == "new_item":
        batch_title = f"[{len(entries)} New Matches] {first_title} (+{extra} more)"
    else:
        batch_title = (
            f"[Equip-Bid Digest: {len(entries)} Alerts] "
            f"{new_count} New, {closing_count} Closing Soon"
        )

    lines: list[str] = []
    for idx, entry in enumerate(entries, start=1):
        item = entry["item"]
        tag = "CLOSING SOON" if entry.get("alert_type") == "closing_soon" else "NEW MATCH"
        item_url = item.get("url") or "https://www.equip-bid.com/auction/list"
        lines.append(
            f"{idx}. [{tag}] {item.get('title', 'Equip-Bid Lot')}\n"
            f"   {_build_item_summary(item)}\n"
            f"   {item_url}"
        )
    plain_message = "\n\n".join(lines)
    return {
        "batch_type": batch_type,
        "title": batch_title,
        "plain_message": plain_message,
        "new_count": new_count,
        "closing_count": closing_count,
    }


def _build_batch_email_html(title: str, entries: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for entry in entries:
        item = entry["item"]
        is_closing = entry.get("alert_type") == "closing_soon"
        badge_bg = "#fef3c7" if is_closing else "#dbeafe"
        badge_fg = "#92400e" if is_closing else "#1e40af"
        badge_label = "CLOSING SOON" if is_closing else "NEW MATCH"
        item_url = item.get("url") or "https://www.equip-bid.com/auction/list"
        image_url = item.get("image_url") or ""
        bid = float(item.get("current_bid") or 0.0)
        closing = item.get("closing_time_raw") or item.get("time_remaining_raw") or "N/A"
        location = item.get("location") or "Location N/A"
        shipping = item.get("shipping_info") or ""
        auction = item.get("auction_title") or ""

        thumb = (
            f'<td style="width:96px;vertical-align:top;padding-right:12px;">'
            f'<img src="{html.escape(image_url)}" alt="" '
            f'style="width:88px;height:88px;object-fit:cover;border-radius:6px;border:1px solid #e2e8f0;">'
            f"</td>"
            if image_url
            else ""
        )
        meta_parts = [f"<strong>Bid: ${bid:,.2f}</strong>", f"Closes: {html.escape(closing)}", html.escape(location)]
        if shipping:
            meta_parts.append(html.escape(shipping))
        if auction:
            meta_parts.append(html.escape(auction))

        cards.append(
            f"""
            <div style="border:1px solid #cbd5e1;border-radius:8px;padding:12px;margin-bottom:12px;background:#ffffff;">
              <table style="width:100%;border-collapse:collapse;">
                <tr>
                  {thumb}
                  <td style="vertical-align:top;">
                    <span style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;
                                 font-weight:700;background:{badge_bg};color:{badge_fg};margin-bottom:6px;">
                      {badge_label}
                    </span>
                    <div style="font-size:15px;font-weight:700;margin-bottom:4px;">
                      <a href="{html.escape(item_url)}" style="color:#0f172a;text-decoration:none;">
                        {html.escape(item.get('title') or 'Equip-Bid Lot')}
                      </a>
                    </div>
                    <div style="font-size:13px;color:#475569;margin-bottom:8px;">
                      {" &bull; ".join(meta_parts)}
                    </div>
                    <a href="{html.escape(item_url)}"
                       style="display:inline-block;padding:6px 12px;background:#2563eb;color:#ffffff;
                              text-decoration:none;border-radius:5px;font-size:12px;font-weight:600;">
                      View Lot
                    </a>
                  </td>
                </tr>
              </table>
            </div>
            """
        )

    return f"""
    <html>
      <body style="font-family:Segoe UI,Arial,sans-serif;color:#1e293b;background:#f8fafc;padding:16px;line-height:1.45;">
        <div style="max-width:680px;margin:0 auto;">
          <h2 style="color:#0f172a;margin:0 0 6px 0;">{html.escape(title)}</h2>
          <p style="color:#475569;font-size:13px;margin:0 0 14px 0;">
            Combined {len(entries)} Equip-Bid alerts triggered within your configured batch window.
          </p>
          {"".join(cards)}
        </div>
      </body>
    </html>
    """


def _build_compact_digest_text(entries: list[dict[str, Any]], max_len: int) -> str:
    lines: list[str] = []
    used = 0
    for idx, entry in enumerate(entries, start=1):
        item = entry["item"]
        bid = float(item.get("current_bid") or 0.0)
        tag = "CLOSING" if entry.get("alert_type") == "closing_soon" else "NEW"
        closing = item.get("time_remaining_raw") or item.get("closing_time_raw") or ""
        suffix = f" ({closing})" if closing else ""
        line = f"{idx}. [{tag}] {item.get('title', 'Lot')} — ${bid:,.2f}{suffix}\n{item.get('url', '')}"
        if used + len(line) + 32 > max_len and lines:
            remaining = len(entries) - idx + 1
            lines.append(f"...and {remaining} more lot(s).")
            break
        lines.append(line)
        used += len(line) + 2
    return "\n\n".join(lines)[:max_len]


async def send_via_channel(
    channel: dict[str, Any],
    alert_type: str,
    title: str,
    message: str,
    item: dict[str, Any],
    search: Optional[dict[str, Any]] = None,
) -> None:
    """Deliver a single notification payload through the specified channel."""
    ctype = channel["channel_type"]
    cfg = channel.get("config") or {}
    item_url = item.get("url") or "https://www.equip-bid.com/auction/list"
    image_url = item.get("image_url") or ""
    bid = float(item.get("current_bid") or 0.0)

    if ctype == "email":
        await asyncio.to_thread(_send_smtp_sync, cfg, title, message, item)
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        if ctype == "discord":
            webhook_url = (cfg.get("webhook_url") or "").strip()
            if not webhook_url:
                raise ValueError("Discord webhook_url is required")
            embed: dict[str, Any] = {
                "title": title[:256],
                "description": message[:2048],
                "url": item_url,
                "color": 15844367 if alert_type == "closing_soon" else 3447003,
                "fields": [
                    {"name": "Current Bid", "value": f"${bid:,.2f}", "inline": True},
                    {
                        "name": "Location",
                        "value": item.get("location") or "N/A",
                        "inline": True,
                    },
                    {
                        "name": "Closing",
                        "value": item.get("closing_time_raw") or item.get("time_remaining_raw") or "N/A",
                        "inline": True,
                    },
                ],
            }
            if image_url:
                embed["thumbnail"] = {"url": image_url}
            resp = await client.post(webhook_url, json={"embeds": [embed]})
            resp.raise_for_status()

        elif ctype == "slack":
            webhook_url = (cfg.get("webhook_url") or "").strip()
            if not webhook_url:
                raise ValueError("Slack webhook_url is required")
            payload = {"text": f"*{title}*\n{message}\n<{item_url}|View Lot on Equip-Bid>"}
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()

        elif ctype == "webhook":
            webhook_url = (cfg.get("webhook_url") or "").strip()
            if not webhook_url:
                raise ValueError("Webhook URL is required")
            headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
            payload = {
                "alert_type": alert_type,
                "title": title,
                "message": message,
                "item": item,
                "search": {"id": search["id"], "name": search["name"]} if search else None,
                "timestamp": database.utc_now_iso(),
            }
            resp = await client.post(webhook_url, json=payload, headers=headers)
            resp.raise_for_status()

        elif ctype == "ntfy":
            server_url = (cfg.get("server_url") or "https://ntfy.sh").strip().rstrip("/")
            topic = (cfg.get("topic") or "").strip().lstrip("/")
            if not topic:
                raise ValueError("ntfy topic is required")
            headers = {
                "Title": title[:200],
                "Click": item_url,
                "Priority": str(cfg.get("priority") or "default"),
            }
            if cfg.get("token"):
                headers["Authorization"] = f"Bearer {cfg['token'].strip()}"
            resp = await client.post(f"{server_url}/{topic}", content=message.encode("utf-8"), headers=headers)
            resp.raise_for_status()

        elif ctype == "gotify":
            server_url = (cfg.get("server_url") or "").strip().rstrip("/")
            app_token = (cfg.get("app_token") or "").strip()
            if not server_url or not app_token:
                raise ValueError("Gotify server_url and app_token are required")
            payload = {
                "title": title,
                "message": f"{message}\n\n[View on Equip-Bid]({item_url})",
                "priority": int(cfg.get("priority", 5)),
                "extras": {"client::display": {"contentType": "text/markdown"}},
            }
            resp = await client.post(
                f"{server_url}/message",
                params={"token": app_token},
                json=payload,
            )
            resp.raise_for_status()

        elif ctype == "pushover":
            api_token = (cfg.get("api_token") or "").strip()
            user_key = (cfg.get("user_key") or "").strip()
            if not api_token or not user_key:
                raise ValueError("Pushover api_token and user_key are required")
            form = {
                "token": api_token,
                "user": user_key,
                "title": title[:250],
                "message": message[:1024],
                "url": item_url,
                "url_title": "View on Equip-Bid",
                "priority": str(cfg.get("priority", 0)),
            }
            resp = await client.post("https://api.pushover.net/1/messages.json", data=form)
            resp.raise_for_status()

        elif ctype == "telegram":
            bot_token = (cfg.get("bot_token") or "").strip()
            chat_id = (cfg.get("chat_id") or "").strip()
            if not bot_token or not chat_id:
                raise ValueError("Telegram bot_token and chat_id are required")
            text = (
                f"<b>{html.escape(title)}</b>\n"
                f"{html.escape(message)}\n"
                f'<a href="{html.escape(item_url)}">View Lot on Equip-Bid</a>'
            )
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()

        elif ctype == "pushbullet":
            access_token = (cfg.get("access_token") or "").strip()
            if not access_token:
                raise ValueError("Pushbullet access_token is required")
            payload: dict[str, Any] = {
                "type": "link",
                "title": title[:250],
                "body": message[:2048],
                "url": item_url,
            }
            if (cfg.get("device_iden") or "").strip():
                payload["device_iden"] = cfg["device_iden"].strip()
            if (cfg.get("channel_tag") or "").strip():
                payload["channel_tag"] = cfg["channel_tag"].strip()
            resp = await client.post(
                "https://api.pushbullet.com/v2/pushes",
                headers={"Access-Token": access_token},
                json=payload,
            )
            resp.raise_for_status()

        else:
            raise ValueError(f"Unsupported channel type: {ctype}")


async def send_batch_via_channel(
    channel: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    """Deliver one or multiple combined alerts through a single notification channel."""
    if not entries:
        return
    if len(entries) == 1:
        entry = entries[0]
        body = entry.get("message") or _build_item_summary(entry["item"])
        await send_via_channel(
            channel,
            entry["alert_type"],
            entry["title"],
            body,
            entry["item"],
            entry.get("search"),
        )
        return

    meta = _format_batch_metadata(entries)
    ctype = channel["channel_type"]
    cfg = channel.get("config") or {}
    batch_title = meta["title"]
    plain_msg = meta["plain_message"]
    first_url = entries[0]["item"].get("url") or "https://www.equip-bid.com/auction/list"

    if ctype == "email":
        html_body = _build_batch_email_html(batch_title, entries)
        plain_body = f"{batch_title}\n\n{plain_msg}\n"
        await asyncio.to_thread(_send_smtp_message, cfg, batch_title, plain_body, html_body)
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        if ctype == "discord":
            webhook_url = (cfg.get("webhook_url") or "").strip()
            if not webhook_url:
                raise ValueError("Discord webhook_url is required")
            embeds = []
            for entry in entries:
                item = entry["item"]
                bid = float(item.get("current_bid") or 0.0)
                emb: dict[str, Any] = {
                    "title": (entry.get("title") or item.get("title") or "Equip-Bid Lot")[:256],
                    "url": item.get("url") or first_url,
                    "color": 15844367 if entry.get("alert_type") == "closing_soon" else 3447003,
                    "fields": [
                        {"name": "Current Bid", "value": f"${bid:,.2f}", "inline": True},
                        {"name": "Closing", "value": item.get("closing_time_raw") or item.get("time_remaining_raw") or "N/A", "inline": True},
                        {"name": "Location", "value": item.get("location") or "N/A", "inline": True},
                    ],
                }
                if item.get("image_url"):
                    emb["thumbnail"] = {"url": item["image_url"]}
                embeds.append(emb)
            for idx in range(0, len(embeds), 10):
                payload: dict[str, Any] = {"embeds": embeds[idx : idx + 10]}
                if idx == 0:
                    payload["content"] = f"**{batch_title}**"
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()

        elif ctype == "slack":
            webhook_url = (cfg.get("webhook_url") or "").strip()
            if not webhook_url:
                raise ValueError("Slack webhook_url is required")
            lines = [f"*{batch_title}*"]
            for entry in entries[:15]:
                item = entry["item"]
                bid = float(item.get("current_bid") or 0.0)
                item_url = item.get("url") or first_url
                lines.append(f"• *{item.get('title', 'Lot')}* — ${bid:,.2f} (<{item_url}|View Lot>)")
            if len(entries) > 15:
                lines.append(f"_...and {len(entries) - 15} more lot(s)._")
            resp = await client.post(webhook_url, json={"text": "\n".join(lines)})
            resp.raise_for_status()

        elif ctype == "webhook":
            webhook_url = (cfg.get("webhook_url") or "").strip()
            if not webhook_url:
                raise ValueError("Webhook URL is required")
            headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
            payload = {
                "alert_type": meta["batch_type"],
                "title": batch_title,
                "message": plain_msg,
                "count": len(entries),
                "items": [e["item"] for e in entries],
                "entries": [
                    {
                        "alert_type": e["alert_type"],
                        "title": e["title"],
                        "item": e["item"],
                        "search": e.get("search"),
                    }
                    for e in entries
                ],
                "timestamp": database.utc_now_iso(),
            }
            resp = await client.post(webhook_url, json=payload, headers=headers)
            resp.raise_for_status()

        elif ctype == "ntfy":
            server_url = (cfg.get("server_url") or "https://ntfy.sh").strip().rstrip("/")
            topic = (cfg.get("topic") or "").strip().lstrip("/")
            if not topic:
                raise ValueError("ntfy topic is required")
            body = _build_compact_digest_text(entries, 1800)
            headers = {
                "Title": batch_title[:200],
                "Click": first_url,
                "Priority": str(cfg.get("priority") or "default"),
            }
            if cfg.get("token"):
                headers["Authorization"] = f"Bearer {cfg['token'].strip()}"
            resp = await client.post(f"{server_url}/{topic}", content=body.encode("utf-8"), headers=headers)
            resp.raise_for_status()

        elif ctype == "gotify":
            server_url = (cfg.get("server_url") or "").strip().rstrip("/")
            app_token = (cfg.get("app_token") or "").strip()
            if not server_url or not app_token:
                raise ValueError("Gotify server_url and app_token are required")
            md_lines = [
                f"- [{html.escape(e['item'].get('title', 'Lot'))}]({e['item'].get('url', first_url)}) — ${float(e['item'].get('current_bid') or 0.0):,.2f}"
                for e in entries
            ]
            payload = {
                "title": batch_title,
                "message": "\n".join(md_lines),
                "priority": int(cfg.get("priority", 5)),
                "extras": {"client::display": {"contentType": "text/markdown"}},
            }
            resp = await client.post(
                f"{server_url}/message",
                params={"token": app_token},
                json=payload,
            )
            resp.raise_for_status()

        elif ctype == "pushover":
            api_token = (cfg.get("api_token") or "").strip()
            user_key = (cfg.get("user_key") or "").strip()
            if not api_token or not user_key:
                raise ValueError("Pushover api_token and user_key are required")
            form = {
                "token": api_token,
                "user": user_key,
                "title": batch_title[:250],
                "message": _build_compact_digest_text(entries, 1024),
                "url": first_url,
                "url_title": "View First Lot",
                "priority": str(cfg.get("priority", 0)),
            }
            resp = await client.post("https://api.pushover.net/1/messages.json", data=form)
            resp.raise_for_status()

        elif ctype == "telegram":
            bot_token = (cfg.get("bot_token") or "").strip()
            chat_id = (cfg.get("chat_id") or "").strip()
            if not bot_token or not chat_id:
                raise ValueError("Telegram bot_token and chat_id are required")
            item_lines = [f"<b>{html.escape(batch_title)}</b>"]
            for entry in entries[:20]:
                item = entry["item"]
                bid = float(item.get("current_bid") or 0.0)
                item_url = item.get("url") or first_url
                tag = "CLOSING SOON" if entry.get("alert_type") == "closing_soon" else "NEW"
                item_lines.append(
                    f'• [{tag}] <a href="{html.escape(item_url)}">{html.escape(item.get("title") or "Lot")}</a> — ${bid:,.2f}'
                )
            if len(entries) > 20:
                item_lines.append(f"<i>...and {len(entries) - 20} more lot(s).</i>")
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": "\n".join(item_lines)[:4096], "parse_mode": "HTML"},
            )
            resp.raise_for_status()

        elif ctype == "pushbullet":
            access_token = (cfg.get("access_token") or "").strip()
            if not access_token:
                raise ValueError("Pushbullet access_token is required")
            payload = {
                "type": "link",
                "title": batch_title[:250],
                "body": _build_compact_digest_text(entries, 2048),
                "url": first_url,
            }
            if (cfg.get("device_iden") or "").strip():
                payload["device_iden"] = cfg["device_iden"].strip()
            if (cfg.get("channel_tag") or "").strip():
                payload["channel_tag"] = cfg["channel_tag"].strip()
            resp = await client.post(
                "https://api.pushbullet.com/v2/pushes",
                headers={"Access-Token": access_token},
                json=payload,
            )
            resp.raise_for_status()

        else:
            raise ValueError(f"Unsupported channel type: {ctype}")


async def dispatch_batch_alerts(
    entries: list[dict[str, Any]],
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Dispatch a single or combined multi-item alert across enabled channels and log it."""
    if not entries:
        return None

    if len(entries) == 1:
        entry = entries[0]
        alert_type = entry["alert_type"]
        title = entry["title"]
        item = entry["item"]
        search = entry.get("search")
        body = entry.get("message") or _build_item_summary(item)
        log_item_id = item.get("id")
        log_search_id = search["id"] if search else None
        log_url = item.get("url") or ""
    else:
        meta = _format_batch_metadata(entries)
        alert_type = meta["batch_type"]
        title = meta["title"]
        body = meta["plain_message"]
        log_item_id = None
        search_ids = {
            e["search"]["id"] for e in entries if e.get("search") and e["search"].get("id") is not None
        }
        log_search_id = next(iter(search_ids)) if len(search_ids) == 1 else None
        log_url = entries[0]["item"].get("url") or ""

    channels = database.list_channels(enabled_only=True, db_path=db_path)
    succeeded: list[str] = []
    errors: list[str] = []
    for ch in channels:
        try:
            await send_batch_via_channel(ch, entries)
            succeeded.append(f"{ch['name']} ({ch['channel_type']})")
        except Exception as exc:
            errors.append(f"{ch['name']}: {exc}")

    if not channels:
        status = "in_app_only"
    elif errors and succeeded:
        status = "partial"
    elif errors and not succeeded:
        status = "error"
    else:
        status = "success"

    return database.insert_alert_log(
        item_id=log_item_id,
        search_id=log_search_id,
        alert_type=alert_type,
        title=title,
        message=body,
        item_url=log_url,
        channels_notified=succeeded,
        status=status,
        error_detail="; ".join(errors),
        db_path=db_path,
    )


async def dispatch_alerts(
    alert_type: str,
    title: str,
    item: dict[str, Any],
    search: Optional[dict[str, Any]] = None,
    message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """Dispatch a single-item alert to all enabled notification channels and record an alert_log entry."""
    result = await dispatch_batch_alerts(
        [
            {
                "alert_type": alert_type,
                "title": title,
                "item": item,
                "search": search,
                "message": message,
            }
        ],
        db_path=db_path,
    )
    assert result is not None
    return result


async def send_test_notification(
    channel: dict[str, Any], db_path: Optional[str] = None
) -> dict[str, Any]:
    """Send a synthetic test alert through a specific channel and log the result."""
    sample_item = {
        "id": None,
        "title": "Test Alert: Miller Welder & Fabrication Lot",
        "url": "https://www.equip-bid.com/auction/list",
        "image_url": "",
        "current_bid": 45.00,
        "next_required_bid": 47.50,
        "location": "Kansas City, MO",
        "closing_time_raw": "Ends in 2h 15m",
        "auction_title": "Equip-Bid Test Auction",
    }
    title = "[Equip-Bid Monitor] Test Notification"
    body = f"Test alert delivered via '{channel['name']}' ({channel['channel_type']})."
    try:
        await send_via_channel(channel, "test", title, body, sample_item, None)
        return database.insert_alert_log(
            item_id=None,
            search_id=None,
            alert_type="test",
            title=title,
            message=body,
            item_url=sample_item["url"],
            channels_notified=[f"{channel['name']} ({channel['channel_type']})"],
            status="success",
            error_detail="",
            db_path=db_path,
        )
    except Exception as exc:
        log = database.insert_alert_log(
            item_id=None,
            search_id=None,
            alert_type="test",
            title=title,
            message=body,
            item_url=sample_item["url"],
            channels_notified=[],
            status="error",
            error_detail=str(exc),
            db_path=db_path,
        )
        raise RuntimeError(str(exc)) from exc
