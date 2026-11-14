"""Background scheduler and search execution logic."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app import config, database, notifier, scraper

logger = logging.getLogger("equipbid.scheduler")

SEARCH_DELAY_SECONDS: float = 10.0


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
    search_id: int,
    db_path: Optional[str] = None,
    *,
    queue_alerts: bool = False,
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run a single saved search against Equip-Bid, upsert matches, and send/queue alerts."""
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
    now = now_utc or datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries: list[dict[str, Any]] = []
    closing_entries: list[dict[str, Any]] = []
    new_count = 0
    closing_count = 0

    for lot in matched:
        stored_item, is_new = database.upsert_matched_item(
            lot, search_id=search["id"], db_path=db_path
        )

        # 1) New Match Alert
        if search.get("alert_on_new") and (is_new or not stored_item.get("new_alert_sent")):
            bid = float(stored_item.get("current_bid") or 0.0)
            alert_title = f"[New Match: {search['name']}] {stored_item['title']} — ${bid:,.2f}"
            entry = {
                "alert_type": "new_item",
                "title": alert_title,
                "item": stored_item,
                "search": search,
            }
            if queue_alerts:
                database.enqueue_pending_alert(
                    item_id=stored_item["id"],
                    search_id=search["id"],
                    alert_type="new_item",
                    title=alert_title,
                    created_at=now_iso,
                    db_path=db_path,
                )
            else:
                new_entries.append(entry)
            database.mark_item_alert_flags(
                stored_item["id"], new_alert_sent=True, db_path=db_path
            )
            new_count += 1

        # 2) Closing Soon Alert
        closing_entry = _collect_closing_alert(
            stored_item,
            closing_hours=search.get("closing_soon_hours"),
            max_bid=search.get("max_bid"),
            now_utc=now,
            search=search,
            db_path=db_path,
        )
        if closing_entry is not None:
            if queue_alerts:
                database.enqueue_pending_alert(
                    item_id=stored_item["id"],
                    search_id=search["id"],
                    alert_type="closing_soon",
                    title=closing_entry["title"],
                    created_at=now_iso,
                    db_path=db_path,
                )
            else:
                closing_entries.append(closing_entry)
            closing_count += 1

    if not queue_alerts:
        if new_entries:
            await notifier.dispatch_batch_alerts(new_entries, db_path=db_path)
        if closing_entries:
            await notifier.dispatch_batch_alerts(closing_entries, db_path=db_path)

    database.update_search_run_stats(search["id"], match_count=len(matched), db_path=db_path)

    return {
        "search_id": search["id"],
        "search_name": search["name"],
        "total_scraped": len(raw_items),
        "matched": len(matched),
        "new_alerts": new_count,
        "closing_alerts": closing_count,
    }


def _latest_half_hour_slot(now_utc: datetime) -> datetime:
    """Most recent :00 or :30 boundary <= now_utc."""
    minute = 0 if now_utc.minute < 30 else 30
    return now_utc.replace(minute=minute, second=0, microsecond=0)


def _latest_alternate_half_hour_slot(now_utc: datetime) -> datetime:
    """Most recent :15 or :45 boundary <= now_utc."""
    base = now_utc.replace(second=0, microsecond=0)
    if base.minute >= 45:
        return base.replace(minute=45)
    if base.minute >= 15:
        return base.replace(minute=15)
    return (base - timedelta(hours=1)).replace(minute=45)


def _is_search_due(search: dict[str, Any], now_utc: datetime) -> bool:
    last_run = _parse_iso_utc(search.get("last_run_at"))
    if last_run is None:
        return True
    interval_minutes = max(1, int(search.get("check_interval_minutes", 30)))
    if interval_minutes == 30:
        return last_run < _latest_half_hour_slot(now_utc)
    return (now_utc - last_run).total_seconds() >= interval_minutes * 60


