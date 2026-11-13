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


def _send_smtp_sync(cfg: dict[str, Any], title: str, message: str, item: dict[str, Any]) -> None:
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

    item_url = item.get("url") or "https://www.equip-bid.com/auction/list"
    image_url = item.get("image_url") or ""
    bid = float(item.get("current_bid") or 0.0)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

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

        else:
            raise ValueError(f"Unsupported channel type: {ctype}")


async def dispatch_alerts(
    alert_type: str,
    title: str,
    item: dict[str, Any],
    search: Optional[dict[str, Any]] = None,
    message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """Dispatch an alert to all enabled notification channels and record an alert_log entry."""
    body = message or _build_item_summary(item)
    channels = database.list_channels(enabled_only=True, db_path=db_path)

    succeeded: list[str] = []
    errors: list[str] = []
    for ch in channels:
        try:
            await send_via_channel(ch, alert_type, title, body, item, search)
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
        item_id=item.get("id"),
        search_id=search["id"] if search else None,
        alert_type=alert_type,
        title=title,
        message=body,
        item_url=item.get("url") or "",
        channels_notified=succeeded,
        status=status,
        error_detail="; ".join(errors),
        db_path=db_path,
    )


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
