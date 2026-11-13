"""Background scheduler and search execution logic."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app import config, database, notifier, scraper

logger = logging.getLogger("equipbid.scheduler")


def _parse_iso_utc(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_duration_short(hours_float: float) -> str:
    total_minutes = max(1, int(hours_float * 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


async def execute_saved_search(
    search_id: int, db_path: Optional[str] = None
) -> dict[str, Any]:
    """Run a single saved search against Equip-Bid, upsert matches, and send alerts."""
    search = database.get_search(search_id, db_path=db_path)
    if not search:
        raise ValueError(f"Saved search {search_id} not found")

    settings = database.get_site_settings(db_path=db_path)
    effective_zip = (search.get("zip_code") or "").strip() or str(
        settings.get("default_zip_code") or ""
    ).strip()
    search_dist = int(search.get("distance_radius", -1))
    effective_distance = (
        search_dist
        if search_dist != -1
        else int(settings.get("default_distance_radius", -1))
    )
    combined_exclude = ", ".join(
        part.strip()
        for part in (search.get("exclude_words", ""), settings.get("global_exclude_words", ""))
        if part and str(part).strip()
    )
    include_shippable = bool(search.get("include_shippable_out_of_range", True))
    effective_search = dict(search)
    effective_search["zip_code"] = effective_zip
    effective_search["distance_radius"] = effective_distance
    effective_search["exclude_words"] = combined_exclude
    effective_search["include_shippable_out_of_range"] = include_shippable

    raw_items = await scraper.scrape_search_lots(
        keywords=search["keywords"],
        zip_code=effective_zip,
        distance_radius=effective_distance,
        min_bid=search.get("min_bid"),
        max_bid=search.get("max_bid"),
        auction_id=search.get("auction_id", ""),
        sort_field=search.get("sort_field", "close"),
        max_pages=int(search.get("max_pages", 2)),
        include_shippable_out_of_range=include_shippable,
    )

    matched = [item for item in raw_items if scraper.filter_lot_item(item, effective_search)]
    now_utc = datetime.now(timezone.utc)
    new_alerts = 0
    closing_alerts = 0

    for lot in matched:
        stored_item, is_new = database.upsert_matched_item(
            lot, search_id=search["id"], db_path=db_path
        )

        # 1) New Match Alert
        if search.get("alert_on_new") and (is_new or not stored_item.get("new_alert_sent")):
            bid = float(stored_item.get("current_bid") or 0.0)
            alert_title = f"[New Match: {search['name']}] {stored_item['title']} — ${bid:,.2f}"
            await notifier.dispatch_alerts(
                alert_type="new_item",
                title=alert_title,
                item=stored_item,
                search=search,
                db_path=db_path,
            )
            database.mark_item_alert_flags(
                stored_item["id"], new_alert_sent=True, db_path=db_path
            )
            new_alerts += 1

        # 2) Closing Soon Alert
        if await _maybe_dispatch_closing_alert(
            stored_item,
            closing_hours=search.get("closing_soon_hours"),
            max_bid=search.get("max_bid"),
            now_utc=now_utc,
            search=search,
            db_path=db_path,
        ):
            closing_alerts += 1

    database.update_search_run_stats(search["id"], match_count=len(matched), db_path=db_path)

    return {
        "search_id": search["id"],
        "search_name": search["name"],
        "total_scraped": len(raw_items),
        "matched": len(matched),
        "new_alerts": new_alerts,
        "closing_alerts": closing_alerts,
    }


def _is_search_due(search: dict[str, Any], now_utc: datetime) -> bool:
    last_run = _parse_iso_utc(search.get("last_run_at"))
    if last_run is None:
        return True
    interval_seconds = max(1, int(search.get("check_interval_minutes", 30))) * 60
    return (now_utc - last_run).total_seconds() >= interval_seconds


async def _maybe_dispatch_closing_alert(
    stored_item: dict[str, Any],
    *,
    closing_hours: Optional[float],
    max_bid: Optional[float],
    now_utc: datetime,
    search: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Send a closing-soon alert if within window and not yet notified."""
    closing_dt = _parse_iso_utc(stored_item.get("closing_at"))
    if (
        closing_hours is None
        or float(closing_hours) <= 0
        or closing_dt is None
        or stored_item.get("closing_soon_alert_sent")
    ):
        return False

    hours_left = (closing_dt - now_utc).total_seconds() / 3600.0
    within_budget = max_bid is None or float(stored_item.get("current_bid") or 0.0) <= float(max_bid)
    if 0 < hours_left <= float(closing_hours) and within_budget:
        bid = float(stored_item.get("current_bid") or 0.0)
        time_left_str = _format_duration_short(hours_left)
        alert_title = f"[Closing Soon ({time_left_str})] {stored_item['title']} — ${bid:,.2f}"
        await notifier.dispatch_alerts(
            alert_type="closing_soon",
            title=alert_title,
            item=stored_item,
            search=search,
            db_path=db_path,
        )
        database.mark_item_alert_flags(
            stored_item["id"],
            closing_soon_alert_sent=True,
            is_read=False,
            db_path=db_path,
        )
        return True
    return False


