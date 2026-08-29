#!/usr/bin/env python3
"""
MEXC Launchpool / Airdrop+ / Kickstarter watcher -> Telegram

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
  DRY_RUN          ("1" = khong gui Telegram, chi in ra man hinh)
"""

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

BASE = "https://www.mexc.com"
LANG = os.getenv("MEXC_LANG", "en-US")
STATE_FILE = pathlib.Path(os.getenv("STATE_FILE", "seen.json"))
MAX_NOTIFY = int(os.getenv("MAX_NOTIFY", "10"))
DRY_RUN = os.getenv("DRY_RUN") == "1"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# (nhan hien thi, duong dan, bo loc tu khoa hoac None = lay tat ca)
SOURCES = [
    ("Launchpool",  "/announcements/tag/launchpool-28", None),
    ("Airdrop+",    "/announcements/tag/airdrop-32",    None),
    ("Kickstarter", "/announcements/new-listings",
     re.compile(r"kickstarter|launchpool|airdrop", re.I)),
]

# href="/announcements/article/ten-bai-viet-17827791534551"  (co the co prefix ngon ngu)
ARTICLE_RE = re.compile(
    r'href="(?P<path>/(?:[a-z]{2}-[A-Z]{2}/)?announcements/article/'
    r'(?P<slug>[A-Za-z0-9\-]+?)-(?P<id>\d{10,}))"'
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def fetch(url, tries=3):
    """Tai HTML, co retry + backoff."""
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
            "Cache-Control": "no-cache",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"  ! loi tai {url}: {e} (lan {i + 1}/{tries})")
            time.sleep(2 ** i + random.random())
    raise RuntimeError(f"khong tai duoc {url}: {last}")


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
    found = {}
    for label, path, keyword in SOURCES:
        url = f"{BASE}/{LANG}{path}" if LANG and LANG != "en-US" else f"{BASE}{path}"
        log(f"Dang kiem tra {label}: {url}")
        try:
            page = fetch(url)
        except RuntimeError as e:
            log(f"  ! bo qua {label}: {e}")
            continue

        n = 0
        for m in ARTICLE_RE.finditer(page):
            aid = m.group("id")
            slug = m.group("slug")
            title = find_title(page, m.start(), slug)
            if keyword and not (keyword.search(title) or keyword.search(slug)):
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
            }
        log(f"  -> {n} bai khop")
    return found


def load_state():
    if not STATE_FILE.exists():
        return {"seen": {}, "initialized": False}
    try:
        data = json.loads(STATE_FILE.read_text("utf-8"))
        data.setdefault("seen", {})
        data.setdefault("initialized", False)
        return data
    except Exception as e:  # noqa: BLE001
        log(f"! state hong ({e}), tao lai tu dau")
        return {"seen": {}, "initialized": False}


def save_state(state):
    # giu toi da 800 id gan nhat cho file khoi phinh
    seen = state["seen"]
    if len(seen) > 800:
        keep = sorted(seen.items(), key=lambda kv: kv[0], reverse=True)[:800]
        state["seen"] = dict(keep)
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


def main():
    state = load_state()
    found = collect()

    if not found:
        log("Khong lay duoc bai nao (MEXC co the doi giao dien hoac chan IP). Giu nguyen state.")
        return 1

    new = [a for aid, a in found.items() if aid not in state["seen"]]
    new.sort(key=lambda a: a["id"], reverse=True)

    if not state["initialized"]:
        # Lan chay dau: chi ghi nhan, khong ban 30 tin cu vao mat
        for aid, a in found.items():
            state["seen"][aid] = a["title"]
        state["initialized"] = True
        save_state(state)
        telegram_send(
            "✅ <b>MEXC watcher da khoi dong</b>\n"
            f"Da ghi nhan {len(found)} bai hien co. "
            "Tu gio chi bao khi co bai <b>moi</b>."
        )
        log(f"Khoi tao xong voi {len(found)} bai.")
        return 0

    if not new:
        log("Khong co bai moi.")
        save_state(state)
        return 0

    if len(new) > MAX_NOTIFY:
        log(f"! {len(new)} bai moi cung luc - nghi ngo MEXC doi HTML, chi gui {MAX_NOTIFY} bai.")
        new = new[:MAX_NOTIFY]

    ok_all = True
    for a in new:
        tag = " / ".join(a["sources"])
        msg = (
            f"🚀 <b>MEXC {html.escape(tag)}</b>\n\n"
            f"<b>{html.escape(a['title'])}</b>\n\n"
            f'<a href="{a["url"]}">Xem thong bao</a>'
        )
        if telegram_send(msg):
            state["seen"][a["id"]] = a["title"]
            log(f"Da gui: {a['title']}")
        else:
            ok_all = False
            log(f"! Gui that bai, se thu lai lan sau: {a['title']}")
        time.sleep(1)

    save_state(state)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
