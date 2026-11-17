import os
import json
import re
import base64
import hashlib
from datetime import datetime
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

# --- PRODUCT LIST (ตัวอย่างสินค้าเบื้องต้น) ---
PRODUCTS_DB = {
    "l": "Lager", "r": "Rose", "d": "Dunkel",
    "galf": "Galaxy แบน", "galr": "Galaxy กลม"
}
CODES = list(PRODUCTS_DB.keys())

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

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    
    # ตรวจสอบความปลอดภัย Signature ของ LINE
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
        print(f"❌ Error in callback: {e}")

    return "OK", 200

def handle_message(event):
    msg = event["message"]
    if msg.get("type") != "text":
        return
    
    text = msg.get("text", "").strip()
    reply_token = event["replyToken"]

    # ทดสอบคำสั่ง "สรุป" แบบง่ายสุดๆ เพื่อเช็กว่าบอทตอบ Flex/Text กลับมาไหม
    if text == "สรุป":
        try:
            # ดึงข้อมูล orders จาก Supabase
            res = supabase.table("orders").select("*").execute()
            orders = res.data or []

            if not orders:
                send_reply(reply_token, {"type": "text", "text": "📭 ยังไม่มีข้อมูลออเดอร์ในระบบ"})
                return

            # สร้าง Flex Message แบบ Carousel ง่ายๆ
            bubbles = []
            for o in orders:
                shop_id = o.get("shop_id")
                date_str = o.get("ddate", "ไม่ระบุวันที่")
                
                # ดึงชื่อร้าน
                shop_res = supabase.table("shops").select("name").eq("id", shop_id).execute()
                shop_name = shop_res.data[0]["name"] if shop_res.data and shop_res.data[0] else f"ร้าน ID: {shop_id}"

                bubbles.append({
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": f"วันที่: {date_str}", "weight": "bold", "size": "md"},
                            {"type": "text", "text": f"ร้าน: {shop_name}", "size": "sm", "color": "#555555"},
                            {"type": "separator", "margin": "md"},
                            {"type": "text", "text": f"สถานะ: {o.get('status', 'pending')}", "size": "xs", "margin": "md", "color": "#06C755"}
                        ]
                    }
                })

            flex_msg = {
                "type": "flex",
                "altText": "สรุปออเดอร์",
                "contents": {
                    "type": "carousel",
                    "contents": bubbles[:10]  # จำกัดไม่เกิน 10 bubbles ต่อ carousel
                }
            }
            send_reply(reply_token, flex_msg)

        except Exception as e:
            print(f"❌ Error fetching summary: {e}")
            send_reply(reply_token, {"type": "text", "text": f"⚠️ เกิดข้อผิดพลาดในการดึงข้อมูล: {str(e)}"})
    else:
        send_reply(reply_token, {"type": "text", "text": f"ได้รับข้อความแล้ว: {text} (พิมพ์ 'สรุป' เพื่อดูรายการ)"})

def handle_postback(event):
    reply_token = event["replyToken"]
    data = event["postback"].get("data", "")
    send_reply(reply_token, {"type": "text", "text": f"ได้รับ Postback: {data}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
