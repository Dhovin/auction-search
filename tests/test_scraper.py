"""Tests for Equip-Bid HTML parsing, datetime parsing, and search filtering."""

from datetime import datetime, timezone

import pytest

from app import scraper

SAMPLE_SEARCH_HTML = """
<div class="lot-list">
  <div class="row">
    <div class="col-xs-10">
      <h4 id="itemTitle11008830" data-auction-title="Brand New Amazon Overstock Truck!">
        <a href="/auction/48446/item/1051">
          <strong>$140 YESWELDER Welding Cart with Lockable Cabinet</strong>
        </a>
      </h4>
    </div>
    <div class="col-xs-2">
      <h4><a href="/auction/48446/item/1051">Lot: 1051</a></h4>
    </div>
  </div>
  <div class="row">
    <div class="col-lg-12">
      <span><small><a href="/auction/48446">Brand New Amazon Overstock Truck!</a> by Agent 86 Auction LLC</small></span>
      <small>Wichita, KS</small> | <small></small>
    </div>
  </div>
  <div class="row">
    <div class="col-xs-12 col-sm-4">
      <a href="/auction/48446/item/1051">
        <img class="auction-img" src="https://cdn.example.com/48446/M_49514118.jpg">
      </a>
    </div>
    <div class="col-xs-12 col-sm-5">
      <div><strong>Current Bid: <span class="pull-right"><span class="lot-current-bid" id="lot_current_bid_lot_equip-bid_48446_11008830">$1,250.50</span></span></strong></div>
      <div>Next Required Bid: <span id="lot_next_required_bid_lot_equip-bid_48446_11008830">$1,275.00</span></div>
      <div><small>High Bidder: <span id="lot_current_high_bidder_list_lot_equip-bid_48446_11008830">#64159</span></small></div>
    </div>
    <div class="col-xs-12 col-sm-3 text-center">
      <div class="auction-listing-timer">
        <div title="-06:00 UTC"><b>Wednesday 11/18/202602:32 pm CST</b></div>
        <span><h3 class="lot-timer" id="lot_timer_lot_equip-bid_48446_11008830">5d 03h 08m</h3></span>
        <i class="bi-truck cross-through" title="No Shipping"></i>
      </div>
    </div>
  </div>
  <div class="row">
    <div class="col-xs-12">
      <small class="categories"><a href="/auction/search?category_ids=2">Commercial &amp; Industrial &gt; Automotive</a></small>
    </div>
  </div>
  <div class="hidden-xs hidden-sm" style="border-top: 1px solid #e2e2e2;"></div>

  <div class="row">
    <div class="col-xs-10">
      <h4 id="itemTitle10992931" data-auction-title="Wichita Midtown Auction">
        <a href="/auction/47997/item/1256">
          <strong>Chicago Welding Stud Welder (Broken)</strong>
        </a>
      </h4>
    </div>
  </div>
  <div class="row">
    <div class="col-lg-12">
      <span><small><a href="/auction/47997">Wichita Midtown Auction</a> by Bam Bam Auction LLC</small></span>
      <small>Kansas City, MO</small>
    </div>
  </div>
  <div class="row">
    <div class="col-xs-12 col-sm-5">
      <span class="lot-current-bid" id="lot_current_bid_lot_equip-bid_47997_10992931">$15.00</span>
    </div>
    <div class="col-xs-12 col-sm-3">
      <div class="auction-listing-timer">
        <span><h3 class="lot-timer" id="lot_timer_lot_equip-bid_47997_10992931">02:15:00</h3></span>
      </div>
    </div>
  </div>
</div>
"""

