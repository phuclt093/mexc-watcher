#!/usr/bin/env python3
"""
Theo doi burn token san (MX, KCS, HTX, CET) -> Telegram

Cach hoat dong:
  1. Doc TONG CUNG (total supply) hien tai cua tung token.
     - Uu tien on-chain qua Etherscan API V2 (chinh xac, cap nhat tuc thi)
     - Khong co key / token da chain -> lay tu CoinGecko
  2. So voi so lieu lan truoc luu trong burn.json:
     - cung giam  -> san vua BURN -> ban tin ngay
     - cung tang  -> chi ghi log (san mint them / nguon sai)
  3. Luu snapshot dau moi ngay (UTC) -> tinh duoc "hom nay burn bao nhieu",
     "7 ngay", "30 ngay".
  4. Moi tuan (mac dinh sang thu Hai) ban 1 tin tong ket ca 4 token.

Da burn = cung ban dau - tong cung hien tai.  Con lai = tong cung hien tai.

Bien moi truong:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (bat buoc, dung chung voi mexc_watch)
  ETHERSCAN_API_KEY      key mien phi tu etherscan.io -> bat doc on-chain
  COINGECKO_API_KEY      Demo key mien phi tu coingecko.com (khuyen dung, do bi 429)
  BURN_WATCH             "0" de tat han tinh nang nay
  BURN_TOKENS            danh sach token theo doi, vd "MX,KCS" (mac dinh tat ca)
  BURN_STATE_FILE        mac dinh "burn.json"
  BURN_INTERVAL_MIN      mac dinh 60 - toi thieu bao nhieu phut moi kiem tra lai
  BURN_MIN_PCT           mac dinh 0.005 - bo qua thay doi nho hon % nay (nhieu lam tron)
  BURN_DIGEST_DAY        mac dinh "mon" (mon..sun | daily | off) - ngay gui tong ket
  BURN_DIGEST_HOUR_UTC   mac dinh 1 (= 8h sang gio VN)
  DRY_RUN                "1" = in ra man hinh, khong gui Telegram
"""

import html
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

from mexc_watch import PROXIES, UA, log, telegram_send

STATE_FILE = pathlib.Path(os.getenv("BURN_STATE_FILE", "burn.json"))
ENABLED = os.getenv("BURN_WATCH", "1") != "0"
INTERVAL_MIN = int(os.getenv("BURN_INTERVAL_MIN", "60"))
MIN_PCT = float(os.getenv("BURN_MIN_PCT", "0.005"))
DIGEST_DAY = os.getenv("BURN_DIGEST_DAY", "mon").strip().lower()
DIGEST_HOUR = int(os.getenv("BURN_DIGEST_HOUR_UTC", "1"))
ONLY = [s.strip().upper() for s in os.getenv("BURN_TOKENS", "").split(",") if s.strip()]
# Token khong phai cua minh: chi bao khi dot LON, khoi nhieu vi burn thoi gian thuc
OTHER_MIN_PCT = float(os.getenv("BURN_OTHER_MIN_PCT", "0.5"))
# Thu muc xuat du lieu cho trang bieu do (de trong = tat)
DOCS_DIR = pathlib.Path(os.getenv("DOCS_DATA_DIR", "docs/data"))

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "").strip()
CG_KEY = os.getenv("COINGECKO_API_KEY", "").strip()

