"""Equip-Bid HTML scraper and parser for /auction/search and /auction/list."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app import config

_ITEM_HREF_RE = re.compile(r"/auction/(\d+)/item/(\d+)")
_AUCTION_HREF_RE = re.compile(r"^/auction/(\d+)(?:\?|$)")
_ITEM_TITLE_ID_RE = re.compile(r"^itemTitle(\d+)$")
_LOT_NUM_TITLE_RE = re.compile(r"^Lot\s*#?\s*\d+$", re.IGNORECASE)
_CLOSING_DT_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s*(\d{1,2}:\d{2}\s*[ap]m)", re.IGNORECASE)
_CLOSING_NAMED_DT_RE = re.compile(
    r"([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\s*(\d{1,2}:\d{2})\s*([ap]m)(?:\s*([A-Z]{2,4}))?",
    re.IGNORECASE,
)
_UTC_OFFSET_RE = re.compile(r"([+-]\d{2}):?(\d{2})")
_TZ_ABBR_OFFSETS = {
    "CST": -6,
    "CDT": -5,
    "EST": -5,
    "EDT": -4,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "UTC": 0,
}
_CURRENCY_RE = re.compile(r"[\d,]+(?:\.\d{1,2})?")
_REL_WEEK_RE = re.compile(r"(\d+)\s*w", re.IGNORECASE)
_REL_DAY_RE = re.compile(r"(\d+)\s*d", re.IGNORECASE)
_REL_HOUR_RE = re.compile(r"(\d+)\s*h", re.IGNORECASE)
_REL_MIN_RE = re.compile(r"(\d+)\s*m", re.IGNORECASE)
_REL_SEC_RE = re.compile(r"(\d+)\s*s", re.IGNORECASE)
_REL_HMS_RE = re.compile(r"^\s*(\d{1,2}):(\d{2}):(\d{2})\s*$")


def parse_currency(text: str) -> Optional[float]:
    """Parse a currency string like '$1,250.50' into a float."""
    if not text:
        return None
    match = _CURRENCY_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_utc_offset(title_attr: str) -> timezone:
    """Parse timezone offset from title attribute like '-06:00 UTC' (defaults to -06:00 CST)."""
    if title_attr:
        match = _UTC_OFFSET_RE.search(title_attr)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            if hours < 0:
                minutes = -minutes
            return timezone(timedelta(hours=hours, minutes=minutes))
    return timezone(timedelta(hours=-6))


def parse_relative_timer(timer_text: str, now_utc: Optional[datetime] = None) -> Optional[str]:
    """Convert relative countdown text like '1w 3d', '5d 03h 08m', or '07:04:43' to UTC ISO."""
    if not timer_text:
        return None
    base = now_utc or datetime.now(timezone.utc)
    hms = _REL_HMS_RE.match(timer_text)
    if hms:
        delta = timedelta(
            hours=int(hms.group(1)),
            minutes=int(hms.group(2)),
            seconds=int(hms.group(3)),
        )
        return (base + delta).strftime("%Y-%m-%dT%H:%M:%SZ")

    weeks = int(m.group(1)) if (m := _REL_WEEK_RE.search(timer_text)) else 0
    days = int(m.group(1)) if (m := _REL_DAY_RE.search(timer_text)) else 0
    hours = int(m.group(1)) if (m := _REL_HOUR_RE.search(timer_text)) else 0
    minutes = int(m.group(1)) if (m := _REL_MIN_RE.search(timer_text)) else 0
    seconds = int(m.group(1)) if (m := _REL_SEC_RE.search(timer_text)) else 0
    if any([weeks, days, hours, minutes, seconds]):
        delta = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)
        return (base + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def parse_equipbid_closing_time(
    closing_raw: str,
    tz_title: str = "",
    timer_text: str = "",
    now_utc: Optional[datetime] = None,
) -> Optional[str]:
    """Parse Equip-Bid closing time (numeric or named month date formats)."""
    if closing_raw:
        match = _CLOSING_DT_RE.search(closing_raw)
        if match:
            date_part = match.group(1)
            time_part = re.sub(r"\s+", " ", match.group(2).strip().upper())
            try:
                naive = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %I:%M %p")
                tz = parse_utc_offset(tz_title)
                aware = naive.replace(tzinfo=tz)
                return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass

        named_match = _CLOSING_NAMED_DT_RE.search(closing_raw)
        if named_match:
            date_part = re.sub(r"\s+", " ", named_match.group(1).strip())
            time_part = f"{named_match.group(2)} {named_match.group(3).upper()}"
            abbr = (named_match.group(4) or "").upper()
            for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
                try:
                    naive = datetime.strptime(f"{date_part} {time_part}", fmt)
                    if tz_title and _UTC_OFFSET_RE.search(tz_title):
                        tz = parse_utc_offset(tz_title)
                    elif abbr in _TZ_ABBR_OFFSETS:
                        tz = timezone(timedelta(hours=_TZ_ABBR_OFFSETS[abbr]))
                    else:
                        tz = parse_utc_offset(tz_title)
                    aware = naive.replace(tzinfo=tz)
                    return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    continue
    return parse_relative_timer(timer_text, now_utc=now_utc)


def _abs_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    return urljoin(config.EQUIPBID_BASE_URL + "/", path_or_url.lstrip("/"))


def _collect_lot_block(header_row: Tag) -> list[Tag]:
    """Collect sibling rows belonging to a single lot card until the next divider or lot header."""
    block: list[Tag] = [header_row]
    for sib in header_row.find_next_siblings():
        if not isinstance(sib, Tag):
            continue
        classes = sib.get("class") or []
        style = sib.get("style") or ""
        if "border-top" in style and sib.name == "div":
            break
        if "row" in classes and sib.find("h4", id=_ITEM_TITLE_ID_RE):
            break
        block.append(sib)
    return block


def parse_lot_search_html(html: str, now_utc: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Parse individual lot cards from Equip-Bid /auction/search HTML."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for h4 in soup.find_all("h4", id=_ITEM_TITLE_ID_RE):
        id_match = _ITEM_TITLE_ID_RE.match(h4.get("id", ""))
        internal_lot_id = id_match.group(1) if id_match else ""

        link = h4.find("a", href=_ITEM_HREF_RE)
        if not link:
            continue
        href = link.get("href", "")
        href_match = _ITEM_HREF_RE.search(href)
        if not href_match:
            continue

        auction_id, lot_number = href_match.group(1), href_match.group(2)
        lot_key = f"{auction_id}:{lot_number}"
        if lot_key in seen_keys:
            continue
        seen_keys.add(lot_key)

        title = link.get_text(" ", strip=True)
        auction_title = (h4.get("data-auction-title") or "").strip()
        url = _abs_url(f"/auction/{auction_id}/item/{lot_number}")

        header_row = h4.find_parent("div", class_="row")
        block = _collect_lot_block(header_row) if header_row else [h4]

        # Direct ID lookups where Equip-Bid embeds auction + internal lot ID
        bid_suffix = f"lot_equip-bid_{auction_id}_{internal_lot_id}"
        bid_el = soup.find(id=f"lot_current_bid_{bid_suffix}")
        next_bid_el = soup.find(id=f"lot_next_required_bid_{bid_suffix}")
        high_bidder_el = soup.find(id=f"lot_current_high_bidder_list_{bid_suffix}")
        timer_el = soup.find(id=f"lot_timer_{bid_suffix}")

        image_url = ""
        affiliate = ""
        location = ""
        category = ""
        shipping_info = ""
        closing_time_raw = ""
        tz_title = ""

        for node in block:
            if not bid_el:
                found_bid = node.select_one(".lot-current-bid")
                if found_bid:
                    bid_el = found_bid
            if not timer_el:
                found_timer = node.select_one("h3.lot-timer")
                if found_timer:
                    timer_el = found_timer

            if not image_url:
                img = node.select_one("img.auction-img")
                if img and img.get("src"):
                    image_url = _abs_url(img["src"])

            if not category:
                cat_link = node.select_one("small.categories a")
                if cat_link:
                    category = cat_link.get_text(" ", strip=True)

            if not shipping_info:
                truck = node.select_one("i.bi-truck")
                if truck and truck.get("title"):
                    shipping_info = truck["title"].strip()

            if not closing_time_raw:
                timer_box = node.select_one(".auction-listing-timer")
                if timer_box:
                    dt_div = timer_box.select_one("div[title]")
                    if dt_div:
                        tz_title = dt_div.get("title", "")
                        closing_time_raw = dt_div.get_text(" ", strip=True)

            # Auction title, affiliate, and location row
            if not affiliate or not location:
                col12 = node.select_one(".col-lg-12")
                if col12:
                    auc_link = col12.select_one(f'a[href^="/auction/{auction_id}"]')
                    if auc_link:
                        if not auction_title:
                            auction_title = auc_link.get_text(" ", strip=True)
                        small_parent = auc_link.find_parent("small")
                        if small_parent:
                            full_txt = small_parent.get_text(" ", strip=True)
                            auc_txt = auc_link.get_text(" ", strip=True)
                            remainder = full_txt.replace(auc_txt, "", 1).strip()
                            if remainder.lower().startswith("by "):
                                affiliate = remainder[3:].strip()
                    for sm in col12.find_all("small", recursive=False):
                        if not sm.find("a"):
                            loc_txt = sm.get_text(" ", strip=True)
                            if loc_txt and not loc_txt.startswith("|"):
                                location = loc_txt
                                break

        current_bid = parse_currency(bid_el.get_text(strip=True)) if bid_el else 0.0
        if current_bid is None:
            current_bid = 0.0
        next_required_bid = (
            parse_currency(next_bid_el.get_text(strip=True)) if next_bid_el else None
        )
        high_bidder = high_bidder_el.get_text(" ", strip=True) if high_bidder_el else ""
        time_remaining_raw = timer_el.get_text(" ", strip=True) if timer_el else ""
        closing_at = parse_equipbid_closing_time(
            closing_time_raw,
            tz_title=tz_title,
            timer_text=time_remaining_raw,
            now_utc=now_utc,
        )

        items.append(
            {
                "lot_key": lot_key,
                "auction_id": auction_id,
                "lot_number": lot_number,
                "internal_lot_id": internal_lot_id,
                "title": title,
                "url": url,
                "image_url": image_url,
                "current_bid": current_bid,
                "next_required_bid": next_required_bid,
                "high_bidder": high_bidder,
                "auction_title": auction_title,
                "affiliate": affiliate,
                "location": location,
                "category": category,
                "shipping_info": shipping_info,
                "closing_time_raw": closing_time_raw,
                "closing_at": closing_at,
                "time_remaining_raw": time_remaining_raw,
            }
        )

    return items


def parse_auction_list_html(html: str, now_utc: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Parse live auction cards from Equip-Bid /auction/list HTML."""
    soup = BeautifulSoup(html, "html.parser")
    auctions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for panel in soup.select(".panel.panel-default"):
        title_link = panel.select_one(".auction-title a[href*='/auction/']")
        if not title_link:
            continue
        href = title_link.get("href", "")
        id_match = _AUCTION_HREF_RE.search(href)
        if not id_match:
            continue
        auction_id = id_match.group(1)
        if auction_id in seen_ids:
            continue
        seen_ids.add(auction_id)

        title = title_link.get_text(" ", strip=True)
        url = _abs_url(f"/auction/{auction_id}")

        affiliate_el = panel.select_one(".panel-body p small strong")
        logo_el = panel.select_one(".panel-body img.img-responsive")
        affiliate = (
            affiliate_el.get_text(" ", strip=True)
            if affiliate_el
            else (logo_el.get("alt", "").strip() if logo_el else "")
        )
        logo_url = _abs_url(logo_el["src"]) if logo_el and logo_el.get("src") else ""

        location = ""
        globe_icon = panel.select_one("i.bi-globe-americas")
        if globe_icon and globe_icon.parent:
            location = globe_icon.parent.get_text(" ", strip=True)

        item_count_text = ""
        tag_icon = panel.select_one("i.bi-tag-fill")
        if tag_icon and tag_icon.parent:
            item_count_link = tag_icon.parent.find("a")
            item_count_text = (
                item_count_link.get_text(" ", strip=True)
                if item_count_link
                else tag_icon.parent.get_text(" ", strip=True)
            )

        closing_time_raw = ""
        tz_title = ""
        countdown = ""
        status_text = ""
        timer_box = panel.select_one(".auction-listing-timer")
        if timer_box:
            span = timer_box.select_one("span[title]")
            if span:
                tz_title = span.get("title", "")
                closing_time_raw = span.get_text(" ", strip=True)
            cd_el = timer_box.select_one("b.text-info")
            if cd_el:
                countdown = cd_el.get_text(" ", strip=True)
            for b_tag in timer_box.find_all("b"):
                txt = b_tag.get_text(" ", strip=True)
                if txt in {"Active", "Closing", "Closed", "Upcoming"}:
                    status_text = txt
                    break

        closing_at = parse_equipbid_closing_time(
            closing_time_raw, tz_title=tz_title, timer_text=countdown, now_utc=now_utc
        )

        shipping_info = ""
        truck_icon = panel.select_one("i.bi-truck")
        if truck_icon and truck_icon.get("title"):
            shipping_info = truck_icon["title"].strip()

        sample_images: list[str] = []
        for img in panel.select("ul.light-slider img.auction-img, ul.lightSlider img.auction-img")[:4]:
            src = img.get("src")
            if src:
                sample_images.append(_abs_url(src))

        auctions.append(
            {
                "auction_id": auction_id,
                "title": title,
                "url": url,
                "affiliate": affiliate,
                "logo_url": logo_url,
                "location": location,
                "shipping_info": shipping_info,
                "item_count_text": item_count_text,
                "closing_time_raw": closing_time_raw,
                "closing_at": closing_at,
                "countdown": countdown,
                "status": status_text or "Active",
                "sample_images": sample_images,
            }
        )

    return auctions