SAMPLE_AUCTION_LIST_HTML = """
<div class="panel panel-default">
  <div class="panel-body">
    <div class="row">
      <div class="col-xs-6 col-sm-2">
        <img class="img-responsive" src="https://cdn.example.com/logo.jpg" alt="Bam Bam Auction LLC">
        <p><small><strong>Bam Bam Auction LLC</strong></small></p>
      </div>
      <div class="col-xs-6 col-sm-3">
        <div class="auction-listing-timer">
          <p><small><b>Begins Closing Today</b> <span title="-06:00 UTC / CST">11/13/2026 06:15 pm</span></small>
          <b class="text-info">6h 57m 2s</b> <b>Active</b></p>
        </div>
      </div>
      <div class="col-sm-7">
        <div class="auction-title"><a href="/auction/47997">Wichita Midtown Auction</a></div>
        <div><i class="bi-globe-americas"></i> 700 E 17th St N, Wichita, KS 67214</div>
        <div><i class="bi-tag-fill"></i> <a href="/auction/47997">263 Items</a></div>
      </div>
    </div>
    <ul class="lightSlider">
      <li class="lslide"><a href="/auction/47997/item/2"><img class="auction-img" src="/img/2.jpg"></a></li>
    </ul>
  </div>
</div>
"""


def test_parse_lot_search_html_and_concatenated_timestamp():
    now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
    items = scraper.parse_lot_search_html(SAMPLE_SEARCH_HTML, now_utc=now)
    assert len(items) == 2

    first = items[0]
    assert first["lot_key"] == "48446:1051"
    assert first["auction_id"] == "48446"
    assert first["lot_number"] == "1051"
    assert first["internal_lot_id"] == "11008830"
    assert first["title"] == "$140 YESWELDER Welding Cart with Lockable Cabinet"
    assert first["current_bid"] == 1250.50
    assert first["next_required_bid"] == 1275.00
    assert first["high_bidder"] == "#64159"
    assert first["affiliate"] == "Agent 86 Auction LLC"
    assert first["location"] == "Wichita, KS"
    assert first["shipping_info"] == "No Shipping"
    assert first["category"] == "Commercial & Industrial > Automotive"
    assert first["image_url"] == "https://cdn.example.com/48446/M_49514118.jpg"
    # 11/18/2026 02:32 pm -06:00 == 2026-11-18T20:32:00Z
    assert first["closing_at"] == "2026-11-18T20:32:00Z"

    second = items[1]
    assert second["lot_key"] == "47997:1256"
    assert second["current_bid"] == 15.0
    # Fallback relative HH:MM:SS timer: 12:00:00 + 02:15:00 = 14:15:00
    assert second["closing_at"] == "2026-11-13T14:15:00Z"


def test_filter_lot_item():
    item = {
        "title": "Miller MIG 211 Welder with Spool Gun",
        "category": "Metal Fabrication",
        "current_bid": 225.0,
    }
    assert scraper.filter_lot_item(
        item,
        {"must_include": "miller, mig", "exclude_words": "broken, parts", "min_bid": 100, "max_bid": 300},
    )
    assert not scraper.filter_lot_item(item, {"exclude_words": "spool"})
    assert not scraper.filter_lot_item(item, {"must_include": "tig"})
    assert not scraper.filter_lot_item(item, {"max_bid": 200})
    assert not scraper.filter_lot_item(item, {"min_bid": 250})


def test_parse_auction_list_html():
    auctions = scraper.parse_auction_list_html(SAMPLE_AUCTION_LIST_HTML)
    assert len(auctions) == 1
    auc = auctions[0]
    assert auc["auction_id"] == "47997"
    assert auc["title"] == "Wichita Midtown Auction"
    assert auc["affiliate"] == "Bam Bam Auction LLC"
    assert auc["location"] == "700 E 17th St N, Wichita, KS 67214"
    assert auc["item_count_text"] == "263 Items"
    assert auc["countdown"] == "6h 57m 2s"
    assert auc["status"] == "Active"
    # 11/13/2026 06:15 pm -06:00 == 2026-11-14T00:15:00Z
    assert auc["closing_at"] == "2026-11-14T00:15:00Z"
    assert auc["sample_images"] == ["https://www.equip-bid.com/img/2.jpg"]
    assert auc["shipping_info"] == ""


