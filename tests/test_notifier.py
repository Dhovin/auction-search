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
