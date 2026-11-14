"""Tests for multi-channel notification dispatchers."""

from unittest.mock import MagicMock

import pytest

from app import database, notifier


class FakeResponse:
    def raise_for_status(self):
        return None


@pytest.mark.asyncio
async def test_all_http_channels_dispatch(monkeypatch, tmp_path):
    db_file = str(tmp_path / "notifier_test.db")
    database.init_db(db_file)

    calls = []

    async def fake_post(self, url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    channels_to_add = [
        ("Discord", "discord", {"webhook_url": "https://discord.com/api/webhooks/123"}),
        ("Slack", "slack", {"webhook_url": "https://hooks.slack.com/services/abc"}),
        ("Webhook", "webhook", {"webhook_url": "https://example.com/hook", "headers": {"X-Test": "1"}}),
        ("ntfy", "ntfy", {"server_url": "https://ntfy.sh", "topic": "test-topic", "token": "tok"}),
        ("Gotify", "gotify", {"server_url": "https://gotify.example.com", "app_token": "g-tok", "priority": 7}),
        ("Pushover", "pushover", {"user_key": "u123", "api_token": "a456", "priority": 1}),
        ("Pushbullet", "pushbullet", {"access_token": "pb-tok", "device_iden": "dev1"}),
        ("Telegram", "telegram", {"bot_token": "bot123", "chat_id": "999"}),
    ]
    for name, ctype, cfg in channels_to_add:
        database.create_channel(
            {"name": name, "channel_type": ctype, "config": cfg, "enabled": True},
            db_path=db_file,
        )

    search = database.create_search(
        {"name": "Welders", "keywords": "welder"},
        db_path=db_file,
    )

    item = {
        "id": None,
        "title": "Miller Welder",
        "url": "https://www.equip-bid.com/auction/1/item/2",
        "image_url": "https://cdn.example.com/1.jpg",
        "current_bid": 95.0,
        "location": "Wichita, KS",
        "closing_time_raw": "11/18/2026 02:32 pm CST",
    }
    log = await notifier.dispatch_alerts(
        alert_type="new_item",
        title="[New Match] Miller Welder",
        item=item,
        search=search,
        db_path=db_file,
    )

    assert log["status"] == "success"
    assert len(calls) == 8
    urls = [c[0] for c in calls]
    assert "https://discord.com/api/webhooks/123" in urls
    assert "https://hooks.slack.com/services/abc" in urls
    assert "https://example.com/hook" in urls
    assert "https://ntfy.sh/test-topic" in urls
    assert "https://gotify.example.com/message" in urls
    assert "https://api.pushover.net/1/messages.json" in urls
    assert "https://api.pushbullet.com/v2/pushes" in urls
    assert "https://api.telegram.org/botbot123/sendMessage" in urls


@pytest.mark.asyncio
async def test_email_smtp_channel(monkeypatch, tmp_path):
    db_file = str(tmp_path / "smtp_test.db")
    database.init_db(db_file)

    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = smtp_instance
    smtp_factory = MagicMock(return_value=smtp_cm)
    monkeypatch.setattr("smtplib.SMTP", smtp_factory)

    ch = database.create_channel(
        {
            "name": "Email",
            "channel_type": "email",
            "config": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user@example.com",
                "password": "secret",
                "from_email": "alerts@example.com",
                "to_email": "me@example.com",
                "use_tls": True,
                "use_ssl": False,
            },
            "enabled": True,
        },
        db_path=db_file,
    )

    log = await notifier.send_test_notification(ch, db_path=db_file)
    assert log["status"] == "success"
    smtp_factory.assert_called_once_with("smtp.example.com", 587, timeout=20)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("user@example.com", "secret")
    smtp_instance.sendmail.assert_called_once()


@pytest.mark.asyncio
async def test_batch_email_and_http_digest(monkeypatch, tmp_path):
    db_file = str(tmp_path / "batch_notifier_test.db")
    database.init_db(db_file)

    http_calls = []

    async def fake_post(self, url, **kwargs):
        http_calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = smtp_instance
    monkeypatch.setattr("smtplib.SMTP", MagicMock(return_value=smtp_cm))

    database.create_channel(
        {
            "name": "Email",
            "channel_type": "email",
            "config": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user@example.com",
                "password": "secret",
                "from_email": "alerts@example.com",
                "to_email": "me@example.com",
                "use_tls": True,
                "use_ssl": False,
            },
            "enabled": True,
        },
        db_path=db_file,
    )
    database.create_channel(
        {"name": "Discord", "channel_type": "discord", "config": {"webhook_url": "https://discord.com/api/webhooks/123"}, "enabled": True},
        db_path=db_file,
    )
    database.create_channel(
        {"name": "Webhook", "channel_type": "webhook", "config": {"webhook_url": "https://example.com/hook"}, "enabled": True},
        db_path=db_file,
    )

    entries = [
        {
            "alert_type": "closing_soon",
            "title": "[Closing Soon (2h 0m)] CNC Milling Vise — $55.00",
            "item": {
                "id": None,
                "title": "CNC Milling Vise",
                "url": "https://www.equip-bid.com/auction/100/item/1",
                "current_bid": 55.0,
                "closing_time_raw": "Today 5:00 PM",
                "location": "Kansas City, MO",
            },
        },
        {
            "alert_type": "closing_soon",
            "title": "[Closing Soon (2h 10m)] Mitutoyo Caliper — $35.00",
            "item": {
                "id": None,
                "title": "Mitutoyo Caliper",
                "url": "https://www.equip-bid.com/auction/100/item/2",
                "current_bid": 35.0,
                "closing_time_raw": "Today 5:10 PM",
                "location": "Kansas City, MO",
            },
        },
        {
            "alert_type": "new_item",
            "title": "[New Match] Lincoln Welder — $210.00",
            "item": {
                "id": None,
                "title": "Lincoln Welder",
                "url": "https://www.equip-bid.com/auction/101/item/3",
                "current_bid": 210.0,
                "closing_time_raw": "Tomorrow 6:00 PM",
                "location": "Independence, MO",
            },
        },
    ]

    log = await notifier.dispatch_batch_alerts(entries, db_path=db_file)
    assert log["status"] == "success"
    assert log["alert_type"] == "digest"

    # Single combined email containing all 3 items
    assert smtp_instance.sendmail.call_count == 1
    raw_msg = smtp_instance.sendmail.call_args[0][2]
    assert "CNC Milling Vise" in raw_msg
    assert "Mitutoyo Caliper" in raw_msg
    assert "Lincoln Welder" in raw_msg
    assert "Equip-Bid Digest: 3 Alerts" in raw_msg

    # Single Discord post with 3 embeds, single Webhook post with 3 items
    assert len(http_calls) == 2
    discord_payload = next(c[1]["json"] for c in http_calls if "discord.com" in c[0])
    assert len(discord_payload["embeds"]) == 3
    webhook_payload = next(c[1]["json"] for c in http_calls if "example.com" in c[0])
    assert webhook_payload["count"] == 3
    assert len(webhook_payload["items"]) == 3