def test_has_shipping_available():
    assert scraper.has_shipping_available("Shipping Available") is True
    assert scraper.has_shipping_available("shipping available") is True
    assert scraper.has_shipping_available("No Shipping") is False
    assert scraper.has_shipping_available("") is False
    assert scraper.has_shipping_available("Shipping Depends Upon Item") is False
    assert scraper.has_shipping_available("Shipping Depends Upon Item", allow_depends=True) is True


@pytest.mark.asyncio
async def test_scrape_search_lots_includes_shippable_out_of_range(monkeypatch):
    in_range_html = """
    <div class="lot-list">
      <div class="row">
        <div class="col-xs-10">
          <h4 id="itemTitle1"><a href="/auction/100/item/1"><strong>Local Tool (Pickup Only)</strong></a></h4>
        </div>
      </div>
      <div class="row">
        <div class="col-xs-12 col-sm-5"><span class="lot-current-bid">$20.00</span></div>
        <div class="col-xs-12 col-sm-3"><div class="auction-listing-timer"><i class="bi-truck cross-through" title="No Shipping"></i></div></div>
      </div>
    </div>
    """
    all_distance_html = """
    <div class="lot-list">
      <div class="row">
        <div class="col-xs-10">
          <h4 id="itemTitle1"><a href="/auction/100/item/1"><strong>Local Tool (Pickup Only)</strong></a></h4>
        </div>
      </div>
      <div class="row">
        <div class="col-xs-12 col-sm-5"><span class="lot-current-bid">$20.00</span></div>
        <div class="col-xs-12 col-sm-3"><div class="auction-listing-timer"><i class="bi-truck cross-through" title="No Shipping"></i></div></div>
      </div>
      <div class="hidden-xs hidden-sm" style="border-top: 1px solid #e2e2e2;"></div>
      <div class="row">
        <div class="col-xs-10">
          <h4 id="itemTitle2"><a href="/auction/200/item/2"><strong>Remote Shippable Drill</strong></a></h4>
        </div>
      </div>
      <div class="row">
        <div class="col-xs-12 col-sm-5"><span class="lot-current-bid">$35.00</span></div>
        <div class="col-xs-12 col-sm-3"><div class="auction-listing-timer"><i class="bi-truck" title="Shipping Available"></i></div></div>
      </div>
      <div class="hidden-xs hidden-sm" style="border-top: 1px solid #e2e2e2;"></div>
      <div class="row">
        <div class="col-xs-10">
          <h4 id="itemTitle3"><a href="/auction/300/item/3"><strong>Remote Local-Only Saw</strong></a></h4>
        </div>
      </div>
      <div class="row">
        <div class="col-xs-12 col-sm-5"><span class="lot-current-bid">$40.00</span></div>
        <div class="col-xs-12 col-sm-3"><div class="auction-listing-timer"><i class="bi-truck cross-through" title="No Shipping"></i></div></div>
      </div>
    </div>
    """

    class FakeResp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeClient:
        calls = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            FakeClient.calls.append(dict(params or {}))
            if str((params or {}).get("distance_radius")) == "50":
                return FakeResp(in_range_html)
            return FakeResp(all_distance_html)

    monkeypatch.setattr("app.scraper.httpx.AsyncClient", FakeClient)

    items = await scraper.scrape_search_lots(
        keywords="tool",
        zip_code="64108",
        distance_radius=50,
        max_pages=1,
        include_shippable_out_of_range=True,
    )
    assert [i["lot_key"] for i in items] == ["100:1", "200:2"]
    assert items[1]["shipping_info"] == "Shipping Available"
    assert items[1]["out_of_range_shippable"] is True
    assert len(FakeClient.calls) == 2

    FakeClient.calls.clear()
    items_local_only = await scraper.scrape_search_lots(
        keywords="tool",
        zip_code="64108",
        distance_radius=50,
        max_pages=1,
        include_shippable_out_of_range=False,
    )
    assert [i["lot_key"] for i in items_local_only] == ["100:1"]
    assert len(FakeClient.calls) == 1


