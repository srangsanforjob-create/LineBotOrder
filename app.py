import base64
import hashlib
import hmac
import json
import os
import re
import threading
import traceback
from calendar import monthrange
from datetime import date, datetime
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import requests
from flask import Flask, abort, request

SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
TZ = ZoneInfo("Asia/Bangkok")

PRODUCT_CATEGORIES = {
    "Beer": {"L": "Lager", "R": "Rose", "D": "Dunkel"},
    "Amenity": {"M": "MUG", "P": "PINE", "J": "JUG", "T": "TOWER"},
    "Support": {"SUPL": "Lager support", "SUPR": "Rose support", "SUPD": "Dunkel support"},
    "Equipment": {"H40L": "Hoshizaki 40L", "MCT": "Stainless Mobile Counter", "STB": "Stainless Table"},
    "POSM": {"AST": "A-Stand", "STD": "Standee", "AA5": "อะคริลิก A5", "AA6": "อะคริลิก A6"}
}

PRODUCT_CODES = {}
for cat, items in PRODUCT_CATEGORIES.items():
    PRODUCT_CODES.update(items)

CODES = list(PRODUCT_CODES.keys())

STATUSES = {
    "ordered": ("✅", "Order แล้ว"),
    "slip": ("👍", "อัพสลิปแล้ว"),
    "credit": ("💳", "Credit"),
    "overdue": ("❌", "Overdue"),
    "short": ("❗", "วงเงินไม่พอ"),
}
AUTO_MATCH = 0.85
ASK_MATCH = 0.60

app = Flask(__name__)
LOCK = threading.Lock()

COLS = {
    "shops": ["id", "name", "aliases"],
    "orders": ["id", "shop_id", "ddate", *CODES, "status", "by_user"],
    "pending": ["id", "name", *CODES, "ddate", "mode", "by_user"],
}
INT_COLS = {"id", "shop_id", *CODES}
DATA = {tab: [] for tab in COLS}
_ss = None


def _spreadsheet():
    global _ss
    if _ss is None:
        import gspread
        gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDENTIALS"]))
        _ss = gc.open_by_key(os.environ["SHEET_ID"])
        have = {w.title for w in _ss.worksheets()}
        for tab, cols in COLS.items():
            if tab not in have:
                ws = _ss.add_worksheet(title=tab, rows=1000, cols=len(cols))
                ws.append_row(cols)
    return _ss


def sheet_read():
    res = _spreadsheet().values_batch_get(list(COLS))["valueRanges"]
    return {tab: vr.get("values", []) for tab, vr in zip(COLS, res)}


def sheet_append(tab, values):
    _spreadsheet().worksheet(tab).append_row(values, value_input_option="RAW")


def sheet_update(tab, row, values):
    _spreadsheet().worksheet(tab).update(values=[values], range_name=f"A{row}", value_input_option="RAW")


def sheet_delete(tab, row):
    _spreadsheet().worksheet(tab).delete_rows(row)


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def load():
    raw = sheet_read()
    for tab, cols in COLS.items():
        rows = []
        for i, r in enumerate(raw.get(tab, [])[1:], start=2):
            r = list(r) + [""] * (len(cols) - len(r))
            d = dict(zip(cols, r))
            for k in INT_COLS & set(cols):
                d[k] = num(d[k])
            if not d["id"]:
                continue
            d["_row"] = i
            rows.append(d)
        DATA[tab] = rows


def add(tab, d):
    d["id"] = max([x["id"] for x in DATA[tab]] or [0]) + 1
    sheet_append(tab, [d.get(c, "") for c in COLS[tab]])
    d["_row"] = max([x["_row"] for x in DATA[tab]] or [1]) + 1
    DATA[tab].append(d)
    return d


def update(tab, d):
    sheet_update(tab, d["_row"], [d.get(c, "") for c in COLS[tab]])


def remove(tab, d):
    sheet_delete(tab, d["_row"])
    DATA[tab].remove(d)
    for x in DATA[tab]:
        if x["_row"] > d["_row"]:
            x["_row"] -= 1


def shop_by_id(sid):
    return next((s for s in DATA["shops"] if s["id"] == sid), None)


def order_by_id(oid):
    o = next((o for o in DATA["orders"] if o["id"] == oid), None)
    if o:
        sh = shop_by_id(o["shop_id"])
        return dict(o, name=sh["name"] if sh else "?")
    return None


