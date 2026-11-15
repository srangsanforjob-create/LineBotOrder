import base64
import hashlib
import hmac
import json
import os
import re
import threading
import traceback
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
    "POSM": {"AST": "A-Stand", "STD": "Standee", "AA5": "อะคริลิก A5", "AA6": "อะคริลิก A6"},
}

PRODUCT_CODES = {}
for cat, items in PRODUCT_CATEGORIES.items():
    PRODUCT_CODES.update(items)

CODES = list(PRODUCT_CODES.keys())

STATUSES = {
    "pending": ("⏳", "ยังไม่ได้ Order"),
    "ordered": ("✅", "Order แล้ว"),
    "slip": ("👍", "อัปสลิปแล้ว"),
    "credit": ("💳", "Credit"),
    "overdue": ("❌", "Overdue"),
    "short": ("❗", "วงเงินไม่พอ"),
}
AUTO_MATCH = 0.85

app = Flask(__name__)
LOCK = threading.Lock()

USER_SESSIONS = {}

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
        secret_path = "/etc/secrets/driven-current-323807-98d50517d033.json"
        try:
            gc = gspread.service_account(filename=secret_path)
        except Exception as e:
            print(f"❌ ERROR: ไม่สามารถอ่านไฟล์ Secret Credentials ได้: {e}")
            raise
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


def parse_date_input(text_str):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text_str)
    if m:
        d, mth, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        try:
            return date(yr, mth, d).isoformat()
        except ValueError:
            return None
    return None


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
    # ปรับให้ดึงทุกวันที่ในฐานข้อมูล (รวมถึงวันที่ผ่านมาแล้วด้วย เพื่อให้แก้ไขสเตตัสย้อนหลังได้) เรียงจากเก่าไปใหม่หรือใหม่ไปเก่าตามต้องการ
    return sorted({o["ddate"] for o in DATA["orders"] if o.get("ddate")}, reverse=False)


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
    if s:
        return s["id"]
    cands = candidates(name)
    if cands and cands[0][0] >= AUTO_MATCH:
        return cands[0][1]["id"]
    return add("shops", {"name": dn, "aliases": ""})["id"]


def get_session(user_id):
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"items": {}, "step": None, "pending_code": None, "edit_order_id": None}
    return USER_SESSIONS[user_id]


def cart_summary(items):
    if not items:
        return "ยังไม่ได้เลือกสินค้า"
    return "\n".join(f"• {PRODUCT_CODES.get(c, c)} ({c}) x {q}" for c, q in items.items() if q > 0)


# ---------- FLEX MESSAGES ----------

def flex_category_menu(user_id):
    sess = get_session(user_id)
    items = sess["items"]
    edit_id = sess.get("edit_order_id")

    title_text = f"✏️ แก้ไขออเดอร์ #{edit_id}" if edit_id else "🛒 เลือกหมวดหมู่สินค้า"

    cat_buttons = []
    for cat in PRODUCT_CATEGORIES.keys():
        cat_buttons.append({
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "action": {"type": "postback", "label": f"📦 {cat}", "data": f"cat|{cat}"}
        })

    body_contents = [
        {"type": "text", "text": title_text, "weight": "bold", "size": "lg"},
        {"type": "separator", "margin": "sm"},
        {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "margin": "sm",
            "contents": [
                {"type": "text", "text": "รายการสินค้า:", "size": "xs", "color": "#888888"},
                {"type": "text", "text": cart_summary(items), "size": "sm", "wrap": True, "weight": "bold"}
            ]
        },
        {"type": "separator", "margin": "md"},
        {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": cat_buttons},
    ]

    footer_contents = []
    if items:
        btn_label = "✅ บันทึกการแก้ไข" if edit_id else "✅ ยืนยันรายการ / ใส่ชื่อร้าน"
        footer_contents.append({
            "type": "button",
            "style": "primary",
            "color": "#06C755",
            "height": "sm",
            "action": {"type": "postback", "label": btn_label, "data": "checkout"}
        })
        footer_contents.append({
            "type": "button",
            "style": "link",
            "height": "sm",
            "color": "#FF3B30",
            "action": {"type": "postback", "label": "🗑️ ล้างรายการ", "data": "clear_cart"}
        })

    bubble = {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "contents": body_contents}
    }
    if footer_contents:
        bubble["footer"] = {"type": "box", "layout": "vertical", "spacing": "xs", "contents": footer_contents}

    return {"type": "flex", "altText": "ฟอร์มเลือกสินค้า", "contents": bubble}


def flex_items_in_category(cat, user_id):
    sess = get_session(user_id)
    items = sess["items"]
    cat_items = PRODUCT_CATEGORIES.get(cat, {})

    rows = [
        {"type": "text", "text": f"📦 หมวด: {cat}", "weight": "bold", "size": "lg"},
        {"type": "text", "text": "กดปุ่มเพื่อเพิ่มหรือระบุจำนวนสินค้า", "size": "xs", "color": "#888888"},
        {"type": "separator", "margin": "sm"},
    ]

    for code, name in cat_items.items():
        qty = items.get(code, 0)
        check = "☑️" if qty > 0 else "⬜"
        qty_label = f" ({qty})" if qty > 0 else ""

        rows.append({
            "type": "box",
            "layout": "horizontal",
            "alignItems": "center",
            "spacing": "sm",
            "margin": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": f"{check} {name}{qty_label}",
                    "size": "sm",
                    "wrap": True,
                    "flex": 5
                },
                {
                    "type": "button",
                    "style": "primary" if qty > 0 else "secondary",
                    "height": "sm",
                    "flex": 2,
                    "action": {"type": "postback", "label": "+1", "data": f"add|{code}|1|{cat}"}
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "flex": 3,
                    "action": {"type": "postback", "label": "ใส่จำนวน", "data": f"ask_qty|{code}|{cat}"}
                }
            ]
        })

    footer = {
        "type": "box",
        "layout": "horizontal",
        "spacing": "sm",
        "contents": [
            {
                "type": "button",
                "style": "secondary",
                "height": "sm",
                "action": {"type": "postback", "label": "⬅️ กลับหน้าหมวด", "data": "menu"}
            },
            {
                "type": "button",
                "style": "primary",
                "color": "#06C755",
                "height": "sm",
                "action": {"type": "postback", "label": "✅ ตะกร้าสินค้า", "data": "menu"}
            }
        ]
    }

    return {
        "type": "flex",
        "altText": f"เลือกสินค้าหมวด {cat}",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "body": {"type": "box", "layout": "vertical", "contents": rows},
            "footer": footer
        }
    }


