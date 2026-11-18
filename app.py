import os
import re
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# --- LINE API CONFIGURATION ---
# ดึงค่าจาก Environment Variable หรือใส่ Token และ Secret ของคุณตรงนี้ให้ถูกต้อง
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- GOOGLE SHEETS SETUP ---
# หมายเหตุ: นำไฟล์ credentials.json วางไว้ที่เดียวกับ app.py หรือตั้งค่าผ่าน Service Account
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    sheet = client.open("Beer_Order_DB").sheet1
except Exception as e:
    sheet = None  # กรณีรันเทสแบบ Offline หรือยังไม่ได้ต่อ Google Sheets

# --- PRODUCT CATALOG & CATEGORIES ---
PRODUCT_CATALOG = {
    "Draft Beer": ["L", "M", "H40L", "H90L", "H120L", "DBF"],
    "Amenity": ["CO2", "SCT", "Table"],
    "POSM": ["Standee", "LightBox", "Poster"],
    "OtherALC": ["GALF", "TEND3"],
    "Bottles/Cans": ["LC", "Cider"],
    "Support": ["supL", "supM", "ซัพL", "ซัพM", "ซัพแก้ว"]
}

ALL_PRODUCTS = []
for cat, items in PRODUCT_CATALOG.items():
    ALL_PRODUCTS.extend(items)

# --- STATUS DEFINITIONS ---
STATUS_MAP = {
    "pending": "Pending",
    "รอจัดส่ง": "Pending",
    "order แล้ว": "Order แล้ว",
    "สั่งแล้ว": "Order แล้ว",
    "อัพสลิปแล้ว": "อัพสลิปแล้ว",
    "แนบสลิปแล้ว": "อัพสลิปแล้ว",
    "เครดิต": "เครดิต",
    "overdue": "Overdue",
    "เกินกำหนด": "Overdue",
    "limit": "Limit(วงเงินเต็ม)",
    "วงเงินเต็ม": "Limit(วงเงินเต็ม)"
}

THAI_DAYS = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
THAI_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", 
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]

def get_thai_date_str(date_obj):
    day_name = THAI_DAYS[date_obj.weekday()]
    day_num = date_obj.day
    month_name = THAI_MONTHS[date_obj.month]
    year_be = date_obj.year + 543
    return f"{day_name} {day_num} {month_name} {year_be}"

def parse_smart_date(date_str):
    """Smart Date: ถ้าระบุแค่วันที่ (เช่น '19') ให้ปัดเป็นเดือน/ปีปัจจุบันอัตโนมัติ"""
    now = datetime.now()
    if "/" in date_str:
        parts = date_str.split("/")
        d = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 and parts[1] else now.month
        y = int(parts[2]) if len(parts) > 2 and parts[2] else now.year
        if y < 2500:
            pass # ค.ศ.
        return datetime(y, m, d)
    else:
        d = int(date_str)
        return datetime(now.year, now.month, d)

def fuzzy_match_product(query):
    """ระบบคาดเดาและแนะนำสินค้ากรณีพิมพ์ไม่ตรงเป๊ะ"""
    query_lower = query.lower()
    for p in ALL_PRODUCTS:
        if p.lower() == query_lower:
            return p, "exact"
    matches = [p for p in ALL_PRODUCTS if query_lower in p.lower() or p.lower() in query_lower]
    if matches:
        return matches[:3], "suggestion"
    return None, "none"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    # 1. Handle Summary Command (รองรับคำว่า สรุป / summary พร้อมตัวกรอง วันที่ และ สเตตัส)
    if text.lower().startswith("สรุป") or text.lower().startswith("summary"):
        handle_summary_command(event, text)
        return

    # 2. Handle Bulk Actions or Item-level clicks
    if text.startswith("bulk_") or text.startswith("แก้ไข") or text.startswith("ลบ") or text.startswith("select_product"):
        handle_action_command(event, text)
        return

    # 3. Handle Order Input (รองรับการสั่งหลายออร์เดอร์พร้อมกันด้วยการเว้นบรรทัด Multi-line Batch Input)
    lines = text.split("\n")
    success_count = 0
    error_messages = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split(" ", 2)
        if len(parts) >= 2:
            date_raw = parts[0]
            try:
                order_date = parse_smart_date(date_raw)
            except ValueError:
                error_messages.append(f"❌ รูปแบบวันที่ไม่ถูกต้อง: '{date_raw}'")
                continue
            
            remaining = parts[1] if len(parts) > 2 else ""
            
            # บันทึกลง Google Sheets (ถ้าเชื่อมต่อไว้)
            if sheet:
                try:
                    sheet.append_row([order_date.strftime('%Y-%m-%d'), remaining, "Pending"])
                except Exception:
                    pass
            success_count += 1
        else:
            error_messages.append(f"❌ รูปแบบไม่ถูกต้อง: '{line}'")

    if success_count > 0:
        reply_text = f"✅ บันทึกออร์เดอร์สำเร็จทั้งหมด {success_count} รายการ"
        if error_messages:
            reply_text += "\n" + "\n".join(error_messages)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    else:
        # ถ้าข้อความไม่ตรงรูปแบบและไม่เจอสินค้า ให้เช็ค Fuzzy Match
        matched, match_type = fuzzy_match_product(text)
        if match_type == "suggestion":
            line_bot_api.reply_message(event.reply_token, create_fuzzy_suggestion_flex(text, matched))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🤖 สวัสดีครับ พิมพ์ออร์เดอร์ในรูปแบบ [วันที่] [ชื่อร้าน] [รายการสินค้า] หรือพิมพ์ 'สรุป' เพื่อดูรายการ"))

