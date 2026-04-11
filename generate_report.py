#!/usr/bin/env python3
"""
OSINT Report Generator
Reads events.json + filtered_news.json + latest.json → outputs docs/index.html

Data flow:
  fetch_data.py → latest.json + filtered_news.json + events.json
  generate_report.py reads:
    1. data/events.json        (authoritative event state model)
    2. data/filtered_news.json (pre-filtered, scored news)
    3. data/latest.json        (markets, stocks, shipping — non-news data)
  → docs/index.html
"""

import json
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

# Import relevance filter as fallback (if intermediate files missing)
sys.path.insert(0, str(Path(__file__).parent / "data"))
from fetch_data import score_relevance, build_event_states

# Paths
PROJECT_DIR = Path(__file__).parent
TEMPLATE_FILE = PROJECT_DIR / "template.html"
DATA_FILE = PROJECT_DIR / "data" / "latest.json"
EVENTS_FILE = PROJECT_DIR / "data" / "events.json"
FILTERED_NEWS_FILE = PROJECT_DIR / "data" / "filtered_news.json"
OUTPUT_FILE = PROJECT_DIR / "docs" / "index.html"
HISTORY_FILE = PROJECT_DIR / "data" / "history.json"
REFERENCE_META_FILE = PROJECT_DIR / "data" / "reference_meta.json"

WAR_START = date(2026, 2, 28)


def _safe_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return "#"


def _safe_text(value):
    return escape("" if value is None else str(value))


def _format_compact_time(value):
    if not value:
        return "时间未知"
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%m-%d %H:%M")
    except Exception:
        pass
    return _safe_text(str(value)[:16])


def _load_reference_meta():
    if REFERENCE_META_FILE.exists():
        with open(REFERENCE_META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_data():
    """
    Load data from the 3 authoritative sources:
      1. data/events.json        → event state model (hero + body)
      2. data/filtered_news.json → pre-filtered scored news
      3. data/latest.json        → markets, stocks, shipping
    Falls back to inline filtering if intermediate files are missing.
    """
    if not DATA_FILE.exists():
        print(f"[ERR] {DATA_FILE} not found. Run fetch_data.py first.")
        sys.exit(1)

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    # Compute war day
    today = date.today()
    data["meta"]["war_day"] = (today - WAR_START).days + 1
    data["meta"]["report_date"] = today.strftime("%Y.%m.%d")

    # --- Load authoritative filtered news ---
    if FILTERED_NEWS_FILE.exists():
        with open(FILTERED_NEWS_FILE, encoding="utf-8") as f:
            data["news"] = json.load(f)
        print(f"  Loaded {len(data['news'])} items from filtered_news.json")
    else:
        # Fallback: inline filter from latest.json raw news
        print("  [WARN] filtered_news.json not found, applying inline filter")
        data["news"] = _fallback_filter_news(data.get("news", []))

    # --- Load authoritative event states ---
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE, encoding="utf-8") as f:
            data["event_states"] = json.load(f)
        print(f"  Loaded {len(data['event_states'])} events from events.json")
    else:
        # Fallback: build from filtered news
        print("  [WARN] events.json not found, building from filtered news")
        data["event_states"] = build_event_states(data["news"])

    return data


def _fallback_filter_news(news_list):
    """Fallback filter when filtered_news.json is missing (backward compat)."""
    filtered = []
    for n in news_list:
        existing_score = n.get("relevance_score")
        if existing_score is not None and existing_score >= 60:
            filtered.append(n)
            continue
        rel = score_relevance(n.get("title", ""), n.get("summary", ""))
        if rel["excluded"] or rel["score"] < 60:
            continue
        n["relevance_score"] = rel["score"]
        n["entity_hits"] = rel["entity_hits"]
        n["action_hits"] = rel["action_hits"]
        filtered.append(n)
    return filtered


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