def test_extract_lot_ids_from_url():
    text = """
    https://www.equip-bid.com/auction/48423/item/12963
    https://www.equip-bid.com/auction/48386/item/6003 <- shipping available
    https://www.equip-bid.com/auction/48423/item/12963?foo=bar
    """
    assert scraper.extract_lot_ids_from_url(text) == [
        ("48423", "12963"),
        ("48386", "6003"),
    ]
    assert scraper.extract_lot_ids_from_url("https://www.equip-bid.com/auction/list") == []


def test_parse_single_lot_html():
    html_no_ship = """
    <html>
      <head><title>Lot of Cisco Routers | Equip-Bid</title></head>
      <body>
        <div class="container lot-detail">
          <h3 id="auction_title"><a href="/auction/48423">KC Liquidation (Click to View Lots)</a></h3>
          <h4 id="affiliate_name"><a href="/affiliate-profile/detail/22355">Equip-Bid.com</a></h4>
          <span class="lot-title">Lot of Cisco Routers, APC &amp; CyberPower UPS Units</span>
          <span class="lot-title">Lot #12963</span>
          <span class="lot-guid">Item: bd27-10999351</span>
          <h1 class="lot-timer" id="lot_timer_lot_equip-bid_48423_10999351">2w 4d</h1>
          <span id="lot_scheduled_close">Tue, Dec 1, 2026 7:30pm CST</span>
          <span id="lot_current_high_bidder_detail_lot_equip-bid_48423_10999351">High Bidder: #36359</span>
          <span class="lot-current-bid" id="lot_current_bid_lot_equip-bid_48423_10999351">$21.00</span>
          <span id="lot_next_required_bid_lot_equip-bid_48423_10999351">$22.00</span>
          <div id="lot_description">
            <div id="lot_category"><a>Commercial &amp; Industrial</a> &gt; <a>Office Equipment</a></div>
            <table><tr><td><small>Shipping:</small></td><td><small>No</small></td></tr></table>
            <div id="contact_info"><div class="row"><div class="col-sm-6"><span>15411 Hangar Rd, Kansas City, MO 64147</span></div></div></div>
          </div>
        </div>
        <script>
          Galleria.run('.galleria', {
            dataSource: [{"image":"https:\\/\\/cdn.example.com\\/48423\\/49476253.jpg","thumb":"https:\\/\\/cdn.example.com\\/48423\\/T_49476253.jpg"}]
          });
        </script>
      </body>
    </html>
    """
    lot = scraper.parse_single_lot_html(html_no_ship, "48423", "12963")
    assert lot["lot_key"] == "48423:12963"
    assert lot["internal_lot_id"] == "10999351"
    assert lot["title"] == "Lot of Cisco Routers, APC & CyberPower UPS Units"
    assert lot["auction_title"] == "KC Liquidation"
    assert lot["affiliate"] == "Equip-Bid.com"
    assert lot["location"] == "15411 Hangar Rd, Kansas City, MO 64147"
    assert lot["category"] == "Commercial & Industrial > Office Equipment"
    assert lot["current_bid"] == 21.0
    assert lot["next_required_bid"] == 22.0
    assert lot["high_bidder"] == "#36359"
    assert lot["shipping_info"] == "No Shipping"
    # Dec 1, 2026 7:30pm CST (-06:00) == 2026-12-02T01:30:00Z
    assert lot["closing_at"] == "2026-12-02T01:30:00Z"
    assert lot["image_url"] == "https://cdn.example.com/48423/49476253.jpg"

    html_ship_yes = html_no_ship.replace("<small>No</small>", "<small>Yes</small>").replace(
        "Tue, Dec 1, 2026 7:30pm CST", "Sat, Nov 14, 2026 5:31pm CST"
    )
    lot_ship = scraper.parse_single_lot_html(html_ship_yes, "48386", "6003")
    assert lot_ship["shipping_info"] == "Shipping Available"
    assert lot_ship["closing_at"] == "2026-11-14T23:31:00Z"
