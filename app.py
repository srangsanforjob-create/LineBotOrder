import os
import json
import re
import base64
import hashlib
import hmac
from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import Flask, request, abort
import requests
from supabase import create_client, Client

# --- CONFIG ---
SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TZ = ZoneInfo("Asia/Bangkok")
app = Flask(__name__)

# --- FULL PRODUCT DATABASE & MAPPINGS ---
PRODUCTS_DB = {
    "l": "Lager", "r": "Rose", "d": "Dunkel",
    "m": "MUG", "p": "PINE", "j": "JUG", "t": "TOWER",
    "h40l": "Hoshizaki 40L", "h90": "Hoshizaki 90L", "h120": "Hoshizaki 120L",
    "sct": "Stainless Counter", "st": "Stainless Table",
    "ast": "A-Stand", "std": "Standee", "aa5": "อะคริลิก A5", "aa6": "อะคริลิก A6",
    "galf": "Galaxy แบน 350ml", "galr": "Galaxy กลม 700ml",
    "tend3": "Tendo 360ml", "tend7": "Tendo 700ml",
    "kach": "Kacha 375ml",
    "sojy": "Soju โยเกิร์ต", "sojp": "Soju พีช",
    "sojg": "Soju องุ่น", "sojf": "Soju เกรปฟรุ๊ต", "sojs": "Soju สตรอเบอรี่"
}

CODES = list(PRODUCTS_DB.keys())

ALIAS_MAP = {
    "lager": "l", "ลากิอร์": "l", "ลีโอ": "l", "เบียร์": "l", "l": "l",
    "rose": "r", "โรส": "r", "r": "r",
    "dunkel": "d", "ดุงเกล": "d", "ดังก์เกล": "d",
    "mug": "m", "แก้วมัค": "m", "แก้ว": "m",
    "pine": "p", "ไพน์": "p",
    "jug": "j", "เหยือก": "j",
    "tower": "t", "ทาวเวอร์": "t",
    "h40l": "h40l", "h90": "h90", "h120": "h120",
    "counter": "sct", "เคาน์เตอร์": "sct", "sct": "sct",
    "table": "st", "โต๊ะ": "st", "st": "st",
    "astand": "ast", "ast": "ast",
    "standee": "std", "สแตนดี้": "std", "std": "std",
    "galaxyแบน": "galf", "กาแล็กซี่แบน": "galf", "galf": "galf", "gal-f": "galf", "แบน": "galf",
    "galaxyกลม": "galr", "กาแล็กซี่กลม": "galr", "galr": "galr", "gal-r": "galr", "กลม": "galr",
    "tendo360": "tend3", "เทนโด360": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "เทนโด700": "tend7", "tend7": "tend7",
    "kacha": "kach", "คชา": "kach", "kach": "kach",
    "sojuyogurt": "sojy", "โซจโยเกิร์ต": "sojy", "sojy": "sojy",
    "sojupeach": "sojp", "โซจพีช": "sojp", "sojp": "sojp",
    "sojugrape": "sojg", "โซจองุ่น": "sojg", "sojg": "sojg",
    "soju grapefruit": "sojf", "sojf": "sojf",
    "sojustrawberry": "sojs", "โซจสตรอ": "sojs", "sojs": "sojs"
}

STATUSES = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"),
    "overdue": ("🚨", "เลยกำหนดชำระ / Overdue", "#FF334B"),
    "insufficient_credit": ("⚠️", "วงเงินไม่พอ / วงเงินเต็ม", "#FF334B")
}

def num(v):
    try:
        return int(v)
    except Exception:
        return 0

def fetch_fresh_data():
    try:
        shops_res = supabase.table("shops").select("*").execute()
        orders_res = supabase.table("orders").select("*").execute()
        shops = shops_res.data or []
        orders = [{k: num(r[k]) if k in CODES else r[k] for k in r} for r in (orders_res.data or [])]
        return shops, orders
    except Exception as e:
        print(f"❌ DB Fetch Error: {e}")
        return [], []

def get_or_create_shop(name):
    shops, _ = fetch_fresh_data()
    dn = name.strip()
    if not dn.startswith("ร้าน"):
        dn = "ร้าน " + dn
    s = next((s for s in shops if s["name"] == dn), None)
    if s:
        return s
    try:
        res = supabase.table("shops").insert({
            "name": dn, 
            "aliases": "", 
            "credit_limit": 50000, 
            "current_balance": 0
        }).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"❌ Shop Create Error: {e}")
    return None

def shop_by_id(sid, shops_cache):
    return next((s for s in shops_cache if str(s.get("id")) == str(sid)), None)

def dmy(iso):
    try:
        y, m, d = iso.split("-")
        return f"{int(d):02d}/{int(m):02d}/{y}"
    except Exception:
        return iso

def today():
    return datetime.now(TZ).date()

def resolve_date(day_val):
    t = today()
    try:
        return date(t.year, t.month, day_val).isoformat()
    except Exception:
        return t.isoformat()

