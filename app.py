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
    # Draft Beer
    "l": "Lager", "r": "Rose", "d": "Dunkel",
    # Glasses & Towers
    "m": "MUG", "p": "PINE", "j": "JUG", "t": "TOWER",
    # Dispensers
    "h40l": "Hoshizaki 40L", "h90": "Hoshizaki 90L", "h120": "Hoshizaki 120L",
    # Stainless Furniture
    "sct": "Stainless Counter", "st": "Stainless Table",
    # POSM & Marketing
    "ast": "A-Stand", "std": "Standee", "aa5": "อะคริลิก A5", "aa6": "อะคริลิก A6",
    # Galaxy
    "galf": "Galaxy แบน 350ml", "galr": "Galaxy กลม 700ml",
    # Tendo
    "tend3": "Tendo 360ml", "tend7": "Tendo 700ml",
    # Kacha
    "kach": "Kacha 375ml",
    # Soju
    "sojy": "Soju โยเกิร์ต", "sojp": "Soju พีช",
    "sojg": "Soju องุ่น", "sojf": "Soju เกรปฟรุ๊ต", "sojs": "Soju สตรอเบอรี่"
}

CODES = list(PRODUCTS_DB.keys())

ALIAS_MAP = {
    "lager": "l", "l": "l",
    "rose": "r", "r": "r",
    "dunkel": "d", "d": "d",
    "mug": "m", "m": "m",
    "pine": "p", "p": "p",
    "jug": "j", "j": "j",
    "tower": "t", "t": "t",
    "h40l": "h40l", "h90": "h90", "h120": "h120",
    "counter": "sct", "sct": "sct",
    "table": "st", "st": "st",
    "astand": "ast", "ast": "ast",
    "standee": "std", "std": "std",
    "galaxyแบน": "galf", "galf": "galf", "gal-f": "galf",
    "galaxyกลม": "galr", "galr": "galr", "gal-r": "galr",
    "tendo360": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "tend7": "tend7",
    "kacha": "kach", "kach": "kach",
    "sojuyogurt": "sojy", "sojy": "sojy",
    "sojupeach": "sojp", "sojp": "sojp",
    "sojugrape": "sojg", "sojg": "sojg",
    "soju grapefruit": "sojf", "sojf": "sojf",
    "sojustrawberry": "sojs", "sojs": "sojs"
}

# --- STATUSES (เพิ่ม credit เข้าไปเรียบร้อย) ---
STATUSES = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"),
    "overdue": ("🚨", "เลยกำหนดชำระ / Overdue", "#FF334B"),
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

def shop_by_id(sid):
    shops, _ = fetch_fresh_data()
    return next((s for s in shops if str(s.get("id")) == str(sid)), None)

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
    _, orders = fetch_fresh_data()
    if not orders:
        return {"type": "text", "text": "📭 ยังไม่มีข้อมูลออเดอร์ในระบบ"}

    bubbles = []
    for o in orders:
        sh = shop_by_id(o["shop_id"])
        shop_name = sh["name"] if sh else "ร้านค้า"
        credit_limit = num(sh.get("credit_limit", 50000)) if sh else 50000
        current_balance = num(sh.get("current_balance", 0)) if sh else 0
        
        date_str = o.get("ddate", "ไม่ระบุ")
        status_key = o.get("status", "pending")
        icon, label, color = STATUSES.get(status_key, ("⏳", "Pending", "#FF9900"))

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

        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"📅 {dmy(date_str)}", "weight": "bold", "size": "sm", "color": "#555555"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": shop_name, "weight": "bold", "size": "md", "color": "#111111"},
                    {"type": "text", "text": f"{icon} {label}", "size": "xs", "weight": "bold", "color": color, "margin": "xs"},
                    {"type": "text", "text": f"💳 วงเงินคงเหลือ: {credit_limit - current_balance:,.2f} / {credit_limit:,.2f} ฿", "size": "xxs", "color": "#888888", "margin": "sm"},
                    {"type": "separator", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": item_rows}
                ]
            }
        })

    return {
        "type": "flex",
        "altText": "สรุปรายการออเดอร์",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10]
        }
    }

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
    except Exception as e:
        print(f"❌ Error: {e}")

    return "OK", 200

def handle_message(event):
    msg = event["message"]
    if msg.get("type") != "text":
        return
    text = msg.get("text", "").strip()
    reply_token = event["replyToken"]

    if text == "สรุป":
        res_obj = build_summary_carousel()
        send_reply(reply_token, res_obj)
        return

    # รูปแบบการพิมพ์ออเดอร์ เช่น: 17 เจ๊โน galf 2
    parts = text.split()
    if len(parts) >= 3 and parts[0].isdigit():
        d_val = int(parts[0])
        resolved_dt = resolve_date(d_val)
        shop_name = parts[1]
        raw_product = parts[2].lower()
        qty = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 1

        shop = get_or_create_shop(shop_name)
        shop_id = shop["id"]

        # ตรวจสอบวงเงิน (Credit Limit Check)
        credit_limit = num(shop.get("credit_limit", 50000))
        current_balance = num(shop.get("current_balance", 0))
        estimated_cost = qty * 500  # ตัวอย่างราคาประเมินต่อหน่วย
        
        if current_balance + estimated_cost > credit_limit:
            send_reply(reply_token, {
                "type": "text", 
                "text": f"⚠️ ขออภัยครับ วงเงินร้าน {shop_name} ไม่พอสำหรับการสั่งซื้อนี้!\n(วงเงินจำกัด: {credit_limit:,.2f} ฿, ยอดใช้ไป: {current_balance:,.2f} ฿)"
            })
            return

        code = ALIAS_MAP.get(raw_product, "galf")

        # บันทึกลง Supabase (กำหนดสถานะเริ่มต้นเป็น credit ได้ หรือคง pending ไว้ตามต้องการ)
        _, current_orders = fetch_fresh_data()
        existing = next((o for o in current_orders if str(o["shop_id"]) == str(shop_id) and o.get("ddate") == resolved_dt), None)
        
        if existing:
            oid = existing["id"]
            curr_q = num(existing.get(code, 0))
            supabase.table("orders").update({code: curr_q + qty}).eq("id", oid).execute()
        else:
            payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": "credit", code: qty}
            supabase.table("orders").insert(payload).execute()

        # อัปเด่ายอดเงินสะสมของร้านใน Supabase
        supabase.table("shops").update({"current_balance": current_balance + estimated_cost}).eq("id", shop_id).execute()

        # ตอบกลับด้วยการ์ดสรุปผลทันที
        res_obj = build_summary_carousel()
        send_reply(reply_token, res_obj)
        return

    send_reply(reply_token, {"type": "text", "text": f"พิมพ์ 'สรุป' หรือสั่งออเดอร์ เช่น '17 เจ๊โน galaxyแบน 2'"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
