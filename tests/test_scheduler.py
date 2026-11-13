"""Tests for wall-clock aligned saved searches and tiered watched-item refresh schedules."""

from datetime import datetime, timedelta, timezone
import asyncio

from app import config, database, scheduler


def test_saved_search_half_hour_schedule():
    search = {"check_interval_minutes": 30, "last_run_at": "2026-11-13T12:30:05Z"}
    assert scheduler._is_search_due(search, datetime(2026, 11, 13, 12, 45, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_search_due(search, datetime(2026, 11, 13, 12, 59, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_search_due(search, datetime(2026, 11, 13, 13, 0, 0, tzinfo=timezone.utc)) is True

    search["last_run_at"] = "2026-11-13T13:00:12Z"
    assert scheduler._is_search_due(search, datetime(2026, 11, 13, 13, 15, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_search_due(search, datetime(2026, 11, 13, 13, 30, 0, tzinfo=timezone.utc)) is True


def test_tracked_item_alternate_half_hour_and_urgency_tiers():
    now = datetime(2026, 11, 13, 14, 5, 0, tzinfo=timezone.utc)
    # Before :15 of hour 14, latest alternate slot is 13:45
    assert scheduler._latest_alternate_half_hour_slot(now) == datetime(2026, 11, 13, 13, 45, 0, tzinfo=timezone.utc)

    # Normal watched item (>= 4h left): runs at :15 and :45
    watched_far = {
        "is_watched": True,
        "closing_at": "2026-11-13T20:00:00Z",
        "last_seen_at": "2026-11-13T12:45:05Z",
    }
    assert scheduler._is_tracked_item_due(watched_far, datetime(2026, 11, 13, 13, 0, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_tracked_item_due(watched_far, datetime(2026, 11, 13, 13, 15, 0, tzinfo=timezone.utc)) is True

    watched_far["last_seen_at"] = "2026-11-13T13:15:02Z"
    assert scheduler._is_tracked_item_due(watched_far, datetime(2026, 11, 13, 13, 30, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_tracked_item_due(watched_far, datetime(2026, 11, 13, 13, 45, 0, tzinfo=timezone.utc)) is True

    # Under 4 hours remaining -> every 15 minutes (:00, :15, :30, :45)
    watched_4h = {
        "is_watched": True,
        "closing_at": "2026-11-13T16:30:00Z",
        "last_seen_at": "2026-11-13T13:15:02Z",
    }
    assert scheduler._is_tracked_item_due(watched_4h, datetime(2026, 11, 13, 13, 29, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_tracked_item_due(watched_4h, datetime(2026, 11, 13, 13, 30, 0, tzinfo=timezone.utc)) is True

    # Under 1 hour remaining -> every 5 minutes
    watched_1h = {
        "is_watched": True,
        "closing_at": "2026-11-13T14:00:00Z",
        "last_seen_at": "2026-11-13T13:15:02Z",
    }
    assert scheduler._is_tracked_item_due(watched_1h, datetime(2026, 11, 13, 13, 19, 0, tzinfo=timezone.utc)) is False
    assert scheduler._is_tracked_item_due(watched_1h, datetime(2026, 11, 13, 13, 20, 0, tzinfo=timezone.utc)) is True

    # Under 10 minutes remaining -> every 1 minute
    watched_10m = {
        "is_watched": True,
        "closing_at": "2026-11-13T13:25:00Z",
        "last_seen_at": "2026-11-13T13:15:02Z",
    }
    assert scheduler._is_tracked_item_due(watched_10m, datetime(2026, 11, 13, 13, 15, 45, tzinfo=timezone.utc)) is False
    assert scheduler._is_tracked_item_due(watched_10m, datetime(2026, 11, 13, 13, 16, 0, tzinfo=timezone.utc)) is True

    # Unwatched manual item stays on :15 / :45 even under 10 minutes
    manual_unwatched = {
        "is_watched": False,
        "closing_at": "2026-11-13T13:25:00Z",
        "last_seen_at": "2026-11-13T13:15:02Z",
    }
    assert scheduler._is_tracked_item_due(manual_unwatched, datetime(2026, 11, 13, 13, 16, 0, tzinfo=timezone.utc)) is False

    # Already ended item does not refresh
    ended = {
        "is_watched": True,
        "closing_at": "2026-11-13T13:10:00Z",
        "last_seen_at": "2026-11-13T13:00:00Z",
    }
    assert scheduler._is_tracked_item_due(ended, datetime(2026, 11, 13, 13, 15, 0, tzinfo=timezone.utc)) is False


def test_run_due_searches_10s_delay_and_refreshes_watched_items(monkeypatch, tmp_path):
    db_file = str(tmp_path / "sched_test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_file)
    database.init_db(db_file)

    s1 = database.create_search({"name": "Search A", "keywords": "welder", "check_interval_minutes": 30}, db_path=db_file)
    s2 = database.create_search({"name": "Search B", "keywords": "lathe", "check_interval_minutes": 30}, db_path=db_file)

    # Mark both as run at 12:30:05 so they are due at 13:00:00
    with database.get_connection(db_file) as conn:
        conn.execute("UPDATE saved_searches SET last_run_at = '2026-11-13T12:30:05Z'")

    # Add a watched item belonging to s1 (closing in 8m -> 1m tier) and a manual item
    database.upsert_matched_item(
        {
            "lot_key": "5001:10",
            "auction_id": "5001",
            "lot_number": "10",
            "title": "Watched Miller TIG",
            "url": "https://www.equip-bid.com/auction/5001/item/10",
            "current_bid": 100.0,
            "closing_at": "2026-11-13T13:08:00Z",
        },
        search_id=s1["id"],
        is_watched=True,
        db_path=db_file,
    )
    database.upsert_matched_item(
        {
            "lot_key": "5002:20",
            "auction_id": "5002",
            "lot_number": "20",
            "title": "Manual Item",
            "url": "https://www.equip-bid.com/auction/5002/item/20",
            "current_bid": 15.0,
            "closing_at": "2026-11-13T20:00:00Z",
        },
        search_id=None,
        is_watched=False,
        db_path=db_file,
    )
    # Set both items' last_seen_at to 12:46:00 (after 12:45 slot, before 13:00 1m slot)
    with database.get_connection(db_file) as conn:
        conn.execute("UPDATE matched_items SET last_seen_at = '2026-11-13T12:46:00Z'")

    sleep_calls = []
    orig_sleep = asyncio.sleep

    async def fake_sleep(delay):
        sleep_calls.append(delay)
        await orig_sleep(0)

    scraped_searches = []
    scraped_lots = []

    async def fake_scrape_search_lots(**kwargs):
        scraped_searches.append(kwargs["keywords"])
        return []

    async def fake_scrape_single_lot(auction_id, lot_number):
        scraped_lots.append(f"{auction_id}:{lot_number}")
        return {
            "lot_key": f"{auction_id}:{lot_number}",
            "auction_id": auction_id,
            "lot_number": lot_number,
            "title": "Watched Miller TIG",
            "url": f"https://www.equip-bid.com/auction/{auction_id}/item/{lot_number}",
            "current_bid": 125.0,
            "closing_at": "2026-11-13T13:08:00Z",
        }

    monkeypatch.setattr("app.scheduler.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.scraper.scrape_search_lots", fake_scrape_search_lots)
    monkeypatch.setattr("app.scraper.scrape_single_lot", fake_scrape_single_lot)

    now_1300 = datetime(2026, 11, 13, 13, 0, 0, tzinfo=timezone.utc)
    asyncio.run(scheduler.run_due_searches(db_path=db_file, now_utc=now_1300))

    assert set(scraped_searches) == {"welder", "lathe"}
    assert sleep_calls.count(10.0) == 1  # between Search A and Search B
    # At 13:00: watched <10m item refreshed immediately; manual far-out item waits for 13:15
    assert scraped_lots == ["5001:10"]

    # Also test 13:01:00 -> saved searches do NOT run, watched <10m item runs every 1 minute
    scraped_searches.clear()
    scraped_lots.clear()
    with database.get_connection(db_file) as conn:
        conn.execute("UPDATE matched_items SET last_seen_at = '2026-11-13T13:00:05Z' WHERE lot_key = '5001:10'")
    asyncio.run(
        scheduler.run_due_searches(
            db_path=db_file, now_utc=datetime(2026, 11, 13, 13, 1, 0, tzinfo=timezone.utc)
        )
    )
    assert scraped_searches == []
    assert scraped_lots == ["5001:10"]

    # Simulate 13:15:00 with a watched item still active (closes 13:20:00) -> manual + watched both run
    scraped_searches.clear()
    scraped_lots.clear()
    with database.get_connection(db_file) as conn:
        conn.execute(
            "UPDATE matched_items SET closing_at = '2026-11-13T13:20:00Z', last_seen_at = '2026-11-13T13:01:05Z' WHERE lot_key = '5001:10'"
        )
    now_1315 = datetime(2026, 11, 13, 13, 15, 0, tzinfo=timezone.utc)
    asyncio.run(scheduler.run_due_searches(db_path=db_file, now_utc=now_1315))

    assert scraped_searches == []
    assert set(scraped_lots) == {"5001:10", "5002:20"}