def _split_csv_terms(raw: str) -> list[str]:
    return [term.strip().lower() for term in (raw or "").split(",") if term.strip()]


def filter_lot_item(item: dict[str, Any], search_config: dict[str, Any]) -> bool:
    """Apply saved-search local filters (must_include, exclude_words, min_bid, max_bid)."""
    title_lower = (item.get("title") or "").lower()
    searchable = f"{title_lower} {(item.get('category') or '').lower()}"

    must_terms = _split_csv_terms(search_config.get("must_include", ""))
    for term in must_terms:
        if term not in searchable:
            return False

    exclude_terms = _split_csv_terms(search_config.get("exclude_words", ""))
    for term in exclude_terms:
        if term in title_lower:
            return False

    bid = float(item.get("current_bid") or 0.0)
    min_bid = search_config.get("min_bid")
    if min_bid is not None and bid < float(min_bid):
        return False

    max_bid = search_config.get("max_bid")
    if max_bid is not None and bid > float(max_bid):
        return False

    return True


def has_shipping_available(
    shipping_info: Optional[str], *, allow_depends: bool = False
) -> bool:
    """Return True if an item or auction advertises shipping availability."""
    text = (shipping_info or "").strip().lower()
    if not text or "no shipping" in text:
        return False
    if "shipping available" in text:
        return True
    if allow_depends and "shipping depends" in text:
        return True
    return False