def send_reply(reply_token, messages):
    if not isinstance(messages, list):
        messages = [messages]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": messages
    }
    res = requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)
    print(f"DEBUG Reply Status: {res.status_code}, Body: {res.text}")

def build_summary_carousel():
    try:
        shops, orders = fetch_fresh_data()
        if not orders:
            return {"type": "text", "text": "📭 ยังไม่มีข้อมูลออเดอร์ในระบบ"}

        grouped_by_date = {}
        for o in orders:
            dt = o.get("ddate", "ไม่ระบุ")
            if dt not in grouped_by_date:
                grouped_by_date[dt] = []
            grouped_by_date[dt].append(o)

        bubbles = []
        for date_str, date_orders in sorted(grouped_by_date.items()):
            shop_contents = []
            
            for idx, o in enumerate(date_orders):
                sh = shop_by_id(o["shop_id"], shops)
                shop_name = sh["name"] if sh else "ร้านค้า"
                order_id = o.get("id")
                status_key = o.get("status", "credit")
                icon, label, color = STATUSES.get(status_key, ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"))

                item_rows = []
                for code in CODES:
                    q = num(o.get(code, 0))
                    if q > 0:
                        p_name = PRODUCTS_DB.get(code, code)
                        item_rows.append({
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": f"• {p_name}", "size": "sm", "color": "#333333", "flex": 4},
                                {"type": "text", "text": str(q), "size": "sm", "align": "end", "weight": "bold", "flex": 1}
                            ]
                        })
                if not item_rows:
                    item_rows.append({"type": "text", "text": "ไม่มีสินค้า", "size": "sm", "color": "#888888"})

                if idx > 0:
                    shop_contents.append({"type": "separator", "margin": "lg"})

                # รายละเอียดแต่ละร้าน พร้อมปุ่มเปลี่ยนสเตตัสรายร้าน
                shop_contents.extend([
                    {"type": "text", "text": shop_name, "weight": "bold", "size": "md", "color": "#111111", "margin": "md"},
                    {"type": "text", "text": f"{icon} {label}", "size": "xs", "weight": "bold", "color": color, "margin": "xs"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": item_rows},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "Order ✅",
                                    "data": f"action=status&id={order_id}&status=ordered"
                                }
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "สลิป 👍",
                                    "data": f"action=status&id={order_id}&status=slip"
                                }
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "เครดิต 💳",
                                    "data": f"action=status&id={order_id}&status=credit"
                                }
                            }
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "Overdue 🚨",
                                    "data": f"action=status&id={order_id}&status=overdue"
                                }
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "วงเงินเต็ม ⚠️",
                                    "data": f"action=status&id={order_id}&status=insufficient_credit"
                                }
                            }
                        ]
                    }
                ])

            # ส่วนหัวของการ์ดแต่ละวัน เพิ่มปุ่มจัดการทั้งหมด (Bulk Actions)
            bubbles.append({
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": f"📅 สรุปยอดวันที่ {dmy(date_str)}", "weight": "bold", "size": "sm", "color": "#ffffff"},
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#1DB446",
                                    "action": {
                                        "type": "postback",
                                        "label": "Order ทั้งหมด ✅",
                                        "data": f"action=bulk_status&date={date_str}&status=ordered"
                                    }
                                },
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#00B900",
                                    "action": {
                                        "type": "postback",
                                        "label": "สลิปทั้งหมด 👍",
                                        "data": f"action=bulk_status&date={date_str}&status=slip"
                                    }
                                }
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#FF334B",
                                    "action": {
                                        "type": "postback",
                                        "label": "ยกเลิกทั้งหมด ❌",
                                        "data": f"action=bulk_cancel&date={date_str}"
                                    }
                                }
                            ]
                        }
                    ],
                    "backgroundColor": "#06C755"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": shop_contents
                }
            })

        return {
            "type": "flex",
            "altText": "สรุปรายการออเดอร์รายวัน",
            "contents": {
                "type": "carousel",
                "contents": bubbles[:10]
            }
        }
    except Exception as e:
        print(f"❌ Build Carousel Error: {e}")
        return {"type": "text", "text": f"❌ เกิดข้อผิดพลาดในการสร้างการ์ดสรุป: {str(e)}"}

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    if SECRET:
        h = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        if base64.b64encode(h).decode("utf-8") != signature:
            abort(400)

    try:
        events = json.loads(body).get("events", [])
        for event in events:
            if event.get("type") == "message":
                handle_message(event)
            elif event.get("type") == "postback":
                handle_postback(event)
    except Exception as e:
        print(f"❌ Callback Error: {e}")

    return "OK", 200

