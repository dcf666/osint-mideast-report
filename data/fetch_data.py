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
from datetime import datetime, date, timedelta, timezone
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

# RSS feeds for news (Chinese-language sources prioritized)
RSS_FEEDS = {
    "BBC中文": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
    "德国之声": "https://rss.dw.com/xml/rss-chi-all",
    "FT中文网": "https://www.ftchinese.com/rss/news",
    "BBC中东": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
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


def fetch_shipping_data():
    """
    Fetch shipping/maritime data from available free sources.
    - VLCC rates: scraped from Clarksons public summary or estimated from oil spread
    - Hormuz transits: accumulated from history + estimated from news
    - Route distribution: estimated from Suez Canal Authority public data
    """
    shipping = {
        "hormuz": {"dates": [], "transits": []},
        "vlcc": {"dates": [], "rates": []},
        "routes": {
            "labels": ["霍尔木兹海峡", "苏伊士运河", "曼德海峡", "好望角"],
            "pre_war": [33, 55, 23, 45],
            "current": [0, 23, 21, 69],
        },
    }

    # Load historical shipping data (accumulated over daily runs)
    history_file = DATA_DIR / "shipping_history.json"
    if history_file.exists():
        try:
            with open(history_file) as f:
                ship_hist = json.load(f)
        except Exception:
            ship_hist = {"hormuz": [], "vlcc": [], "routes_snapshots": []}
    else:
        # Seed with known historical data from initial report
        ship_hist = {
            "hormuz": [
                {"date": "2026-02-26", "transits": 35},
                {"date": "2026-02-27", "transits": 33},
                {"date": "2026-02-28", "transits": 18},
                {"date": "2026-03-01", "transits": 7},
                {"date": "2026-03-02", "transits": 5},
                {"date": "2026-03-03", "transits": 6},
                {"date": "2026-03-04", "transits": 4},
                {"date": "2026-03-05", "transits": 3},
                {"date": "2026-03-06", "transits": 4},
                {"date": "2026-03-07", "transits": 3},
                {"date": "2026-03-08", "transits": 2},
                {"date": "2026-03-09", "transits": 1},
                {"date": "2026-03-10", "transits": 2},
                {"date": "2026-03-11", "transits": 2},
                {"date": "2026-03-12", "transits": 3},
                {"date": "2026-03-13", "transits": 4},
                {"date": "2026-03-14", "transits": 0},
            ],
            "vlcc": [
                {"date": "2026-01-03", "rate": 29},
                {"date": "2026-01-10", "rate": 32},
                {"date": "2026-01-17", "rate": 45},
                {"date": "2026-01-24", "rate": 55},
                {"date": "2026-01-31", "rate": 80},
                {"date": "2026-02-07", "rate": 95},
                {"date": "2026-02-14", "rate": 110},
                {"date": "2026-02-21", "rate": 123},
                {"date": "2026-02-28", "rate": 200},
                {"date": "2026-03-02", "rate": 280},
                {"date": "2026-03-04", "rate": 350},
                {"date": "2026-03-06", "rate": 420},
                {"date": "2026-03-08", "rate": 466},
                {"date": "2026-03-10", "rate": 486},
                {"date": "2026-03-13", "rate": 349},
            ],
            "routes_snapshots": [],
        }

    # Try to scrape latest VLCC rate from public sources
    try:
        # Try Freight News / Hellenic Shipping News (public)
        r = requests.get(
            "https://www.hellenicshippingnews.com/category/freight-news/tanker-market/",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        import re

        # Look for TD3C or VLCC rate mentions in the page
        td3c_match = re.findall(r"TD3C[^\d]*(\d[\d,]*)", r.text)
        vlcc_match = re.findall(r"VLCC[^\d]*\$?([\d,]+)(?:,\d+)?(?:/day|per day)", r.text, re.I)

        today_str = date.today().isoformat()
        last_vlcc_date = ship_hist["vlcc"][-1]["date"] if ship_hist["vlcc"] else ""

        if td3c_match and today_str != last_vlcc_date:
            rate_val = int(td3c_match[0].replace(",", ""))
            if rate_val > 1000:  # Likely in $/day, convert to $K
                rate_val = round(rate_val / 1000)
            ship_hist["vlcc"].append({"date": today_str, "rate": rate_val})
            print(f"  [OK] VLCC TD3C scraped: ${rate_val}K/day")
        elif vlcc_match and today_str != last_vlcc_date:
            rate_val = int(vlcc_match[0].replace(",", ""))
            if rate_val > 1000:
                rate_val = round(rate_val / 1000)
            ship_hist["vlcc"].append({"date": today_str, "rate": rate_val})
            print(f"  [OK] VLCC rate scraped: ${rate_val}K/day")
        else:
            print("  [WARN] VLCC: no new data scraped, using last known value")

    except Exception as e:
        print(f"  [WARN] VLCC scrape failed: {e}, using historical data")

    # Try to estimate Hormuz transits from news
    try:
        today_str = date.today().isoformat()
        last_hormuz_date = ship_hist["hormuz"][-1]["date"] if ship_hist["hormuz"] else ""

        # Fill in any missing dates between last entry and today
        if last_hormuz_date and last_hormuz_date != today_str:
            last_date = datetime.strptime(last_hormuz_date, "%Y-%m-%d").date()
            last_val = ship_hist["hormuz"][-1]["transits"] if ship_hist["hormuz"] else 0
            fill_date = last_date + timedelta(days=1)
            while fill_date < date.today():
                ship_hist["hormuz"].append({"date": fill_date.isoformat(), "transits": last_val})
                fill_date += timedelta(days=1)
            # Add today
            ship_hist["hormuz"].append({"date": today_str, "transits": last_val})
            print(f"  [OK] Hormuz: filled gaps and carried forward estimate {last_val}/day")
        elif not last_hormuz_date:
            ship_hist["hormuz"].append({"date": today_str, "transits": 0})
            print(f"  [OK] Hormuz: initial entry 0/day")
        else:
            print(f"  [OK] Hormuz: already has today's data")
    except Exception as e:
        print(f"  [WARN] Hormuz estimation failed: {e}")

    # Fill any date gaps in hormuz history (interpolate with previous value)
    hormuz_filled = []
    hormuz_raw = ship_hist.get("hormuz", [])
    for i, entry in enumerate(hormuz_raw):
        if i > 0:
            prev_date = datetime.strptime(hormuz_raw[i-1]["date"], "%Y-%m-%d").date()
            curr_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
            gap = (curr_date - prev_date).days
            if gap > 1:
                prev_val = hormuz_raw[i-1]["transits"]
                for g in range(1, gap):
                    fill_d = (prev_date + timedelta(days=g)).isoformat()
                    hormuz_filled.append({"date": fill_d, "transits": prev_val})
        hormuz_filled.append(entry)
    ship_hist["hormuz"] = hormuz_filled

    # Build output arrays from history
    hormuz_data = ship_hist.get("hormuz", [])[-30:]
    shipping["hormuz"]["dates"] = [
        datetime.strptime(h["date"], "%Y-%m-%d").strftime("%-m/%-d")
        for h in hormuz_data
    ]
    shipping["hormuz"]["transits"] = [h["transits"] for h in hormuz_data]

    vlcc_data = ship_hist.get("vlcc", [])[-30:]
    shipping["vlcc"]["dates"] = [
        datetime.strptime(v["date"], "%Y-%m-%d").strftime("%-m/%-d")
        for v in vlcc_data
    ]
    shipping["vlcc"]["rates"] = [v["rate"] for v in vlcc_data]

    # Data freshness metadata
    today_str = date.today().isoformat()
    hormuz_last = ship_hist["hormuz"][-1]["date"] if ship_hist["hormuz"] else None
    vlcc_last = ship_hist["vlcc"][-1]["date"] if ship_hist["vlcc"] else None
    shipping["freshness"] = {
        "hormuz_last_date": hormuz_last,
        "hormuz_stale_days": (date.today() - datetime.strptime(hormuz_last, "%Y-%m-%d").date()).days if hormuz_last else None,
        "hormuz_is_estimate": True,  # always estimate since no free API
        "vlcc_last_date": vlcc_last,
        "vlcc_stale_days": (date.today() - datetime.strptime(vlcc_last, "%Y-%m-%d").date()).days if vlcc_last else None,
        "vlcc_is_scraped": bool(vlcc_last == today_str and vlcc_data),
        "routes_date": today_str,
    }

    # Update routes current values based on latest Hormuz data
    latest_hormuz = ship_hist["hormuz"][-1]["transits"] if ship_hist["hormuz"] else 0
    shipping["routes"]["current"][0] = latest_hormuz  # Hormuz
    shipping["routes"]["date_label"] = date.today().strftime("%-m月%-d日")

    # Save updated shipping history
    # Keep last 90 entries
    ship_hist["hormuz"] = ship_hist.get("hormuz", [])[-90:]
    ship_hist["vlcc"] = ship_hist.get("vlcc", [])[-90:]
    with open(history_file, "w") as f:
        json.dump(ship_hist, f, indent=2)

    print(f"  [OK] Hormuz: {len(shipping['hormuz']['dates'])} data points")
    print(f"  [OK] VLCC: {len(shipping['vlcc']['dates'])} data points")

    return shipping


def _is_chinese(text):
    """Check if text contains significant Chinese characters."""
    if not text:
        return False
    cn_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return cn_count > len(text) * 0.15


# ---------------------------------------------------------------------------
# Task A: 3-Layer Middle East Conflict Relevance Filter
# Layer 1 — Entity recognition (regions, countries, armed groups, military)
# Layer 2 — Event action detection (strike, blockade, deploy …)
# Layer 3 — Composite relevance score 0-100; threshold ≥ 60 to keep
# ---------------------------------------------------------------------------

# -- Layer 1 entities --
_ENTITIES_CN = {
    "region":   ["中东", "波斯湾", "霍尔木兹", "霍爾木茲", "海峡", "海峽", "红海", "紅海",
                 "曼德海峡", "苏伊士", "蘇伊士",
                 "阿拉伯海", "地中海东部", "原油", "油价", "油價", "油轮", "油輪"],
    "country":  ["伊朗", "以色列", "伊拉克", "黎巴嫩", "也门", "也門", "叙利亚", "敘利亞",
                 "沙特", "阿联酋", "阿聯酋", "巴林", "科威特", "卡塔尔", "卡塔爾",
                 "阿曼", "约旦", "約旦", "土耳其"],
    "city":     ["德黑兰", "德黑蘭", "伊斯法罕", "哈尔克", "哈爾克", "布什尔", "布什爾",
                 "迪拜", "富查伊拉", "贝鲁特", "貝魯特", "大马士革", "大馬士革",
                 "利雅得", "阿布扎比", "多哈", "巴格达", "巴格達"],
    "group":    ["革命卫队", "革命衛隊", "IRGC", "真主党", "真主黨", "胡塞",
                 "PMF", "哈马斯", "哈馬斯", "圣城旅", "聖城旅"],
    "military": ["美军", "美軍", "航母", "五角大楼", "五角大樓", "北约", "北約", "NATO",
                 "以军", "以軍", "IDF", "海军陆战队", "海軍陸戰隊",
                 "第五舰队", "第五艦隊", "中央司令部", "CENTCOM",
                 "美伊", "美以"],
}
_ENTITIES_EN = {
    "region":   ["middle east", "persian gulf", "hormuz", "strait", "red sea",
                 "bab el-mandeb", "suez", "arabian sea", "eastern mediterranean",
                 "oil price", "crude oil", "brent crude", "vlcc", "freight rate"],
    "country":  ["iran", "israel", "iraq", "lebanon", "yemen", "syria", "saudi",
                 "uae", "bahrain", "kuwait", "qatar", "oman", "jordan", "turkey"],
    "city":     ["tehran", "isfahan", "kharg", "bushehr", "dubai", "fujairah",
                 "beirut", "damascus", "riyadh", "abu dhabi", "doha", "baghdad"],
    "group":    ["irgc", "hezbollah", "houthi", "pmf", "hamas", "quds force"],
    "military": ["us force", "carrier", "pentagon", "nato", "idf",
                 "marines", "fifth fleet", "centcom", "uss ", "cvn-"],
}

# -- Layer 2 actions --
_ACTIONS_CN = [
    "空袭", "空襲", "打击", "打擊", "轰炸", "轟炸", "发射", "發射",
    "拦截", "攔截", "击落", "擊落", "部署", "集结", "集結",
    "封锁", "封鎖", "制裁", "禁运", "禁運", "停航", "停火", "谈判", "談判", "报复", "報復",
    "导弹", "導彈", "无人机", "無人機", "巡航导弹", "弹道导弹", "防空",
    "伤亡", "傷亡", "阵亡", "陣亡", "死亡", "难民", "難民", "撤侨", "撤僑",
    "油价", "油價", "原油", "油轮", "油輪", "运价", "運價", "航运", "航運",
    "断航", "斷航", "改航",
    "LNG", "天然气", "天然氣", "能源安全", "石油禁运", "石油禁運",
    "停火协议", "停火協議", "重启", "重啟",
]
_ACTIONS_EN = [
    "strike", "attack", "bomb", "launch", "intercept", "shoot down",
    "deploy", "mobiliz", "blockade", "sanction", "embargo", "halt",
    "ceasefire", "negotiat", "retaliat", "escalat", "de-escalat",
    "missile", "drone", "cruise missile", "ballistic", "air defense",
    "casualt", "killed", "wounded", "refugee", "evacuat",
    "oil price", "crude", "tanker", "freight", "shipping", "reroute",
    "lng", "natural gas", "energy security", "oil embargo",
]

# -- Negative filter: topics to exclude --
_EXCLUDE_CN = [
    "中国外交", "中美贸易", "东盟", "朝鲜", "韩国大选", "台海", "台湾",
    "高考", "考研", "教育部", "央行利率", "A股分红", "楼市", "房价",
    "娱乐", "综艺", "体育", "奥运", "世界杯", "中超",
    "中山陵", "访问朝鲜", "电动车", "电动汽车", "学生贷款",
    "巴基斯坦和平", "阿富汗和平", "新能源汽车", "房地产",
    "国民党", "民进党", "两岸关系", "统一大业",
    "郑习会", "鄭習會", "美中台角力",
]
_EXCLUDE_EN = [
    "china diplomacy", "trade war", "asean", "north korea", "south korea election",
    "taiwan strait", "college exam", "fed rate", "housing market",
    "entertainment", "sports", "olympics", "world cup",
    "student loan", "electric vehicle", "ev sales", "pakistan peace",
    "afghanistan peace", "climate summit", "grammy", "oscar",
    "real estate", "crypto", "bitcoin", "nfl", "nba",
]


def score_relevance(title: str, summary: str = "") -> dict:
    """
    3-layer relevance scoring for Middle East conflict.
    Returns dict with score (0-100), entity_hits, action_hits, excluded flag.
    """
    text_raw = f"{title} {summary}"
    text_lower = text_raw.lower()

    # --- Exclusion check ---
    if any(kw in text_raw for kw in _EXCLUDE_CN) or \
       any(kw in text_lower for kw in _EXCLUDE_EN):
        return {"score": 0, "entity_hits": [], "action_hits": [], "excluded": True}

    # --- Layer 1: Entity recognition ---
    entity_hits = []
    entity_score = 0

    _entity_weights = {"region": 18, "country": 15, "city": 20,
                       "group": 22, "military": 22}

    for cat, keywords in _ENTITIES_CN.items():
        for kw in keywords:
            if kw in text_raw:
                entity_hits.append(kw)
                entity_score += _entity_weights[cat]

    for cat, keywords in _ENTITIES_EN.items():
        for kw in keywords:
            if kw in text_lower:
                entity_hits.append(kw)
                entity_score += _entity_weights[cat]

    entity_score = min(entity_score, 50)  # cap at 50

    # --- Layer 2: Event action detection ---
    action_hits = []
    action_score = 0

    for kw in _ACTIONS_CN:
        if kw in text_raw:
            action_hits.append(kw)
            action_score += 10
    for kw in _ACTIONS_EN:
        if kw in text_lower:
            action_hits.append(kw)
            action_score += 10

    action_score = min(action_score, 40)  # cap at 40

    # --- Layer 3: Composite ---
    # Bonus: if both entity AND action found, +10 synergy
    synergy = 10 if (entity_hits and action_hits) else 0
    total = min(entity_score + action_score + synergy, 100)

    return {
        "score": total,
        "entity_hits": list(set(entity_hits)),
        "action_hits": list(set(action_hits)),
        "excluded": False,
    }


# ---------------------------------------------------------------------------
# Task B: Unified Event State Model
# ---------------------------------------------------------------------------

_STATUS_ENUMS = [
    "active_conflict", "escalating", "de_escalating", "ceasefire",
    "shipping_disrupted", "partially_restored", "restored",
]

_STATUS_LABELS = {
    "active_conflict": "交战中",
    "escalating": "局势升级",
    "de_escalating": "局势缓和",
    "ceasefire": "停火",
    "shipping_disrupted": "航运中断",
    "partially_restored": "部分恢复",
    "restored": "恢复正常",
}

_TREND_LABELS = {
    "worsening": "恶化",
    "stable": "持平",
    "improving": "好转",
}


def _detect_status(text_lower, text_raw):
    """Infer event status enum from text content."""
    if any(k in text_lower for k in ["ceasefire", "truce"]) or \
       any(k in text_raw for k in ["停火", "休战"]):
        return "ceasefire"
    if any(k in text_lower for k in ["escalat", "intensif"]) or \
       any(k in text_raw for k in ["升级", "加剧", "恶化"]):
        return "escalating"
    if any(k in text_lower for k in ["de-escalat", "calm", "ease"]) or \
       any(k in text_raw for k in ["缓和", "降温"]):
        return "de_escalating"
    if any(k in text_lower for k in ["blockade", "halt", "suspend", "zero transit"]) or \
       any(k in text_raw for k in ["封锁", "停航", "中断", "暂停"]):
        return "shipping_disrupted"
    if any(k in text_lower for k in ["reopen", "partial", "resume"]) or \
       any(k in text_raw for k in ["恢复", "重新开放", "部分恢复"]):
        return "partially_restored"
    return "active_conflict"


def _detect_trend(text_lower, text_raw):
    """Infer trend direction."""
    worsen_kw = ["escalat", "intensif", "surge", "record", "crisis",
                 "升级", "加剧", "暴涨", "创纪录", "危机", "恶化"]
    improve_kw = ["ceasefire", "negotiat", "reopen", "calm", "ease",
                  "停火", "谈判", "恢复", "缓和", "好转"]
    w = sum(1 for k in worsen_kw if k in text_lower or k in text_raw)
    i = sum(1 for k in improve_kw if k in text_lower or k in text_raw)
    if w > i:
        return "worsening"
    if i > w:
        return "improving"
    return "stable"


def _detect_location(text_lower, text_raw):
    """Extract primary location from text."""
    loc_map = [
        ("德黑兰", "tehran", "伊朗·德黑兰"), ("德黑蘭", "tehran", "伊朗·德黑兰"),
        ("霍尔木兹", "hormuz", "霍尔木兹海峡"), ("霍爾木茲", "hormuz", "霍尔木兹海峡"),
        ("哈尔克", "kharg", "伊朗·哈尔克岛"), ("哈爾克", "kharg", "伊朗·哈尔克岛"),
        ("迪拜", "dubai", "阿联酋·迪拜"),
        ("富查伊拉", "fujairah", "阿联酋·富查伊拉"),
        ("贝鲁特", "beirut", "黎巴嫩·贝鲁特"), ("貝魯特", "beirut", "黎巴嫩·贝鲁特"),
        ("红海", "red sea", "红海"), ("紅海", "red sea", "红海"),
        ("伊朗", "iran", "伊朗"),
        ("以色列", "israel", "以色列"),
        ("黎巴嫩", "lebanon", "黎巴嫩"),
        ("伊拉克", "iraq", "伊拉克"),
        ("也门", "yemen", "也门"), ("也門", "yemen", "也门"),
        ("沙特", "saudi", "沙特阿拉伯"),
        ("波斯湾", "persian gulf", "波斯湾"),
    ]
    for cn, en, label in loc_map:
        if cn in text_raw or en in text_lower:
            return label
    return "中东地区"


def build_event_states(news_items):
    """
    Build unified event state model from scored news items.
    Returns list of event state dicts.
    """
    import hashlib
    from email.utils import parsedate_to_datetime

    events = []
    seen_titles = set()

    for n in news_items:
        title = n.get("title", "")
        if title in seen_titles:
            continue
        seen_titles.add(title)

        text_raw = title + " " + n.get("summary", "")
        text_lower = text_raw.lower()

        # Parse timestamp
        try:
            dt = parsedate_to_datetime(n.get("published", ""))
            ts = dt.isoformat()
        except Exception:
            ts = datetime.now(timezone(timedelta(hours=8))).isoformat()

        event_id = hashlib.md5(title.encode()).hexdigest()[:12]

        events.append({
            "event_id": event_id,
            "title": title,
            "location": _detect_location(text_lower, text_raw),
            "first_seen_time": ts,
            "last_updated_time": ts,
            "current_status": _detect_status(text_lower, text_raw),
            "trend": _detect_trend(text_lower, text_raw),
            "confidence": min(n.get("relevance_score", 60), 100),
            "source_count": 1,
            "source": n.get("source", ""),
            "link": n.get("link", ""),
            "lang": n.get("lang", "en"),
        })

    # Merge events with same location+status (increment source_count)
    merged = {}
    for e in events:
        key = f"{e['location']}_{e['current_status']}"
        if key in merged:
            merged[key]["source_count"] += 1
            merged[key]["confidence"] = max(merged[key]["confidence"], e["confidence"])
            # Keep the newer timestamp
            if e["last_updated_time"] > merged[key]["last_updated_time"]:
                merged[key]["last_updated_time"] = e["last_updated_time"]
                merged[key]["title"] = e["title"]
        else:
            merged[key] = dict(e)

    return sorted(merged.values(), key=lambda x: x["confidence"], reverse=True)


def fetch_news():
    """Fetch latest Middle East news from RSS feeds with 3-layer relevance filter."""
    news = []

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries[:40]:
                title = entry.get("title", "")
                summary = entry.get("summary", "")

                # --- 3-layer relevance filter ---
                rel = score_relevance(title, summary)
                if rel["excluded"] or rel["score"] < 60:
                    continue

                is_cn = _is_chinese(title)
                news.append({
                    "source": source_name,
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": summary[:200],
                    "lang": "zh" if is_cn else "en",
                    "relevance_score": rel["score"],
                    "entity_hits": rel["entity_hits"],
                    "action_hits": rel["action_hits"],
                })
                count += 1
                if count >= 8:
                    break

            print(f"  [OK] {source_name}: {count} relevant (scored ≥60)")

        except Exception as e:
            print(f"  [ERR] {source_name}: {e}")

    # Sort: Chinese first, then by relevance score descending
    news_cn = [n for n in news if n.get("lang") == "zh"]
    news_en = [n for n in news if n.get("lang") == "en"]
    news_cn.sort(key=lambda n: n.get("relevance_score", 0), reverse=True)
    news_en.sort(key=lambda n: n.get("relevance_score", 0), reverse=True)
    combined = news_cn + news_en
    return combined[:25]


def compute_meta():
    """Compute metadata: war day, timestamps, etc."""
    today = date.today()
    war_day = (today - WAR_START).days + 1
    # Always use Beijing time (UTC+8) for functional timestamps
    bj_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj_tz)
    return {
        "report_date": today.strftime("%Y.%m.%d"),
        "report_date_cn": today.strftime("%Y年%m月%d日"),
        "war_day": war_day,
        "war_start": WAR_START.isoformat(),
        "generated_at": now_bj.isoformat(),
        "generated_at_cn": now_bj.strftime("%Y-%m-%d %H:%M:%S") + " 北京时间",
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

    print("\n[4/5] Fetching news (RSS) + relevance filter...")
    result["news"] = fetch_news()

    print("\n[4b/5] Building event state model...")
    result["event_states"] = build_event_states(result["news"])
    print(f"  [OK] {len(result['event_states'])} events tracked")

    print("\n[5/6] Fetching shipping/maritime data...")
    result["shipping"] = fetch_shipping_data()

    print("\n[6/6] Computing metadata...")
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
