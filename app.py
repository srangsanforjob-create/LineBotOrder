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

CODES = ["L", "R", "D"]  # product codes (columns L, R, D in the orders tab)
STATUSES = {
    "ordered": ("✅", "Order แล้ว"),
    "slip": ("👍", "อัพสลิปแล้ว"),
    "credit": ("💳", "Credit"),
    "overdue": ("❌", "Overdue"),
    "short": ("❗", "วงเงินไม่พอ"),
}
AUTO_MATCH = 0.85   # at or above: treat as the same shop automatically
ASK_MATCH = 0.60    # between ASK_MATCH and AUTO_MATCH: ask which shop

app = Flask(__name__)
LOCK = threading.Lock()  # one event at a time, so Google Sheet rows stay consistent

# ---------- Google Sheet storage ----------
# Three tabs are created automatically: shops, orders, pending.
COLS = {
    "shops": ["id", "name", "aliases"],
    "orders": ["id", "shop_id", "ddate", "L", "R", "D", "status", "by_user"],
    "pending": ["id", "name", "L", "R", "D", "ddate", "mode", "by_user"],
}
INT_COLS = {"id", "shop_id", "L", "R", "D"}
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
    """Read all three tabs in one API call at the start of each webhook request."""
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


# ---------- helpers ----------
def text(s):
    return {"type": "text", "text": s}


def today():
    return datetime.now(TZ).date()


def norm(s):
    s = s.lower().replace("ร้าน", "")  # drop the word "ร้าน" before stripping tone marks
    s = re.sub("[\u0e47-\u0e4c]", "", s)  # tone marks and similar
    return re.sub(r"\s+", "", s)


def display_name(name):
    n = name.strip()
    return n if n.startswith("ร้าน") else "ร้าน " + n


def dmy(iso):
    y, m, d = iso.split("-")
    return f"{int(d):02d}/{int(m):02d}/{y}"


def codes_text(o):
    return " ".join(f"{c}{o[c]}" for c in CODES if o[c])


def total_text(rows):
    t = {c: sum(r[c] for r in rows) for c in CODES}
    return f"{sum(t.values())} ถัง ({codes_text(t)})"


def status_line(rows):
    return "  ".join(
        f"{e} {sum(1 for r in rows if r['status'] == k)}" for k, (e, _) in STATUSES.items()
    )


def resolve(day, month=None):
    """Day-only: this month if day >= today, otherwise next month."""
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


def end_date(start, day, month=None):
    try:
        if month:
            e = date(start.year, month, day)
            return e if e >= start else date(start.year + 1, month, day)
        if day >= start.day:
            return date(start.year, start.month, day)
        y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        return date(y, m, day)
    except ValueError:
        return None


def upcoming_dates():
    t = today().isoformat()
    return sorted({o["ddate"] for o in DATA["orders"] if o["ddate"] >= t})


# ---------- shop matching ----------
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


# ---------- message builders ----------
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
    for d, rs in by.items():
        lines.append(f"{dmy(d)[:5]}  {len(rs)} ร้าน  {total_text(rs)}")
    lines += ["", f"📋 รวม {len(rows)} ร้าน {total_text(rows)}", status_line(rows)]
    return text("\n".join(lines))


def quick(msg, items):
    return {
        "type": "text",
        "text": msg,
        "quickReply": {
            "items": [
                {"type": "action", "action": {"type": "postback", "label": l[:20], "data": d}}
                for l, d in items
            ]
        },
    }


# ---------- commands ----------
ORDER_RE = re.compile(
    r"^(แก้\s*)?(.+?)\s+((?:[" + "".join(CODES) + r"]\s*\d+\s*)+)\s*ส่ง\s*(\d{1,2})(?:\s*/\s*(\d{1,2}))?\s*$",
    re.I,
)


