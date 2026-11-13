"""FastAPI application for Equip-Bid Auction Search & Alerting."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app import database, notifier, scheduler, scraper
from app.models import (
    ItemFlagUpdate,
    NotificationChannelCreate,
    NotificationChannelUpdate,
    SavedSearchCreate,
    SavedSearchUpdate,
    SiteSettingsUpdate,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#2563eb"/>'
    '<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" '
    'fill="#ffffff" font-family="Arial,sans-serif" font-weight="bold" font-size="28">EB</text>'
    "</svg>"
)


class _NoiseProbeFilter(logging.Filter):
    """Suppress local Razer Wyvrn/Synapse WebSocket probes and paired 403 rejection logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "/wyvrn/Synapse" in msg or "connection rejected (403 Forbidden)" in msg:
            return False
        return True


def _install_log_filters() -> None:
    probe_filter = _NoiseProbeFilter()
    for logger_name in ("uvicorn.access", "uvicorn.error"):
        target_logger = logging.getLogger(logger_name)
        if not any(isinstance(f, _NoiseProbeFilter) for f in target_logger.filters):
            target_logger.addFilter(probe_filter)


_install_log_filters()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_log_filters()
    database.init_db()
    stop_event = asyncio.Event()
    task = asyncio.create_task(scheduler.scheduler_loop(stop_event))
    app.state.scheduler_running = True
    try:
        yield
    finally:
        app.state.scheduler_running = False
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Equip-Bid Auction Search & Monitor",
    description="Automated search and multi-channel alerting for Equip-Bid auctions.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon() -> Response:
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "scheduler_running": bool(getattr(app.state, "scheduler_running", False)),
        "timestamp": database.utc_now_iso(),
    }


@app.get("/api/stats")
async def get_stats() -> dict[str, Any]:
    return database.get_dashboard_stats()


# ---------------------------------------------------------------------------
# Site-Wide Settings API
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return database.get_site_settings()


@app.put("/api/settings")
async def update_settings(payload: SiteSettingsUpdate) -> dict[str, Any]:
    return database.update_site_settings(payload.model_dump(exclude_unset=True))


# ---------------------------------------------------------------------------
# Saved Searches API
# ---------------------------------------------------------------------------

@app.get("/api/searches")
async def list_searches() -> list[dict[str, Any]]:
    return database.list_searches()


@app.post("/api/searches", status_code=201)
async def create_search(payload: SavedSearchCreate) -> dict[str, Any]:
    data = payload.model_dump()
    settings = database.get_site_settings()
    if "check_interval_minutes" not in payload.model_fields_set:
        data["check_interval_minutes"] = int(settings.get("default_check_interval_minutes") or 30)
    if "closing_soon_hours" not in payload.model_fields_set:
        default_closing = settings.get("default_closing_soon_hours")
        data["closing_soon_hours"] = (
            float(default_closing) if default_closing and float(default_closing) > 0 else None
        )
    if "include_shippable_out_of_range" not in payload.model_fields_set:
        data["include_shippable_out_of_range"] = bool(
            settings.get("include_shippable_out_of_range", True)
        )
    run_now = data.pop("run_immediately", False)
    created = database.create_search(data)
    if run_now:
        try:
            run_result = await scheduler.execute_saved_search(created["id"])
            created = database.get_search(created["id"]) or created
            created["last_run_result"] = run_result
        except Exception as exc:
            created["last_run_error"] = str(exc)
    return created


