#!/usr/bin/env python3
"""
Bao pool moi mo cho token dang nam giu (MX, KCS, HTX, CET) -> Telegram

Cach hoat dong:
  1. Tai cac trang thong bao (server-rendered HTML) cua MEXC.
  2. Trich xuat moi link bai viet dang /announcements/article/<slug>-<id>.
  3. So sanh voi state trong seen.json -> bai nao chua thay thi ban Telegram.
  4. Ghi lai state.

Bien moi truong bat buoc:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Tuy chon:
  MEXC_LANG        (mac dinh "en-US", vd "vi-VN")
  STATE_FILE       (mac dinh "seen.json")
  MAX_NOTIFY       (mac dinh 10 - chong spam neu MEXC doi HTML)
  PROXY_MODE       ("auto" mac dinh | "direct" chi tai thang | "proxy" chi qua proxy)
  KUCOIN / HTX / COINEX   ("0" de tat theo doi tung san)
  MAX_AGE_HOURS    (mac dinh 72 - bo qua bai cu hon nguong nay, 0 = tat)
  TITLE_DEDUPE_DAYS (mac dinh 30 - chan bai trung tieu de trong khoang nay, 0 = tat)
  DRY_RUN          ("1" = khong gui Telegram, chi in ra man hinh)
"""

import calendar
import html
import json
import os
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import article

BASE = "https://www.mexc.com"
LANG = os.getenv("MEXC_LANG", "en-US")
STATE_FILE = pathlib.Path(os.getenv("STATE_FILE", "seen.json"))
MAX_NOTIFY = int(os.getenv("MAX_NOTIFY", "10"))
DRY_RUN = os.getenv("DRY_RUN") == "1"
PROXY_MODE = os.getenv("PROXY_MODE", "auto").lower()
WATCH_KUCOIN = os.getenv("KUCOIN", "1") != "0"
WATCH_HTX = os.getenv("HTX", "1") != "0"
WATCH_COINEX = os.getenv("COINEX", "1") != "0"
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "72"))
TITLE_DEDUPE_DAYS = int(os.getenv("TITLE_DEDUPE_DAYS", "30"))

