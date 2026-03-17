#!/usr/bin/env python3
"""
OSINT Daily Data Fetcher
Fetches oil prices, gold, FX, A-share stocks, and news from free public sources.
Output: data/latest.json
"""

import json
import os
import sys
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
import feedparser

# --- Constants ---
WAR_START = date(2026, 2, 28)
DATA_DIR = Path(__file__).parent
OUTPUT_FILE = DATA_DIR / "latest.json"

# A-share stock codes for Eastmoney API
STOCK_LIST = {
    # 航运
    "601872": "招商轮船",
    "600026": "中远海能",
    "601975": "招商南油",
    # 油气
    "600938": "中国海油",
    "601857": "中国石油",
    "600028": "中国石化",
    "603619": "中曼石油",
    "600759": "洲际油气",
    # 油服
    "601808": "中海油服",
    "002353": "杰瑞股份",
    # LNG
    "600803": "新奥股份",
    "600256": "广汇能源",
    # 集运
    "601919": "中远海控",
    # 军工
    "600760": "中航沈飞",
    "600893": "航发动力",
    "600150": "中国船舶",
    # 黄金
    "600547": "山东黄金",
    "600988": "赤峰黄金",
    "600489": "中金黄金",
    # 其他
    "601088": "中国神华",
}

SECTOR_CODES = {
    "航运": "BK0475",
    "油气": "BK0414",
    "油服": "BK0414",
    "LNG": "BK0478",
}

# RSS feeds for news
RSS_FEEDS = {
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "BBC World": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "Reuters": "https://www.rss-bridge.org/bridge01/?action=display&bridge=Reuters&feed=world&format=Atom",
}


def fetch_yahoo_finance():
    """Fetch oil, gold, FX data from Yahoo Finance via yfinance."""
    data = {}
    try:
        import yfinance as yf

        tickers = {
            "brent": "BZ=F",
            "wti": "CL=F",
            "gold": "GC=F",
            "usd_cny": "CNY=X",
            "nat_gas": "NG=F",
        }

        for key, symbol in tickers.items():
            try:
                tk = yf.Ticker(symbol)
                hist = tk.history(period="3mo")
                if hist.empty:
                    print(f"  [WARN] No data for {symbol}")
                    continue

                current = float(hist["Close"].iloc[-1])
                dates_list = [d.strftime("%m/%d") for d in hist.index[-30:]]
                prices_list = [round(float(p), 2) for p in hist["Close"].iloc[-30:]]

                # Calculate changes
                if len(hist) >= 2:
                    prev = float(hist["Close"].iloc[-2])
                    day_change = round((current - prev) / prev * 100, 2)
                else:
                    day_change = 0

                # War start comparison
                war_start_idx = hist.index.searchsorted(
                    datetime(2026, 2, 28).replace(tzinfo=hist.index.tz)
                    if hist.index.tz
                    else datetime(2026, 2, 28)
                )
                if war_start_idx < len(hist):
                    war_start_price = float(hist["Close"].iloc[war_start_idx])
                    war_change = round(
                        (current - war_start_price) / war_start_price * 100, 2
                    )
                else:
                    war_change = None

                data[key] = {
                    "current": current,
                    "day_change_pct": day_change,
                    "war_change_pct": war_change,
                    "dates": dates_list,
                    "prices": prices_list,
                    "updated": datetime.now().isoformat(),
                }
                print(f"  [OK] {key}: ${current:.2f} ({day_change:+.2f}%)")

            except Exception as e:
                print(f"  [ERR] {symbol}: {e}")
                data[key] = {"current": None, "error": str(e)}

    except ImportError:
        print("  [ERR] yfinance not installed, using fallback")
        data = _yahoo_fallback()

    return data


def _yahoo_fallback():
    """Fallback: fetch from Yahoo Finance public API directly."""
    data = {}
    symbols = {"brent": "BZ=F", "wti": "CL=F", "gold": "GC=F", "usd_cny": "CNY=X"}
    headers = {"User-Agent": "Mozilla/5.0"}

    for key, symbol in symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=3mo&interval=1d"
            r = requests.get(url, headers=headers, timeout=15)
            j = r.json()
            result = j["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            timestamps = result["timestamp"]

            valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
            if not valid:
                continue

            dates_list = [
                datetime.fromtimestamp(t).strftime("%m/%d") for t, _ in valid[-30:]
            ]
            prices_list = [round(c, 2) for _, c in valid[-30:]]
            current = prices_list[-1]
            prev = prices_list[-2] if len(prices_list) >= 2 else current
            day_change = round((current - prev) / prev * 100, 2)

            data[key] = {
                "current": current,
                "day_change_pct": day_change,
                "dates": dates_list,
                "prices": prices_list,
                "updated": datetime.now().isoformat(),
            }
            print(f"  [OK-fallback] {key}: ${current:.2f}")

        except Exception as e:
            print(f"  [ERR-fallback] {symbol}: {e}")
            data[key] = {"current": None, "error": str(e)}

    return data


def fetch_eastmoney_stocks():
    """Fetch A-share stock data from Eastmoney public API."""
    stocks = {}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }

    for code, name in STOCK_LIST.items():
        try:
            # Determine market prefix
            prefix = "1." if code.startswith("6") else "0."
            secid = prefix + code

            url = (
                f"https://push2.eastmoney.com/api/qt/stock/get?"
                f"secid={secid}&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f170,f171"
            )
            r = requests.get(url, headers=headers, timeout=10)
            j = r.json()

            if j.get("data"):
                d = j["data"]
                current = d.get("f43", 0) / 100 if d.get("f43") else None
                change_pct = d.get("f170", 0) / 100 if d.get("f170") else None
                high = d.get("f44", 0) / 100 if d.get("f44") else None
                low = d.get("f45", 0) / 100 if d.get("f45") else None
                volume = d.get("f47", 0)

                stocks[code] = {
                    "name": name,
                    "price": current,
                    "change_pct": change_pct,
                    "high": high,
                    "low": low,
                    "volume": volume,
                }
                sign = "+" if change_pct and change_pct > 0 else ""
                pct_str = f"{sign}{change_pct}%" if change_pct else "N/A"
                print(f"  [OK] {name}({code}): ¥{current} ({pct_str})")
            else:
                stocks[code] = {"name": name, "price": None, "error": "no data"}
                print(f"  [WARN] {name}({code}): no data")

        except Exception as e:
            stocks[code] = {"name": name, "price": None, "error": str(e)}
            print(f"  [ERR] {name}({code}): {e}")

    return stocks


