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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TZ = ZoneInfo("Asia/Bangkok")

PRODUCT_CATEGORIES = {
    "Beer": {"l": "Lager", "r": "Rose", "d": "Dunkel"},
    "Amenity": {"m": "MUG", "p": "PINE", "j": "JUG", "t": "TOWER"},
    "อุปกรณ์ติดตั้ง": {
        "h40l": "Hoshizaki 40L",
        "h90": "Hoshizaki 90L",
        "h120": "Hoshizaki 120L",
        "sct": "Stanless Counter",
        "st": "Stanless Table"
    },
    "POSM": {"ast": "A-Stand", "std": "Standee", "aa5": "อะคริลิก A5", "aa6": "อะคริลิก A6"},
    "OtherALC": {
        "galf": "Galaxy แบน 350ml",
        "galr": "Galaxy กลม 700ml",
        "tend3": "Tendo 360ml",
        "tend7": "Tendo 700ml",
        "kach": "Kacha 375ml",
        "sojy": "Soju โยเกิร์ต",
        "sojp": "Soju พีช",
        "sojg": "Soju องุ่น",
        "sojf": "Soju เกรปฟรุ๊ต",
        "sojs": "Soju สตรอเบอรี่"
    },
    "SupportAll": {
        "supl": "sup Lager",
        "supr": "sup Rose",
        "supd": "sup Dunkel",
        "supm": "sup MUG",
        "supp": "sup PINE",
        "supj": "sup JUG",
        "supt": "sup TOWER",
        "suph40l": "sup Hoshizaki 40L",
        "suph90": "sup Hoshizaki 90L",
        "suph120": "sup Hoshizaki 120L",
        "supsct": "sup Stanless Counter",
        "supst": "sup Stanless Table",
        "supast": "sup A-Stand",
        "supstd": "sup Standee",
        "supaa5": "sup อะคริลิก A5",
        "supaa6": "sup อะคริลิก A6",
        "supgalf": "sup Galaxy แบน 350ml",
        "supgalr": "sup Galaxy กลม 700ml",
        "suptend3": "sup Tendo 360ml",
        "suptend7": "sup Tendo 700ml",
        "supkach": "sup Kacha 375ml",
        "supsojy": "sup Soju โยเกิร์ต",
        "supsojp": "sup Soju พีช",
        "supsojg": "sup Soju องุ่น",
        "supsojf": "sup Soju เกรปฟรุ๊ต",
        "supsojs": "sup Soju สตรอเบอรี่"
    }
}

EXTRA_ALIASES = {
    "h40": "h40l",
    "counter": "sct",
    "table": "st",
    "celli": "h40l",
    "L": "l", "R": "r", "D": "d", "M": "m", "P": "p", "J": "j", "T": "t",
    "H40L": "h40l", "H90": "h90", "H120": "h120", "SCT": "sct", "ST": "st",
    "AST": "ast", "STD": "std", "AA5": "aa5", "AA6": "aa6",
    "GALF": "galf", "GALR": "galr", "TEND3": "tend3", "TEND7": "tend7",
    "KACH": "kach", "SOJY": "sojy", "SOJP": "sojp", "SOJG": "sojg", "SOJF": "sojf", "SOJS": "sojs",
    "supL": "supl", "supR": "supr", "supD": "supd", "supM": "supm", "supP": "supp", "supJ": "supj", "supT": "supt",
    "supH40L": "suph40l", "supH90": "suph90", "supH120": "suph120", "supSCT": "supsct", "supST": "supst",
    "supAST": "supast", "supSTD": "supstd", "supAA5": "supaa5", "supAA6": "supaa6",
    "supGALF": "supgalf", "supGALR": "supgalr", "supTEND3": "suptend3", "supTEND7": "suptend7",
    "supKACH": "supkach", "supSOJY": "supsojy", "supSOJP": "supsojp", "supSOJG": "supsojg", "supSOJF": "supsojf", "supSOJS": "supsojs"
}

PRODUCT_CODES = {}
for cat, items in PRODUCT_CATEGORIES.items():
    PRODUCT_CODES.update(items)

CODES = list(PRODUCT_CODES.keys())