def finish(shop_id, d, qty, mode, user):
    iso = d.isoformat()
    row = next((o for o in DATA["orders"] if o["shop_id"] == shop_id and o["ddate"] == iso), None)
    if row:
        for k in CODES:
            row[k] = row[k] + qty[k] if mode == "add" else qty[k]
        update("orders", row)
    else:
        add("orders", {"shop_id": shop_id, "ddate": iso, "status": "", "by_user": user, **qty})
    return [flex_dates(upcoming_dates())]


def order(m, user):
    edit, name, q, day, mon = m.groups()
    qty = {c: 0 for c in CODES}
    for code, n in re.findall(r"([A-Za-z])\s*(\d+)", q):
        if code.upper() in qty:
            qty[code.upper()] += int(n)
    if not sum(qty.values()):
        return None
    d = resolve(int(day), int(mon) if mon else None)
    if not d:
        return [text(f"วันที่ไม่ถูกต้อง: ส่ง {day}" + (f"/{mon}" if mon else ""))]
    mode = "set" if edit else "add"
    cands = candidates(name)
    if cands and cands[0][0] >= AUTO_MATCH:
        return finish(cands[0][1]["id"], d, qty, mode, user)
    near = [(s, sh) for s, sh in cands if s >= ASK_MATCH][:3]
    if not near:
        return finish(get_or_create_shop(name), d, qty, mode, user)
    p = add("pending", {"name": name, "ddate": d.isoformat(), "mode": mode, "by_user": user, **qty})
    items = [(sh["name"], f"m|{p['id']}|{sh['id']}") for _, sh in near]
    items.append((f"ร้านใหม่: {name}", f"m|{p['id']}|new"))
    return [quick(f"“{name}” คือร้านไหนครับ", items)]


def do_delete(order_id):
    r = order_by_id(order_id)
    if not r:
        return [text("ไม่พบออเดอร์นี้แล้ว")]
    remove("orders", next(o for o in DATA["orders"] if o["id"] == order_id))
    return [text(f"ลบ {r['name']} ({codes_text(r)}) วันที่ {dmy(r['ddate'])} แล้ว"),
            flex_dates(upcoming_dates())]


def delete(m):
    name, day, mon = m.groups()
    cands = candidates(name)
    if not cands or cands[0][0] < ASK_MATCH:
        return [text(f"ไม่พบ {name}")]
    shop = cands[0][1]
    rows = sorted([o for o in DATA["orders"] if o["shop_id"] == shop["id"]], key=lambda o: o["ddate"])
    if day:
        d = resolve(int(day), int(mon) if mon else None)
        rows = [r for r in rows if d and r["ddate"] == d.isoformat()]
    else:
        rows = [r for r in rows if r["ddate"] >= today().isoformat()]
    if not rows:
        return [text(f"ไม่พบออเดอร์ของ {shop['name']}")]
    if len(rows) > 1:
        items = [(f"{dmy(r['ddate'])[:5]} {codes_text(r)}", f"del|{r['id']}") for r in rows[:13]]
        return [quick(f"{shop['name']} มีหลายวันส่ง ลบวันไหนครับ", items)]
    return do_delete(rows[0]["id"])


def summary(t):
    s = t.replace(" ", "")
    try:
        if s == "สรุป":
            return [flex_dates(upcoming_dates())]
        mm = re.match(r"^สรุปเดือน(\d{1,2})$", s)
        if mm:
            m, y = int(mm.group(1)), today().year
            d1, d2 = date(y, m, 1), date(y, m, monthrange(y, m)[1])
            return [compact(f"สรุปเดือน {m}/{y}", d1.isoformat(), d2.isoformat())]
        rg = re.match(r"^สรุป(?:วันที่)?(\d{1,2})(?:/(\d{1,2}))?(?:-|ถึง)(\d{1,2})(?:/(\d{1,2}))?$", s)
        if rg:
            a, am, b, bm = rg.groups()
            d1 = resolve(int(a), int(am) if am else None)
            d2 = end_date(d1, int(b), int(bm) if bm else None) if d1 else None
            if not (d1 and d2):
                return [text("วันที่ไม่ถูกต้อง")]
            return [compact(f"สรุป {dmy(d1.isoformat())[:5]} - {dmy(d2.isoformat())[:5]}",
                            d1.isoformat(), d2.isoformat())]
        sd = re.match(r"^สรุป(?:วันที่)?(\d{1,2})(?:/(\d{1,2}))?$", s)
        if sd:
            d = resolve(int(sd.group(1)), int(sd.group(2)) if sd.group(2) else None)
            if not d:
                return [text("วันที่ไม่ถูกต้อง")]
            return [flex_dates([d.isoformat()])]
    except ValueError:
        return [text("วันที่ไม่ถูกต้อง")]
    return None