def handle_postback(event):
    reply_token = event["replyToken"]
    data = event.get("postback", {}).get("data", "")
    
    params = dict(item.split("=") for item in data.split("&") if "=" in item)
    action = params.get("action")
    
    try:
        if action == "status":
            order_id = params.get("id")
            new_status = params.get("status")
            supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()
            print(f"✅ Order {order_id} status updated to {new_status}")
            
        elif action == "bulk_status":
            target_date = params.get("date")
            new_status = params.get("status")
            supabase.table("orders").update({"status": new_status}).eq("ddate", target_date).execute()
            print(f"✅ All orders on {target_date} updated to {new_status}")
            
        elif action == "bulk_cancel":
            target_date = params.get("date")
            supabase.table("orders").delete().eq("ddate", target_date).execute()
            print(f"✅ All orders on {target_date} deleted/cancelled")
            
    except Exception as e:
        print(f"❌ Postback Action Error: {e}")
        send_reply(reply_token, {"type": "text", "text": f"❌ เกิดข้อผิดพลาดในการจัดการระบบ: {e}"})
        return

    res_obj = build_summary_carousel()
    send_reply(reply_token, res_obj)

def handle_message(event):
    msg = event["message"]
    if msg.get("type") != "text":
        return
    text = msg.get("text", "").strip()
    reply_token = event["replyToken"]

    if text in ["สรุป", "ยอด", "list"]:
        res_obj = build_summary_carousel()
        send_reply(reply_token, res_obj)
        return

    if text in ["คู่มือ", "ช่วยเหลือ", "help"]:
        help_text = (
            "📖 วิธีการใช้งานบอทสั่งของ:\n\n"
            "1️⃣ สั่งแบบใช้งวดวันนี้ (ง่ายที่สุด):\n"
            "พิมพ์ [ชื่อร้าน] [สินค้า] [จำนวน]\n"
            "เช่น: เจ๊โน galf 2\n\n"
            "2️⃣ สั่งแบบระบุวัน:\n"
            "พิมพ์ [วัน] [ชื่อร้าน] [สินค้า] [จำนวน]\n"
            "เช่น: 17 เจ๊โน galf 2\n\n"
            "3️⃣ คำสั่งอื่นๆ:\n"
            "- พิมพ์ 'สรุป' เพื่อดูการ์ดออเดอร์ทั้งหมด\n"
            "- พิมพ์ 'ดูรหัส' เพื่อดูชื่อย่อสินค้า"
        )
        send_reply(reply_token, {"type": "text", "text": help_text})
        return

    if text == "ดูรหัส":
        product_list = "\n".join([f"- {k}: {v}" for k, v in PRODUCTS_DB.items()])
        send_reply(reply_token, {"type": "text", "text": f"📋 รหัส/คำย่อสินค้า:\n{product_list}"})
        return

    parts = text.split()
    
    if len(parts) >= 2 and not parts[0].isdigit():
        resolved_dt = today().isoformat()
        shop_name = parts[0]
        raw_product = parts[1].lower()
        qty = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1

        process_order(event, reply_token, resolved_dt, shop_name, raw_product, qty)
        return

    if len(parts) >= 3 and parts[0].isdigit():
        d_val = int(parts[0])
        resolved_dt = resolve_date(d_val)
        shop_name = parts[1]
        raw_product = parts[2].lower()
        qty = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 1

        process_order(event, reply_token, resolved_dt, shop_name, raw_product, qty)
        return

    send_reply(reply_token, {"type": "text", "text": "💡 ไม่เข้าใจคำสั่ง พิมพ์ 'คู่มือ' เพื่อดูวิธีสั่งซื้อครับ"})

def process_order(event, reply_token, resolved_dt, shop_name, raw_product, qty):
    shop = get_or_create_shop(shop_name)
    if not shop:
        send_reply(reply_token, {"type": "text", "text": f"❌ ไม่สามารถสร้างหรือหาร้าน '{shop_name}' ในระบบได้"})
        return
        
    shop_id = shop["id"]

    code = ALIAS_MAP.get(raw_product)
    if not code:
        send_reply(reply_token, {
            "type": "text", 
            "text": f"❌ ไม่พบสินค้า '{raw_product}' พิมพ์ 'ดูรหัส' เพื่อดูรายการสินค้าทั้งหมดครับ"
        })
        return

    _, current_orders = fetch_fresh_data()
    existing = next((o for o in current_orders if str(o["shop_id"]) == str(shop_id) and o.get("ddate") == resolved_dt), None)
    
    try:
        if existing:
            oid = existing["id"]
            curr_q = num(existing.get(code, 0))
            supabase.table("orders").update({code: curr_q + qty}).eq("id", oid).execute()
        else:
            payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": "credit", code: qty}
            supabase.table("orders").insert(payload).execute()

    except Exception as db_err:
        print(f"❌ DB Error: {db_err}")
        send_reply(reply_token, {"type": "text", "text": f"❌ เกิดข้อผิดพลาดในการบันทึกข้อมูล: {db_err}"})
        return

    res_obj = build_summary_carousel()
    send_reply(reply_token, res_obj)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