STATUS_MAP = {
    "order": "ordered",
    "ordered": "ordered",
    "slipt": "slip",
    "slip": "slip",
    "over": "overdue",
    "overdue": "overdue",
    "limit": "short",
    "short": "short"
}

STATUSES = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "Credit", "#0088CC"),
    "overdue": ("⚠️", "Overdue", "#FF334B"),
    "short": ("❗", "วงเงินไม่พอ", "#FF334B"),
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


def update_db(tab, oid, payload):
    supabase.table(tab).update(payload).eq("id", oid).execute()
    for item in DATA[tab]:
        if item.get("id") == oid:
            item.update(payload)


def delete_db(tab, oid):
    supabase.table(tab).delete().eq("id", oid).execute()
    DATA[tab] = [item for item in DATA[tab] if item.get("id") != oid]


def shop_by_id(sid):
    return next((s for s in DATA["shops"] if s["id"] == sid), None)


def dmy(iso):
    try:
        y, m, d = iso.split("-")
        return f"{int(d):02d}/{int(m):02d}/{y}"
    except:
        return iso


def resolve_date(day_val, month_val=None, year_val=None):
    t = today()
    try:
        if year_val:
            if year_val < 100:
                year_val += 2000
            if month_val:
                return date(year_val, month_val, day_val).isoformat()
            return date(t.year, month_val or t.month, day_val).isoformat()
        
        if month_val:
            d = date(t.year, month_val, day_val)
            return d.isoformat() if d >= t else date(t.year + 1, month_val, day_val).isoformat()
        
        return date(t.year, t.month, day_val).isoformat()
    except ValueError:
        return None


def get_or_create_shop(name):
    dn = name.strip()
    if not dn.startswith("ร้าน"):
        dn = "ร้าน " + dn
    s = next((s for s in DATA["shops"] if s["name"] == dn), None)
    if s:
        return s["id"]
    new_shop = add("shops", {"name": dn, "aliases": ""})
    return new_shop["id"]


def today():
    return datetime.now(TZ).date()


def flex_order_summary(order_record, shop_name):
    status_key = order_record.get("status", "pending")
    icon, status_label, status_color = STATUSES.get(status_key, ("⏳", "ยังไม่ได้ Order", "#FF9900"))
    order_id = order_record.get("id")
    
    item_rows = []
    for code in CODES:
        qty = order_record.get(code, 0)
        if qty > 0:
            p_name = PRODUCT_CODES.get(code, code)
            item_rows.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"• {p_name} ({code.upper()})", "size": "sm", "color": "#333333", "flex": 4},
                    {"type": "text", "text": str(qty), "size": "sm", "align": "end", "weight": "bold", "color": "#111111", "flex": 1}
                ]
            })
            
    if not item_rows:
        item_rows.append({"type": "text", "text": "ไม่มีรายการสินค้า", "size": "sm", "color": "#888888"})

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🍻 เบียร์สดเยอรมันตะวันแดง", "weight": "bold", "color": "#1DB446", "size": "xs"},
                {"type": "text", "text": "ใบสรุปรายการออเดอร์", "weight": "bold", "size": "lg", "margin": "sm", "color": "#111111"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "separator", "color": "#EEEEEE"},
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "ร้าน:", "size": "sm", "color": "#888888", "flex": 2},
                        {"type": "text", "text": shop_name, "size": "sm", "weight": "bold", "color": "#111111", "flex": 5, "wrap": True}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "วันที่จัดส่ง:", "size": "sm", "color": "#888888", "flex": 2},
                        {"type": "text", "text": dmy(order_record.get("ddate", "")), "size": "sm", "weight": "bold", "color": "#111111", "flex": 5}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "สถานะ:", "size": "sm", "color": "#888888", "flex": 2},
                        {"type": "text", "text": f"{icon} {status_label}", "size": "sm", "weight": "bold", "color": status_color, "flex": 5}
                    ]
                },
                {"type": "separator", "color": "#EEEEEE", "margin": "sm"},
                {"type": "text", "text": "รายการสินค้าทั้งหมด", "weight": "bold", "size": "xs", "color": "#777777"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": item_rows
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "xs",
                    "contents": [
                        {"type": "button", "style": "primary", "color": "#06C755", "height": "sm", "action": {"type": "postback", "label": "✅ Order", "data": f"status|ordered|{order_id}"}},
                        {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "👍 Slip", "data": f"status|slip|{order_id}"}}
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "xs",
                    "contents": [
                        {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "⏳ Pending", "data": f"status|pending|{order_id}"}},
                        {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "⚠️ Overdue", "data": f"status|overdue|{order_id}"}}
                    ]
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "color": "#FF334B",
                    "action": {"type": "postback", "label": "🗑️ ลบ Order นี้", "data": f"delete|{order_id}"}
                }
            ]
        }
    }
    return {"type": "flex", "altText": f"ใบสรุปออเดอร์ {shop_name}", "contents": bubble}