def orders_between(d1, d2):
    return sorted(
        [o for o in DATA["orders"] if d1 <= o["ddate"] <= d2], key=lambda o: (o["ddate"], o["id"])
    )


def text(s):
    return {"type": "text", "text": s}


def today():
    return datetime.now(TZ).date()


def norm(s):
    s = s.lower().replace("ร้าน", "")
    s = re.sub("[\u0e47-\u0e4c]", "", s)
    return re.sub(r"\s+", "", s)


def display_name(name):
    n = name.strip()
    return n if n.startswith("ร้าน") else "ร้าน " + n


def dmy(iso):
    y, m, d = iso.split("-")
    return f"{int(d):02d}/{int(m):02d}/{y}"


def codes_text(o):
    return " ".join(f"{c}{o[c]}" for c in CODES if o.get(c, 0))


def total_text(rows):
    t = {c: sum(r.get(c, 0) for r in rows) for c in CODES}
    total_qty = sum(t.values())
    details = codes_text(t)
    return f"{total_qty} ชิ้น ({details})" if details else "0 ชิ้น"


def status_line(rows):
    return "  ".join(
        f"{e} {sum(1 for r in rows if r['status'] == k)}" for k, (e, _) in STATUSES.items()
    )


def resolve(day, month=None):
    t = today()
    try:
        if month:
            d = date(t.year, month, day)
            return d if d >= t else date(t.year + 1, month, day)
        if day >= t.day:
            return date(t.year, t.month, day)
        y, m = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
        return date(y, m, day)
    except ValueError:
        return None


def upcoming_dates():
    t = today().isoformat()
    return sorted({o["ddate"] for o in DATA["orders"] if o["ddate"] >= t})


def candidates(name):
    n = norm(name)
    out = []
    for s in DATA["shops"]:
        names = [norm(s["name"])] + [a for a in s["aliases"].split("|") if a]
        best = max(SequenceMatcher(None, n, x).ratio() for x in names)
        out.append((best, s))
    out.sort(key=lambda t: -t[0])
    return out


def get_or_create_shop(name):
    dn = display_name(name)
    s = next((s for s in DATA["shops"] if s["name"] == dn), None)
    return s["id"] if s else add("shops", {"name": dn, "aliases": ""})["id"]


def add_alias(shop_id, name):
    s = shop_by_id(shop_id)
    n = norm(name)
    if s and n and n != norm(s["name"]) and n not in s["aliases"].split("|"):
        s["aliases"] = (s["aliases"] + "|" + n).strip("|")
        update("shops", s)


def flex_dates(dates):
    bubbles = []
    for d in dates[:12]:
        rows = [order_by_id(o["id"]) for o in sorted(
            [o for o in DATA["orders"] if o["ddate"] == d], key=lambda o: o["id"])]
        if not rows:
            continue
        body = [{"type": "text", "text": f"🍺 Order {dmy(d)}", "weight": "bold", "wrap": True}]
        for i, r in enumerate(rows, 1):
            st = STATUSES.get(r["status"])
            emo = st[0] if st else ""
            label = f"{st[0]} {st[1]}" if st else "สถานะ"
            body.append(
                {
                    "type": "box",
                    "layout": "horizontal",
                    "alignItems": "center",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{i}. {r['name']} {codes_text(r)} {emo}".strip(),
                            "wrap": True,
                            "flex": 5,
                            "size": "sm",
                        },
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "flex": 4,
                            "action": {"type": "postback", "label": label[:20], "data": f"pick|{r['id']}"},
                        },
                    ],
                }
            )
        body.append({"type": "text", "text": f"📋 รวม {total_text(rows)}", "size": "sm", "wrap": True})
        body.append({"type": "text", "text": status_line(rows), "size": "xs", "color": "#555555"})
        bubbles.append(
            {"type": "bubble", "size": "mega",
             "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body}}
        )
    if not bubbles:
        return text("ยังไม่มีออเดอร์")
    return {"type": "flex", "altText": "สรุป Order",
            "contents": {"type": "carousel", "contents": bubbles}}


def compact(title, d1, d2):
    rows = orders_between(d1, d2)
    if not rows:
        return text("ไม่มีออเดอร์ในช่วงนี้")
    by = {}
    for r in rows:
        by.setdefault(r["ddate"], []).append(r)
    lines = [f"📅 {title}", ""]
    for d,