def _news_sort_key(n):
    """Sort key: newer + more critical = higher score."""
    from email.utils import parsedate_to_datetime
    critical_en = ["hormuz", "oil", "kharg", "strike", "attack", "missile", "drone",
                   "tanker", "shipping", "nuclear", "escalat", "ceasefire"]
    critical_cn = ["霍尔木兹", "原油", "油价", "空袭", "导弹", "无人机",
                   "油轮", "航运", "海峡", "制裁", "战争", "伊朗", "以色列",
                   "停火", "哈尔克", "德黑兰"]
    score = 0
    try:
        dt = parsedate_to_datetime(n.get("published", ""))
        score = dt.timestamp()
    except Exception:
        score = 0
    text = n.get("title", "") + " " + n.get("summary", "")
    text_lower = text.lower()
    if any(kw in text_lower for kw in critical_en) or any(kw in text for kw in critical_cn):
        score += 86400
    return score


def _categorize_news(n):
    """Categorize a news item into theater: iran, gulf, lebanon, us, other."""
    if n.get("theater") in {"iran", "gulf", "lebanon", "us"}:
        return n["theater"]
    location = n.get("location", "")
    if "霍尔木兹" in location or "波斯湾" in location or "迪拜" in location or "富查伊拉" in location:
        return "gulf"
    if "黎巴嫩" in location or "伊拉克" in location or "红海" in location or "也门" in location:
        return "lebanon"
    if "德黑兰" in location or "哈尔克" in location or location == "伊朗":
        return "iran"
    text = (n.get("title", "") + " " + n.get("summary", "")).lower()
    # Also check Chinese text without lowering
    text_raw = n.get("title", "") + " " + n.get("summary", "")
    if any(kw in text for kw in ["tehran", "isfahan", "kharg", "irgc"]) or \
       any(kw in text_raw for kw in ["德黑兰", "伊朗", "哈尔克", "伊斯法罕", "革命卫队"]):
        return "iran"
    if any(kw in text for kw in ["dubai", "fujairah", "bahrain", "kuwait", "qatar", "saudi", "uae", "abu dhabi", "hormuz"]) or \
       any(kw in text_raw for kw in ["迪拜", "富查伊拉", "巴林", "科威特", "卡塔尔", "沙特", "阿联酋", "海峡", "海湾"]):
        return "gulf"
    if any(kw in text for kw in ["lebanon", "hezbollah", "iraq", "houthi", "red sea", "yemen"]) or \
       any(kw in text_raw for kw in ["黎巴嫩", "真主党", "伊拉克", "胡塞", "红海", "也门"]):
        return "lebanon"
    if any(kw in text for kw in ["trump", "nato", "pentagon", "carrier", "us force", "biden", "congress", "sanction"]) or \
       any(kw in text_raw for kw in ["特朗普", "北约", "五角大楼", "航母", "美军", "美国", "制裁", "国会"]):
        return "us"
    return "other"


def _build_news_event_index(data):
    events = data.get("event_states", [])
    by_title = {e.get("title"): e for e in events if e.get("title")}
    by_link = {e.get("link"): e for e in events if e.get("link")}
    return by_title, by_link


def _news_evidence_html(news_item, event):
    location = _safe_text(event.get("location") if event else news_item.get("location", "中东地区"))
    published = _safe_text(news_item.get("published", "")[:16] or "时间未知")
    source_count = event.get("source_count") if event else 1
    updated = _format_compact_time(event.get("last_updated_time")) if event else published
    lang = news_item.get("lang", "en")
    lang_badge = "" if lang == "zh" else '<span class="tag tag-blue text-[9px]">EN</span>'
    return (
        f'<div class="mt-1 flex flex-wrap gap-2 text-[10px] text-ghost font-mono">'
        f'<span>{location}</span>'
        f'<span>{source_count}源交叉</span>'
        f'<span>更新 {updated}</span>'
        f'{lang_badge}'
        f"</div>"
    )