CG_BASE = "https://api.coingecko.com/api/v3"
ES_BASE = "https://api.etherscan.io/v2/api"

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# initial  = cung ban dau (truoc khi burn dot nao) -> dung de tinh "tong da dot"
# contract = chi dat khi TOAN BO cung nam tren 1 contract EVM duy nhat.
#            CET (Ethereum chi la phan cau noi, cung that nam tren CoinEx Chain) va
#            HTX (trai tren TRON + ETH + BSC) -> khong doc on-chain duoc bang 1 lenh,
#            de None va lay so tong hop cua CoinGecko.
TOKENS = [
    # own=True: token ban dang giu -> bao moi lan dot du nho
    dict(key="MX", exch="MEXC", own=True, initial=1_000_000_000,
         cg=["mx-token"],
         chain=1, contract="0x11eeF04c884E24d9B7B4760e7476D06ddF797f36", decimals=18),
    dict(key="KCS", exch="KuCoin", own=True, initial=200_000_000,
         cg=["kucoin-shares", "kucoin-token"],
         chain=1, contract="0xf34960d9d60be18cC1D5Afc1A6F012A723a28811", decimals=6),
    dict(key="HTX", exch="HTX", own=True, initial=999_990_000_000_000,
         cg=["htx-dao", "htx"],
         chain=None, contract=None, decimals=None),
    dict(key="CET", exch="CoinEx", own=True, initial=10_000_000_000,
         cg=["coinex-token"],
         chain=None, contract=None, decimals=None),
    # own=False: theo doi de so sanh, chi bao khi dot lon (>= BURN_OTHER_MIN_PCT)
    dict(key="BNB", exch="Binance", own=False, initial=200_000_000,
         cg=["binancecoin"],
         chain=None, contract=None, decimals=None),
    dict(key="OKB", exch="OKX", own=False, initial=300_000_000,
         cg=["okb"],
         chain=None, contract=None, decimals=None),
    dict(key="BGB", exch="Bitget", own=False, initial=2_000_000_000,
         cg=["bitget-token"],
         chain=None, contract=None, decimals=None),
    dict(key="GT", exch="Gate", own=False, initial=300_000_000,
         cg=["gatetoken", "gatechain-token"],
         chain=None, contract=None, decimals=None),
]


# ---------------------------------------------------------------- HTTP

def _http(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url, want=None, tries=2):
    """Tai JSON: thu truc tiep truoc, that bai thi di vong qua proxy doc trang.
    API key luon nam trong query string (khong dung header) de con proxy duoc."""
    last = None
    for i in range(tries):
        try:
            data = json.loads(_http(url))
            if want and not want(data):
                raise ValueError("JSON khong co du lieu mong doi")
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"  ! truc tiep loi ({e}) - lan {i + 1}/{tries}")
            time.sleep(1.5 * (i + 1))
    for name, build in PROXIES:
        try:
            data = json.loads(_http(build(url), timeout=40))
            if want and not want(data):
                raise ValueError("JSON khong co du lieu mong doi")
            log(f"  (qua proxy {name})")
            return data
        except Exception as e:  # noqa: BLE001
            last = e
    log(f"  ! khong lay duoc {url.split('?')[0]} ({last})")
    return None


# ---------------------------------------------------------------- nguon so lieu

def etherscan_decimals(t, state):
    """Goi decimals() tren contract, cache lai trong state de khoi hoi lai."""
    cache = state.setdefault("decimals", {})
    if t["key"] in cache:
        return cache[t["key"]]
    url = (f"{ES_BASE}?chainid={t['chain']}&module=proxy&action=eth_call"
           f"&to={t['contract']}&data=0x313ce567&tag=latest&apikey={ETHERSCAN_KEY}")
    d = get_json(url, want=lambda j: isinstance(j.get("result"), str))
    dec = t["decimals"]
    if d:
        try:
            v = int(d["result"], 16)
            if 0 <= v <= 36:
                dec = v
        except Exception:  # noqa: BLE001
            pass
    cache[t["key"]] = dec
    return dec


def etherscan_supply(t, state):
    if not (ETHERSCAN_KEY and t["contract"]):
        return None
    dec = etherscan_decimals(t, state)
    url = (f"{ES_BASE}?chainid={t['chain']}&module=stats&action=tokensupply"
           f"&contractaddress={t['contract']}&apikey={ETHERSCAN_KEY}")
    d = get_json(url, want=lambda j: str(j.get("status")) == "1" and j.get("result"))
    if not d:
        return None
    try:
        return int(str(d["result"])) / (10 ** dec)
    except Exception as e:  # noqa: BLE001
        log(f"  ! Etherscan tra ve so la cho {t['key']}: {e}")
        return None


