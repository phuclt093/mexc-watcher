#!/usr/bin/env python3
"""
Boc chi tiet tu than bai thong bao: thoi gian mo/dong pool va tong thuong.

Trang danh sach chi cho tieu de. Moi thu quan trong - pool mo luc nao, dong luc
nao, thuong bao nhieu - nam trong noi dung bai. Module nay tai bai roi rut ra.

Khong import mexc_watch (tranh vong lap import): ham fetch duoc truyen vao.

Cac dinh dang thoi gian gap tren cac san:
  May 25, 2026, 13:00 (UTC)        <- MEXC
  2026-05-25 13:00:00 (UTC+8)      <- KuCoin / HTX
  25 May 2026 13:00 UTC
  25/05/2026 13:00
"""

import calendar
import html
import re
import time

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t ]+")

# Moi mau bat mot moc "ngay + gio". Chi nhan moc CO GIO - ngay tran khong co gio
# thuong la ngay dang bai, khong phai moc su kien.
DT_PATTERNS = [
    # 2026-05-25 13:00[:00]  |  2026/05/25 13:00
    re.compile(r"(?P<y>20\d{2})[-/](?P<mo>\d{1,2})[-/](?P<d>\d{1,2})"
               r"[ T,]+(?P<H>\d{1,2}):(?P<M>\d{2})(?::\d{2})?"),
    # May 25, 2026, 13:00  |  May 25 2026 13:00
    re.compile(r"(?P<mon>[A-Z][a-z]{2})[a-z]*\.?\s+(?P<d>\d{1,2}),?\s+"
               r"(?P<y>20\d{2}),?\s+(?P<H>\d{1,2}):(?P<M>\d{2})"),
    # 25 May 2026 13:00
    re.compile(r"(?P<d>\d{1,2})\s+(?P<mon>[A-Z][a-z]{2})[a-z]*\.?\s+"
               r"(?P<y>20\d{2}),?\s+(?P<H>\d{1,2}):(?P<M>\d{2})"),
    # 25/05/2026 13:00 (chi nhan khi doan duoc dau la ngay dau la thang)
    re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>20\d{2}),?\s+"
               r"(?P<H>\d{1,2}):(?P<M>\d{2})"),
]

# mui gio di ngay sau moc thoi gian: "(UTC)", "UTC+8", "(UTC+05:30)"
TZ_RE = re.compile(r"\s*\(?\s*UTC\s*(?:(?P<sign>[+-])\s*(?P<h>\d{1,2})"
                   r"(?::(?P<m>\d{2}))?)?\s*\)?", re.I)

# dong co kha nang chua khoang thoi gian su kien
PERIOD_HINT = re.compile(
    r"event period|activity period|activity time|staking period|subscription period"
    r"|campaign period|promotion period|farming period|event time|duration"
    r"|thoi gian|thời gian", re.I)

REWARD_HINT = re.compile(
    r"total (airdrop|reward|prize|pool)|prize pool|reward pool|total of|share (a )?\d",
    re.I)

AMOUNT_RE = re.compile(r"\b\d[\d,\.]{2,}\s*[A-Z][A-Z0-9]{1,10}\b")


def to_text(body):
    """HTML / payload JSON -> text thuan, mot dong mot y."""
    if not body:
        return ""
    txt = SCRIPT_RE.sub(" ", body)
    txt = re.sub(r"<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", txt, flags=re.I)
    txt = TAG_RE.sub(" ", txt)
    txt = html.unescape(txt)
    txt = txt.replace("\\n", "\n").replace("\\u002F", "/")
    txt = WS_RE.sub(" ", txt)
    lines = [ln.strip() for ln in txt.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _epoch(y, mo, d, H, M, off_sec=0):
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 0 <= H <= 23 and 0 <= M <= 59):
        return None
    try:
        return calendar.timegm((y, mo, d, H, M, 0, 0, 0, 0)) - off_sec
    except Exception:  # noqa: BLE001
        return None