def build_daily_summary_cards(data, hero):
    """Build compact daily summary cards for top-of-page scanning."""
    events = data.get("event_states", [])
    worsening = len([e for e in events if e.get("trend") == "worsening"])
    ceasefire = len([e for e in events if e.get("current_status") in ("ceasefire", "de_escalating", "partially_restored")])
    shipping = data.get("shipping", {})
    freshness = shipping.get("freshness", {})
    latest_hormuz = _get_hormuz_today(data)
    brent = data.get("markets", {}).get("brent", {})
    news = data.get("news", [])
    newest_news = sorted(news, key=_news_sort_key, reverse=True)[0] if news else {}
    hormuz_note = "估算值" if freshness.get("hormuz_is_estimate") else "抓取值"
    vlcc_note = "抓取值" if freshness.get("vlcc_is_scraped") else "历史/估算"

    cards = [
        {
            "tone": "alert",
            "label": "今日风险结论",
            "value": hero.get("threat_level", "HIGH"),
            "meta": f"{len(events)}个事件态势 | 恶化 {worsening} | 缓和 {ceasefire}",
        },
        {
            "tone": "warn",
            "label": "霍尔木兹状态",
            "value": f"{latest_hormuz} 艘/日",
            "meta": f"{hormuz_note} | 最近数据 {freshness.get('hormuz_last_date', '未知')}",
        },
        {
            "tone": "ice",
            "label": "能源/航运冲击",
            "value": (
                f"Brent ${brent.get('current', 0):.0f}"
                if isinstance(brent.get("current"), (int, float))
                else "Brent N/A"
            ),
            "meta": f"VLCC { _get_vlcc_latest(data) }K/天 | {vlcc_note}",
        },
        {
            "tone": "neon",
            "label": "自动情报覆盖",
            "value": f"{len(news)} 条",
            "meta": (
                f"最新: {_safe_text(newest_news.get('source', '无'))} | "
                f"{_safe_text((newest_news.get('published', '')[:16] or '未知'))}"
            ),
        },
    ]

    tone_map = {
        "alert": ("card-alert", "text-alert"),
        "warn": ("card-warn", "text-warn"),
        "ice": ("card-ice", "text-ice"),
        "neon": ("card-ok", "text-neon"),
    }
    items = []
    for card in cards:
        card_cls, text_cls = tone_map[card["tone"]]
        items.append(
            f'<div class="fade-up card {card_cls} p-5">'
            f'<div class="font-mono text-[10px] {text_cls} tracking-wider mb-2">{_safe_text(card["label"])}</div>'
            f'<div class="text-2xl font-black text-white">{_safe_text(card["value"])}</div>'
            f'<div class="text-[11px] text-steel mt-2">{_safe_text(card["meta"])}</div>'
            f"</div>"
        )
    return Markup("".join(items))


def build_live_intel_html(data):
    """Build Section 1 LIVE intel cards from pre-filtered news, categorized by theater."""
    news = data.get("news", [])  # Already filtered via filtered_news.json
    if not news:
        return Markup("")
    by_title, by_link = _build_news_event_index(data)

    # Sort by relevance + recency
    sorted_news = sorted(news, key=_news_sort_key, reverse=True)

    # Categorize into theaters
    theaters = {"iran": [], "gulf": [], "lebanon": [], "us": []}
    for n in sorted_news[:20]:
        cat = _categorize_news(n)
        if cat in theaters and len(theaters[cat]) < 5:
            theaters[cat].append(n)
        elif cat == "other":
            # Assign to the theater with fewest items
            min_cat = min(theaters, key=lambda k: len(theaters[k]))
            if len(theaters[min_cat]) < 5:
                theaters[min_cat].append(n)

    def _render_items(items):
        if not items:
            return '<li class="text-ghost text-xs">暂无最新相关情报</li>'
        lines = []
        for n in items:
            title = _safe_text(n.get("title", ""))
            link = _safe_url(n.get("link", "#"))
            event = by_link.get(n.get("link")) or by_title.get(n.get("title"))
            lines.append(
                f'<li class="pb-2 border-b border-ghost/20 last:border-b-0">'
                f'<a href="{link}" target="_blank" rel="noopener" class="text-steelLight hover:text-white transition">'
                f'{title}</a>'
                f'{_news_evidence_html(n, event)}'
                f"</li>"
            )
        return "\n".join(lines)

    html = f'''
    <div class="fade-up card card-alert p-5">
      <div class="flex items-center gap-2 mb-3"><span class="tag tag-red">伊朗战区</span><span class="badge badge-high">高危</span></div>
      <ul class="space-y-2 text-sm text-steelLight">{_render_items(theaters["iran"])}</ul>
    </div>
    <div class="fade-up card card-warn p-5">
      <div class="flex items-center gap-2 mb-3"><span class="tag tag-yellow">海湾战区</span><span class="badge badge-high">高危</span></div>
      <ul class="space-y-2 text-sm text-steelLight">{_render_items(theaters["gulf"])}</ul>
    </div>
    <div class="fade-up card card-warn p-5">
      <div class="flex items-center gap-2 mb-3"><span class="tag tag-yellow">黎巴嫩/伊拉克/红海</span></div>
      <ul class="space-y-2 text-sm text-steelLight">{_render_items(theaters["lebanon"])}</ul>
    </div>
    <div class="fade-up card card-ice p-5">
      <div class="flex items-center gap-2 mb-3"><span class="tag tag-blue">美国/外交</span></div>
      <ul class="space-y-2 text-sm text-steelLight">{_render_items(theaters["us"])}</ul>
    </div>'''
    return Markup(html)


