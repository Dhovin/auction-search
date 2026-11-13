"""Tests for Equip-Bid HTML parsing, datetime parsing, and search filtering."""

from datetime import datetime, timezone

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