def handle_text(txt, user):
    t = txt.strip()
    m = ORDER_RE.match(t)
    if m:
        return order(m, user)
    m = re.match(r"^ลบ\s*(.+?)(?:\s+(\d{1,2})(?:/(\d{1,2}))?)?$", t)
    if m:
        return delete(m)
    if t.startswith("สรุป"):
        return summary(t)
    return None  # not an order or command: stay silent


def handle_postback(data, user):
    p = data.split("|")
    if p[0] == "pick":
        r = order_by_id(int(p[1]))
        if not r:
            return [text("ไม่พบออเดอร์นี้แล้ว")]
        items = [(f"{e} {l}", f"set|{p[1]}|{k}") for k, (e, l) in STATUSES.items()]
        return [quick(f"เลือกสถานะของ {r['name']} ({dmy(r['ddate'])[:5]})", items)]
    if p[0] == "set":
        r = order_by_id(int(p[1]))
        if not r or p[2] not in STATUSES:
            return [text("ไม่พบออเดอร์นี้แล้ว")]
        o = next(o for o in DATA["orders"] if o["id"] == int(p[1]))
        o["status"] = p[2]
        update("orders", o)
        e, l = STATUSES[p[2]]
        return [text(f"อัพเดตสถานะ {r['name']}: {l} {e}")]
    if p[0] == "del":
        return do_delete(int(p[1]))
    if p[0] == "m":
        pend = next((x for x in DATA["pending"] if x["id"] == int(p[1])), None)
        if not pend:
            return [text("คำสั่งนี้หมดอายุแล้ว กรุณาพิมพ์ใหม่")]
        remove("pending", pend)
        if p[2] == "new":
            sid = get_or_create_shop(pend["name"])
        else:
            sid = int(p[2])
            add_alias(sid, pend["name"])
        qty = {k: pend[k] for k in CODES}
        return finish(sid, date.fromisoformat(pend["ddate"]), qty, pend["mode"], pend["by_user"])
    return None


# ---------- LINE webhook ----------
def reply(reply_token, messages):
    r = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={"Authorization": "Bearer " + TOKEN},
        json={"replyToken": reply_token, "messages": messages[:5]},
        timeout=10,
    )
    if r.status_code != 200:
        print("LINE reply error", r.status_code, r.text)


@app.get("/")
def health():
    return "ok"


@app.post("/callback")
def callback():
    body = request.get_data()
    sig = request.headers.get("X-Line-Signature", "")
    mac = base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(mac, sig):
        abort(400)
    events = json.loads(body).get("events", [])
    relevant = [
        ev for ev in events
        if ev["type"] == "postback" or (ev["type"] == "message" and ev["message"]["type"] == "text")
    ]
    if not relevant:
        return "OK"
    with LOCK:
        try:
            load()  # one read of the Google Sheet per webhook request
        except Exception:
            traceback.print_exc()
            return "OK"
        for ev in relevant:
            try:
                user = ev.get("source", {}).get("userId", "")
                if ev["type"] == "message":
                    msgs = handle_text(ev["message"]["text"], user)
                else:
                    msgs = handle_postback(ev["postback"]["data"], user)
                if msgs:
                    reply(ev["replyToken"], msgs)
            except Exception:
                traceback.print_exc()
    return "OK"
