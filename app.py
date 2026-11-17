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
    payload = {k: v for k, v in d.items() if k != "_row"}
    if "id" in payload:
        payload.pop("id")
        
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


def codes_text(o):
    return " ".join(f"{c}{o[c]}" for c in CODES if o.get(c, 0))


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


# ---------- LINE WEBHOOK ROUTE & HANDLERS ----------

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    
    try:
        if SECRET:
            hash = hmac.new(SECRET.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).digest()
            computed_signature = base64.b64encode(hash).decode('utf-8')
            if computed_signature != signature:
                abort(400)
    except Exception as e:
        print(f"❌ Signature Verification Error: {e}")
        abort(400)

    try:
        json_data = json.loads(body)
        for event in json_data.get("events", []):
            event_type = event.get("type")
            if event_type == "message":
                handle_message(event)
            elif event_type == "postback":
                handle_postback(event)
    except Exception as e:
        print(f"❌ Parse Event Error: {e}")
        traceback.print_exc()

    return "OK", 200


def handle_message(event):
    user_id = event["source"]["userId"]
    msg_text = event["message"].get("text", "").strip()
    
    # ยืดหยุ่น: หากพิมพ์ "เมนู" ให้เรียกหน้าเลือกสินค้า หากพิมพ์ข้อความอื่นๆ สามารถนำไปประมวลผลต่อได้ทันที
    if msg_text == "เมนู":
        reply_flex(event["replyToken"], flex_category_menu(user_id))
    else:
        # รองรับการพิมพ์ข้อความทั่วไปหรือชื่อร้าน/รายการสินค้า
        reply_text(event["replyToken"], f"รับข้อความ: {msg_text}")


def handle_postback(event):
    user_id = event["source"]["userId"]
    data = event["postback"]["data"]
    parts = data.split("|")
    action = parts[0]
    
    if action == "cat":
        cat = parts[1]
        reply_flex(event["replyToken"], flex_items_in_category(cat, user_id))
    elif action == "menu":
        reply_flex(event["replyToken"], flex_category_menu(user_id))
    elif action == "clear_cart":
        sess = get_session(user_id)
        sess["items"] = {}
        reply_flex(event["replyToken"], flex_category_menu(user_id))
    elif action == "add":
        code = parts[1]
        val = int(parts[2])
        cat = parts[3]
        sess = get_session(user_id)
        sess["items"][code] = sess["items"].get(code, 0) + val
        reply_flex(event["replyToken"], flex_items_in_category(cat, user_id))


def reply_text(reply_token, text_message):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text_message}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)


def reply_flex(reply_token, flex_message):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [flex_message]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)


if __name__ == "__main__":
    load()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