async def refresh_manual_items(
    db_path: Optional[str] = None, *, force: bool = True
) -> dict[str, int]:
    """Re-scrape manually added items to keep bids, timers, and closing-soon alerts updated."""
    items = database.list_manual_active_items(db_path=db_path)
    if not items:
        return {"refreshed": 0, "closing_alerts": 0}

    settings = database.get_site_settings(db_path=db_path)
    interval_sec = max(1, int(settings.get("default_check_interval_minutes") or 30)) * 60
    closing_hours = settings.get("default_closing_soon_hours")
    now_utc = datetime.now(timezone.utc)
    refreshed = 0
    closing_alerts = 0

    for item in items:
        if not force:
            last_seen = _parse_iso_utc(item.get("last_seen_at"))
            if last_seen is not None and (now_utc - last_seen).total_seconds() < interval_sec:
                continue
        closing_dt = _parse_iso_utc(item.get("closing_at"))
        if closing_dt is not None and closing_dt <= now_utc:
            continue
        try:
            lot = await scraper.scrape_single_lot(item["auction_id"], item["lot_number"])
            stored_item, _ = database.upsert_matched_item(
                lot, search_id=None, db_path=db_path
            )
            refreshed += 1
            if await _maybe_dispatch_closing_alert(
                stored_item,
                closing_hours=closing_hours,
                max_bid=None,
                now_utc=now_utc,
                search=None,
                db_path=db_path,
            ):
                closing_alerts += 1
        except Exception as exc:
            logger.warning("Failed refreshing manual item %s: %s", item.get("lot_key"), exc)
        await asyncio.sleep(0.2)

    return {"refreshed": refreshed, "closing_alerts": closing_alerts}


async def run_due_searches(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Run all enabled searches whose interval has elapsed."""
    now_utc = datetime.now(timezone.utc)
    searches = database.list_searches(enabled_only=True, db_path=db_path)
    results: list[dict[str, Any]] = []
    for search in searches:
        if not _is_search_due(search, now_utc):
            continue
        try:
            res = await execute_saved_search(search["id"], db_path=db_path)
            results.append(res)
        except Exception as exc:
            logger.exception("Failed running search %s (%s): %s", search["id"], search["name"], exc)
        await asyncio.sleep(1.0)
    await refresh_manual_items(db_path=db_path, force=False)
    return results


async def run_all_enabled_searches(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Force-run all enabled saved searches immediately."""
    searches = database.list_searches(enabled_only=True, db_path=db_path)
    results: list[dict[str, Any]] = []
    for search in searches:
        try:
            res = await execute_saved_search(search["id"], db_path=db_path)
            results.append(res)
        except Exception as exc:
            logger.exception("Failed running search %s: %s", search["id"], exc)
            results.append(
                {
                    "search_id": search["id"],
                    "search_name": search["name"],
                    "error": str(exc),
                }
            )
        await asyncio.sleep(0.5)
    await refresh_manual_items(db_path=db_path, force=True)
    return results


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Periodic background scheduler loop."""
    logger.info("Scheduler loop started (tick=%ss)", config.SCHEDULER_TICK_SECONDS)
    while not stop_event.is_set():
        try:
            await run_due_searches()
        except Exception as exc:
            logger.exception("Scheduler tick error: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.SCHEDULER_TICK_SECONDS)
        except asyncio.TimeoutError:
            continue
    logger.info("Scheduler loop stopped")