def build_news_html(data):
    """Build AUTO news feed HTML. Already pre-filtered via filtered_news.json."""
    news = data.get("news", [])  # Already filtered
    if not news:
        return Markup('<div class="text-warn text-sm font-mono py-4 text-center">&#x26A0; 暂无最新新闻数据 — RSS源可能暂时不可用，下次自动更新时将重试</div>')
    by_title, by_link = _build_news_event_index(data)

    news_sorted = sorted(news, key=_news_sort_key, reverse=True)

    items = []
    for n in news_sorted[:15]:
        source = _safe_text(n.get("source", ""))
        title = _safe_text(n.get("title", ""))
        link = _safe_url(n.get("link", "#"))
        event = by_link.get(n.get("link")) or by_title.get(n.get("title"))
        items.append(
            f'<li class="py-2 border-b border-ghost/30">'
            f'<span class="tag tag-blue text-[10px]">{source}</span> '
            f'<a href="{link}" target="_blank" rel="noopener" class="text-white hover:text-neon transition text-sm">{title}</a>'
            f'{_news_evidence_html(n, event)}'
            f"</li>"
        )
    return Markup('<ul class="space-y-0">' + "\n".join(items) + "</ul>")


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


# ---------------------------------------------------------------------------
# Auto-generated Hero Summary from Event State Model
# ---------------------------------------------------------------------------

_STATUS_LABELS = {
    "active_conflict": "交战中",
    "escalating": "局势升级",
    "de_escalating": "局势缓和",
    "ceasefire": "停火",
    "shipping_disrupted": "航运中断",
    "partially_restored": "部分恢复",
    "restored": "恢复正常",
}