def coingecko_rows():
    """1 lan goi lay ca supply lan gia cua tat ca token."""
    ids = sorted({c for t in TOKENS for c in t["cg"]})
    url = (f"{CG_BASE}/coins/markets?vs_currency=usd"
           f"&ids={urllib.parse.quote(','.join(ids))}&per_page=250&page=1")
    if CG_KEY:
        url += "&x_cg_demo_api_key=" + urllib.parse.quote(CG_KEY)
    log("Dang hoi CoinGecko ve cung cac token")
    data = get_json(url, want=lambda j: isinstance(j, list))
    rows = {}
    for row in (data or []):
        if isinstance(row, dict) and row.get("id"):
            rows[row["id"]] = row
    log(f"  -> CoinGecko tra ve {len(rows)} token")
    return rows


def read_token(t, state, cg):
    """Tra ve (tong_cung, nguon, gia_usd) - gia co the None."""
    price = None
    for cid in t["cg"]:
        row = cg.get(cid)
        if row and row.get("current_price"):
            price = row["current_price"]
            break

    supply = etherscan_supply(t, state)
    if supply:
        return supply, "on-chain", price

    for cid in t["cg"]:
        row = cg.get(cid)
        if row and row.get("total_supply"):
            return float(row["total_supply"]), "CoinGecko", price
    return None, None, price


# ---------------------------------------------------------------- dinh dang

def fmt(x):
    """So token: rut gon T / B / M cho de doc."""
    if x is None:
        return "?"
    a = abs(x)
    if a >= 1e12:
        return f"{x / 1e12:,.3f}T"
    if a >= 1e9:
        return f"{x / 1e9:,.3f}B"
    if a >= 1e6:
        return f"{x / 1e6:,.3f}M"
    if a >= 1000:
        return f"{x:,.0f}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def fmt_usd(x):
    if not x:
        return ""
    a = abs(x)
    if a >= 1e9:
        return f" (~${x / 1e9:,.2f}B)"
    if a >= 1e6:
        return f" (~${x / 1e6:,.2f}M)"
    if a >= 1000:
        return f" (~${x:,.0f})"
    return f" (~${x:,.2f})"


def bar(pct, width=10):
    n = max(0, min(width, int(round(pct / 100 * width))))
    return "█" * n + "░" * (width - n)


# ---------------------------------------------------------------- state

def load_state():
    if not STATE_FILE.exists():
        return {"tokens": {}, "decimals": {}}
    try:
        d = json.loads(STATE_FILE.read_text("utf-8"))
        d.setdefault("tokens", {})
        d.setdefault("decimals", {})
        return d
    except Exception as e:  # noqa: BLE001
        log(f"! burn state hong ({e}), tao lai tu dau")
        return {"tokens": {}, "decimals": {}}


def save_state(state):
    for rec in state.get("tokens", {}).values():
        days = rec.get("days") or {}
        if len(days) > 40:
            rec["days"] = dict(sorted(days.items())[-40:])
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")


def burn_since(rec, supply, days_back):
    """Da dot bao nhieu ke tu dau ngay (hom nay - days_back)."""
    days = rec.get("days") or {}
    if not days:
        return None
    cutoff = time.strftime("%Y-%m-%d",
                           time.gmtime(time.time() - days_back * 86400))
    older = [v for k, v in sorted(days.items()) if k >= cutoff]
    if not older:
        return None
    return max(0.0, older[0] - supply)


# ---------------------------------------------------------------- tin nhan

def alert_burn(t, burned, supply, price):
    initial = t["initial"]
    total_burned = initial - supply
    msg = (
        f"🔥 <b>{html.escape(t['exch'])} vua burn {html.escape(t['key'])}</b>\n\n"
        f"Dot nay: <b>{fmt(burned)} {t['key']}</b>"
        f"{fmt_usd(burned * price if price else 0)}\n"
        f"Tong da dot: {fmt(total_burned)} / {fmt(initial)} "
        f"({total_burned / initial * 100:.2f}%)\n"
        f"Con lai: <b>{fmt(supply)} {t['key']}</b>\n"
        f"{bar(total_burned / initial * 100)}"
    )
    return telegram_send(msg)