# Doc than bai de lay gio mo/dong pool va tong thuong
ARTICLE_DETAIL = os.getenv("ARTICLE_DETAIL", "1") != "0"
ARTICLE_BUDGET = int(os.getenv("ARTICLE_BUDGET", "60"))
# Nhac truoc khi pool mo / truoc khi pool dong
REMIND_START_MIN = int(os.getenv("REMIND_START_MIN", "30"))
REMIND_END_HOURS = int(os.getenv("REMIND_END_HOURS", "6"))
MAX_REMINDERS = int(os.getenv("MAX_REMINDERS", "5"))
# Gio hien thi trong tin nhan (mac dinh UTC+7 = gio VN)
TZ_H = int(os.getenv("DISPLAY_TZ_HOURS", "7"))
# Canh bao khi bot hong
HEALTH_ALERT = os.getenv("HEALTH_ALERT", "1") != "0"
HEALTH_DOWN_AFTER = int(os.getenv("HEALTH_DOWN_AFTER", "6"))
HEALTH_PARSE_AFTER = int(os.getenv("HEALTH_PARSE_AFTER", "3"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Thong cao buyback/burn chinh thuc cua san. Bo loc nay duoc CONG THEM vao moi
# nguon, de tin cua san ve cung luc burn_watch.py phat hien cung giam on-chain.
WATCH_BURN_NEWS = os.getenv("BURN_NEWS", "1") != "0"
BURN_NEWS_RE = re.compile(
    os.getenv("BURN_NEWS_KEYWORDS",
              r"buy ?back|repurchase|\bburn(s|ing|ed|t)?\b|destruction|token reduction"),
    re.I)

# (nhan hien thi, duong dan, bo loc tu khoa hoac None = lay tat ca)
SOURCES = [
    ("MEXC Launchpool",  "/announcements/tag/launchpool-28", None),
    # Trang MX Exclusives gom ca Kickstarter lan thong cao buyback & burn MX.
    ("MEXC MX Exclusives", "/announcements/mx-exclusives",
     re.compile(r"kickstarter|launchpool", re.I)),
    # Luoi thu hai: Kickstarter thinh thoang chi xuat hien o trang New Listings.
    ("MEXC Kickstarter", "/announcements/new-listings", re.compile(r"kickstarter", re.I)),
]


def classify(text, keyword):
    """Bai nay la gi: 'pool' (co the di farm) | 'burn' (tin dot token) | None (bo qua).

    Xet tu khoa pool TRUOC tu khoa burn co chu y: 'Burning Drop' la ten mot san
    pham launchpool cua KuCoin, khong phai tin dot token."""
    if keyword is not None and keyword.search(text):
        return "pool"
    if WATCH_BURN_NEWS and BURN_NEWS_RE.search(text):
        return "burn"
    return "pool" if keyword is None else None

# KuCoin co API thong bao cong khai, khong can key, khong bi Cloudflare chan.
# GemPool la san pham "launchpool" cua KuCoin: stake KCS/USDT de farm token moi.
KUCOIN_API = "https://api.kucoin.com/api/v3/announcements"
KUCOIN_TYPES = ["activities"]
KUCOIN_FILTER = re.compile(
    os.getenv(
        "KUCOIN_KEYWORDS",
        r"gempool|gem pool|kumining|ku mining|launchpool|launch pool|"
        r"burning drop|pool-x|staking mining|mining campaign",
    ),
    re.I,
)

# HTX: trang danh muc thong bao render san HTML, lay duoc bang GET binh thuong.
# Primepool = khoa HTX/HT de farm token moi. Primelist = mua som token moi.
HTX_BASE = "https://www.htx.com"
HTX_LISTS = [
    ("HTX Primepool", "https://www.htx.com/en-us/support/list/360000031362/"),   # Latest Activities
    ("HTX Primepool", "https://www.htx.com/en-us/support/list/54911014605677/"),  # HTX Earn
]
HTX_LINK_RE = re.compile(r'href="(?P<path>/support/(?P<id>\d{8,})/?)"')
HTX_FILTER = re.compile(
    os.getenv("HTX_KEYWORDS", r"primepool|prime pool|primelist|prime list"), re.I)
HTX_BUDGET = int(os.getenv("HTX_BUDGET", "120"))

# CoinEx dung Zendesk cho trang thong bao -> co API JSON cong khai, khong can key.
# CoinEx KHONG co san pham launchpool; muc Events chu yeu la thuong nap va thi giao dich,
# nen bo loc mac dinh bam vao chu CET de bat su kien lien quan token ban dang giu.
COINEX_API = ("https://coinex-announcement.zendesk.com/api/v2/help_center/en-us/"
              "categories/14108305136532/articles.json"
              "?per_page=30&sort_by=created_at&sort_order=desc")
COINEX_FILTER = re.compile(
    os.getenv("COINEX_KEYWORDS", r"\bCET\b|launchpool|staking mining|mining pool"), re.I)

# Bat duong dan bai viet o BAT KY dau trong trang, khong bat buoc phai nam trong href="".
# Ly do: qua proxy, MEXC doi khi tra ve payload JSON cua Next.js thay vi HTML co the <a>,
# luc do duong dan nam trong "url":"/announcements/article/..." -> regex bam href se trat.
# vd: /announcements/article/ten-bai-viet-17827791534551 (co the co prefix ngon ngu)
ARTICLE_RE = re.compile(
    r'(?P<path>/(?:[a-z]{2}-[A-Z]{2}/)?announcements/article/'
    r'(?P<slug>[A-Za-z0-9\-]+?)-(?P<id>\d{10,}))(?=["\'\\?\s<)&])'
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

# Cac dinh dang ngay gap tren trang danh sach cua tung san
DATE_RES = [
    ("ymd", re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")),          # 2026-08-25
    ("mdy", re.compile(r"\b([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b")),  # Aug 25, 2026
    ("md", re.compile(r"\b(\d{2})/(\d{2})\b")),                                # 08/12 (HTX)
]


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# Cloudflare cua MEXC chan IP datacenter (GitHub Actions, VPS) bang loi 403.
# Cac proxy doc trang duoi day fetch ho tu IP cua ho roi tra ve HTML goc.
PROXIES = [
    ("allorigins", lambda u: "https://api.allorigins.win/raw?url=" + urllib.parse.quote(u, safe="")),
    ("codetabs", lambda u: "https://api.codetabs.com/v1/proxy?quest=" + urllib.parse.quote(u, safe="")),
    ("cors.lol", lambda u: "https://api.cors.lol/?url=" + urllib.parse.quote(u, safe="")),
    ("corsfix", lambda u: "https://proxy.corsfix.com/?" + u),
]

# Tran thoi gian cho toan bo phan MEXC, de job khong treo qua timeout cua workflow.
FETCH_BUDGET = int(os.getenv("FETCH_BUDGET", "300"))
_budget_until = None
_sources_ok = 0   # so nguon tai duoc trong lan chay nay
# Suc khoe tung nguon trong lan chay nay:
#   ok      - tai duoc trang hay khong
#   raw     - so bai boc duoc TRUOC khi loc tu khoa (0 = bo boc tach da hong)
#   matched - so bai con lai sau khi loc
_stats = {}


def note(label, ok, raw=0, matched=0):
    _stats[label] = {"ok": ok, "raw": raw, "matched": matched}

# Cach tai nao da chay duoc trong lan chay nay -> dung luon cho cac URL sau
_working = None


def _raw_get(url, timeout):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _looks_valid(body):
    return bool(body) and "/announcements/article/" in body


def fetch(url, tries=2, valid=None):
    """Tai HTML: thu tai thang truoc, that bai thi di vong qua proxy doc trang."""
    global _working, _sources_ok

    methods = []
    if PROXY_MODE != "proxy":
        methods.append(("direct", lambda u: u, 25))
    if PROXY_MODE != "direct":
        methods.extend((name, fn, 40) for name, fn in PROXIES)

    # uu tien cach da chung minh la chay duoc
    if _working:
        methods.sort(key=lambda m: 0 if m[0] == _working else 1)

    last = None
    for name, build, timeout in methods:
        # direct that bai la do bi chan (chac chan), khong thu lai;
        # proxy hay chap chon nen cho thu 2 lan
        attempts = 1 if name == "direct" else tries
        for i in range(attempts):
            if _budget_until and time.monotonic() > _budget_until:
                raise RuntimeError("het thoi gian danh cho viec tai trang")
            try:
                body = _raw_get(build(url), timeout)
                if not (valid or _looks_valid)(body):
                    raise ValueError("noi dung khong co link bai viet")
                if _working != name:
                    log(f"  (dang dung: {name})")
                    _working = name
                _sources_ok += 1
                return body
            except Exception as e:  # noqa: BLE001
                last = f"{name}: {e}"
                log(f"  ! {name} loi ({e}) - lan {i + 1}/{attempts}")
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"khong tai duoc {url} ({last})")


def _epoch(y, mo, d):
    try:
        return calendar.timegm((int(y), int(mo), int(d), 12, 0, 0, 0, 0, 0))
    except Exception:  # noqa: BLE001
        return None


def date_near(page, pos, window=400):
    """Tim ngay dang sau vi tri link. Tra ve epoch giay, hoac None neu khong thay."""
    chunk = page[pos: pos + window]
    now = time.time()
    for kind, rx in DATE_RES:
        m = rx.search(chunk)
        if not m:
            continue
        if kind == "ymd":
            ts = _epoch(m.group(1), m.group(2), m.group(3))
        elif kind == "mdy":
            mo = MONTHS.get(m.group(1).lower())
            ts = _epoch(m.group(3), mo, m.group(2)) if mo else None
        else:  # "md" khong co nam -> doan nam hien tai, lech qua xa thi lui 1 nam
            year = time.gmtime(now).tm_year
            ts = _epoch(year, m.group(1), m.group(2))
            if ts and ts - now > 30 * 86400:
                ts = _epoch(year - 1, m.group(1), m.group(2))
        if ts:
            return ts
    return None


def too_old(ts):
    """True neu BIET ngay va ngay do cu hon nguong. Khong biet ngay -> khong loai."""
    if not ts or MAX_AGE_HOURS <= 0:
        return False
    return (time.time() - ts) > MAX_AGE_HOURS * 3600


NORM_RE = re.compile(r"[^a-z0-9#]+")


def norm_title(title):
    """Chuan hoa tieu de de so trung: thuong hoa, bo dau cau, gop khoang trang.
    Giu lai chu so va dau # vi 'PrimePool #39' va '#40' la hai su kien khac nhau."""
    return NORM_RE.sub(" ", (title or "").lower()).strip()


def prettify(slug):
    """Fallback: bien slug thanh tieu de doc duoc."""
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:]


def find_title(page, link_start, slug):
    """Lay text ben trong the <a> chua link; khong co thi suy ra tu slug."""
    open_tag_end = page.find(">", link_start)
    close = page.find("</a>", open_tag_end) if open_tag_end != -1 else -1
    if open_tag_end != -1 and close != -1 and close - open_tag_end < 4000:
        inner = page[open_tag_end + 1: close]
        text = html.unescape(TAG_RE.sub(" ", inner))
        text = WS_RE.sub(" ", text).strip()
        if 5 <= len(text) <= 300:
            return text
    return prettify(slug)


def collect():
    """Tra ve dict {article_id: {...}} tu tat ca nguon."""
    global _budget_until
    found = {}
    # Nguon dung API chinh thuc (nhanh, on dinh) lam truoc
    if WATCH_KUCOIN:
        _collect_kucoin(found)
    if WATCH_COINEX:
        _collect_coinex(found)
    # Nguon phai cao HTML lam sau, moi cai co tran thoi gian rieng
    if WATCH_HTX:
        _collect_htx(found)
    _budget_until = time.monotonic() + FETCH_BUDGET
    _collect_mexc(found)
    _budget_until = None
    return found


def _collect_htx(found):
    """HTX: cao trang danh muc thong bao, loc tieu de co Primepool/Primelist."""
    global _budget_until
    _budget_until = time.monotonic() + HTX_BUDGET
    for label, url in HTX_LISTS:
        log(f"Dang kiem tra {label}: {url}")
        try:
            page = fetch(url, valid=lambda b: "/support/" in b)
        except RuntimeError as e:
            log(f"  ! bo qua {label}: {e}")
            note(label, False)
            continue
        page = page.replace("\\/", "/")

        n = old = raw = 0
        for m in HTX_LINK_RE.finditer(page):
            raw += 1
            title = find_title(page, m.start(), "")
            kind = classify(title, HTX_FILTER) if title else None
            if not kind:
                continue
            ts = date_near(page, m.start())
            if too_old(ts):
                old += 1
                continue
            n += 1
            aid = "htx:" + m.group("id")
            if aid in found:
                continue
            found[aid] = {
                "id": aid,
                "title": title,
                "url": HTX_BASE + m.group("path"),
                "sources": [label],
                "ts": ts,
                "kind": kind,
            }
        note(label, True, raw, n)
        log(f"  -> {n} bai khop tren {raw} bai doc duoc"
            + (f" ({old} bai qua cu)" if old else ""))
    _budget_until = None


def _collect_coinex(found):
    """CoinEx: API Zendesk cua trang thong bao, muc Events."""
    log("Dang kiem tra CoinEx (Events)")
    try:
        body = fetch(COINEX_API, valid=lambda b: '"articles"' in b)
    except RuntimeError as e:
        log(f"  ! bo qua CoinEx: {e}")
        note("CoinEx", False)
        return

    try:
        arts = json.loads(body).get("articles") or []
    except Exception as e:  # noqa: BLE001
        log(f"  ! CoinEx tra ve JSON hong: {e}")
        note("CoinEx", False)
        return

    n = old = 0
    for a in arts:
        title = (a.get("title") or "").strip()
        kind = classify(title, COINEX_FILTER) if title else None
        if not kind:
            continue
        ts = None
        raw = a.get("created_at") or ""
        m = re.match(r"(20\d{2})-(\d{2})-(\d{2})", raw)
        if m:
            ts = _epoch(*m.groups())
        if too_old(ts):
            old += 1
            continue
        n += 1
        aid = "cx:" + str(a.get("id"))
        if aid in found:
            continue
        found[aid] = {
            "id": aid,
            "title": title,
            "url": a.get("html_url") or "https://www.coinex.com/en/announcements",
            "sources": ["CoinEx"],
            "ts": ts,
            "kind": kind,
        }
    note("CoinEx", True, len(arts), n)
    log(f"  -> {n} bai khop tren {len(arts)} bai doc duoc"
        + (f" ({old} bai qua cu)" if old else ""))


def _collect_kucoin(found):
    """KuCoin: goi API chinh thuc roi loc theo tu khoa GemPool/Launchpool."""
    for ann_type in KUCOIN_TYPES:
        url = (f"{KUCOIN_API}?currentPage=1&pageSize=30"
               f"&annType={ann_type}&lang=en_US")
        log(f"Dang kiem tra KuCoin ({ann_type})")
        label = f"KuCoin {ann_type}"
        try:
            body = fetch(url, valid=lambda b: '"annId"' in b)
        except RuntimeError as e:
            log(f"  ! bo qua KuCoin {ann_type}: {e}")
            note(label, False)
            continue

        try:
            items = (json.loads(body).get("data") or {}).get("items") or []
        except Exception as e:  # noqa: BLE001
            log(f"  ! KuCoin tra ve JSON hong: {e}")
            note(label, False)
            continue

        n = old = 0
        for it in items:
            title = (it.get("annTitle") or "").strip()
            kind = classify(title, KUCOIN_FILTER) if title else None
            if not kind:
                continue
            ts = (it.get("cTime") or 0) / 1000 or None
            if too_old(ts):
                old += 1
                continue
            n += 1
            aid = "kc:" + str(it.get("annId"))
            if aid in found:
                continue
            found[aid] = {
                "id": aid,
                "title": title,
                "url": it.get("annUrl") or "https://www.kucoin.com/gempool",
                "sources": ["KuCoin Launchpool"],
                "ts": ts,
                "kind": kind,
            }
        note(label, True, len(items), n)
        log(f"  -> {n} bai khop tren {len(items)} bai doc duoc"
            + (f" ({old} bai qua cu)" if old else ""))


def _collect_mexc(found):
    for label, path, keyword in SOURCES:
        url = f"{BASE}/{LANG}{path}" if LANG and LANG != "en-US" else f"{BASE}{path}"
        log(f"Dang kiem tra {label}: {url}")
        try:
            page = fetch(url)
        except RuntimeError as e:
            log(f"  ! bo qua {label}: {e}")
            note(label, False)
            continue
        page = page.replace("\\/", "/")   # go escape trong payload JSON

        n = old = raw = 0
        for m in ARTICLE_RE.finditer(page):
            raw += 1
            aid = m.group("id")
            slug = m.group("slug")
            in_href = "href=" in page[max(0, m.start() - 60):m.start()]
            title = find_title(page, m.start(), slug) if in_href else prettify(slug)
            kind = classify(f"{title} {slug}", keyword)
            if not kind:
                continue
            ts = date_near(page, m.start())
            if too_old(ts):
                old += 1
                continue
            n += 1
            if aid in found:
                if label not in found[aid]["sources"]:
                    found[aid]["sources"].append(label)
                continue
            found[aid] = {
                "id": aid,
                "title": title,
                "url": BASE + m.group("path"),
                "sources": [label],
                "ts": ts,
                "kind": kind,
            }
        note(label, True, raw, n)
        log(f"  -> {n} bai khop tren {raw} bai doc duoc"
            + (f" ({old} bai qua cu)" if old else ""))


def _blank_state():
    return {"seen": {}, "titles": {}, "initialized": False,
            "agenda": {}, "health": {}}


def load_state():
    if not STATE_FILE.exists():
        return _blank_state()
    try:
        data = json.loads(STATE_FILE.read_text("utf-8"))
        for k, v in _blank_state().items():
            data.setdefault(k, v)
        return data
    except Exception as e:  # noqa: BLE001
        log(f"! state hong ({e}), tao lai tu dau")
        return _blank_state()


def save_state(state):
    # giu toi da 800 id gan nhat cho file khoi phinh
    seen = state["seen"]
    if len(seen) > 800:
        keep = sorted(seen.items(), key=lambda kv: kv[0], reverse=True)[:800]
        state["seen"] = dict(keep)

    # kho tieu de chi can giu trong khoang dedupe, qua han thi don di
    if TITLE_DEDUPE_DAYS > 0:
        cutoff = time.time() - TITLE_DEDUPE_DAYS * 86400
        state["titles"] = {k: v for k, v in state.get("titles", {}).items() if v >= cutoff}
    else:
        state["titles"] = {}
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def telegram_send(text):
    if DRY_RUN:
        log("DRY_RUN, khong gui:\n" + text)
        return True
    if not BOT_TOKEN or not CHAT_ID:
        log("! thieu TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID")
        return False

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for i in range(3):
        try:
            req = urllib.request.Request(url, data=payload)
            with urllib.request.urlopen(req, timeout=20) as r:
                json.loads(r.read().decode())
                return True
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            log(f"! Telegram HTTP {e.code}: {body}")
            if e.code == 429:
                time.sleep(5 * (i + 1))
                continue
            return False
        except Exception as e:  # noqa: BLE001
            log(f"! Telegram loi: {e}")
            time.sleep(2 ** i)
    return False


# ---------------------------------------------------------------- suc khoe bot

def check_health(state):
    """Bot hong ma im lang thi giong het 'dang khong co pool nao'. Hai kieu hong:

      1. Khong tai duoc nguon nao (Cloudflare chan, proxy chet het).
      2. Tai duoc nhung boc ra 0 bai - san doi HTML, regex khong con khop.
         Kieu nay nguy hiem hon: Actions van xanh, bot van 'chay', nhung mu tit.
    """
    h = state.setdefault("health", {})
    h.setdefault("sources", {})
    msgs = []

    if _sources_ok == 0:
        h["fail_streak"] = h.get("fail_streak", 0) + 1
        if (HEALTH_ALERT and h["fail_streak"] >= HEALTH_DOWN_AFTER
                and not h.get("down_notified")):
            msgs.append(
                "🛑 <b>Bot khong tai duoc nguon nao</b>\n\n"
                f"Da that bai {h['fail_streak']} lan lien tiep. "
                "Co the IP bi chan hoac cac proxy doc trang deu chet.\n"
                "Trong luc nay bot KHONG the phat hien pool moi.")
            h["down_notified"] = True
    else:
        if h.get("down_notified"):
            msgs.append("✅ <b>Bot da tai duoc nguon tro lai</b>")
        h["fail_streak"] = 0
        h["down_notified"] = False

    for label, st in _stats.items():
        if not st["ok"]:
            continue
        rec = h["sources"].setdefault(label, {})
        if st["raw"] > 0:
            if rec.get("notified"):
                msgs.append(f"✅ <b>Nguon {html.escape(label)} boc bai lai binh thuong</b>")
            rec["zero"] = 0
            rec["notified"] = False
        else:
            rec["zero"] = rec.get("zero", 0) + 1
            if (HEALTH_ALERT and rec["zero"] >= HEALTH_PARSE_AFTER
                    and not rec.get("notified")):
                msgs.append(
                    f"⚠️ <b>Nguon {html.escape(label)} co the da hong</b>\n\n"
                    f"Tai trang thanh cong {rec['zero']} lan lien tiep nhung khong "
                    "boc duoc bai nao. Nhieu kha nang san doi cau truc HTML, "
                    "can sua lai regex.")
                rec["notified"] = True

    for m in msgs:
        telegram_send(m)
    return len(msgs)


# ---------------------------------------------------------------- lich pool

def local_time(ts, fmt="%H:%M %d/%m"):
    return time.strftime(fmt, time.gmtime(ts + TZ_H * 3600))


def human_left(sec):
    sec = max(0, int(sec))
    h, m = sec // 3600, (sec % 3600) // 60
    if h >= 24:
        return f"{h // 24} ngay {h % 24} gio"
    if h:
        return f"{h} gio {m} phut"
    return f"{m} phut"


def detail_lines(d):
    """Cac dong 'gio mo/dong' + 'tong thuong' de gan vao tin bao pool moi."""
    out = []
    if d.get("start") or d.get("end"):
        parts = []
        if d.get("start"):
            parts.append("Mo " + local_time(d["start"]))
        if d.get("end"):
            parts.append("Dong " + local_time(d["end"]))
        out.append("🕐 " + " · ".join(parts) + " (gio VN)")
    if d.get("rewards"):
        out.append("🎁 Thuong: " + html.escape(d["rewards"]))
    return out


def remember_schedule(state, a, detail, tag):
    if not (detail.get("start") or detail.get("end")):
        return
    state.setdefault("agenda", {})[a["id"]] = {
        "title": a["title"],
        "url": a["url"],
        "tag": tag,
        "start": detail.get("start"),
        "end": detail.get("end"),
        "sent": [],
    }


def run_agenda(state):
    """Bao truoc khi pool mo, va bao truoc khi pool dong de con kip rut token."""
    now = time.time()
    agenda = state.setdefault("agenda", {})
    sent = 0
    for aid, it in sorted(agenda.items()):
        start, end = it.get("start"), it.get("end")
        # pool da dong han 3 ngay -> quen di cho nhe state
        if end and now > end + 3 * 86400:
            del agenda[aid]
            continue
        if not end and start and now > start + 30 * 86400:
            del agenda[aid]
            continue
        if sent >= MAX_REMINDERS:
            continue

        done = it.setdefault("sent", [])
        head = f'<b>{html.escape(it["title"])}</b>\n\n'
        tail = f'\n\n<a href="{it["url"]}">Xem thong bao</a>'

        if (start and "open" not in done
                and -1800 <= start - now <= REMIND_START_MIN * 60):
            when = ("dang mo" if start <= now
                    else "con " + human_left(start - now))
            if telegram_send(
                    f"⏰ <b>Pool sap mo</b> - {when}\n"
                    f"{html.escape(it.get('tag') or '')}\n\n{head}"
                    f"🕐 Mo luc {local_time(start)} (gio VN){tail}"):
                done.append("open")
                sent += 1
                log(f"Da nhac mo: {it['title'][:60]}")

        if (end and "close" not in done
                and 0 <= end - now <= REMIND_END_HOURS * 3600):
            if telegram_send(
                    f"⚠️ <b>Pool sap dong</b> - con {human_left(end - now)}\n"
                    f"{html.escape(it.get('tag') or '')}\n\n{head}"
                    f"Nho rut token ve.\n"
                    f"🕐 Dong luc {local_time(end)} (gio VN){tail}"):
                done.append("close")
                sent += 1
                log(f"Da nhac dong: {it['title'][:60]}")
    return sent


def main():
    state = load_state()
    found = collect()
    check_health(state)

    if _sources_ok == 0:
        # Khong nguon nao tai duoc -> loi that su, giu nguyen state de lan sau bat lai
        log("! Khong nguon nao tai duoc (bi chan IP hoac tat ca proxy chet). Giu nguyen state.")
        save_state(state)
        return 1

    log(f"Da tai duoc {_sources_ok} nguon, tim thay {len(found)} bai trong pham vi theo doi.")

    new = [a for aid, a in found.items() if aid not in state["seen"]]
    new.sort(key=lambda a: a["id"], reverse=True)

    if not state["initialized"]:
        # Lan chay dau: chi ghi nhan, khong ban 30 tin cu vao mat
        now = time.time()
        for aid, a in found.items():
            state["seen"][aid] = a["title"]
            state["titles"][norm_title(a["title"])] = now
        state["initialized"] = True
        save_state(state)
        telegram_send(
            "✅ <b>Pool watcher da khoi dong</b>\n"
            f"Da ghi nhan {len(found)} pool dang mo. "
            "Tu gio chi bao khi co pool <b>moi</b>."
        )
        log(f"Khoi tao xong voi {len(found)} bai.")
        return 0

    if len(new) > MAX_NOTIFY:
        log(f"! {len(new)} bai moi cung luc - nghi ngo MEXC doi HTML, chi gui {MAX_NOTIFY} bai.")
        new = new[:MAX_NOTIFY]

    if not new:
        log("Khong co pool moi.")

    ok_all = True
    dup = 0
    detail_until = time.monotonic() + ARTICLE_BUDGET
    for a in new:
        key = norm_title(a["title"])
        if TITLE_DEDUPE_DAYS > 0 and key and key in state["titles"]:
            # bai nay da bao roi duoi mot ID khac (san sua bai / dang lai o muc khac)
            state["seen"][a["id"]] = a["title"]
            dup += 1
            log(f"Bo qua (trung tieu de da bao): {a['title'][:70]}")
            continue

        tag = " / ".join(a["sources"])
        kind = a.get("kind", "pool")
        when = ""
        if a.get("ts"):
            when = "\n📅 " + time.strftime("%d/%m/%Y", time.gmtime(a["ts"]))

        # Mo bai ra lay gio mo/dong pool. Tin burn thi khong can - no la tin da roi.
        detail = {}
        if kind == "pool" and ARTICLE_DETAIL and time.monotonic() < detail_until:
            detail = article.enrich(a["url"], fetch)
            if detail:
                log(f"  (boc duoc tu than bai: {', '.join(sorted(detail))})")

        if kind == "burn":
            head = f"🔥 <b>{html.escape(tag)} · Tin burn/buyback</b>"
        else:
            head = f"🚀 <b>{html.escape(tag)}</b>"
        extra = detail_lines(detail)
        msg = (
            f"{head}{when}\n\n"
            f"<b>{html.escape(a['title'])}</b>\n\n"
            + ("\n".join(extra) + "\n\n" if extra else "")
            + f'<a href="{a["url"]}">Xem thong bao</a>'
        )
        if telegram_send(msg):
            state["seen"][a["id"]] = a["title"]
            state["titles"][key] = time.time()
            remember_schedule(state, a, detail, tag)
            log(f"Da gui: {a['title']}")
        else:
            ok_all = False
            log(f"! Gui that bai, se thu lai lan sau: {a['title']}")
        time.sleep(1)

    if dup:
        log(f"({dup} bai bi chan vi trung tieu de voi bai da bao)")

    run_agenda(state)
    save_state(state)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