def _item_refresh_slot_start(item: dict[str, Any], now_utc: datetime) -> Optional[datetime]:
    """Return the active refresh slot start for a watched/manual item, or None if ended."""
    closing_dt = _parse_iso_utc(item.get("closing_at"))
    if closing_dt is not None and closing_dt <= now_utc:
        return None

    if item.get("is_watched") and closing_dt is not None:
        seconds_left = (closing_dt - now_utc).total_seconds()
        if seconds_left <= 600:
            # Under 10 minutes: update every 1 minute
            return now_utc.replace(second=0, microsecond=0)
        if seconds_left <= 3600:
            # Under 1 hour: update every 5 minutes
            return now_utc.replace(
                minute=(now_utc.minute // 5) * 5, second=0, microsecond=0
            )
        if seconds_left <= 14400:
            # Under 4 hours: update every 15 minutes
            return now_utc.replace(
                minute=(now_utc.minute // 15) * 15, second=0, microsecond=0
            )

    # Normal watched items (>= 4h or unknown closing) & manual items: :15 and :45
    return _latest_alternate_half_hour_slot(now_utc)


def _is_tracked_item_due(item: dict[str, Any], now_utc: datetime) -> bool:
    slot_start = _item_refresh_slot_start(item, now_utc)
    if slot_start is None:
        return False
    last_seen = _parse_iso_utc(item.get("last_seen_at"))
    if last_seen is None:
        return True
    return last_seen < slot_start


def _collect_closing_alert(
    stored_item: dict[str, Any],
    *,
    closing_hours: Optional[float],
    max_bid: Optional[float],
    now_utc: datetime,
    search: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Mark and return a closing-soon alert entry if within window and not yet notified."""
    closing_dt = _parse_iso_utc(stored_item.get("closing_at"))
    if (
        closing_hours is None
        or float(closing_hours) <= 0
        or closing_dt is None
        or stored_item.get("closing_soon_alert_sent")
    ):
        return None

    hours_left = (closing_dt - now_utc).total_seconds() / 3600.0
    within_budget = max_bid is None or float(stored_item.get("current_bid") or 0.0) <= float(max_bid)
    if 0 < hours_left <= float(closing_hours) and within_budget:
        bid = float(stored_item.get("current_bid") or 0.0)
        time_left_str = _format_duration_short(hours_left)
        alert_title = f"[Closing Soon ({time_left_str})] {stored_item['title']} — ${bid:,.2f}"
        database.mark_item_alert_flags(
            stored_item["id"],
            closing_soon_alert_sent=True,
            is_read=False,
            db_path=db_path,
        )
        return {
            "alert_type": "closing_soon",
            "title": alert_title,
            "item": stored_item,
            "search": search,
        }
    return None


async def refresh_tracked_items(
    db_path: Optional[str] = None,
    *,
    force: bool = True,
    now_utc: Optional[datetime] = None,
    queue_alerts: bool = False,
) -> dict[str, int]:
    """Re-scrape watched and manually added items on their tiered schedule."""
    items = database.list_watched_and_manual_active_items(db_path=db_path)
    if not items:
        return {"refreshed": 0, "closing_alerts": 0}

    settings = database.get_site_settings(db_path=db_path)
    default_closing_hours = settings.get("default_closing_soon_hours")
    now = now_utc or datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    search_cache: dict[int, Optional[dict[str, Any]]] = {}
    refreshed = 0
    closing_entries: list[dict[str, Any]] = []

    for item in items:
        closing_dt = _parse_iso_utc(item.get("closing_at"))
        if closing_dt is not None and closing_dt <= now:
            continue
        if not force and not _is_tracked_item_due(item, now):
            continue

        parent_search_id = item.get("search_id")
        parent_search: Optional[dict[str, Any]] = None
        if parent_search_id is not None:
            if parent_search_id not in search_cache:
                search_cache[parent_search_id] = database.get_search(
                    parent_search_id, db_path=db_path
                )
            parent_search = search_cache[parent_search_id]

        closing_hours = (
            parent_search.get("closing_soon_hours")
            if parent_search is not None
            else default_closing_hours
        )
        max_bid = parent_search.get("max_bid") if parent_search is not None else None

        try:
            lot = await scraper.scrape_single_lot(item["auction_id"], item["lot_number"])
            stored_item, _ = database.upsert_matched_item(
                lot, search_id=parent_search_id, db_path=db_path
            )
            refreshed += 1
            closing_entry = _collect_closing_alert(
                stored_item,
                closing_hours=closing_hours,
                max_bid=max_bid,
                now_utc=now,
                search=parent_search,
                db_path=db_path,
            )
            if closing_entry is not None:
                if queue_alerts:
                    database.enqueue_pending_alert(
                        item_id=stored_item["id"],
                        search_id=parent_search_id,
                        alert_type="closing_soon",
                        title=closing_entry["title"],
                        created_at=now_iso,
                        db_path=db_path,
                    )
                closing_entries.append(closing_entry)
        except Exception as exc:
            logger.warning("Failed refreshing tracked item %s: %s", item.get("lot_key"), exc)
        await asyncio.sleep(0.2)

    if not queue_alerts and closing_entries:
        await notifier.dispatch_batch_alerts(closing_entries, db_path=db_path)

    return {"refreshed": refreshed, "closing_alerts": len(closing_entries)}


refresh_manual_items = refresh_tracked_items


async def flush_pending_alerts(
    db_path: Optional[str] = None,
    *,
    force: bool = False,
    now_utc: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Flush pending alerts into one combined notification once the batch window elapses or an item is urgent."""
    pending = database.list_pending_alerts(db_path=db_path)
    if not pending:
        return None

    dismissed_ids = [p["pending_id"] for p in pending if p["item"].get("is_dismissed")]
    active = [p for p in pending if not p["item"].get("is_dismissed")]
    if not active:
        database.delete_pending_alerts(dismissed_ids, db_path=db_path)
        return None

    now = now_utc or datetime.now(timezone.utc)
    settings = database.get_site_settings(db_path=db_path)
    raw_batch = settings.get("alert_batch_minutes")
    batch_minutes = max(0, int(raw_batch if raw_batch is not None else 15))

    should_flush = force or batch_minutes == 0
    if not should_flush:
        oldest_dt = min(_parse_iso_utc(p.get("created_at")) or now for p in active)
        if (now - oldest_dt).total_seconds() >= batch_minutes * 60:
            should_flush = True

    if not should_flush:
        # Never hold alerts past urgency if any queued item is closing within 30 minutes
        for p in active:
            closing_dt = _parse_iso_utc(p["item"].get("closing_at"))
            if closing_dt is not None and (closing_dt - now).total_seconds() <= 1800:
                should_flush = True
                break

    if not should_flush:
        if dismissed_ids:
            database.delete_pending_alerts(dismissed_ids, db_path=db_path)
        return None

    log = await notifier.dispatch_batch_alerts(active, db_path=db_path)
    database.delete_pending_alerts([p["pending_id"] for p in pending], db_path=db_path)
    return log


async def run_due_searches(
    db_path: Optional[str] = None,
    *,
    now_utc: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Run all enabled searches on schedule, refresh watched/manual items, and flush alert batches."""
    now = now_utc or datetime.now(timezone.utc)
    searches = database.list_searches(enabled_only=True, db_path=db_path)
    due_searches = [s for s in searches if _is_search_due(s, now)]
    results: list[dict[str, Any]] = []
    for idx, search in enumerate(due_searches):
        if idx > 0 and SEARCH_DELAY_SECONDS > 0:
            await asyncio.sleep(SEARCH_DELAY_SECONDS)
        try:
            res = await execute_saved_search(
                search["id"], db_path=db_path, queue_alerts=True, now_utc=now
            )
            results.append(res)
        except Exception as exc:
            logger.exception("Failed running search %s (%s): %s", search["id"], search["name"], exc)
    await refresh_tracked_items(
        db_path=db_path, force=False, now_utc=now, queue_alerts=True
    )
    await flush_pending_alerts(db_path=db_path, force=False, now_utc=now)
    return results


async def run_all_enabled_searches(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Force-run all enabled saved searches immediately and send one combined alert digest."""
    searches = database.list_searches(enabled_only=True, db_path=db_path)
    results: list[dict[str, Any]] = []
    for search in searches:
        try:
            res = await execute_saved_search(
                search["id"], db_path=db_path, queue_alerts=True
            )
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
    await refresh_tracked_items(db_path=db_path, force=True, queue_alerts=True)
    await flush_pending_alerts(db_path=db_path, force=True)
    return results


def _seconds_until_next_tick(now_utc: Optional[datetime] = None) -> float:
    """Align 60s ticks cleanly just past each wall-clock minute boundary."""
    tick = float(config.SCHEDULER_TICK_SECONDS)
    if tick < 60.0:
        return max(0.5, tick)
    now = now_utc or datetime.now(timezone.utc)
    wait = (60.0 - now.second) - (now.microsecond / 1_000_000.0) + 0.25
    return max(1.0, min(tick, wait))


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Periodic background scheduler loop."""
    logger.info("Scheduler loop started (tick=%ss)", config.SCHEDULER_TICK_SECONDS)
    while not stop_event.is_set():
        try:
            await run_due_searches()
        except Exception as exc:
            logger.exception("Scheduler tick error: %s", exc)
        try:
            timeout = _seconds_until_next_tick()
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            continue
    logger.info("Scheduler loop stopped")