def flex_daily_summary(target_date_str, orders_list):
    bubbles = []
    for ord_rec in orders_list:
        sh = shop_by_id(ord_rec["shop_id"])
        sh_name = sh["name"] if sh else "ร้านค้า"
        status_key = ord_rec.get("status", "pending")
        icon, status_label, status_color = STATUSES.get(status_key, ("⏳", "ยังไม่ได้ Order", "#FF9900"))
        order_id = ord_rec.get("id")
        
        item_rows = []
        for code in CODES:
            qty = ord_rec.get(code, 0)
            if qty > 0:
                p_name = PRODUCT_CODES.get(code, code)
                item_rows.append({
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"• {p_name} ({code.upper()})", "size": "sm", "color": "#333333", "flex": 4},
                        {"type": "text", "text": str(qty), "size": "sm", "align": "end", "weight": "bold", "color": "#111111", "flex": 1}
                    ]
                })
        if not item_rows:
            item_rows.append({"type": "text", "text": "ไม่มีรายการสินค้า", "size": "sm", "color": "#888888"})

        bubble = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "🍻 สรุปยอดจัดส่งประจำวัน", "weight": "bold", "color": "#1DB446", "size": "xs"},
                    {"type": "text", "text": sh_name, "weight": "bold", "size": "lg", "margin": "sm", "color": "#111111", "wrap": True}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "separator", "color": "#EEEEEE"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "วันที่:", "size": "sm", "color": "#888888", "flex": 2},
                            {"type": "text", "text": dmy(target_date_str), "size": "sm", "weight": "bold", "color": "#111111", "flex": 5}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "สถานะ:", "size": "sm", "color": "#888888", "flex": 2},
                            {"type": "text", "text": f"{icon} {status_label}", "size": "sm", "weight": "bold", "color": status_color, "flex": 5}
                        ]
                    },
                    {"type": "separator", "color": "#EEEEEE", "margin": "sm"},
                    {"type": "text", "text": "รายการสินค้า", "weight": "bold", "size": "xs", "color": "#777777"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "contents": item_rows}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "xs",
                        "contents": [
                            {"type": "button", "style": "primary", "color": "#06C755", "height": "sm", "action": {"type": "postback", "label": "✅ Order", "data": f"status|ordered|{order_id}"}},
                            {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "👍 Slip", "data": f"status|slip|{order_id}"}}
                        ]
                    },
                    {
                        "type": "button",
                        "style": "link",
                        "height": "sm",
                        "color": "#FF334B",
                        "action": {"type": "postback", "label": "🗑️ ลบ Order นี้", "data": f"delete|{order_id}"}
                    }
                ]
            }
        }
        bubbles.append(bubble)

    return {
        "type": "flex",
        "altText": f"สรุปออเดอร์วันที่ {dmy(target_date_str)}",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }


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
        abort(400)

    try:
        json_data = json.loads(body)
        for event in json_data.get("events", []):
            if event.get("type") == "message":
                handle_message(event)
            elif event.get("type") == "postback":
                handle_postback(event)
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()

    return "OK", 200