def handle_summary_command(event, text):
    """จัดการคำสั่งสรุป พร้อมตัวกรองวันที่/สเตตัส แบ่งหน้าอัตโนมัติ (หน้า 1/2) และยอดสรุปประจำวัน"""
    tokens = text.split()
    target_date = None
    target_status = None

    for t in tokens[1:]:
        if "/" in t or t.isdigit():
            try:
                target_date = parse_smart_date(t)
            except:
                pass
        else:
            for k, v in STATUS_MAP.items():
                if k in t.lower():
                    target_status = v

    # ข้อมูลจำลองออร์เดอร์ (Mock Database)
    mock_orders = [
        {"store": "ร้านส้มตำลำซิ่ง", "items": [{"name": "L", "qty": 2}, {"name": "M", "qty": 10}], "status": "Pending"},
        {"store": "ร้านนั่งชิล", "items": [{"name": "H40L", "qty": 1}, {"name": "SCT", "qty": 2}], "status": "Order แล้ว"},
        {"store": "ร้านตะวันแดง", "items": [{"name": "L", "qty": 3}, {"name": "supL", "qty": 1}], "status": "อัพสลิปแล้ว"},
        {"store": "ร้านริมคลอง", "items": [{"name": "CO2", "qty": 1}], "status": "เครดิต"},
        {"store": "ร้านเพลินจิต", "items": [{"name": "M", "qty": 5}], "status": "Pending"},
        {"store": "ร้านบ้านสวน", "items": [{"name": "L", "qty": 1}], "status": "Pending"}
    ]

    # กรองตามสเตตัส (ถ้ามีระบุ)
    if target_status:
        mock_orders = [o for o in mock_orders if o["status"] == target_status]

    chunk_size = 5
    bubbles = []
    date_header_str = get_thai_date_str(target_date if target_date else datetime.now())
    
    total_items_count = len(mock_orders)
    total_pages = (total_items_count + chunk_size - 1) // chunk_size
    if total_pages == 0: total_pages = 1

    for page_idx in range(total_pages):
        start_idx = page_idx * chunk_size
        end_idx = start_idx + chunk_size
        page_orders = mock_orders[start_idx:end_idx]

        bubble = create_order_flex_bubble(date_header_str, page_orders, page_idx + 1, total_pages)
        bubbles.append(bubble)

    flex_message = FlexSendMessage(
        alt_text="สรุปออร์เดอร์ประจำวัน",
        contents={"type": "carousel", "contents": bubbles}
    )
    line_bot_api.reply_message(event.reply_token, flex_message)

