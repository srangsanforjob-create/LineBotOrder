import os
import json
import re
import base64
import hashlib
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, abort
import requests
from supabase import create_client, Client

# --- CONFIGURATION ---
SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not all([SECRET, TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ Critical Config Missing!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TZ = ZoneInfo("Asia/Bangkok")
app = Flask(__name__)

# --- PRODUCT DATABASE ---
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
    "lager": "l", "ลาเกอร์": "l", "ลากิอร์": "l", "ลีโอ": "l", "เบียร์": "l", "l": "l",
    "rose": "r", "โรส": "r", "โรเซ่": "r", "r": "r",
    "dunkel": "d", "ดุงเกล": "d", "ดังก์เกล": "d", "ดำ": "d", "d": "d",
    "mug": "m", "แก้วมัค": "m", "มัค": "m", "m": "m",
    "pine": "p", "ไพน์": "p", "ไพนต์": "p", "p": "p",
    "jug": "j", "เหยือก": "j", "j": "j",
    "tower": "t", "ทาวเวอร์": "t", "ทาว": "t", "t": "t",
    "h40l": "h40l", "h40": "h40l", "40l": "h40l",
    "h90": "h90", "h90l": "h90", "90l": "h90",
    "h120": "h120", "h120l": "h120", "120l": "h120",
    "counter": "sct", "เคาน์เตอร์": "sct", "sct": "sct",
    "table": "st", "โต๊ะ": "st", "st": "st",
    "astand": "ast", "a-stand": "ast", "ast": "ast",
    "standee": "std", "สแตนดี้": "std", "std": "std",
    "aa5": "aa5", "a5": "aa5", "อะคริลิกa5": "aa5",
    "aa6": "aa6", "a6": "aa6", "อะคริลิกa6": "aa6",
    "galaxyแบน": "galf", "กาแล็กซี่แบน": "galf", "galf": "galf", "gal-f": "galf", "แบน": "galf",
    "galaxyกลม": "galr", "กาแล็กซี่กลม": "galr", "galr": "galr", "gal-r": "galr", "กลม": "galr",
    "tendo360": "tend3", "เทนโด360": "tend3", "เทนโดเล็ก": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "เทนโด700": "tend7", "เทนโดใหญ่": "tend7", "tend7": "tend7",
    "kacha": "kach", "คชา": "kach", "kach": "kach",
    "sojuyogurt": "sojy", "โซจูโยเกิร์ต": "sojy", "โซจโยเกิร์ต": "sojy", "โยเกิร์ต": "sojy", "sojy": "sojy",
    "sojupeach": "sojp", "โซจูพีช": "sojp", "โซจพีช": "sojp", "พีช": "sojp", "sojp": "sojp",
    "sojugrape": "sojg", "โซจูองุ่น": "sojg", "โซจองุ่น": "sojg", "องุ่น": "sojg", "sojg": "sojg",
    "sojugrapefruit": "sojf", "โซจูเกรปฟรุ๊ต": "sojf", "เกรปฟรุ๊ต": "sojf", "sojf": "sojf",
    "sojustrawberry": "sojs", "โซจูสตรอเบอรี่": "sojs", "โซจสตรอ": "sojs", "สตรอเบอรี่": "sojs", "sojs": "sojs"
}

STATUS_LABELS = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"),
    "overdue": ("🚨", "เลยกำหนดชำระ / Overdue", "#FF334B"),
    "insufficient_credit": ("⚠️", "วงเงินไม่พอ / วงเงินเต็ม", "#FF334B")
}

STATUS_KEYWORDS = {
    'pending': 'pending', 'รอดำเนินการ': 'pending', 'ยังไม่ได้ออเดอร์': 'pending', 'รอยืนยัน': 'pending',
    'order': 'ordered', 'ออเดอร์': 'ordered', 'สั่งแล้ว': 'ordered', 'ยืนยันออเดอร์': 'ordered',
    'slip': 'slip', 'สลิป': 'slip', 'จ่ายเงินแล้ว': 'slip', 'แนบสลิป': 'slip',
    'credit': 'credit', 'เครดิต': 'credit', 'เงินเชื่อ': 'credit',
    'overdue': 'overdue', 'เกินกำหนด': 'overdue',
    'insufficient_credit': 'insufficient_credit', 'วงเงินเต็ม': 'insufficient_credit'
}

DAYS_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
MONTHS_TH = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
]

def format_thai_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = DAYS_TH[dt.weekday()]
        month_name = MONTHS_TH[dt.month - 1]
        year_th = dt.year + 543
        return f"วัน{day_name} ที่ {dt.day} {month_name} {year_th}"
    except:
        return f"วันที่ {date_str}"

def safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0

def get_bangkok_date_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def fetch_data(chat_id):
    try:
        shops_res = supabase.table("shops").select("*").execute()
        orders_res = supabase.table("orders").select("*").eq("chat_id", chat_id).order("id", desc=False).execute()
        shops = shops_res.data or []
        orders = orders_res.data or []
        return shops, orders
    except Exception as e:
        print(f"Database Error: {e}")
        return [], []

