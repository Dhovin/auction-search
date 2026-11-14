"""SQLite persistence layer for saved searches, matched lots, channels, and alert logs."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

from app import config


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with trailing Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Yield a configured SQLite connection that commits on clean exit."""
    target = db_path or config.DATABASE_PATH
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Create database tables and indexes if they do not exist."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                keywords TEXT NOT NULL,
                must_include TEXT NOT NULL DEFAULT '',
                exclude_words TEXT NOT NULL DEFAULT '',
                min_bid REAL NULL,
                max_bid REAL NULL,
                zip_code TEXT NOT NULL DEFAULT '',
                distance_radius INTEGER NOT NULL DEFAULT -1,
                include_shippable_out_of_range INTEGER NOT NULL DEFAULT 1,
                auction_id TEXT NOT NULL DEFAULT '',
                sort_field TEXT NOT NULL DEFAULT 'close',
                max_pages INTEGER NOT NULL DEFAULT 2,
                check_interval_minutes INTEGER NOT NULL DEFAULT 30,
                alert_on_new INTEGER NOT NULL DEFAULT 1,
                closing_soon_hours REAL NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT NULL,
                last_match_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS matched_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_key TEXT NOT NULL UNIQUE,
                search_id INTEGER NULL REFERENCES saved_searches(id) ON DELETE SET NULL,
                auction_id TEXT NOT NULL,
                lot_number TEXT NOT NULL,
                internal_lot_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                current_bid REAL NOT NULL DEFAULT 0.0,
                next_required_bid REAL NULL,
                high_bidder TEXT NOT NULL DEFAULT '',
                auction_title TEXT NOT NULL DEFAULT '',
                affiliate TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                shipping_info TEXT NOT NULL DEFAULT '',
                closing_time_raw TEXT NOT NULL DEFAULT '',
                closing_at TEXT NULL,
                time_remaining_raw TEXT NOT NULL DEFAULT '',
                is_read INTEGER NOT NULL DEFAULT 0,
                is_watched INTEGER NOT NULL DEFAULT 0,
                is_dismissed INTEGER NOT NULL DEFAULT 0,
                new_alert_sent INTEGER NOT NULL DEFAULT 0,
                closing_soon_alert_sent INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_matched_items_search ON matched_items(search_id);
            CREATE INDEX IF NOT EXISTS idx_matched_items_closing ON matched_items(closing_at);

            CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                config_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NULL REFERENCES matched_items(id) ON DELETE SET NULL,
                search_id INTEGER NULL REFERENCES saved_searches(id) ON DELETE SET NULL,
                alert_type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                item_url TEXT NOT NULL DEFAULT '',
                channels_notified TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                error_detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS site_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES matched_items(id) ON DELETE CASCADE,
                search_id INTEGER NULL REFERENCES saved_searches(id) ON DELETE SET NULL,
                alert_type TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pending_alerts_created ON pending_alerts(created_at);
            """
        )
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(saved_searches)").fetchall()
        }
        if "include_shippable_out_of_range" not in cols:
            conn.execute(
                "ALTER TABLE saved_searches ADD COLUMN include_shippable_out_of_range INTEGER NOT NULL DEFAULT 1"
            )


DEFAULT_SITE_SETTINGS: dict[str, Any] = {
    "default_zip_code": "",
    "default_distance_radius": -1,
    "global_exclude_words": "",
    "default_check_interval_minutes": 30,
    "default_closing_soon_hours": 4.0,
    "include_shippable_out_of_range": True,
    "alert_batch_minutes": 15,
}


def _row_to_search(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["alert_on_new"] = bool(d["alert_on_new"])
    d["enabled"] = bool(d["enabled"])
    d["include_shippable_out_of_range"] = bool(d.get("include_shippable_out_of_range", 1))
    return d


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["is_read"] = bool(d["is_read"])
    d["is_watched"] = bool(d["is_watched"])
    d["is_dismissed"] = bool(d["is_dismissed"])
    d["new_alert_sent"] = bool(d["new_alert_sent"])
    d["closing_soon_alert_sent"] = bool(d["closing_soon_alert_sent"])
    return d


def _row_to_channel(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["config"] = json.loads(d.pop("config_json") or "{}")
    except json.JSONDecodeError:
        d["config"] = {}
    d["enabled"] = bool(d["enabled"])
    return d


# ---------------------------------------------------------------------------
# Saved Searches CRUD
# ---------------------------------------------------------------------------

def list_searches(enabled_only: bool = False, db_path: Optional[str] = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        sql = "SELECT * FROM saved_searches"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id DESC"
        rows = conn.execute(sql).fetchall()
        return [_row_to_search(r) for r in rows]


def get_search(search_id: int, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM saved_searches WHERE id = ?", (search_id,)).fetchone()
        return _row_to_search(row) if row else None


def create_search(data: dict[str, Any], db_path: Optional[str] = None) -> dict[str, Any]:
    now = utc_now_iso()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO saved_searches (
                name, keywords, must_include, exclude_words,
                min_bid, max_bid, zip_code, distance_radius, include_shippable_out_of_range,
                auction_id, sort_field, max_pages, check_interval_minutes,
                alert_on_new, closing_soon_hours, enabled, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"].strip(),
                data["keywords"].strip(),
                data.get("must_include", "").strip(),
                data.get("exclude_words", "").strip(),
                data.get("min_bid"),
                data.get("max_bid"),
                data.get("zip_code", "").strip(),
                int(data.get("distance_radius", -1)),
                1 if data.get("include_shippable_out_of_range", True) else 0,
                data.get("auction_id", "").strip(),
                data.get("sort_field", "close"),
                int(data.get("max_pages", 2)),
                int(data.get("check_interval_minutes", 30)),
                1 if data.get("alert_on_new", True) else 0,
                data.get("closing_soon_hours"),
                1 if data.get("enabled", True) else 0,
                now,
            ),
        )
        search_id = cur.lastrowid
        row = conn.execute("SELECT * FROM saved_searches WHERE id = ?", (search_id,)).fetchone()
        return _row_to_search(row)


def update_search(
    search_id: int, updates: dict[str, Any], db_path: Optional[str] = None
) -> Optional[dict[str, Any]]:
    allowed = {
        "name",
        "keywords",
        "must_include",
        "exclude_words",
        "min_bid",
        "max_bid",
        "zip_code",
        "distance_radius",
        "include_shippable_out_of_range",
        "auction_id",
        "sort_field",
        "max_pages",
        "check_interval_minutes",
        "alert_on_new",
        "closing_soon_hours",
        "enabled",
    }
    fields: list[str] = []
    values: list[Any] = []
    for key, val in updates.items():
        if key not in allowed:
            continue
        if key in {"alert_on_new", "enabled", "include_shippable_out_of_range"}:
            val = 1 if val else 0
        elif isinstance(val, str):
            val = val.strip()
        fields.append(f"{key} = ?")
        values.append(val)

    if not fields:
        return get_search(search_id, db_path)

    values.append(search_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"UPDATE saved_searches SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM saved_searches WHERE id = ?", (search_id,)).fetchone()
        return _row_to_search(row)


def update_search_run_stats(
    search_id: int, match_count: int, last_run_at: Optional[str] = None, db_path: Optional[str] = None
) -> None:
    run_ts = last_run_at or utc_now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE saved_searches SET last_run_at = ?, last_match_count = ? WHERE id = ?",
            (run_ts, match_count, search_id),
        )


def delete_search(search_id: int, db_path: Optional[str] = None) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Matched Items CRUD
# ---------------------------------------------------------------------------

def upsert_matched_item(
    item: dict[str, Any],
    search_id: Optional[int],
    db_path: Optional[str] = None,
    is_watched: Optional[bool] = None,
) -> tuple[dict[str, Any], bool]:
    """Insert or update a matched lot. Returns (item_dict, is_new)."""
    now = utc_now_iso()
    lot_key = item["lot_key"]
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM matched_items WHERE lot_key = ?", (lot_key,)
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO matched_items (
                    lot_key, search_id, auction_id, lot_number, internal_lot_id,
                    title, url, image_url, current_bid, next_required_bid,
                    high_bidder, auction_title, affiliate, location, category,
                    shipping_info, closing_time_raw, closing_at, time_remaining_raw,
                    is_read, is_watched, is_dismissed, new_alert_sent,
                    closing_soon_alert_sent, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, 0, 0, ?, ?)
                """,
                (
                    lot_key,
                    search_id,
                    item["auction_id"],
                    item["lot_number"],
                    item.get("internal_lot_id", ""),
                    item["title"],
                    item["url"],
                    item.get("image_url", ""),
                    float(item.get("current_bid", 0.0)),
                    item.get("next_required_bid"),
                    item.get("high_bidder", ""),
                    item.get("auction_title", ""),
                    item.get("affiliate", ""),
                    item.get("location", ""),
                    item.get("category", ""),
                    item.get("shipping_info", ""),
                    item.get("closing_time_raw", ""),
                    item.get("closing_at"),
                    item.get("time_remaining_raw", ""),
                    1 if is_watched else 0,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM matched_items WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return _row_to_item(row), True

        force_watch = 1 if is_watched is True else 0
        conn.execute(
            """
            UPDATE matched_items
            SET search_id = COALESCE(?, search_id),
                internal_lot_id = CASE WHEN ? != '' THEN ? ELSE internal_lot_id END,
                title = ?,
                url = ?,
                image_url = CASE WHEN ? != '' THEN ? ELSE image_url END,
                current_bid = ?,
                next_required_bid = ?,
                high_bidder = ?,
                auction_title = CASE WHEN ? != '' THEN ? ELSE auction_title END,
                affiliate = CASE WHEN ? != '' THEN ? ELSE affiliate END,
                location = CASE WHEN ? != '' THEN ? ELSE location END,
                category = CASE WHEN ? != '' THEN ? ELSE category END,
                shipping_info = CASE WHEN ? != '' THEN ? ELSE shipping_info END,
                closing_time_raw = ?,
                closing_at = COALESCE(?, closing_at),
                time_remaining_raw = ?,
                is_watched = CASE WHEN ? = 1 THEN 1 ELSE is_watched END,
                is_dismissed = CASE WHEN ? = 1 THEN 0 ELSE is_dismissed END,
                last_seen_at = ?
            WHERE id = ?
            """,
            (
                search_id,
                item.get("internal_lot_id", ""),
                item.get("internal_lot_id", ""),
                item["title"],
                item["url"],
                item.get("image_url", ""),
                item.get("image_url", ""),
                float(item.get("current_bid", 0.0)),
                item.get("next_required_bid"),
                item.get("high_bidder", ""),
                item.get("auction_title", ""),
                item.get("auction_title", ""),
                item.get("affiliate", ""),
                item.get("affiliate", ""),
                item.get("location", ""),
                item.get("location", ""),
                item.get("category", ""),
                item.get("category", ""),
                item.get("shipping_info", ""),
                item.get("shipping_info", ""),
                item.get("closing_time_raw", ""),
                item.get("closing_at"),
                item.get("time_remaining_raw", ""),
                force_watch,
                force_watch,
                now,
                existing["id"],
            ),
        )
        row = conn.execute(
            "SELECT * FROM matched_items WHERE id = ?", (existing["id"],)
        ).fetchone()
        return _row_to_item(row), False


def mark_item_alert_flags(
    item_id: int,
    new_alert_sent: Optional[bool] = None,
    closing_soon_alert_sent: Optional[bool] = None,
    is_read: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if new_alert_sent is not None:
        fields.append("new_alert_sent = ?")
        values.append(1 if new_alert_sent else 0)
    if closing_soon_alert_sent is not None:
        fields.append("closing_soon_alert_sent = ?")
        values.append(1 if closing_soon_alert_sent else 0)
    if is_read is not None:
        fields.append("is_read = ?")
        values.append(1 if is_read else 0)
    if not fields:
        return
    values.append(item_id)
    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE matched_items SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )


def list_items(
    search_id: Optional[int] = None,
    unread_only: bool = False,
    watched_only: bool = False,
    closing_soon_only: bool = False,
    include_dismissed: bool = False,
    manual_only: bool = False,
    max_bid: Optional[float] = None,
    q: Optional[str] = None,
    sort: str = "closing_asc",
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []

    if not include_dismissed:
        where.append("m.is_dismissed = 0")
    if manual_only:
        where.append("m.search_id IS NULL")
    elif search_id is not None:
        where.append("m.search_id = ?")
        params.append(search_id)
    if unread_only:
        where.append("m.is_read = 0")
    if watched_only:
        where.append("m.is_watched = 1")
    if max_bid is not None:
        where.append("m.current_bid <= ?")
        params.append(max_bid)
    if closing_soon_only:
        now = datetime.now(timezone.utc)
        horizon = (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        where.append("m.closing_at IS NOT NULL AND m.closing_at >= ? AND m.closing_at <= ?")
        params.extend([now_iso, horizon])
    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(m.title LIKE ? OR m.auction_title LIKE ? OR m.location LIKE ? OR m.category LIKE ?)"
        )
        params.extend([like, like, like, like])

    order_map = {
        "closing_asc": "CASE WHEN m.closing_at IS NULL THEN 1 ELSE 0 END, m.closing_at ASC, m.id DESC",
        "newest": "m.first_seen_at DESC, m.id DESC",
        "bid_asc": "m.current_bid ASC, m.id DESC",
        "bid_desc": "m.current_bid DESC, m.id DESC",
    }
    order_by = order_map.get(sort, order_map["closing_asc"])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
        SELECT m.*, s.name AS search_name
        FROM matched_items m
        LEFT JOIN saved_searches s ON s.id = m.search_id
        {where_sql}
        ORDER BY {order_by}
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_item(r) for r in rows]


def list_manual_active_items(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Return active non-dismissed items that were added manually by URL."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM matched_items WHERE search_id IS NULL AND is_dismissed = 0 ORDER BY id DESC"
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def list_watched_and_manual_active_items(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all active non-dismissed watched or manually tracked items."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT m.*, s.name AS search_name
            FROM matched_items m
            LEFT JOIN saved_searches s ON s.id = m.search_id
            WHERE m.is_dismissed = 0
              AND (m.is_watched = 1 OR m.search_id IS NULL)
            ORDER BY CASE WHEN m.closing_at IS NULL THEN 1 ELSE 0 END, m.closing_at ASC, m.id DESC
            """
        ).fetchall()
        return [_row_to_item(r) for r in rows]


def set_item_flag(
    item_id: int, column: str, value: bool, db_path: Optional[str] = None
) -> Optional[dict[str, Any]]:
    if column not in {"is_read", "is_watched", "is_dismissed"}:
        raise ValueError(f"Unsupported item flag column: {column}")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"UPDATE matched_items SET {column} = ? WHERE id = ?",
            (1 if value else 0, item_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            """
            SELECT m.*, s.name AS search_name
            FROM matched_items m
            LEFT JOIN saved_searches s ON s.id = m.search_id
            WHERE m.id = ?
            """,
            (item_id,),
        ).fetchone()
        return _row_to_item(row)


def mark_all_items_read(
    search_id: Optional[int] = None, db_path: Optional[str] = None
) -> int:
    with get_connection(db_path) as conn:
        if search_id is not None:
            cur = conn.execute(
                "UPDATE matched_items SET is_read = 1 WHERE is_read = 0 AND search_id = ?",
                (search_id,),
            )
        else:
            cur = conn.execute("UPDATE matched_items SET is_read = 1 WHERE is_read = 0")
        return cur.rowcount


# ---------------------------------------------------------------------------
# Notification Channels CRUD
# ---------------------------------------------------------------------------

def list_channels(enabled_only: bool = False, db_path: Optional[str] = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        sql = "SELECT * FROM notification_channels"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id DESC"
        rows = conn.execute(sql).fetchall()
        return [_row_to_channel(r) for r in rows]


def get_channel(channel_id: int, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM notification_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return _row_to_channel(row) if row else None


def create_channel(data: dict[str, Any], db_path: Optional[str] = None) -> dict[str, Any]:
    now = utc_now_iso()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO notification_channels (name, channel_type, config_json, enabled, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["name"].strip(),
                data["channel_type"],
                json.dumps(data.get("config", {})),
                1 if data.get("enabled", True) else 0,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM notification_channels WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_channel(row)


def update_channel(
    channel_id: int, updates: dict[str, Any], db_path: Optional[str] = None
) -> Optional[dict[str, Any]]:
    fields: list[str] = []
    values: list[Any] = []
    if "name" in updates and updates["name"] is not None:
        fields.append("name = ?")
        values.append(updates["name"].strip())
    if "channel_type" in updates and updates["channel_type"] is not None:
        fields.append("channel_type = ?")
        values.append(updates["channel_type"])
    if "config" in updates and updates["config"] is not None:
        fields.append("config_json = ?")
        values.append(json.dumps(updates["config"]))
    if "enabled" in updates and updates["enabled"] is not None:
        fields.append("enabled = ?")
        values.append(1 if updates["enabled"] else 0)

    if not fields:
        return get_channel(channel_id, db_path)

    values.append(channel_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"UPDATE notification_channels SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM notification_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return _row_to_channel(row)


def delete_channel(channel_id: int, db_path: Optional[str] = None) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Alert Logs & Dashboard Stats
# ---------------------------------------------------------------------------

def insert_alert_log(
    item_id: Optional[int],
    search_id: Optional[int],
    alert_type: str,
    title: str,
    message: str,
    item_url: str,
    channels_notified: list[str],
    status: str,
    error_detail: str = "",
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO alert_logs (
                item_id, search_id, alert_type, title, message,
                item_url, channels_notified, status, error_detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                search_id,
                alert_type,
                title,
                message,
                item_url,
                ", ".join(channels_notified),
                status,
                error_detail,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM alert_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_alert_logs(limit: int = 100, db_path: Optional[str] = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT l.*, s.name AS search_name
            FROM alert_logs l
            LEFT JOIN saved_searches s ON s.id = l.search_id
            ORDER BY l.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_dashboard_stats(db_path: Optional[str] = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    soon_iso = (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection(db_path) as conn:
        unread = conn.execute(
            "SELECT COUNT(*) FROM matched_items WHERE is_dismissed = 0 AND is_read = 0"
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM matched_items WHERE is_dismissed = 0"
        ).fetchone()[0]
        watched = conn.execute(
            "SELECT COUNT(*) FROM matched_items WHERE is_dismissed = 0 AND is_watched = 1"
        ).fetchone()[0]
        closing_soon = conn.execute(
            """
            SELECT COUNT(*) FROM matched_items
            WHERE is_dismissed = 0
              AND closing_at IS NOT NULL
              AND closing_at >= ?
              AND closing_at <= ?
            """,
            (now_iso, soon_iso),
        ).fetchone()[0]
        active_searches = conn.execute(
            "SELECT COUNT(*) FROM saved_searches WHERE enabled = 1"
        ).fetchone()[0]
        enabled_channels = conn.execute(
            "SELECT COUNT(*) FROM notification_channels WHERE enabled = 1"
        ).fetchone()[0]
        recent_alerts = conn.execute("SELECT COUNT(*) FROM alert_logs").fetchone()[0]
        return {
            "unread_count": unread,
            "total_matches": total,
            "watched_count": watched,
            "closing_soon_count": closing_soon,
            "active_searches": active_searches,
            "enabled_channels": enabled_channels,
            "recent_alerts_count": recent_alerts,
        }


def get_site_settings(db_path: Optional[str] = None) -> dict[str, Any]:
    """Return site-wide default settings merged with built-in defaults."""
    settings = dict(DEFAULT_SITE_SETTINGS)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT key, value_json FROM site_settings").fetchall()
        for row in rows:
            key = row["key"]
            if key in DEFAULT_SITE_SETTINGS:
                try:
                    settings[key] = json.loads(row["value_json"])
                except json.JSONDecodeError:
                    pass
    return settings


def update_site_settings(
    updates: dict[str, Any], db_path: Optional[str] = None
) -> dict[str, Any]:
    """Persist one or more site-wide settings and return the full updated settings."""
    valid_updates = {k: v for k, v in updates.items() if k in DEFAULT_SITE_SETTINGS}
    if valid_updates:
        with get_connection(db_path) as conn:
            for key, value in valid_updates.items():
                conn.execute(
                    """
                    INSERT INTO site_settings (key, value_json)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                    """,
                    (key, json.dumps(value)),
                )
    return get_site_settings(db_path=db_path)


def enqueue_pending_alert(
    *,
    item_id: int,
    alert_type: str,
    title: str,
    search_id: Optional[int] = None,
    created_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Queue an alert for digest batching without duplicating (item_id, alert_type)."""
    ts = created_at or utc_now_iso()
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM pending_alerts WHERE item_id = ? AND alert_type = ?",
            (item_id, alert_type),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO pending_alerts (item_id, search_id, alert_type, title, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, search_id, alert_type, title, ts),
        )
        return int(cur.lastrowid)


def list_pending_alerts(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Return pending alerts joined with the latest matched_items and saved_searches rows."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                p.id AS pending_id,
                p.alert_type AS pending_alert_type,
                p.title AS pending_title,
                p.created_at AS pending_created_at,
                p.search_id AS pending_search_id,
                m.*,
                s.name AS search_name
            FROM pending_alerts p
            JOIN matched_items m ON m.id = p.item_id
            LEFT JOIN saved_searches s ON s.id = COALESCE(p.search_id, m.search_id)
            ORDER BY p.created_at ASC, p.id ASC
            """
        ).fetchall()
        results: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            pending_id = d.pop("pending_id")
            pending_alert_type = d.pop("pending_alert_type")
            pending_title = d.pop("pending_title")
            pending_created_at = d.pop("pending_created_at")
            pending_search_id = d.pop("pending_search_id")
            d["is_read"] = bool(d["is_read"])
            d["is_watched"] = bool(d["is_watched"])
            d["is_dismissed"] = bool(d["is_dismissed"])
            d["new_alert_sent"] = bool(d["new_alert_sent"])
            d["closing_soon_alert_sent"] = bool(d["closing_soon_alert_sent"])
            results.append(
                {
                    "pending_id": pending_id,
                    "alert_type": pending_alert_type,
                    "title": pending_title,
                    "created_at": pending_created_at,
                    "search_id": pending_search_id,
                    "search": (
                        {"id": pending_search_id, "name": d.get("search_name") or ""}
                        if pending_search_id is not None
                        else None
                    ),
                    "item": d,
                }
            )
        return results


def delete_pending_alerts(pending_ids: list[int], db_path: Optional[str] = None) -> None:
    if not pending_ids:
        return
    placeholders = ", ".join("?" for _ in pending_ids)
    with get_connection(db_path) as conn:
        conn.execute(
            f"DELETE FROM pending_alerts WHERE id IN ({placeholders})",
            tuple(pending_ids),
        )
