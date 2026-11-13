"""Integration tests for FastAPI endpoints, search execution, and closing-soon alerts."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import config, database
from app.main import app


def test_full_api_workflow(monkeypatch, tmp_path):
    db_file = str(tmp_path / "api_test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_file)

    soon_utc = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def fake_scrape_search_lots(**kwargs):
        return [
            {
                "lot_key": "48446:1051",
                "auction_id": "48446",
                "lot_number": "1051",
                "internal_lot_id": "11008830",
                "title": "Miller Millermatic 211 Welder",
                "url": "https://www.equip-bid.com/auction/48446/item/1051",
                "image_url": "https://cdn.example.com/a.jpg",
                "current_bid": 150.0,
                "next_required_bid": 155.0,
                "high_bidder": "#1001",
                "auction_title": "Industrial Auction",
                "affiliate": "Agent 86",
                "location": "Wichita, KS",
                "category": "Metal Fabrication",
                "shipping_info": "No Shipping",
                "closing_time_raw": "Today",
                "closing_at": soon_utc,
                "time_remaining_raw": "2h 0m",
            },
            {
                "lot_key": "48446:1052",
                "auction_id": "48446",
                "lot_number": "1052",
                "internal_lot_id": "11008831",
                "title": "Broken Welder Parts Only",
                "url": "https://www.equip-bid.com/auction/48446/item/1052",
                "image_url": "",
                "current_bid": 20.0,
                "next_required_bid": 25.0,
                "high_bidder": "",
                "auction_title": "Industrial Auction",
                "affiliate": "Agent 86",
                "location": "Wichita, KS",
                "category": "Metal Fabrication",
                "shipping_info": "",
                "closing_time_raw": "Today",
                "closing_at": soon_utc,
                "time_remaining_raw": "2h 0m",
            },
        ]

    monkeypatch.setattr("app.scraper.scrape_search_lots", fake_scrape_search_lots)

    with TestClient(app) as client:
        # Health & stats
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        # Create saved search with run_immediately=True
        resp = client.post(
            "/api/searches",
            json={
                "name": "Miller Welders",
                "keywords": "welder",
                "exclude_words": "broken, parts",
                "max_bid": 300,
                "zip_code": "67214",
                "distance_radius": 50,
                "closing_soon_hours": 4.0,
                "alert_on_new": True,
                "run_immediately": True,
            },
        )
        assert resp.status_code == 201
        created = resp.json()
        assert created["last_run_result"]["matched"] == 1
        assert created["last_run_result"]["new_alerts"] == 1
        assert created["last_run_result"]["closing_alerts"] == 1
        search_id = created["id"]

        # Verify matched items list & unread stats
        items_resp = client.get("/api/items")
        assert items_resp.status_code == 200
        items = items_resp.json()
        assert len(items) == 1
        item_id = items[0]["id"]
        assert items[0]["is_read"] is False

        stats = client.get("/api/stats").json()
        assert stats["unread_count"] == 1
        assert stats["closing_soon_count"] == 1

        # Watch, mark read, dismiss
        assert client.post(f"/api/items/{item_id}/watch", json={"value": True}).json()["is_watched"] is True
        assert client.post(f"/api/items/{item_id}/read", json={"value": True}).json()["is_read"] is True
        assert client.get("/api/stats").json()["unread_count"] == 0

        # Alerts log should have 2 entries (new_item + closing_soon)
        alerts = client.get("/api/alerts").json()
        assert len(alerts) == 2
        assert {a["alert_type"] for a in alerts} == {"new_item", "closing_soon"}

        # Channel CRUD
        ch = client.post(
            "/api/channels",
            json={"name": "My Discord", "channel_type": "discord", "config": {"webhook_url": "https://example.com"}},
        ).json()
        assert len(client.get("/api/channels").json()) == 1
        assert client.delete(f"/api/channels/{ch['id']}").status_code == 200

        # Delete saved search
        assert client.delete(f"/api/searches/{search_id}").status_code == 200


def test_site_settings_and_search_defaults(monkeypatch, tmp_path):
    db_file = str(tmp_path / "settings_test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_file)

    captured_lot_calls = []
    captured_auction_calls = []

    async def fake_scrape_search_lots(**kwargs):
        captured_lot_calls.append(kwargs)
        return [
            {
                "lot_key": "9001:101",
                "auction_id": "9001",
                "lot_number": "101",
                "title": "DeWalt 20V Impact Driver",
                "url": "https://www.equip-bid.com/auction/9001/item/101",
                "current_bid": 45.0,
            },
            {
                "lot_key": "9001:102",
                "auction_id": "9001",
                "lot_number": "102",
                "title": "DeWalt 20V Impact Driver Damaged Box",
                "url": "https://www.equip-bid.com/auction/9001/item/102",
                "current_bid": 25.0,
            },
        ]

    async def fake_scrape_live_auctions(**kwargs):
        captured_auction_calls.append(kwargs)
        return []

    monkeypatch.setattr("app.scraper.scrape_search_lots", fake_scrape_search_lots)
    monkeypatch.setattr("app.scraper.scrape_live_auctions", fake_scrape_live_auctions)

    with TestClient(app) as client:
        defaults = client.get("/api/settings").json()
        assert defaults["default_zip_code"] == ""
        assert defaults["default_distance_radius"] == -1
        assert defaults["include_shippable_out_of_range"] is True

        updated = client.put(
            "/api/settings",
            json={
                "default_zip_code": " 64108 ",
                "default_distance_radius": 50,
                "global_exclude_words": "damaged",
                "default_check_interval_minutes": 15,
                "default_closing_soon_hours": 6.0,
                "include_shippable_out_of_range": False,
            },
        ).json()
        assert updated["default_zip_code"] == "64108"
        assert updated["default_distance_radius"] == 50
        assert updated["global_exclude_words"] == "damaged"
        assert updated["include_shippable_out_of_range"] is False

        created = client.post(
            "/api/searches",
            json={
                "name": "KC DeWalt",
                "keywords": "dewalt",
                "run_immediately": True,
            },
        ).json()
        assert created["check_interval_minutes"] == 15
        assert created["closing_soon_hours"] == 6.0
        assert created["include_shippable_out_of_range"] is False
        assert created["last_run_result"]["matched"] == 1
        assert captured_lot_calls[-1]["zip_code"] == "64108"
        assert captured_lot_calls[-1]["distance_radius"] == 50
        assert captured_lot_calls[-1]["include_shippable_out_of_range"] is False

        client.get("/api/live-auctions")
        assert captured_auction_calls[-1]["zip_code"] == "64108"
        assert captured_auction_calls[-1]["distance_radius"] == 50
        assert captured_auction_calls[-1]["include_shippable_out_of_range"] is False

        client.get("/api/live-auctions?use_defaults=false&include_shippable_out_of_range=true")
        assert captured_auction_calls[-1]["zip_code"] == ""
        assert captured_auction_calls[-1]["distance_radius"] == -1
        assert captured_auction_calls[-1]["include_shippable_out_of_range"] is True
