# Equip-Bid Auction Search & Monitor

A self-hosted Docker web application for creating automated searches on [Equip-Bid](https://www.equip-bid.com/auction/list) and receiving alerts when matching items appear or are closing soon.

## Features
- **Live Auction Browser (`/auction/list`)**: Filter active Equip-Bid auctions by ZIP code, distance radius, and closing/newest sort order, and launch a lot search inside any auction in one click.
- **Saved Lot Searches (`/auction/search`)**: Configure keyword searches with must-include terms, exclude words, min/max current bid thresholds, ZIP code + distance radius, specific auction ID, check interval, and closing-soon alert thresholds.
- **Live Preview**: Preview matching Equip-Bid lots before saving a search rule.
- **In-App Dashboard**: Unread match badges, closing-soon highlights, watched/favorite tracking, mark read/unread, and dismiss.
- **Multi-Channel Alerting**:
  - In-App Dashboard & Alert History Log
  - Email (SMTP / STARTTLS / SSL)
  - Discord Webhook
  - Slack Webhook
  - Custom JSON Webhook
  - ntfy, Gotify, Pushover, and Telegram Bot

## Quick Start with Docker Compose

```bash
docker compose up -d --build
```

Open `http://localhost:8080` in your browser. Data persists in `./data/auction_search.db`.

## Local Development & Tests

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Run tests:
```bash
pytest -v
```