def _own_block(t, state):
    supply, initial = t["supply"], t["initial"]
    total_burned = initial - supply
    pct = total_burned / initial * 100
    rec = state["tokens"].get(t["key"], {})
    d1 = burn_since(rec, supply, 0)
    d7 = burn_since(rec, supply, 7)
    d30 = burn_since(rec, supply, 30)
    return (
        f"🔥 <b>{html.escape(t['key'])}</b> · {html.escape(t['exch'])}\n"
        f"   Con lai: <b>{fmt(supply)}</b> / {fmt(initial)}\n"
        f"   Da dot: {fmt(total_burned)} ({pct:.2f}%) {bar(pct)}\n"
        f"   Hom nay: {fmt(d1) if d1 is not None else '—'}"
        f" · 7 ngay: {fmt(d7) if d7 is not None else '—'}"
        f" · 30 ngay: {fmt(d30) if d30 is not None else '—'}\n"
        f"   <i>nguon: {t['source']}</i>\n")


def digest(state, snapshot):
    have = [t for t in snapshot if t["supply"]]
    if not have:
        log("! Khong co token nao co so lieu, bo qua tin tong ket.")
        return False

    lines = ["📊 <b>Tong ket burn token san</b>",
             time.strftime("%d/%m/%Y", time.gmtime()), ""]

    mine = [t for t in have if t.get("own")]
    if mine:
        lines.append("<b>━ Token ban dang giu ━</b>\n")
        for t in mine:
            lines.append(_own_block(t, state))

    others = sorted((t for t in have if not t.get("own")),
                    key=lambda t: -(t["initial"] - t["supply"]) / t["initial"])
    if others:
        lines.append("<b>━ Cac san khac ━</b>")
        rows = []
        for t in others:
            pct = (t["initial"] - t["supply"]) / t["initial"] * 100
            rows.append(f"{t['key']:<4}{pct:>6.1f}%  {bar(pct, 8)}  con {fmt(t['supply'])}")
        lines.append("<pre>" + "\n".join(rows) + "</pre>")

    missing = [t["key"] for t in snapshot if not t["supply"]]
    if missing:
        lines.append(f"<i>Khong lay duoc so lieu: {', '.join(missing)}</i>")
    lines.append("<i>Da dot = cung ban dau - tong cung hien tai.</i>")
    return telegram_send("\n".join(lines))


def export_docs(state, snapshot):
    """Ghi du lieu cho trang bieu do GitHub Pages. Hong thi ke, khong duoc lam
    gay luong bao burn."""
    if not str(DOCS_DIR).strip():
        return
    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        tokens, rows = [], []
        for r in snapshot:
            if not r["supply"]:
                continue
            rec = state["tokens"].get(r["key"], {})
            burned = r["initial"] - r["supply"]
            tokens.append({
                "key": r["key"], "exch": r["exch"], "own": bool(r.get("own")),
                "initial": r["initial"], "supply": r["supply"], "burned": burned,
                "pct": burned / r["initial"] * 100,
                "source": r["source"], "price": r.get("price"),
                "d1": burn_since(rec, r["supply"], 0),
                "d7": burn_since(rec, r["supply"], 7),
                "d30": burn_since(rec, r["supply"], 30),
                "days": rec.get("days") or {},
            })
            for day, sup in sorted((rec.get("days") or {}).items()):
                rows.append(f"{day},{r['key']},{sup:.0f}")
        tokens.sort(key=lambda x: -x["pct"])
        (DOCS_DIR / "burn.json").write_text(json.dumps(
            {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "tokens": tokens}, ensure_ascii=False, indent=1), "utf-8")
        (DOCS_DIR / "burn_history.csv").write_text(
            "date,token,total_supply\n" + "\n".join(sorted(rows)) + "\n", "utf-8")
        log(f"Da xuat du lieu bieu do ({len(tokens)} token)")
    except Exception as e:  # noqa: BLE001
        log(f"! khong xuat duoc du lieu bieu do: {e}")