def _http_headers() -> dict[str, str]:
    return {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _build_lot_search_params(
    *,
    keywords: str,
    page: int,
    zip_code: str,
    distance_radius: int,
    min_bid: Optional[float],
    max_bid: Optional[float],
    auction_id: str,
    sort_field: str,
) -> dict[str, str]:
    return {
        "lot_list_format": "short",
        "page": str(page),
        "auction_id": auction_id or "",
        "search_phrase_inline": keywords,
        "affiliate_id": "0",
        "distance_radius": str(distance_radius),
        "distance_zip": zip_code or "",
        "min_bid_amount": str(min_bid) if min_bid is not None else "",
        "max_bid_amount": str(max_bid) if max_bid is not None else "",
        "lot_sort_field": sort_field or "close",
        "search": "Search",
    }


async def scrape_search_lots(
    keywords: str,
    zip_code: str = "",
    distance_radius: int = -1,
    min_bid: Optional[float] = None,
    max_bid: Optional[float] = None,
    auction_id: str = "",
    sort_field: str = "close",
    max_pages: int = 2,
    include_shippable_out_of_range: bool = True,
) -> list[dict[str, Any]]:
    """Fetch and parse item search results across 1..max_pages from /auction/search.

    When a ZIP + distance radius is active and ``include_shippable_out_of_range`` is True,
    a second pass queries all distances and merges any out-of-range lots that offer shipping.
    """
    all_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    page_limit = max(1, max_pages)

    async with httpx.AsyncClient(
        headers=_http_headers(),
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        for page in range(1, page_limit + 1):
            params = _build_lot_search_params(
                keywords=keywords,
                page=page,
                zip_code=zip_code,
                distance_radius=distance_radius,
                min_bid=min_bid,
                max_bid=max_bid,
                auction_id=auction_id,
                sort_field=sort_field,
            )
            resp = await client.get(f"{config.EQUIPBID_BASE_URL}/auction/search", params=params)
            resp.raise_for_status()
            page_items = parse_lot_search_html(resp.text)
            if not page_items:
                break
            new_on_page = 0
            for item in page_items:
                if item["lot_key"] not in seen_keys:
                    seen_keys.add(item["lot_key"])
                    all_items.append(item)
                    new_on_page += 1
            if new_on_page == 0 or len(page_items) < 20:
                break

        has_radius_filter = (
            distance_radius > 0
            and bool((zip_code or "").strip())
            and not (auction_id or "").strip()
        )
        if include_shippable_out_of_range and has_radius_filter:
            seen_shippable_pass: set[str] = set()
            for page in range(1, page_limit + 1):
                params = _build_lot_search_params(
                    keywords=keywords,
                    page=page,
                    zip_code="",
                    distance_radius=-1,
                    min_bid=min_bid,
                    max_bid=max_bid,
                    auction_id=auction_id,
                    sort_field=sort_field,
                )
                resp = await client.get(f"{config.EQUIPBID_BASE_URL}/auction/search", params=params)
                resp.raise_for_status()
                page_items = parse_lot_search_html(resp.text)
                if not page_items:
                    break
                new_in_pass = 0
                for item in page_items:
                    lot_key = item["lot_key"]
                    if lot_key not in seen_shippable_pass:
                        seen_shippable_pass.add(lot_key)
                        new_in_pass += 1
                    if lot_key not in seen_keys and has_shipping_available(
                        item.get("shipping_info")
                    ):
                        seen_keys.add(lot_key)
                        item["out_of_range_shippable"] = True
                        all_items.append(item)
                if new_in_pass == 0 or len(page_items) < 20:
                    break

    return all_items


async def _fetch_auction_list_page(
    client: httpx.AsyncClient,
    *,
    zip_code: str,
    distance_radius: int,
    sort_field: str,
) -> list[dict[str, Any]]:
    params = {
        "sort_field": sort_field if sort_field in {"end", "published"} else "end",
        "affiliate": "0",
        "distance_radius": str(distance_radius),
        "distance_zip": zip_code or "",
    }
    resp = await client.get(f"{config.EQUIPBID_BASE_URL}/auction/list", params=params)
    resp.raise_for_status()
    return parse_auction_list_html(resp.text)


def extract_lot_ids_from_url(url_or_text: str) -> list[tuple[str, str]]:
    """Extract deduplicated (auction_id, lot_number) pairs from Equip-Bid item URLs or text."""
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _ITEM_HREF_RE.finditer(url_or_text or ""):
        pair = (match.group(1), match.group(2))
        if pair not in seen:
            seen.add(pair)
            results.append(pair)
    return results


def _extract_galleria_first_image(soup: BeautifulSoup) -> str:
    """Extract primary lot image URL from Galleria initialization script."""
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        body = script.string or script.get_text() or ""
        idx = body.find("dataSource")
        if idx == -1:
            continue
        bracket_pos = body.find("[", idx)
        if bracket_pos == -1:
            continue
        try:
            data, _ = decoder.raw_decode(body, bracket_pos)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                candidate = first.get("image") or first.get("thumb") or ""
                if candidate:
                    return _abs_url(str(candidate))
    return ""


def parse_single_lot_html(
    html: str,
    auction_id: str,
    lot_number: str,
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Parse an individual Equip-Bid lot page (/auction/{id}/item/{lot})."""
    soup = BeautifulSoup(html, "html.parser")
    lot_key = f"{auction_id}:{lot_number}"
    url = _abs_url(f"/auction/{auction_id}/item/{lot_number}")

    title = ""
    for span in soup.select(".lot-detail span.lot-title"):
        txt = span.get_text(" ", strip=True)
        if txt and not _LOT_NUM_TITLE_RE.match(txt):
            title = txt
            break
    if not title and soup.title:
        raw_page_title = soup.title.get_text(" ", strip=True)
        if "|" in raw_page_title:
            title = raw_page_title.split("|", 1)[0].strip()
    if not title:
        raise ValueError(f"Could not locate lot title on page for {lot_key}")

    internal_lot_id = ""
    guid_el = soup.select_one("span.lot-guid")
    if guid_el:
        guid_match = re.search(r"(\d+)$", guid_el.get_text(" ", strip=True))
        if guid_match:
            internal_lot_id = guid_match.group(1)

    bid_el = soup.select_one('span[id^="lot_current_bid_lot_equip-bid_"]')
    if not internal_lot_id and bid_el and bid_el.get("id"):
        id_match = re.search(r"_(\d+)$", bid_el["id"])
        if id_match:
            internal_lot_id = id_match.group(1)

    next_bid_el = soup.select_one('span[id^="lot_next_required_bid_lot_equip-bid_"]')
    high_bidder_el = soup.select_one('span[id^="lot_current_high_bidder_detail_lot_equip-bid_"]')
    timer_el = soup.select_one('h1.lot-timer, [id^="lot_timer_lot_equip-bid_"]')
    close_el = soup.find(id="lot_scheduled_close")

    current_bid = parse_currency(bid_el.get_text(" ", strip=True)) if bid_el else 0.0
    if current_bid is None:
        current_bid = 0.0
    next_required_bid = (
        parse_currency(next_bid_el.get_text(" ", strip=True)) if next_bid_el else None
    )
    high_bidder_raw = high_bidder_el.get_text(" ", strip=True) if high_bidder_el else ""
    high_bidder = re.sub(r"^High Bidder:\s*", "", high_bidder_raw, flags=re.IGNORECASE).strip()

    auction_title_el = soup.select_one("#auction_title a, #auction_title")
    auction_title = auction_title_el.get_text(" ", strip=True) if auction_title_el else ""
    auction_title = re.sub(r"\s*\(Click to View Lots\)\s*$", "", auction_title, flags=re.IGNORECASE).strip()

    affiliate_el = soup.select_one("#affiliate_name a, #affiliate_name")
    affiliate = affiliate_el.get_text(" ", strip=True) if affiliate_el else ""

    location_el = soup.select_one("#contact_info .col-sm-6 span, .lot-detail span.location p, .lot-detail span.location")
    location = location_el.get_text(" ", strip=True) if location_el else ""

    cat_links = [a.get_text(" ", strip=True) for a in soup.select("#lot_category a") if a.get_text(strip=True)]
    category = " > ".join(cat_links)

    shipping_info = ""
    lot_desc = soup.find(id="lot_description")
    if lot_desc:
        for tr in lot_desc.select("table tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and "shipping" in cells[0].lower():
                ans = cells[1].strip().lower()
                if ans == "yes":
                    shipping_info = "Shipping Available"
                elif ans == "no":
                    shipping_info = "No Shipping"
                elif "depend" in ans:
                    shipping_info = "Shipping Depends Upon Item"
                else:
                    shipping_info = cells[1].strip()
                break

    closing_time_raw = close_el.get_text(" ", strip=True) if close_el else ""
    time_remaining_raw = timer_el.get_text(" ", strip=True) if timer_el else ""
    closing_at = parse_equipbid_closing_time(
        closing_time_raw,
        timer_text=time_remaining_raw,
        now_utc=now_utc,
    )
    image_url = _extract_galleria_first_image(soup)

    return {
        "lot_key": lot_key,
        "auction_id": str(auction_id),
        "lot_number": str(lot_number),
        "internal_lot_id": internal_lot_id,
        "title": title,
        "url": url,
        "image_url": image_url,
        "current_bid": current_bid,
        "next_required_bid": next_required_bid,
        "high_bidder": high_bidder,
        "auction_title": auction_title,
        "affiliate": affiliate,
        "location": location,
        "category": category,
        "shipping_info": shipping_info,
        "closing_time_raw": closing_time_raw,
        "closing_at": closing_at,
        "time_remaining_raw": time_remaining_raw,
    }


async def scrape_single_lot(auction_id: str, lot_number: str) -> dict[str, Any]:
    """Fetch and parse a single Equip-Bid item detail page."""
    url = f"{config.EQUIPBID_BASE_URL}/auction/{auction_id}/item/{lot_number}"
    async with httpx.AsyncClient(
        headers=_http_headers(),
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_single_lot_html(resp.text, auction_id=auction_id, lot_number=lot_number)


async def scrape_live_auctions(
    zip_code: str = "",
    distance_radius: int = -1,
    sort_field: str = "end",
    include_shippable_out_of_range: bool = True,
) -> list[dict[str, Any]]:
    """Fetch and parse live auctions from /auction/list, optionally merging shippable out-of-range sales."""
    async with httpx.AsyncClient(
        headers=_http_headers(),
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        auctions = await _fetch_auction_list_page(
            client,
            zip_code=zip_code,
            distance_radius=distance_radius,
            sort_field=sort_field,
        )
        if include_shippable_out_of_range and distance_radius > 0 and bool((zip_code or "").strip()):
            seen_ids = {a["auction_id"] for a in auctions}
            all_auctions = await _fetch_auction_list_page(
                client,
                zip_code="",
                distance_radius=-1,
                sort_field=sort_field,
            )
            for auction in all_auctions:
                if auction["auction_id"] not in seen_ids and has_shipping_available(
                    auction.get("shipping_info"), allow_depends=True
                ):
                    seen_ids.add(auction["auction_id"])
                    auction["out_of_range_shippable"] = True
                    auctions.append(auction)
        return auctions
