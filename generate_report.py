#!/usr/bin/env python3
"""
OSINT Report Generator
Reads template.html + data/latest.json → outputs docs/index.html
Uses Jinja2 for template rendering with injected live data.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

# Paths
PROJECT_DIR = Path(__file__).parent
TEMPLATE_FILE = PROJECT_DIR / "template.html"
DATA_FILE = PROJECT_DIR / "data" / "latest.json"
OUTPUT_FILE = PROJECT_DIR / "docs" / "index.html"
HISTORY_FILE = PROJECT_DIR / "data" / "history.json"

WAR_START = date(2026, 2, 28)


def load_data():
    """Load latest.json and compute derived values."""
    if not DATA_FILE.exists():
        print(f"[ERR] {DATA_FILE} not found. Run fetch_data.py first.")
        sys.exit(1)

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    # Compute war day
    today = date.today()
    data["meta"]["war_day"] = (today - WAR_START).days + 1
    data["meta"]["report_date"] = today.strftime("%Y.%m.%d")

    return data


def build_chart_data(data):
    """Build ECharts-ready data arrays from fetched data."""
    charts = {}

    # Oil prices chart
    markets = data.get("markets", {})
    brent = markets.get("brent", {})
    wti = markets.get("wti", {})

    charts["oil"] = {
        "dates": brent.get("dates", []),
        "brent": brent.get("prices", []),
        "wti": wti.get("prices", []),
        "brent_current": brent.get("current"),
        "wti_current": wti.get("current"),
        "brent_change": brent.get("day_change_pct"),
        "brent_war_change": brent.get("war_change_pct"),
    }

    # Gold chart
    gold = markets.get("gold", {})
    charts["gold"] = {
        "dates": gold.get("dates", []),
        "prices": gold.get("prices", []),
        "current": gold.get("current"),
        "change": gold.get("day_change_pct"),
    }

    # FX
    usd_cny = markets.get("usd_cny", {})
    charts["fx"] = {
        "current": usd_cny.get("current"),
        "change": usd_cny.get("day_change_pct"),
    }

    # A-share stock performance for bar chart
    stocks = data.get("stocks", {})
    stock_names = []
    stock_changes = []
    # Sort by change_pct descending
    sorted_stocks = sorted(
        [(code, info) for code, info in stocks.items() if info.get("change_pct") is not None],
        key=lambda x: x[1]["change_pct"],
        reverse=True,
    )
    for code, info in sorted_stocks[:12]:
        stock_names.append(info["name"])
        stock_changes.append(info["change_pct"])

    charts["ashare"] = {
        "names": stock_names,
        "changes": stock_changes,
    }

    # Shipping / Maritime charts
    shipping = data.get("shipping", {})

    hormuz = shipping.get("hormuz", {})
    charts["hormuz"] = {
        "dates": hormuz.get("dates", []),
        "transits": hormuz.get("transits", []),
    }

    vlcc = shipping.get("vlcc", {})
    charts["vlcc"] = {
        "dates": vlcc.get("dates", []),
        "rates": vlcc.get("rates", []),
    }

    routes = shipping.get("routes", {})
    charts["routes"] = {
        "labels": routes.get("labels", []),
        "pre_war": routes.get("pre_war", []),
        "current": routes.get("current", []),
    }

    return charts


def build_news_html(data):
    """Build news items HTML from fetched RSS data."""
    news = data.get("news", [])
    if not news:
        return '<div class="text-steel text-sm">暂无最新新闻数据</div>'

    items = []
    for n in news[:10]:
        source = n.get("source", "")
        title = n.get("title", "")
        link = n.get("link", "#")
        published = n.get("published", "")
        items.append(
            f'<li class="py-2 border-b border-ghost/30">'
            f'<span class="tag tag-blue text-[10px]">{source}</span> '
            f'<a href="{link}" target="_blank" class="text-white hover:text-neon transition text-sm">{title}</a>'
            f'<span class="text-steel text-xs ml-2">{published[:16]}</span>'
            f"</li>"
        )
    return '<ul class="space-y-0">' + "\n".join(items) + "</ul>"


def generate():
    """Main generation pipeline."""
    print("=" * 60)
    print(f"OSINT Report Generator — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Load data
    print("[1/4] Loading data...")
    data = load_data()
    meta = data["meta"]
    print(f"  War Day: {meta['war_day']}")
    print(f"  Report Date: {meta['report_date']}")

    # Build chart data
    print("[2/4] Building chart data...")
    charts = build_chart_data(data)

    # Build news HTML
    print("[3/4] Building news section...")
    news_html = build_news_html(data)

    # Render template
    print("[4/4] Rendering template...")
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_DIR)),
        autoescape=False,  # HTML template, we control the output
    )
    template = env.get_template("template.html")

    # Prepare context
    markets = data.get("markets", {})
    brent = markets.get("brent", {})
    wti = markets.get("wti", {})
    gold = markets.get("gold", {})
    usd_cny = markets.get("usd_cny", {})

    context = {
        # Meta
        "war_day": meta["war_day"],
        "report_date": meta["report_date"],
        "report_date_cn": meta.get("report_date_cn", meta["report_date"]),
        "generated_at": meta.get("generated_at_cn", ""),
        # Market prices (current)
        "brent_price": brent.get("current", "N/A"),
        "wti_price": wti.get("current", "N/A"),
        "gold_price": gold.get("current", "N/A"),
        "usd_cny_rate": usd_cny.get("current", "N/A"),
        "brent_change": brent.get("day_change_pct", 0),
        "brent_war_change": brent.get("war_change_pct", 0),
        # Chart data as JSON strings for JS injection
        "chart_data_json": json.dumps(charts, ensure_ascii=False),
        # News HTML
        "news_html": news_html,
        # Stock data for tables
        "stocks": data.get("stocks", {}),
        "sectors": data.get("sectors", {}),
        # Raw data for advanced use
        "raw_data_json": json.dumps(data, ensure_ascii=False, default=str),
    }

    html = template.render(**context)

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\nOutput: {OUTPUT_FILE} ({size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    generate()