def handle_message(event):
    msg_text = event["message"].get("text", "").strip()
    
    if msg_text.lower() == "ขอinput":
        help_text = (
            "📖 วิธีการใช้งาน:\n"
            "1. สั่งซื้อ: [วันที่] [ชื่อร้าน] [รหัสสินค้าและจำนวน] [Status]\n"
            "   ตัวอย่าง: 17 ร้าน ABC L2 R3 order\n\n"
            "2. เรียกสรุปยอดรายวัน: สรุป [วันที่]\n"
            "   ตัวอย่าง: สรุป 17 หรือ สรุป 17/11"
        )
        reply_text(event["replyToken"], help_text)
        return

    if msg_text.startswith("สรุป"):
        parts = msg_text.split()
        if len(parts) >= 2:
            date_str = parts[1]
            date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2}))?(?:/(\d{2,4}))?$", date_str)
            if date_match:
                d_val = int(date_match.group(1))
                m_val = int(date_match.group(2)) if date_match.group(2) else None
                y_val = int(date_match.group(3)) if date_match.group(3) else None
                resolved_dt = resolve_date(d_val, m_val, y_val)
                if resolved_dt:
                    matched_orders = [o for o in DATA["orders"] if o.get("ddate") == resolved_dt]
                    if matched_orders:
                        reply_flex(event["replyToken"], flex_daily_summary(resolved_dt, matched_orders))
                        return
                    else:
                        reply_text(event["replyToken"], f"📅 ไม่พบออเดอร์ในวันที่ {dmy(resolved_dt)} ครับ")
                        return

    parts = msg_text.split()
    if len(parts) >= 3:
        date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2}))?(?:/(\d{2,4}))?$", parts[0])
        if date_match:
            d_val = int(date_match.group(1))
            m_val = int(date_match.group(2)) if date_match.group(2) else None
            y_val = int(date_match.group(3)) if date_match.group(3) else None
            resolved_dt = resolve_date(d_val, m_val, y_val)
            if resolved_dt:
                shop_name = parts[1]
                item_tokens = parts[2:]
                
                status_key = "pending"
                if item_tokens:
                    last_token = item_tokens[-1].lower()
                    if last_token in STATUS_MAP:
                        status_key = STATUS_MAP[last_token]
                        item_tokens.pop()
                
                order_items = {}
                for token in item_tokens:
                    m_item = re.match(r"^([a-zA-Z0-9_-]+?)(\d+)$", token)
                    if m_item:
                        code_raw = m_item.group(1)
                        qty = int(m_item.group(2))
                        code = EXTRA_ALIASES.get(code_raw, code_raw).lower()
                        if code in CODES:
                            order_items[code] = order_items.get(code, 0) + qty
                
                if order_items:
                    shop_id = get_or_create_shop(shop_name)
                    payload = {
                        "shop_id": shop_id,
                        "ddate": resolved_dt,
                        "status": status_key,
                        **order_items
                    }
                    inserted = add("orders", payload)
                    sh_obj = shop_by_id(shop_id)
                    sh_display = sh_obj["name"] if sh_obj else shop_name
                    reply_flex(event["replyToken"], flex_order_summary(inserted, sh_display))
                    return

    reply_text(event["replyToken"], "พิมพ์ 'ขอInput' เพื่อดูรูปแบบคำสั่งครับ")


def handle_postback(event):
    data = event["postback"]["data"]
    parts = data.split("|")
    if len(parts) == 3 and parts[0] == "status":
        new_status = parts[1]
        try:
            order_id = int(parts[2])
            update_db("orders", order_id, {"status": new_status})
            updated_order = next((o for o in DATA["orders"] if o["id"] == order_id), None)
            if updated_order:
                sh_obj = shop_by_id(updated_order["shop_id"])
                sh_display = sh_obj["name"] if sh_obj else "ร้านค้า"
                reply_flex(event["replyToken"], flex_order_summary(updated_order, sh_display))
                return
        except Exception as e:
            print(f"❌ Postback Status Error: {e}")
            
    elif len(parts) == 2 and parts[0] == "delete":
        try:
            order_id = int(parts[1])
            delete_db("orders", order_id)
            reply_text(event["replyToken"], f"🗑️ ลบออเดอร์ #{order_id} เรียบร้อยแล้วครับ")
            return
        except Exception as e:
            print(f"❌ Postback Delete Error: {e}")


def reply_text(reply_token, text_message):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text_message}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)


def reply_flex(reply_token, flex_message):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
    payload = {"replyToken": reply_token, "messages": [flex_message]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)


if __name__ == "__main__":
    load()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