def flex_order_actions(order_id):
    o = order_by_id(order_id)
    if not o:
        return text("ไม่พบออเดอร์นี้")

    status_buttons = []
    for k, (emo, label) in STATUSES.items():
        status_buttons.append({
            "type": "button",
            "style": "primary" if o["status"] == k else "secondary",
            "height": "sm",
            "action": {"type": "postback", "label": f"{emo} {label}", "data": f"set_status|{order_id}|{k}"}
        })

    return {
        "type": "flex",
        "altText": f"จัดการออเดอร์ #{order_id}",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"จัดการออเดอร์ #{order_id}", "weight": "bold", "size": "md"},
                    {"type": "text", "text": f"{o['name']} ({dmy(o['ddate'])})", "size": "sm", "color": "#555555"},
                    {"type": "text", "text": f"รายการ: {codes_text(o)}", "size": "xs", "color": "#666666", "wrap": True},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "เปลี่ยนสถานะ (เฉพาะร้านนี้):", "size": "xs", "weight": "bold", "color": "#888888"},
                    *status_buttons,
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "color": "#1D4ED8",
                                "action": {"type": "postback", "label": "✏️ แก้ไขรายการ", "data": f"edit|{order_id}"},
                                "flex": 1
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "color": "#DC2626",
                                "action": {"type": "postback", "label": "🗑️ ลบออเดอร์", "data": f"delete|{order_id}"},
                                "flex": 1
                            }
                        ]
                    }
                ]
            }
        }
    }


def flex_dates(dates):
    bubbles = []
    for d in dates[:12]:
        rows = [order_by_id(o["id"]) for o in sorted(
            [o for o in DATA["orders"] if o["ddate"] == d], key=lambda o: o["id"])]
        if not rows:
            continue

        bulk_buttons = [
            {
                "type": "button",
                "style": "secondary",
                "height": "sm",
                "action": {"type": "postback", "label": "✅ เปลี่ยนทุกร้านเป็น Order แล้ว", "data": f"bulk_status|{d}|ordered"}
            },
            {
                "type": "button",
                "style": "secondary",
                "height": "sm",
                "action": {"type": "postback", "label": "👍 เปลี่ยนทุกร้านเป็น อัปสลิปแล้ว", "data": f"bulk_status|{d}|slip"}
            }
        ]

        delete_day_button = {
            "type": "button",
            "style": "primary",
            "color": "#DC2626",
            "height": "sm",
            "action": {"type": "postback", "label": f"🗑️ ลบออเดอร์ทั้งวัน ({dmy(d)})", "data": f"delete_day|{d}"}
        }

        body = [
            {"type": "text", "text": f"🍺 Order วันที่ {dmy(d)}", "weight": "bold", "size": "md", "wrap": True},
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "margin": "sm",
                "contents": [
                    {"type": "text", "text": "⚡ เมนูปรับสถานะพร้อมกันทุกร้าน:", "size": "xs", "color": "#1D4ED8", "weight": "bold"},
                    *bulk_buttons,
                    {"type": "separator", "margin": "xs"},
                    delete_day_button
                ]
            },
            {"type": "separator", "margin": "md"}
        ]

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
        body.append({"type": "separator", "margin": "md"})
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


def parse_shop_and_date(raw_text):
    txt = raw_text.strip()
    ddate = today()
    m = re.search(r"(?:ส่ง\s*)?(\d{1,2})(?:/(\d{1,2}))?\s*$", txt)
    if m:
        day = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else None
        resolved = resolve(day, month)
        if resolved:
            ddate = resolved
            txt = txt[:m.start()].strip()
    shop_name = txt if txt else "ไม่ระบุร้าน"
    return shop_name, ddate.isoformat()


def save_order_to_sheet(shop_name, ddate_iso, items_dict, user_id):
    sid = get_or_create_shop(shop_name)
    row_data = {
        "shop_id": sid,
        "ddate": ddate_iso,
        "status": "pending",
        "by_user": user_id,
    }
    for c in CODES:
        row_data[c] = items_dict.get(c, 0)
    created = add("orders", row_data)
    return order_by_id(created["id"])


def reply_line(reply_token, messages):
    if not isinstance(messages, list):
        messages = [messages]
    formatted = [m if isinstance(m, dict) else text(str(m)) for m in messages]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {"replyToken": reply_token, "messages": formatted}
    resp = requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)
    if resp.status_code != 200:
        print(f"❌ LINE Reply Error: {resp.status_code} {resp.text}")


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    hash_val = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    computed_signature = base64.b64encode(hash_val).decode("utf-8")

    if computed_signature != signature:
        abort(400)

    try:
        events = json.loads(body).get("events", [])
        for event in events:
            etype = event.get("type