def get_or_create_shop(shop_name):
    clean_name = shop_name.strip()
    if not clean_name.startswith("ร้าน"):
        clean_name = f"ร้าน {clean_name}"
    try:
        existing = supabase.table("shops").select("*").eq("name", clean_name).execute()
        if existing.data and len(existing.data) > 0:
            return existing.data[0]
        new_shop = supabase.table("shops").insert({
            "name": clean_name, "aliases": "", "credit_limit": 50000, "current_balance": 0
        }).execute()
        if new_shop.data:
            return new_shop.data[0]
    except Exception as e:
        print(f"Shop Handling Error: {e}")
    return None

def parse_order_text(raw_text):
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    parsed_items_list = []
    global_errors = []

    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        
        status = 'pending'
        last_word = tokens[-1].lower()
        if last_word in STATUS_KEYWORDS:
            status = STATUS_KEYWORDS[last_word]
            tokens.pop()
        
        if not tokens:
            continue

        first_item_idx = -1
        for i, token in enumerate(tokens):
            clean_tok = token.lower().strip()
            if clean_tok in ALIAS_MAP or clean_tok in CODES:
                first_item_idx = i
                break
            m = re.match(r"^([a-zA-Zก-๙\-]+)(-?\d+)$", clean_tok)
            if m and m.group(1).lower() in ALIAS_MAP:
                first_item_idx = i
                break
        
        if first_item_idx == -1:
            global_errors.append(f"ไม่พบรายการสินค้าในบรรทัด: {line}")
            continue

        shop_name = " ".join(tokens[:first_item_idx]) if first_item_idx > 0 else "ร้านค้าทั่วไป"
        item_tokens = tokens[first_item_idx:]
        
        items = {}
        i = 0
        while i < len(item_tokens):
            tok = item_tokens[i]
            clean_tok = tok.lower().strip()
            
            m = re.match(r"^([a-zA-Zก-๙\-]+)(-?\d+)$", clean_tok)
            if m:
                p_part = m.group(1)
                qty_part = safe_int(m.group(2))
                if p_part in ALIAS_MAP:
                    code = ALIAS_MAP[p_part]
                    items[code] = items.get(code, 0) + qty_part
                    i += 1
                    continue
            
            if clean_tok in ALIAS_MAP:
                code = ALIAS_MAP[clean_tok]
                qty = 1
                if i + 1 < len(item_tokens) and re.match(r"^-?\d+$", item_tokens[i+1]):
                    qty = safe_int(item_tokens[i+1])
                    i += 1
                items[code] = items.get(code, 0) + qty
            else:
                global_errors.append(f"ไม่รู้จักสินค้า: {tok}")
            i += 1
            
        if items:
            parsed_items_list.append({
                "shop_name": shop_name,
                "status": status,
                "items": items
            })
            
    return parsed_items_list, global_errors

