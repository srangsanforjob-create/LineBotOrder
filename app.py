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
from supabase import create_client, Client

SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# ตั้งค่าเชื่อมต่อ Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TZ = ZoneInfo("Asia/Bangkok")

PRODUCT_CATEGORIES = {
    "Beer": {"L": "Lager", "R": "Rose", "D": "Dunkel"},
    "Amenity": {"M": "MUG", "P": "PINE", "J": "JUG", "T": "TOWER"},
    "อุปกรณ์ติดตั้ง": {
        "H40L": "Hoshizaki 40L",
        "H90": "Hoshizaki 90L",
        "H120": "Hoshizaki 120L",
        "SCT": "Stanless Counter",
        "ST": "Stanless Table"
    },
    "POSM": {"AST": "A-Stand", "STD": "Standee", "AA5": "อะคริลิก A5", "AA6": "อะคริลิก A6"},
    "OtherALC": {
        "GALF": "Galaxy แบน 350ml",
        "GALR": "Galaxy กลม 700ml",
        "TEND3": "Tendo 360ml",
        "TEND7": "Tendo 700ml",
        "KACH": "Kacha 375ml",
        "SOJY": "Soju โยเกิร์ต",
        "SOJP": "Soju พีช",
        "SOJG": "Soju องุ่น",
        "SOJF": "Soju เกรปฟรุ๊ต",
        "SOJS": "Soju สตรอเบอรี่"
    },
    "SupportAll": {
        "supL": "sup Lager",
        "supR": "sup Rose",
        "supD": "sup Dunkel",
        "supM": "sup MUG",
        "supP": "sup PINE",
        "supJ": "sup JUG",
        "supT": "sup TOWER",
        "supH40L": "sup Hoshizaki 40L",
        "supH90": "sup Hoshizaki 90L",
        "supH120": "sup Hoshizaki 120L",
        "supSCT": "sup Stanless Counter",
        "supST": "sup Stanless Table",
        "supAST": "sup A-Stand",
        "supSTD": "sup Standee",
        "supAA5": "sup อะคริลิก A5",
        "supAA6": "sup อะคริลิก A6",
        "supGALF": "sup Galaxy แบน 350ml",
        "supGALR": "sup Galaxy กลม 700ml",
        "supTEND3": "sup Tendo 360ml",
        "supTEND7": "sup Tendo 700ml",
        "supKACH": "sup Kacha 375ml",
        "supSOJY": "sup Soju โยเกิร์ต",
        "supSOJP": "sup Soju พีช",
        "supSOJG": "sup Soju องุ่น",
        "supSOJF": "sup Soju เกรปฟรุ๊ต",
        "supSOJS": "sup Soju สตรอเบอรี่"
    }
}

EXTRA_ALIASES = {
    "H40": "H40L",
    "COUNTER": "SCT",
    "TABLE": "ST",
    "CELLI": "H40L"
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

DATA = {"shops": [], "orders": [], "pending": []}


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def load():
    global DATA
    try:
        shops_res = supabase.table("shops").select("*").execute()
        orders_res = supabase.table("orders").select("*").execute()
        pending_res = supabase.table("pending").select("*").execute()

        DATA["shops"] = shops_res.data or []
        
        # จัดการแปลงค่าที่เป็นตัวเลขสินค้าให้เป็น int
        orders = []
        for r in (orders_res.data or []):
            for k in INT_COLS & set(r.keys()):
                r[k] = num(r[k])
            orders.append(r)
        DATA["orders"] = orders

        pending = []
        for r in (pending_res.data or []):
            for k in INT_COLS & set(r.keys()):
                r[k] = num(r[k])
            pending.append(r)
        DATA["pending"] = pending

    except Exception as e:
        print(f"❌ Supabase Load Error: {e}")


INT_COLS = {"id", "shop_id", *CODES}


def add(tab, d):
    # ลบ key ชั่วคราวออกก่อนบันทึก
    payload = {k: v for k, v in d.items() if k != "_row"}
    if "id" in payload:
        payload.pop("id") # ให้ Supabase gen id ให้อัตโนมัติ
        
    res = supabase.table(tab).insert(payload).execute()
    if res.data:
        inserted = res.data[0]
        for k in INT_COLS & set(inserted.keys()):
            inserted[k] = num(inserted[k])
        DATA[tab].append(inserted)
        return inserted
    return d


def update(tab, d):
    payload = {k: v for k, v in d.items() if k != "_row"}
    oid = payload.get("id")
    supabase.table(tab).update(payload).eq("id", oid).execute()


def remove(tab, d):
    oid = d.get("id")
    supabase.table(tab).delete().eq("id", oid).execute()
    DATA[tab] = [x for x in DATA[tab] if x.get("id") != oid]


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
    m = re.search(r"(\d{1,2})(?:/(\d{1,2}))?(?:/(\d{2,4}))?", text_str)
    if m:
        day = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else today().month
        yr = int(m.group(3)) if m.group(3) else today().year
        if yr < 100:
            yr += 2000
        try:
            return date(yr, month, day).isoformat()
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
    new_shop = add("shops", {"name": dn, "aliases": ""})
    return new_shop["id"]


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
                                "action": {"type": "postback", "label": "✏️ แก้ไข", "data": f"edit_order|{order_id}"}
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "color": "#FF3B30",
                                "height": "sm",
                                "action": {"type": "postback", "label": "🗑️ ลบ", "data": f"del_order|{order_id}"}
                            }
                        ]
                    }
                ]
            }
        }
    }