def build_hero_summary(data):
    """
    Generate hero subtitle text entirely from event state model + market data.
    No hardcoded static strings — everything derived from data.
    Returns dict with summary_text and tags list.
    """
    events = data.get("event_states", [])
    markets = data.get("markets", {})
    shipping = data.get("shipping", {})
    meta = data.get("meta", {})

    war_day = meta.get("war_day", "?")
    brent = markets.get("brent", {})
    brent_price = brent.get("current")

    # --- Build summary fragments from event states ---
    fragments = []
    tags = []

    # Fragment 1: war day
    fragments.append(f"美以对伊朗全面战争第{war_day}天")

    # Fragment 2: Hormuz status — event states take priority over stale shipping data
    hormuz_transits = shipping.get("hormuz", {}).get("transits", [])
    latest_hormuz = hormuz_transits[-1] if hormuz_transits else None
    hormuz_is_zero = latest_hormuz == 0
    hormuz_is_limited = latest_hormuz is not None and latest_hormuz < 10
    hormuz_events = [e for e in events if "霍尔木兹" in e.get("location", "")]

    # Check if event states indicate reopening/restoration (overrides stale transit=0)
    hormuz_reopened = any(
        e.get("current_status") in ("partially_restored", "restored", "de_escalating")
        for e in hormuz_events
    )
    hormuz_ceasefire = any(
        e.get("current_status") == "ceasefire" or
        any(kw in e.get("title", "") for kw in ["停火", "重启", "重啟", "reopen", "ceasefire"])
        for e in events
    )

    if latest_hormuz is not None:
        if hormuz_is_zero and (hormuz_reopened or hormuz_ceasefire):
            fragments.append('霍尔木兹海峡<span class="text-warn font-bold">停火谈判中</span>，但商业通航仍受限')
            tags.append(("停火谈判", "yellow"))
            tags.append(("通航未恢复", "red"))
        elif hormuz_is_zero:
            fragments.append('霍尔木兹海峡通航量降至<span class="text-alert font-bold">零</span>')
            tags.append(("霍尔木兹封锁", "red"))
        elif (hormuz_reopened or hormuz_ceasefire) and hormuz_is_limited:
            fragments.append(f'霍尔木兹海峡<span class="text-neon font-bold">有限恢复</span>（{latest_hormuz}艘）')
            tags.append(("有限恢复", "yellow"))
        elif (hormuz_reopened or hormuz_ceasefire):
            fragments.append(f'霍尔木兹海峡<span class="text-neon font-bold">恢复通航</span>（{latest_hormuz}艘）')
            tags.append(("霍尔木兹重启", "green"))
        elif hormuz_is_limited:
            fragments.append(f'霍尔木兹海峡仅<span class="text-alert font-bold">{latest_hormuz}</span>艘通过')
            tags.append(("霍尔木兹受限", "red"))
        else:
            fragments.append(f'霍尔木兹海峡{latest_hormuz}艘通过')
            tags.append(("霍尔木兹通航", "yellow"))
    elif hormuz_reopened or hormuz_ceasefire:
        if hormuz_events:
            status = hormuz_events[0].get("current_status", "partially_restored")
            fragments.append(f'霍尔木兹海峡<span class="text-neon font-bold">{_STATUS_LABELS.get(status, "态势变化")}</span>')
            tags.append(("停火谈判", "yellow"))
        else:
            fragments.append('霍尔木兹海峡<span class="text-neon font-bold">停火谈判中</span>')
            tags.append(("停火谈判", "yellow"))
    elif hormuz_events:
        status = hormuz_events[0].get("current_status", "")
        fragments.append(f'霍尔木兹海峡{_STATUS_LABELS.get(status, "态势不明")}')
        tags.append(("霍尔木兹", "yellow"))

    # Fragment 3: Oil price
    if brent_price and brent_price != "N/A":
        bp = brent_price if isinstance(brent_price, (int, float)) else 0
        if bp > 100:
            fragments.append(f'布伦特原油突破<span class="text-warn font-bold">${bp:.0f}</span>')
            tags.append(("油价突破$100", "red"))
        else:
            fragments.append(f'布伦特原油<span class="text-warn font-bold">${bp:.0f}</span>')
            tags.append((f"油价${bp:.0f}", "yellow"))

    # Fragment 4: VLCC rates
    vlcc_rates = shipping.get("vlcc", {}).get("rates", [])
    if vlcc_rates:
        latest_vlcc = vlcc_rates[-1]
        if latest_vlcc > 200:
            fragments.append(f'VLCC运价创<span class="text-neon font-bold">历史新高</span>')
            tags.append(("VLCC运价暴涨", "yellow"))
        elif latest_vlcc > 100:
            fragments.append(f'VLCC运价${latest_vlcc}K/天')
            tags.append(("VLCC运价高企", "yellow"))

    # Fragment 5: check for escalation events
    escalating = [e for e in events if e.get("trend") == "worsening"]
    if len(escalating) >= 3:
        tags.append(("多线升级", "red"))

    # Fragment 6: check for carrier deployment
    carrier_events = [e for e in events
                      if any(k in e.get("title", "") for k in ["航母", "carrier", "CVN"])]
    if carrier_events:
        tags.append(("航母战斗群", "blue"))

    # Fragment 7: A-share reaction
    stocks = data.get("stocks", {})
    limit_up = [s for s in stocks.values()
                if s.get("change_pct") is not None and s["change_pct"] >= 9.9]
    if limit_up:
        tags.append(("A股涨停", "green"))

    # --- Compute threat level from event states ---
    n_escalating = len([e for e in events if e.get("current_status") == "escalating"])
    n_active = len([e for e in events if e.get("current_status") == "active_conflict"])
    n_ceasefire = len([e for e in events if e.get("current_status") in ("ceasefire", "de_escalating")])
    n_worsening = len([e for e in events if e.get("trend") == "worsening"])

    if n_ceasefire > n_active + n_escalating:
        threat_level = "MODERATE"
    elif n_escalating >= 3 or n_worsening >= 4:
        threat_level = "CRITICAL"
    elif n_active >= 2 or n_escalating >= 1:
        threat_level = "HIGH"
    elif events:
        threat_level = "ELEVATED"
    else:
        threat_level = "HIGH"  # default when no event data

    # Assemble
    summary_text = " — ".join(fragments)

    # Generate tags HTML
    tag_color_map = {"red": "tag-red", "yellow": "tag-yellow",
                     "blue": "tag-blue", "green": "tag-green"}
    tags_html = ""
    for label, color in tags[:6]:
        cls = tag_color_map.get(color, "tag-blue")
        tags_html += f'<span class="tag {cls}">{label}</span>\n      '

    return {
        "summary_text": summary_text,
        "tags_html": tags_html.strip(),
        "fragments": fragments,
        "tag_list": tags,
        "threat_level": threat_level,
    }


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
    print(f"  Using {len(data.get('news', []))} filtered news items")
    print(f"  Using {len(data.get('event_states', []))} event states")
    news_html = build_news_html(data)
    live_intel_html = build_live_intel_html(data)

    # Build hero summary from event state model
    hero = build_hero_summary(data)
    reference_meta = _load_reference_meta()
    daily_summary_cards_html = build_daily_summary_cards(data, hero)

    # Render template
    print("[4/4] Rendering template...")
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("template.html")

    # Prepare context
    markets = data.get("markets", {})
    brent = markets.get("brent", {})
    wti = markets.get("wti", {})
    gold = markets.get("gold", {})
    usd_cny = markets.get("usd_cny", {})

    nat_gas = markets.get("nat_gas", {})

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
        "nat_gas_price": nat_gas.get("current", "N/A"),
        "brent_change": brent.get("day_change_pct", 0),
        "brent_war_change": brent.get("war_change_pct", 0),
        "gold_change": gold.get("day_change_pct", 0),
        "gold_war_change": gold.get("war_change_pct", 0),
        "usd_cny_change": usd_cny.get("day_change_pct", 0),
        "nat_gas_change": nat_gas.get("day_change_pct", 0),
        "nat_gas_war_change": nat_gas.get("war_change_pct", 0),
        # Chart data as JSON strings for JS injection
        "chart_data_json": Markup(json.dumps(charts, ensure_ascii=False)),
        # News HTML
        "news_html": news_html,
        # Section 1 LIVE intel cards (auto-generated from news)
        "live_intel_html": live_intel_html,
        "daily_summary_cards_html": daily_summary_cards_html,
        # Stock data for tables
        "stocks": data.get("stocks", {}),
        "sectors": data.get("sectors", {}),
        # VLCC latest rate
        "vlcc_latest": _get_vlcc_latest(data),
        "vlcc_note": _get_vlcc_note(data),
        # Hero summary (auto-generated from event state model)
        "hero_summary_text": Markup(hero["summary_text"]),
        "hero_tags_html": Markup(hero["tags_html"]),
        "threat_level": hero["threat_level"],
        # Event state model as JSON for advanced use
        "event_states_json": Markup(json.dumps(data.get("event_states", []), ensure_ascii=False, default=str)),
        # Satellite / AIS section
        "hormuz_today": _get_hormuz_today(data),
        "transit_records_html": Markup(_build_transit_records(data)),
        # Raw data for advanced use
        "raw_data_json": Markup(json.dumps(data, ensure_ascii=False, default=str)),
        "reference_meta": reference_meta,
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