def fetch_eastmoney_sectors():
    """Fetch sector indices from Eastmoney."""
    sectors = {}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }

    sector_list = [
        ("航运", "BK0475"),
        ("石油", "BK0414"),
        ("天然气", "BK0478"),
        ("军工", "BK0477"),
        ("黄金", "BK0473"),
    ]

    for name, code in sector_list:
        try:
            url = (
                f"https://push2.eastmoney.com/api/qt/stock/get?"
                f"secid=90.{code}&fields=f43,f170,f171"
            )
            r = requests.get(url, headers=headers, timeout=10)
            j = r.json()

            if j.get("data"):
                d = j["data"]
                change_pct = d.get("f170", 0) / 100 if d.get("f170") else None
                sectors[name] = {"change_pct": change_pct}
                print(f"  [OK] 板块 {name}: {change_pct}%")
            else:
                sectors[name] = {"change_pct": None}

        except Exception as e:
            sectors[name] = {"change_pct": None, "error": str(e)}
            print(f"  [ERR] 板块 {name}: {e}")

    return sectors


def fetch_news():
    """Fetch latest Middle East news from RSS feeds."""
    news = []

    keywords = [
        "iran",
        "israel",
        "hormuz",
        "middle east",
        "tehran",
        "gulf",
        "oil",
        "tanker",
        "houthi",
        "red sea",
        "kharg",
    ]

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries[:30]:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = (title + " " + summary).lower()

                if any(kw in text for kw in keywords):
                    news.append(
                        {
                            "source": source_name,
                            "title": title,
                            "link": entry.get("link", ""),
                            "published": entry.get("published", ""),
                            "summary": summary[:200],
                        }
                    )
                    count += 1
                    if count >= 5:
                        break

            print(f"  [OK] {source_name}: {count} relevant articles")

        except Exception as e:
            print(f"  [ERR] {source_name}: {e}")

    return news[:20]


def compute_meta():
    """Compute metadata: war day, timestamps, etc."""
    today = date.today()
    war_day = (today - WAR_START).days + 1
    return {
        "report_date": today.strftime("%Y.%m.%d"),
        "report_date_cn": today.strftime("%Y年%m月%d日"),
        "war_day": war_day,
        "war_start": WAR_START.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "generated_at_cn": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    print("=" * 60)
    print(f"OSINT Data Fetch — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    result = {}

    print("\n[1/5] Fetching market data (Yahoo Finance)...")
    result["markets"] = fetch_yahoo_finance()

    print("\n[2/5] Fetching A-share stocks (Eastmoney)...")
    result["stocks"] = fetch_eastmoney_stocks()

    print("\n[3/5] Fetching sector indices (Eastmoney)...")
    result["sectors"] = fetch_eastmoney_sectors()

    print("\n[4/5] Fetching news (RSS)...")
    result["news"] = fetch_news()

    print("\n[5/5] Computing metadata...")
    result["meta"] = compute_meta()

    # Load previous data for historical continuity
    prev_file = DATA_DIR / "history.json"
    if prev_file.exists():
        try:
            with open(prev_file) as f:
                history = json.load(f)
        except Exception:
            history = []
    else:
        history = []

    # Append today's snapshot to history (keep last 90 days)
    snapshot = {
        "date": date.today().isoformat(),
        "brent": result["markets"].get("brent", {}).get("current"),
        "wti": result["markets"].get("wti", {}).get("current"),
        "gold": result["markets"].get("gold", {}).get("current"),
        "usd_cny": result["markets"].get("usd_cny", {}).get("current"),
    }
    history.append(snapshot)
    history = history[-90:]

    with open(prev_file, "w") as f:
        json.dump(history, f, indent=2)

    result["history"] = history

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Done. Output: {OUTPUT_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
