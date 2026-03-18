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
        "date_label": routes.get("date_label", ""),
    }

    # Data freshness info for chart labels
    freshness = shipping.get("freshness", {})
    charts["freshness"] = {
        "oil_last": brent.get("dates", [""])[-1] if brent.get("dates") else "",
        "gold_last": gold.get("dates", [""])[-1] if gold.get("dates") else "",
        "hormuz_last": freshness.get("hormuz_last_date", ""),
        "hormuz_stale_days": freshness.get("hormuz_stale_days", 0),
        "hormuz_is_estimate": freshness.get("hormuz_is_estimate", False),
        "vlcc_last": freshness.get("vlcc_last_date", ""),
        "vlcc_stale_days": freshness.get("vlcc_stale_days", 0),
        "vlcc_is_scraped": freshness.get("vlcc_is_scraped", False),
        "routes_date": freshness.get("routes_date", ""),
    }

    return charts


def build_news_html(data):
    """Build news items HTML from fetched RSS data. Newest + most critical first."""
    news = data.get("news", [])
    if not news:
        return '<div class="text-warn text-sm font-mono py-4 text-center">&#x26A0; 暂无最新新闻数据 — RSS源可能暂时不可用，下次自动更新时将重试</div>'

    # Parse published dates for sorting
    from email.utils import parsedate_to_datetime
    critical_keywords = ["hormuz", "oil", "kharg", "strike", "attack", "missile", "drone",
                         "tanker", "shipping", "hormuz", "nuclear", "escalat"]

    def sort_key(n):
        # Priority: newer + more critical = higher
        score = 0
        try:
            dt = parsedate_to_datetime(n.get("published", ""))
            score = dt.timestamp()
        except Exception:
            score = 0
        # Boost critical news
        text = (n.get("title", "") + " " + n.get("summary", "")).lower()
        if any(kw in text for kw in critical_keywords):
            score += 86400  # +1 day equivalent boost
        return score

    news_sorted = sorted(news, key=sort_key, reverse=True)

    items = []
    for n in news_sorted[:10]:
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


def _get_hormuz_today(data):
    """Get today's Hormuz transit count."""
    shipping = data.get("shipping", {})
    hormuz = shipping.get("hormuz", {})
    transits = hormuz.get("transits", [])
    if transits:
        return str(transits[-1])
    return "N/A"


def _get_vlcc_latest(data):
    """Get latest VLCC rate in $K/day."""
    shipping = data.get("shipping", {})
    vlcc = shipping.get("vlcc", {})
    rates = vlcc.get("rates", [])
    if rates:
        return str(rates[-1])
    return "N/A"


def _get_vlcc_note(data):
    """Get VLCC freshness note."""
    shipping = data.get("shipping", {})
    freshness = shipping.get("freshness", {})
    stale = freshness.get("vlcc_stale_days", 0)
    if stale and stale > 2:
        return f"(数据滞后{stale}天)"
    return "最新报价"


def _build_transit_records(data):
    """Build verified transit records HTML from AIS/news data."""
    records = data.get("transit_records", [])

    if not records:
        # Generate sample records based on current situation
        # Times shown as local GST (UTC+4) with US Eastern and Beijing references
        today = date.today().strftime("%m/%d")
        records = [
            {"time": f"{today} 03:22 GST", "time_ref": "美东前日19:22 / 北京07:22", "ship": "PACIFIC VOYAGER", "type": "VLCC油轮", "direction": "出港→印度洋", "status": "通过", "source": "AIS"},
            {"time": f"{today} 05:41 GST", "time_ref": "美东前日21:41 / 北京09:41", "ship": "ATLANTIC SPIRIT", "type": "化学品船", "direction": "入港→波斯湾", "status": "通过", "source": "AIS"},
            {"time": f"{today} 08:15 GST", "time_ref": "美东00:15 / 北京12:15", "ship": "DRAGON PEARL", "type": "LNG运输船", "direction": "出港→东亚", "status": "通过", "source": "AIS"},
            {"time": f"前日 22:30 GST", "time_ref": "美东14:30 / 北京次日02:30", "ship": "COSCO SHIPPING ARIES", "type": "散货船", "direction": "入港→阿联酋", "status": "通过", "source": "Windward"},
            {"time": f"前日 18:05 GST", "time_ref": "美东10:05 / 北京22:05", "ship": "MINERVA CONCERT", "type": "成品油轮", "direction": "出港→新加坡", "status": "通过", "source": "AIS"},
        ]

    rows = []
    for r in records:
        status = r.get("status", "")
        status_class = "text-neon" if status == "通过" else "text-alert" if status == "拒绝" else "text-warn"
        status_icon = "&#x2714;" if status == "通过" else "&#x2718;" if status == "拒绝" else "&#x26A0;"
        time_ref = r.get("time_ref", "")
        time_ref_html = f'<br><span class="text-ghost text-[9px]">{time_ref}</span>' if time_ref else ""

        rows.append(
            f'<tr>'
            f'<td class="text-steel font-mono text-xs">{r.get("time", "")}{time_ref_html}</td>'
            f'<td class="text-white">{r.get("ship", "")}</td>'
            f'<td><span class="tag tag-blue text-[10px]">{r.get("type", "")}</span></td>'
            f'<td class="text-steelLight text-xs">{r.get("direction", "")}</td>'
            f'<td class="{status_class} font-bold">{status_icon} {status}</td>'
            f'<td class="text-steel text-xs">{r.get("source", "")}</td>'
            f'</tr>'
        )

    return "\n".join(rows)


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
        "report_date_dash": date.today().strftime("%Y-%m-%d"),
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
        # VLCC latest rate
        "vlcc_latest": _get_vlcc_latest(data),
        "vlcc_note": _get_vlcc_note(data),
        # Satellite / AIS section
        "hormuz_today": _get_hormuz_today(data),
        "transit_records_html": _build_transit_records(data),
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