def build_carousel(chat_id):
    shops, orders = fetch_data(chat_id)
    if not orders:
        return {"type": "text", "text": "ยังไม่มีรายการออเดอร์ในแชทนี้"}

    shop_map = {str(s["id"]): s for s in shops}
    
    grouped_by_date = {}
    for order in orders:
        ddate = order.get("ddate", get_bangkok_date_str())
        if ddate not in grouped_by_date:
            grouped_by_date[ddate] = []
        grouped_by_date[ddate].append(order)

    bubbles = []
    
    for ddate, date_orders in grouped_by_date.items():
        daily_totals = {code: 0 for code in CODES}
        formatted_date = format_thai_date(ddate)
        
        content_blocks = [
            {"type": "text", "text": formatted_date, "weight": "bold", "size": "md", "color": "#111111"},
            {
                "type": "box", "layout": "horizontal", "spacing": "sm", "margin": "md",
                "contents": [
                    {
                        "type": "button", "action": {
                            "type": "postback", "label": "Order แล้ว",
                            "data": f"action=update_daily&date={ddate}&status=ordered"
                        }, "style": "primary", "color": "#06C755", "height": "sm"
                    },
                    {
                        "type": "button", "action": {
                            "type": "postback", "label": "อัปสลิปแล้ว",
                            "data": f"action=update_daily&date={ddate}&status=slip"
                        }, "style": "primary", "color": "#00B900", "height": "sm"
                    },
                    {
                        "type": "button", "action": {
                            "type": "postback", "label": "ยกเลิกทั้งหมด",
                            "data": f"action=delete_daily&date={ddate}"
                        }, "style": "secondary", "color": "#FF334B", "height": "sm"
                    }
                ]
            },
            {"type": "separator", "margin": "lg"}
        ]
        
        for order in date_orders:
            s_id = str(order.get("shop_id"))
            shop_info = shop_map.get(s_id)
            shop_name = shop_info["name"] if shop_info else "ร้านค้า"
            order_status = order.get("status", "pending")
            icon, label, color = STATUS_LABELS.get(order_status, ("⏳", "ยังไม่ได้ Order", "#FF9900"))

            item_rows = []
            for code in CODES:
                q = safe_int(order.get(code))
                if q > 0:
                    daily_totals[code] += q
                    p_name = PRODUCTS_DB.get(code, code)
                    item_rows.append({
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"• {p_name}", "size": "sm", "color": "#333333", "flex": 4},
                            {"type": "text", "text": str(q), "size": "sm", "align": "end", "weight": "bold", "flex": 1}
                        ]
                    })
            if not item_rows:
                item_rows.append({"type": "text", "text": "ไม่มีสินค้า", "size": "sm", "color": "#888888"})

            content_blocks.append({
                "type": "box", "layout": "vertical", "margin": "md",
                "contents": [
                    {"type": "text", "text": shop_name, "weight": "bold", "size": "sm", "color": "#0066cc"},
                    {"type": "text", "text": f"{icon} {label}", "size": "xs", "weight": "bold", "color": color},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": item_rows},
                    {"type": "separator", "margin": "md"}
                ]
            })

        summary_rows = []
        for code in CODES:
            tot = daily_totals[code]
            if tot > 0:
                p_name = PRODUCTS_DB.get(code, code)
                summary_rows.append({
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"• {p_name}", "size": "sm", "color": "#ffffff", "flex": 4},
                        {"type": "text", "text": str(tot), "size": "sm", "align": "end", "weight": "bold", "color": "#ffffff", "flex": 1}
                    ]
                })
        
        if summary_rows:
            content_blocks.append({
                "type": "box", "layout": "vertical", "margin": "md", "paddingAll": "md",
                "backgroundColor": "#222222", "cornerRadius": "md",
                "contents": [
                    {"type": "text", "text": "📦 รวมยอดสินค้าประจำวันนี้", "weight": "bold", "size": "sm", "color": "#ffcc00"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": summary_rows}
                ]
            })

        bubbles.append({
            "type": "bubble", "size": "mega",
            "body": {
                "type": "box", "layout": "vertical",
                "contents": content_blocks
            }
        })

    return {"type": "flex", "altText": "สรุปรายการออเดอร์ตามวัน", "contents": {"type": "carousel", "contents": bubbles[:10]}}

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    if SECRET:
        hash_val = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        if base64.b64encode(hash_val).decode("utf-8") != signature:
            abort(400)
    try:
        events = json.loads(body).get("events", [])
        for event in events:
            if event.get("type") == "postback":
                data_str = event.get("postback", {}).get("data", "")
                query_params = dict(qp.split("=") for qp in data_str.split("&") if "=" in qp)
                action = query_params.get("action")
                target_date = query_params.get("date")
                source = event.get("source", {})
                chat_type = source.get("type", "user")
                if chat_type == "group": chat_id = source.get("groupId")
                elif chat_type == "room": chat_id = source.get("roomId")
                else: chat_id = source.get("userId", "user")
                
                reply_token = event.get("replyToken", "")
                
                if action == "update_daily" and target_date:
                    new_status = query_params.get("status", "pending")
                    supabase.table("orders").update({"status": new_status}).eq("chat_id", chat_id).eq("ddate", target_date).execute()
                    send_reply(reply_token, [build_carousel(chat_id)])
                elif action == "delete_daily" and target_date:
                    supabase.table("orders").delete().eq("chat_id", chat_id).eq("ddate", target_date).execute()
                    send_reply(reply_token, [build_carousel(chat_id)])
                continue

            if event.get("type") == "message" and event["message"].get("type") == "text":
                text = event["message"]["text"].strip()
                source = event.get("source", {})
                chat_type = source.get("type", "user")
                if chat_type == "group": chat_id = source.get("groupId")
                elif chat_type == "room": chat_id = source.get("roomId")
                else: chat_id = source.get("userId", "user")
                
                reply_token = event.get("replyToken", "")
                
                if text in ["คู่มือ", "ช่วยเหลือ", "help"]:
                    send_reply(reply_token, [{"type": "text", "text": "คู่มือการใช้งาน...\n1. พิมพ์ชื่อร้านและรายการสินค้า\n2. ใส่สถานะต่อท้ายได้ทั้งไทยและอังกฤษ เช่น order, slip"}])
                    continue
                
                parsed_list, errors = parse_order_text(text)
                for entry in parsed_list:
                    shop = get_or_create_shop(entry["shop_name"])
                    if shop:
                        payload = {
                            "chat_id": chat_id, "chat_type": chat_type, "shop_id": shop["id"],
                            "ddate": get_bangkok_date_str(), "status": entry["status"]
                        }
                        for k, v in entry["items"].items(): payload[k] = v
                        supabase.table("orders").insert(payload).execute()
                
                msg_objs = []
                if errors:
                    msg_objs.append({"type": "text", "text": "⚠️ แจ้งเตือน:\n" + "\n".join(errors)})
                msg_objs.append(build_carousel(chat_id))
                send_reply(reply_token, msg_objs)
    except Exception as e:
        print(f"Callback Error: {e}")
    return "OK", 200

def send_reply(reply_token, messages):
    if not reply_token or not messages:
        return
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
    try:
        requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json={"replyToken": reply_token, "messages": messages})
    except Exception as e:
        print(f"Reply Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