def _tz_offset(text, pos):
    """Doc mui gio ngay sau moc thoi gian.
    Tra ve so giay lech, hoac None neu cho do khong ghi mui gio nao."""
    m = TZ_RE.match(text, pos)
    if not m or not m.group(0).strip():
        return None
    if not m.group("h"):
        return 0                      # ghi ro "(UTC)"
    off = int(m.group("h")) * 3600 + int(m.group("m") or 0) * 60
    return -off if m.group("sign") == "-" else off


def _raw_stamps(text):
    """[(epoch coi nhu UTC, lech mui gio hoac None)] theo thu tu xuat hien."""
    out = []
    for rx in DT_PATTERNS:
        for m in rx.finditer(text):
            g = m.groupdict()
            y, H, M = int(g["y"]), int(g["H"]), int(g["M"])
            if g.get("mon"):
                mo = MONTHS.get(g["mon"].lower())
                d = int(g["d"])
                if not mo:
                    continue
            elif g.get("a"):
                a, b = int(g["a"]), int(g["b"])
                if a > 12 and b <= 12:
                    d, mo = a, b
                elif b > 12 and a <= 12:
                    mo, d = a, b
                else:
                    continue          # 05/06/2026 - khong doan noi, bo qua
            else:
                mo, d = int(g["mo"]), int(g["d"])
            ts = _epoch(y, mo, d, H, M)
            if ts:
                out.append((ts, _tz_offset(text, m.end())))
    return out


def timestamps(text):
    """Danh sach epoch UTC cua moi moc thoi gian tim thay.

    Nhieu san chi ghi mui gio MOT lan cho ca khoang:
    "2026-05-25 21:00 - 2026-06-25 21:00 (UTC+8)". Moc nao khong co mui gio
    rieng thi muon mui gio duoc ghi ro o cho khac trong cung doan."""
    raw = _raw_stamps(text)
    known = [o for _, o in raw if o is not None]
    default = known[0] if known else 0
    return sorted({ts - (off if off is not None else default) for ts, off in raw})


def parse_period(text, now=None):
    """Tra ve (bat_dau, ket_thuc) dang epoch. Khong chac chan -> (None, None).

    Uu tien dong co chu 'Event Period' / 'Thoi gian'; khong thay thi lay moc som
    nhat va muon nhat trong ca bai."""
    now = now or time.time()
    lo, hi = now - 60 * 86400, now + 365 * 86400

    def pick(stamps):
        stamps = [s for s in stamps if lo <= s <= hi]
        if len(stamps) < 2:
            return None
        a, b = stamps[0], stamps[-1]
        # pool ngan nhat vai gio, dai nhat vai thang - ngoai khoang nay la bat nham
        if not (3600 <= b - a <= 200 * 86400):
            return None
        return a, b

    for line in text.split("\n"):
        if PERIOD_HINT.search(line):
            got = pick(timestamps(line))
            if got:
                return got
    got = pick(timestamps(text))
    return got if got else (None, None)


def parse_rewards(text):
    """Lay chuoi mo ta tong thuong, vd '10,000,000 KSKD'. Khong thay -> None."""
    for line in text.split("\n"):
        if len(line) > 300 or not REWARD_HINT.search(line):
            continue
        m = AMOUNT_RE.search(line)
        if m:
            return m.group(0).strip()
    return None


def enrich(url, fetcher, now=None):
    """Tai bai va boc chi tiet. Loi gi cung tra ve dict rong - khong duoc lam
    hong luong bao pool chinh."""
    try:
        body = fetcher(url, valid=lambda b: bool(b) and len(b) > 500)
    except Exception:  # noqa: BLE001
        return {}
    text = to_text(body)
    if not text:
        return {}
    start, end = parse_period(text, now)
    out = {}
    if start:
        out["start"] = start
    if end:
        out["end"] = end
    rw = parse_rewards(text)
    if rw:
        out["rewards"] = rw
    return out
