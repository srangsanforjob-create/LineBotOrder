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
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- GOOGLE SHEETS SETUP ---
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    sheet = client.open("Beer_Order_DB").sheet1
except Exception as e:
    sheet = None  # ทำงานแบบ Offline หรือยังไม่ต่อ Sheet ได้

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

# --- 5 STATUS DEFINITIONS & COLORS ---
STATUS_CONFIG = {
    "Pending": {"label": "⏳ Pending", "color": "#aaaaaa"},
    "Order แล้ว": {"label": "🟢 Order แล้ว", "color": "#00b900"},
    "อัพสลิปแล้ว": {"label": "🔵 อัพสลิปแล้ว", "color": "#0066cc"},
    "เครดิต": {"label": "🟠 เครดิต", "color": "#ff9900"},
    "Limit": {"label": "🟣 Limit (วงเงินเต็ม)", "color": "#9933ff"}
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
    """Smart Date: ระบุแค่วันที่ (เช่น '19') ปัดเป็นเดือน/ปีปัจจุบันให้อัตโนมัติ"""
    now = datetime.now()
    if "/" in date_str:
        parts = date_str.split("/")
        d = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 and parts[1] else now.month
        y = int(parts[2]) if len(parts) > 2 and parts[2] else now.year
        return datetime(y, m, d)
    else:
        d = int(date_str)
        return datetime(now.year, now.month, d)

def fuzzy_match_product(query):
    """ระบบคาดเดาและแนะนำสินค้าเมื่อพิมพ์ไม่ตรงเป๊ะ"""
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

    # 1. Handle Summary Command (รองรับคำว่า สรุป / summary พร้อมตัวกรองสถานะ เช่น "สรุป Pending")
    if text.lower().startswith("สรุป") or text.lower().startswith("summary"):
        handle_summary_command(event, text)
        return

    # 2. Handle Action Commands (ทุก Call Action อัปเดตแล้วส่ง Flex สรุปกลับมา)
    if text.startswith("set_status_") or text.startswith("bulk_") or text.startswith("แก้ไข") or text.startswith("ลบ") or text.startswith("select_product"):
        handle_action_command(event, text)
        return

    # 3. Handle Order Input (รองรับ Multi-line Batch Input สั่งหลายบรรทัดพร้อมกัน)
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
            
            if sheet:
                try:
                    sheet.append_row([order_date.strftime('%Y-%m-%d'), remaining, "Pending"])
                except Exception:
                    pass
            success_count += 1
        else:
            error_messages.append(f"❌ รูปแบบไม่ถูกต้อง: '{line}'")

    if success_count > 0:
        handle_summary_command(event, "สรุป")
    else:
        matched, match_type = fuzzy_match_product(text)
        if match_type == "suggestion":
            line_bot_api.reply_message(event.reply_token, create_fuzzy_suggestion_flex(text, matched))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🤖 สวัสดีครับ พิมพ์ออร์เดอร์ในรูปแบบ [วันที่] [ชื่อร้าน] [รายการสินค้า] หรือพิมพ์ 'สรุป' เพื่อดูรายการ"))

def handle_summary_command(event, text):
    """จัดการคำสั่งสรุป พร้อมรองรับการกรองตามสถานะ (เช่น สรุป Limit, สรุป Pending)"""
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
            for k in STATUS_CONFIG.keys():
                if k.lower() in t.lower() or t.lower() in k.lower():
                    target_status = k

    # Mock Data ทดสอบระบบ (5 สเตตัส)
    mock_orders = [
        {"store": "ร้านส้มตำลำซิ่ง", "items": [{"name": "L", "qty": 2}, {"name": "M", "qty": 10}], "status": "Pending"},
        {"store": "ร้านนั่งชิล", "items": [{"name": "H40L", "qty": 1}, {"name": "SCT", "qty": 2}], "status": "Order แล้ว"},
        {"store": "ร้านตะวันแดง", "items": [{"name": "L", "qty": 3}, {"name": "supL", "qty": 1}], "status": "อัพสลิปแล้ว"},
        {"store": "ร้านริมคลอง", "items": [{"name": "CO2", "qty": 1}], "status": "เครดิต"},
        {"store": "ร้านเพลินจิต", "items": [{"name": "M", "qty": 5}], "status": "Limit"},
        {"store": "ร้านบ้านสวน", "items": [{"name": "L", "qty": 1}], "status": "Pending"}
    ]

    if target_status:
        mock_orders = [o for o in mock_orders if o["status"].lower() == target_status.lower()]

    chunk_size = 5
    bubbles = []
    date_header_str = get_thai_date_str(target_date if target_date else datetime.now())
    
    total_items_count = len(mock_orders)
    total_pages = (total_items_count + chunk_size - 1) // chunk_size
    if total_pages == 0: total_pages = 1

    category_summary = {}
    for ord_item in mock_orders:
        for itm in ord_item["items"]:
            category_summary[itm["name"]] = category_summary.get(itm["name"], 0) + itm["qty"]

    for page_idx in range(total_pages):
        start_idx = page_idx * chunk_size
        end_idx = start_idx + chunk_size
        page_orders = mock_orders[start_idx:end_idx]
        is_last_page = (page_idx == total_pages - 1)

        bubble = create_order_flex_bubble(date_header_str, page_orders, page_idx + 1, total_pages, category_summary if is_last_page else None)
        bubbles.append(bubble)

    flex_message = FlexSendMessage(
        alt_text="สรุปออร์เดอร์ประจำวัน",
        contents={"type": "carousel", "contents": bubbles}
    )
    line_bot_api.reply_message(event.reply_token, flex_message)

def handle_action_command(event, text):
    """ทุกปุ่ม Call to Action ทำงานแล้วส่ง Flex สรุปกลับมาเสมอ"""
    if text.startswith("set_status_"):
        parts = text.split("_")
        status_key = parts[2]
        store_name = parts[3] if len(parts) > 3 else "ร้าน"
    elif text.startswith("bulk_"):
        pass
    elif text.startswith("แก้ไข") or text.startswith("ลบ") or text.startswith("select_product"):
        pass

    handle_summary_command(event, "สรุป")

def create_order_flex_bubble(date_title, orders, current_page, total_pages, daily_summary=None):
    """สร้าง Bubble สำหรับ Flex Message พร้อมปุ่มเปลี่ยนสถานะครบทั้ง 5 แบบ"""
    body_contents = [
        {"type": "text", "text": date_title, "weight": "bold", "size": "md", "color": "#1DB446"},
        {"type": "text", "text": f"หน้า {current_page}/{total_pages}", "size": "xs", "color": "#aaaaaa", "margin": "sm"},
        {"type": "separator", "margin": "md"}
    ]

    for idx, ord_item in enumerate(orders):
        store = ord_item["store"]
        status = ord_item["status"]
        items_str = ", ".join([f"{i['name']} x{i['qty']}" for i in ord_item["items"]])
        current_status_conf = STATUS_CONFIG.get(status, {"label": status, "color": "#666666"})

        # จัดแบ่งปุ่มเปลี่ยนสเตตัส 5 สถานะ เป็น 2 แถวใน Flex Message
        status_buttons_row1 = []
        status_buttons_row2 = []
        
        for i, (s_key, s_val) in enumerate(STATUS_CONFIG.items()):
            btn = {
                "type": "button",
                "action": {"type": "message", "label": s_key, "text": f"set_status_{s_key}_{store}"},
                "height": "sm",
                "style": "secondary",
                "color": s_val["color"]
            }
            if i < 3:
                status_buttons_row1.append(btn)
            else:
                status_buttons_row2.append(btn)

        card_contents = [
            {
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": f"{store}", "weight": "bold", "size": "sm", "flex": 3},
                    {"type": "text", "text": current_status_conf["label"], "size": "xs", "color": current_status_conf["color"], "align": "end", "flex": 2}
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
            },
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "xs",
                "spacing": "xs",
                "contents": status_buttons_row1
            }
        ]
        
        if status_buttons_row2:
            card_contents.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "xs",
                "spacing": "xs",
                "contents": status_buttons_row2
            })

        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "spacing": "xs",
            "contents": card_contents
        })
        body_contents.append({"type": "separator", "margin": "sm"})

    # ยอดสรุปประจำวัน แสดงเฉพาะหน้าสุดท้ายเท่านั้น
    if daily_summary:
        summary_text_list = [f"{k}: {v}" for k, v in daily_summary.items()]
        summary_str = " | ".join(summary_text_list) if summary_text_list else "ไม่มีรายการ"

        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "contents": [
                {"type": "text", "text": "📊 สรุปยอดรวมประจำวัน (หน้าสุดท้าย):", "weight": "bold", "size": "xs", "color": "#333333"},
                {"type": "text", "text": summary_str, "size": "xs", "color": "#0066cc", "wrap": True}
            ]
        })

    footer_box = {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "contents": [
            {"type": "button", "action": {"type": "message", "label": "🟢 Order แล้วทั้งหมด", "text": "bulk_order_all"}, "style": "primary", "color": "#00b900", "height": "sm"},
            {"type": "button", "action": {"type": "message", "label": "🔵 อัพสลิปแล้วทั้งหมด", "text": "bulk_slip_all"}, "style": "primary", "color": "#0066cc", "height": "sm"},
            {"type": "button", "action": {"type": "message", "label": "🔴 ยกเลิกทั้งหมด", "text": "bulk_cancel_all"}, "style": "secondary", "height": "sm"}
        ]
    }

    return {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "contents": body_contents},
        "footer": footer_box
    }

def create_fuzzy_suggestion_flex(query, suggestions):
    """สร้าง Flex Message แนะนำสินค้าเมื่อพิมพ์ไม่ตรง"""
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
