import os
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)
from supabase import create_client, Client

app = Flask(__name__)

# --- LINE API CONFIGURATION ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- SUPABASE CONFIGURATION ---
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'YOUR_SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'YOUR_SUPABASE_KEY')

supabase: Client = None
try:
    if SUPABASE_URL != 'YOUR_SUPABASE_URL' and SUPABASE_KEY != 'YOUR_SUPABASE_KEY':
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    app.logger.error(f"Supabase connection error: {e}")

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
    query_lower = query.lower()
    for p in ALL_PRODUCTS:
        if p.lower() == query_lower:
            return p, "exact"
    matches = [p for p in ALL_PRODUCTS if query_lower in p.lower() or p.lower() in query_lower]
    if matches:
        return matches[:3], "suggestion"
    return None, "none"

@app.route("/", methods=['GET'])
def index():
    return "Line Bot Server is running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Please check your channel secret.")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error handling webhook: {e}")
        abort(500)
        
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    app.logger.info(f"Received message: {text}")

    # 1. Handle Summary Command (พิมพ์ "สรุป")
    if text.lower().startswith("สรุป") or text.lower().startswith("summary"):
        handle_summary_command(event, text)
        return

    # 2. Handle Action Commands (กดปุ่ม Call to Action ใน Flex Message)
    if text.startswith("set_status_") or text.startswith("bulk_") or text.startswith("แก้ไข") or text.startswith("ลบ") or text.startswith("select_product"):
        handle_action_command(event, text)
        return

    # 3. Handle Order Input (พิมพ์สั่งออร์เดอร์ปกติ -> บันทึกลง Supabase แล้วส่ง Flex สรุปกลับทันที)
    lines = text.split("\n")
    success_count = 0
    error_messages = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split(" ", 1)
        if len(parts) >= 2:
            date_raw = parts[0]
            order_details = parts[1].strip()
            
            try:
                order_date = parse_smart_date(date_raw)
            except ValueError:
                error_messages.append(f"❌ รูปแบบวันที่ไม่ถูกต้อง: '{date_raw}'")
                continue
            
            store_name = order_details.split(" ")[0] if order_details else "ร้านค้า"
            
            # บันทึกลง Supabase Table 'orders'
            if supabase:
                try:
                    res = supabase.table("orders").insert({
                        "store": store_name,
                        "order_date": order_date.strftime('%Y-%m-%d'),
                        "items_desc": order_details,
                        "status": "Pending"
                    }).execute()
                    app.logger.info(f"Supabase Insert Success: {res}")
                except Exception as e:
                    app.logger.error(f"Supabase Insert Error: {e}")
            
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
    """ดึงข้อมูลจาก Supabase มาสร้าง Flex Message สรุปผล"""
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

    orders_list = []
    if supabase:
        try:
            query = supabase.table("orders").select("*")
            if target_status:
                query = query.eq("status", target_status)
            response = query.execute()
            orders_list = response.data
        except Exception as e:
            app.logger.error(f"Supabase Fetch Error: {e}")

    chunk_size = 5
    bubbles = []
    date_header_str = get_thai_date_str(target_date if target_date else datetime.now())
    
    total_items_count = len(orders_list)
    total_pages = (total_items_count + chunk_size - 1) // chunk_size
    if total_pages == 0: total_pages = 1

    category_summary = {}
    for ord_item in orders_list:
        desc = ord_item.get("items_desc", "")
        category_summary[desc] = category_summary.get(desc, 0) + 1

    for page_idx in range(total_pages):
        start_idx = page_idx * chunk_size
        end_idx = start_idx + chunk_size
        page_orders = orders_list[start_idx:end_idx]
        is_last_page = (page_idx == total_pages - 1)

        bubble = create_order_flex_bubble(date_header_str, page_orders, page_idx + 1, total_pages, category_summary if is_last_page else None)
        bubbles.append(bubble)

    flex_message = FlexSendMessage(
        alt_text="สรุปออร์เดอร์ประจำวัน",
        contents={"type": "carousel", "contents": bubbles}
    )
    line_bot_api.reply_message(event.reply_token, flex_message)

def handle_action_command(event, text):
    """จัดการปุ่มกด Call to Action บน Supabase"""
    if supabase:
        try:
            if text.startswith("set_status_"):
                parts = text.split("_")
                status_key = parts[2]
                store_name = parts[3] if len(parts) > 3 else ""
                
                if status_key == "อัพสลิปแล้ว":
                    supabase.table("orders").delete().eq("store", store_name).execute()
                else:
                    supabase.table("orders").update({"status": status_key}).eq("store", store_name).execute()
                    
            elif text.startswith("ลบ"):
                store_name = text.replace("ลบ", "").strip()
                supabase.table("orders").delete().eq("store", store_name).execute()
        except Exception as e:
            app.logger.error(f"Supabase Action Error: {e}")

    handle_summary_command(event, "สรุป")

def create_order_flex_bubble(date_title, orders, current_page, total_pages, daily_summary=None):
    """สร้าง Flex Carousel Bubble พร้อมปุ่มเปลี่ยนสเตตัส 5 แบบ"""
    body_contents = [
        {"type": "text", "text": date_title, "weight": "bold", "size": "md", "color": "#1DB446"},
        {"type": "text", "text": f"หน้า {current_page}/{total_pages}", "size": "xs", "color": "#aaaaaa", "margin": "sm"},
        {"type": "separator", "margin": "md"}
    ]

    for idx, ord_item in enumerate(orders):
        store = ord_item.get("store", "ร้านค้า")
        status = ord_item.get("status", "Pending")
        items_str = ord_item.get("items_desc", "-")
        current_status_conf = STATUS_CONFIG.get(status, {"label": status, "color": "#666666"})

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

    if daily_summary:
        summary_text_list = [f"{k}" for k, v in daily_summary.items()]
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