def digest_due(state):
    if DIGEST_DAY in ("off", "0", "no"):
        return False
    now = time.gmtime()
    today = time.strftime("%Y-%m-%d", now)
    if state.get("last_digest") == today:
        return False
    if now.tm_hour < DIGEST_HOUR:
        return False
    if DIGEST_DAY == "daily":
        return True
    want = WEEKDAYS.get(DIGEST_DAY)
    if want is None:
        log(f"! BURN_DIGEST_DAY khong hop le ({DIGEST_DAY}), coi nhu 'mon'")
        want = 0
    # tre 1 ngay van gui, de khong mat ban tong ket khi Actions bi tre/loi
    return now.tm_wday == want or (
        state.get("last_digest", "") < time.strftime(
            "%Y-%m-%d", time.gmtime(time.time() - 7 * 86400)))


# ---------------------------------------------------------------- main

def main():
    if not ENABLED:
        log("BURN_WATCH=0, bo qua phan theo doi burn.")
        return 0

    state = load_state()
    now = time.time()
    since = (now - state.get("last_check", 0)) / 60
    force_digest = digest_due(state)
    if since < INTERVAL_MIN and not force_digest:
        log(f"Moi kiem tra burn {since:.0f} phut truoc (nguong {INTERVAL_MIN}p), bo qua.")
        return 0

    tokens = [t for t in TOKENS if not ONLY or t["key"] in ONLY]
    cg = coingecko_rows()

    snapshot = []
    ok_all = True
    first_run = not state["tokens"]
    today = time.strftime("%Y-%m-%d", time.gmtime())

    for t in tokens:
        supply, source, price = read_token(t, state, cg)
        row = dict(t, supply=supply, source=source or "?", price=price)
        snapshot.append(row)
        if not supply:
            log(f"! {t['key']}: khong lay duoc tong cung tu nguon nao.")
            continue
        log(f"{t['key']}: tong cung {fmt(supply)} (nguon {source})")

        rec = state["tokens"].setdefault(t["key"], {})
        prev = rec.get("supply")

        # chan so lieu rac: nhay qua 50% trong 1 lan doc thi gan nhu chac chan la loi nguon
        if prev and not (0.5 * prev <= supply <= 1.5 * prev):
            log(f"! {t['key']}: so lieu nhay bat thuong "
                f"({fmt(prev)} -> {fmt(supply)}), bo qua lan doc nay.")
            continue

        drop = (prev - supply) if prev else 0
        # Token minh giu: bao moi lan dot. Token chi theo doi: chi bao dot lon,
        # vi vai san (BNB) dot theo thoi gian thuc, bao het thi loan.
        thr = MIN_PCT if t.get("own") else OTHER_MIN_PCT
        if prev and drop > 0 and (drop / prev * 100) >= thr:
            log(f"  -> phat hien burn {fmt(drop)} {t['key']}")
            if not first_run and not alert_burn(t, drop, supply, price):
                # gui that bai -> giu nguyen so cu de lan sau bao lai
                ok_all = False
                log(f"  ! gui Telegram that bai, se thu lai: {t['key']}")
                continue
        elif prev and supply > prev:
            log(f"  (cung tang {fmt(supply - prev)} - san mint them hoac nguon lech)")

        rec["supply"] = supply
        rec["source"] = source
        rec["ts"] = now
        rec.setdefault("days", {}).setdefault(today, prev if prev else supply)

    if first_run:
        rows = [r for r in snapshot if r["supply"]]
        if not rows:
            log("! Lan chay dau nhung khong lay duoc so lieu nao, khong luu state.")
            return 1
        telegram_send(
            "✅ <b>Burn watcher da khoi dong</b>\n"
            + "<pre>" + "\n".join(
                f"{r['key']:<4}{(r['initial'] - r['supply']) / r['initial'] * 100:>6.1f}%"
                f"  con {fmt(r['supply'])}"
                for r in sorted(rows, key=lambda x: -(x['initial'] - x['supply']) / x['initial'])
            ) + "</pre>"
            + "\n\nTu gio se bao moi khi san dot them token."
        )
        state["last_check"] = now
        state["last_digest"] = today
        save_state(state)
        export_docs(state, snapshot)
        return 0

    if force_digest and digest(state, snapshot):
        state["last_digest"] = today

    state["last_check"] = now
    save_state(state)
    export_docs(state, snapshot)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