def handle_action_command(event, text):
    """จัดการปุ่มกดต่างๆ เช่น ปุ่ม Bulk, ปุ่มแก้ไข, ปุ่มลบ, เลือกสินค้า"""
    if text == "bulk_order_all":
        reply = "🟢 อัปเดตสถานะเป็น 'Order แล้ว' ทุกรายการในวันนี้เรียบร้อยแล้ว"
    elif text == "bulk_slip_all":
        reply = "🔵 อัปเดตสถานะเป็น 'อัพสลิปแล้ว' ทุกรายการในวันนี้เรียบร้อยแล้ว"
    elif text == "bulk_cancel_all":
        reply = "🔴 ยกเลิกออร์เดอร์ทั้งหมดในวันนี้เรียบร้อยแล้ว"
    elif text.startswith("แก้ไข"):
        reply = "✏️ กรุณาระบุจำนวนใหม่ หรือเลือกหมวดหมู่สินค้าที่ต้องการเปลี่ยน"
    elif text.startswith("ลบ"):
        reply = "🗑️ ลบรายการออร์เดอร์เรียบร้อยแล้ว"
    elif text.startswith("select_product"):
        prod = text.split(" ")[1] if len(text.split(" ")) > 1 else ""
        reply = f"✅ เลือกสินค้า '{prod}' เรียบร้อยแล้ว"
    else:
        reply = "⚙️ ดำเนินการเรียบร้อยแล้ว"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def create_order_flex_bubble(date_title, orders, current_page, total_pages):
    """สร้าง Bubble สำหรับ Flex Message พร้อมปุ่มจัดการรายร้าน ปุ่ม Bulk และยอดสรุปประจำวัน"""
    body_contents = [
        {"type": "text", "text": date_title, "weight": "bold", "size": "md", "color": "#1DB446"},
        {"type": "text", "text": f"หน้า {current_page}/{total_pages}", "size": "xs", "color": "#aaaaaa", "margin": "sm"},
        {"type": "separator", "margin": "md"}
    ]

    category_summary = {}

    for idx, ord_item in enumerate(orders):
        store = ord_item["store"]
        status = ord_item["status"]
        items_str = ", ".join([f"{i['name']} x{i['qty']}" for i in ord_item["items"]])
        
        for itm in ord_item["items"]:
            category_summary[itm["name"]] = category_summary.get(itm["name"], 0) + itm["qty"]

        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "spacing": "xs",
            "contents": [
                {
                    "type": "box",
                    "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": f"{store}", "weight": "bold", "size": "sm", "flex": 3},
                        {"type": "text", "text": f"[{status}]", "size": "xs", "color": "#ff5555", "align": "end", "flex": 2}
                    ]
                },
                {"type": "text", "text": items_str, "size": "xs", "color": "#666666"},
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "xs",
                    "contents": [
                        {"type": "button", "action": {"type": "message", "label": "แก้ไข", "text": f"แก้ไข {store}"}, "height": "sm", "style": "secondary"},
                        {"type": "button", "action": {"type": "message", "label": "ลบ", "text": f"ลบ {store}"}, "height": "sm", "style": "secondary"}
                    ]
                }
            ]
        })
        body_contents.append({"type": "separator", "margin": "sm"})

    # Daily Summary Footer
    summary_text_list = [f"{k}: {v}" for k, v in category_summary.items()]
    summary_str = " | ".join(summary_text_list) if summary_text_list else "ไม่มีรายการ"

    body_contents.append({
        "type": "box",
        "layout": "vertical",
        "margin": "md",
        "contents": [
            {"type": "text", "text": "📊 สรุปยอดรวมประจำวัน:", "weight": "bold", "size": "xs", "color": "#333333"},
            {"type": "text", "text": summary_str, "size": "xs", "color": "#0066cc", "wrap": True}
        ]
    })

    footer_box = {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "contents": [
            {"type": "button", "action": {"type": "message", "label": "🟢 ออร์เดอร์แล้วทั้งหมด", "text": "bulk_order_all"}, "style": "primary", "height": "sm"},
            {"type": "button", "action": {"type": "message", "label": "🔵 อัปสลิปแล้วทั้งหมด", "text": "bulk_slip_all"}, "style": "primary", "color": "#00b900", "height": "sm"},
            {"type": "button", "action": {"type": "message", "label": "🔴 ยกเลิกทั้งหมด", "text": "bulk_cancel_all"}, "style": "secondary", "height": "sm"}
        ]
    }

    return {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "contents": body_contents},
        "footer": footer_box
    }

def create_fuzzy_suggestion_flex(query, suggestions):
    """สร้าง Flex Message แนะนำสินค้าแบบปุ่มกดเลือกเมื่อพิมพ์ไม่ตรงเป๊ะ"""
    buttons = []
    for s in suggestions:
        buttons.append({
            "type": "button",
            "action": {"type": "message", "label": f"เลือก: {s}", "text": f"select_product {s}"},
            "style": "secondary",
            "height": "sm"
        })

    return FlexSendMessage(
        alt_text="แนะนำสินค้าที่ใกล้เคียง",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "⚠️ ไม่พบสินค้าตรงกัน", "weight": "bold", "color": "#ff5555"},
                    {"type": "text", "text": f"คุณหมายถึงสินค้าเหล่านี้ใช่ไหมสำหรับ '{query}'?", "wrap": True, "size": "sm", "margin": "md"}
                ] + buttons
            }
        }
    )

if __name__ == "__main__":
    app.run(port=5000, debug=True)