@app.put("/api/searches/{search_id}")
async def update_search(search_id: int, payload: SavedSearchUpdate) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    updated = database.update_search(search_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return updated


@app.delete("/api/searches/{search_id}")
async def delete_search(search_id: int) -> dict[str, bool]:
    deleted = database.delete_search(search_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {"deleted": True}


@app.post("/api/searches/{search_id}/run")
async def run_search_now(search_id: int) -> dict[str, Any]:
    if not database.get_search(search_id):
        raise HTTPException(status_code=404, detail="Saved search not found")
    try:
        return await scheduler.execute_saved_search(search_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Equip-Bid scrape failed: {exc}") from exc


@app.post("/api/searches/run-all")
async def run_all_searches() -> dict[str, Any]:
    results = await scheduler.run_all_enabled_searches()
    return {"runs": results}


# ---------------------------------------------------------------------------
# Matched Items API
# ---------------------------------------------------------------------------

@app.get("/api/items")
async def list_items(
    search_id: Optional[int] = None,
    unread_only: bool = False,
    watched_only: bool = False,
    closing_soon_only: bool = False,
    include_dismissed: bool = False,
    max_bid: Optional[float] = None,
    q: Optional[str] = None,
    sort: str = Query(default="closing_asc"),
) -> list[dict[str, Any]]:
    return database.list_items(
        search_id=search_id,
        unread_only=unread_only,
        watched_only=watched_only,
        closing_soon_only=closing_soon_only,
        include_dismissed=include_dismissed,
        max_bid=max_bid,
        q=q,
        sort=sort,
    )


@app.post("/api/items/{item_id}/read")
async def set_item_read(item_id: int, payload: ItemFlagUpdate) -> dict[str, Any]:
    item = database.set_item_flag(item_id, "is_read", payload.value)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.post("/api/items/mark-all-read")
async def mark_all_read(search_id: Optional[int] = None) -> dict[str, int]:
    updated = database.mark_all_items_read(search_id=search_id)
    return {"updated": updated}


@app.post("/api/items/{item_id}/watch")
async def set_item_watch(item_id: int, payload: ItemFlagUpdate) -> dict[str, Any]:
    item = database.set_item_flag(item_id, "is_watched", payload.value)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.post("/api/items/{item_id}/dismiss")
async def set_item_dismiss(item_id: int, payload: ItemFlagUpdate) -> dict[str, Any]:
    item = database.set_item_flag(item_id, "is_dismissed", payload.value)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


# ---------------------------------------------------------------------------
# Live Equip-Bid Preview Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/live-auctions")
async def get_live_auctions(
    zip_code: str = "",
    distance_radius: int = -1,
    sort_field: str = "end",
    use_defaults: bool = True,
    include_shippable_out_of_range: Optional[bool] = None,
) -> list[dict[str, Any]]:
    settings = database.get_site_settings()
    effective_zip = zip_code.strip()
    effective_distance = distance_radius
    if use_defaults:
        if not effective_zip:
            effective_zip = str(settings.get("default_zip_code") or "").strip()
        if effective_distance == -1:
            effective_distance = int(settings.get("default_distance_radius", -1))
    effective_shippable = (
        include_shippable_out_of_range
        if include_shippable_out_of_range is not None
        else bool(settings.get("include_shippable_out_of_range", True))
    )
    try:
        return await scraper.scrape_live_auctions(
            zip_code=effective_zip,
            distance_radius=effective_distance,
            sort_field=sort_field,
            include_shippable_out_of_range=effective_shippable,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch live auctions: {exc}") from exc


@app.get("/api/live-search")
async def get_live_search(
    keywords: str = Query(..., min_length=1),
    must_include: str = "",
    exclude_words: str = "",
    min_bid: Optional[float] = None,
    max_bid: Optional[float] = None,
    zip_code: str = "",
    distance_radius: int = -1,
    auction_id: str = "",
    sort_field: str = "close",
    max_pages: int = Query(default=1, ge=1, le=5),
    include_shippable_out_of_range: Optional[bool] = None,
) -> list[dict[str, Any]]:
    settings = database.get_site_settings()
    effective_zip = zip_code.strip() or str(settings.get("default_zip_code") or "").strip()
    effective_distance = (
        distance_radius
        if distance_radius != -1
        else int(settings.get("default_distance_radius", -1))
    )
    effective_shippable = (
        include_shippable_out_of_range
        if include_shippable_out_of_range is not None
        else bool(settings.get("include_shippable_out_of_range", True))
    )
    combined_exclude = ", ".join(
        part.strip()
        for part in (exclude_words, str(settings.get("global_exclude_words") or ""))
        if part and part.strip()
    )
    try:
        items = await scraper.scrape_search_lots(
            keywords=keywords,
            zip_code=effective_zip,
            distance_radius=effective_distance,
            min_bid=min_bid,
            max_bid=max_bid,
            auction_id=auction_id,
            sort_field=sort_field,
            max_pages=max_pages,
            include_shippable_out_of_range=effective_shippable,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to search Equip-Bid: {exc}") from exc

    filter_cfg = {
        "must_include": must_include,
        "exclude_words": combined_exclude,
        "min_bid": min_bid,
        "max_bid": max_bid,
    }
    return [item for item in items if scraper.filter_lot_item(item, filter_cfg)]


# ---------------------------------------------------------------------------
# Notification Channels & Alert Logs API
# ---------------------------------------------------------------------------

@app.get("/api/channels")
async def list_channels() -> list[dict[str, Any]]:
    return database.list_channels()


@app.post("/api/channels", status_code=201)
async def create_channel(payload: NotificationChannelCreate) -> dict[str, Any]:
    return database.create_channel(payload.model_dump())


@app.put("/api/channels/{channel_id}")
async def update_channel(
    channel_id: int, payload: NotificationChannelUpdate
) -> dict[str, Any]:
    updated = database.update_channel(channel_id, payload.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    return updated


@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: int) -> dict[str, bool]:
    deleted = database.delete_channel(channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    return {"deleted": True}


@app.post("/api/channels/{channel_id}/test")
async def test_channel(channel_id: int) -> dict[str, Any]:
    channel = database.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Notification channel not found")
    try:
        log = await notifier.send_test_notification(channel)
        return {"ok": True, "log": log}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Test notification failed: {exc}") from exc


@app.get("/api/alerts")
async def list_alerts(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return database.list_alert_logs(limit=limit)
