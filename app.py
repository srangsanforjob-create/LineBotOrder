from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, PostbackEvent, 
    TextSendMessage, FlexSendMessage
)

app = Flask(__name__)

# ==========================================
# CONFIGURATIONS (ใส่ Channel Access Token และ Secret ของคุณ)
# ==========================================
line_bot_api = LineBotApi('YOUR_CHANNEL_ACCESS_TOKEN')
handler = WebhookHandler('YOUR_CHANNEL_SECRET')

# ==========================================
# DATA & CATALOG DICTIONARY
# ==========================================
PRODUCT_FULL_NAMES = {
    "L": "GTD LAGER 20L",
    "R": "GTD ROSE 20L",
    "D": "GTD DUNKEL",
    "M": "แก้ว (Mug)",
    "J": "เหยือก (Jug)",
    "T": "ทาวเวอร์ (Tower)",
    "CO2": "CO2",
    "supL": "support GTD LAGER 20L",
    "supแก้ว 0.3L": "support แก้ว 0.3L"
}

PRODUCT_CATEGORIES = {
    "beer": {
        "title": "🍺 เบียร์สด (Draft Beer)",
        "items": [
            {"code": "L", "name": "GTD LAGER 20L"},
            {"code": "R", "name": "GTD ROSE 20L"},
            {"code": "D", "name": "GTD DUNKEL"}
        ]
    },
    "support": {
        "title": "🥤 อุปกรณ์ / Support",
        "items": [
            {"code": "CO2", "name": "CO2"},
            {"code": "supL", "name": "support GTD LAGER 20L"},
            {"code": "supแก้ว 0.3L", "name": "support แก้ว 0.3L"}
        ]
    }
}

STATUSES = [
    {"label": "ยังไม่สั่ง", "value": "ยังไม่ได้ออเดอร์"},
    {"label": "ออร์เดอร์", "value": "ออเดอร์แล้ว"},
    {"label": "ส่งสลิปแล้ว", "value": "อัปสลิปแล้ว"},
    {"label": "Overdue", "value": "Overdue"},
    {"label": "เครดิต", "value": "เครดิต"},
    {"label": "วงเงินไม่พอ", "value": "วงเงินไม่พอ"}
]

def get_full_product_name(code):
    return PRODUCT_FULL_NAMES.get(code, code)

# ==========================================
# UI COMPONENTS (FLEX MESSAGES)
# ==========================================

def create_edit_choice_flex(store_name):
    """ การ์ดเลือกโหมดแก้ไข (ซ้าย: แก้จำนวน | ขวา: แก้ไขสินค้า) """
    return FlexSendMessage(
        alt_text=f"เลือกวิธีแก้ไขออเดอร์ {store_name}",
        contents={
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": f"🛠️ แก้ไขออเดอร์: {store_name}",
                        "weight": "bold",
                        "size": "sm",
                        "color": "#333333"
                    },
                    {"type": "separator", "margin": "sm"},
                    {
                        "type": "box",
                        "layout": "horizontal",  # จัดเรียง ซ้าย - ขวา
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "style": "primary",
                                "height": "sm",
                                "color": "#0066CC",  # ซ้าย: แก้ไขจำนวน
                                "action": {
                                    "type": "postback",
                                    "label": "🔢 แก้ไขจำนวน",
                                    "data": f"action=start_edit_qty&store={store_name}"
                                }
                            },
                            {
                                "type": "button",
                                "style": "primary",
                                "height": "sm",
                                "color": "#D35400",  # ขวา: แก้ไขสินค้า
                                "action": {
                                    "type": "postback",
                                    "label": "📦 แก้ไขสินค้า",
                                    "data": f"action=select_category&store={store_name}"
                                }
                            }
                        ]
                    }
                ]
            }
        }
    )

def create_category_flex(store_name):
    """ เลือกหมวดหมู่สินค้าสำหรับการเปลี่ยนสินค้า """
    buttons = []
    for cat_key, cat_data in PRODUCT_CATEGORIES.items():
        buttons.append({
            "type": "button",
            "style": "secondary",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": cat_data["title"],
                "data": f"action=select_item&store={store_name}&cat={cat_key}"
            }
        })
        
    return FlexSendMessage(
        alt_text="เลือกหมวดหมู่สินค้า",
        contents={
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"📁 เลือกหมวดหมู่ ({store_name})", "weight": "bold", "size": "sm"},
                    {"type": "separator", "margin": "sm"}
                ] + buttons
            }
        }
    )

def create_item_flex(store_name, cat_key):
    """ เลือกสินค้าจริงในหมวดหมู่นั้นๆ """
    cat_data = PRODUCT_CATEGORIES.get(cat_key, {"items": []})
    buttons = []
    for item in cat_data["items"]:
        buttons.append({
            "type": "button",
            "style": "primary",
            "height": "sm",
            "color": "#1DB446",
            "action": {
                "type": "postback",
                "label": item["name"],
                "data": f"action=apply_new_item&store={store_name}&sku={item['code']}"
            }
        })
        
    return FlexSendMessage(
        alt_text="เลือกสินค้า",
        contents={
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"📦 เลือกสินค้าที่จะเปลี่ยน ({store_name})", "weight": "bold", "size": "sm"},
                    {"type": "separator", "margin": "sm"}
                ] + buttons
            }
        }
    )

def create_guide_menu_flex():
    """ เมนูคู่มือหลัก (แสดงปุ่มให้เลือกหัวข้อ) """
    return FlexSendMessage(
        alt_text="📖 ศูนย์ช่วยเหลือ & คู่มือการใช้งาน",
        contents={
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": "📖 ศูนย์ช่วยเหลือ & คู่มือ",
                        "weight": "bold",
                        "size": "sm",
                        "color": "#1DB446"
                    },
                    {"type": "text", "text": "กรุณาเลือกหัวข้อที่ต้องการศึกษาครับ:", "size": "xs", "color": "#777777"},
                    {"type": "separator", "margin": "sm"},
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "📊 1. วิธีดูสรุปยอดออเดอร์",
                            "data": "action=guide&topic=summary"
                        }
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "📝 2. วิธี Input ออเดอร์สินค้า",
                            "data": "action=guide&topic=input"
                        }
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "✏️ 3. วิธีแก้ไขออเดอร์รายร้าน",
                            "data": "action=guide&topic=edit"
                        }
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "height": "sm",
                        "color": "#D35400",
                        "action": {
                            "type": "postback",
                            "label": "🍺 4. ดูแคตตาล็อกสินค้าทั้งหมด",
                            "data": "action=guide&topic=catalog"
                        }
                    }
                ]
            }
        }
    )

# ==========================================
# WEBHOOK & EVENT HANDLERS (FIXED CALLBACK)
# ==========================================

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    
    # ✅ จุดที่แก้ไข: ดึงข้อมูลแบบ Raw Data (as_text=False) แล้ว decode เป็น utf-8 ให้ถูกต้อง
    body = request.get_data(as_text=False).decode('utf-8')
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    text = event.message.text.strip().lower()
    
    # 1. เช็กคำสั่งเรียกดูคู่มือ
    if text in ["คู่มือ", "help", "วิธีใช้", "แคตตาล็อก"]:
        guide_menu = create_guide_menu_flex()
        line_bot_api.reply_message(event.reply_token, guide_menu)
        return
        
    # 2. เช็กกรณีพิมพ์ตัวเลขเดี่ยวๆ (เพื่ออัปเดตจำนวนสินค้าหลังเลือกโหมดแก้จำนวน)
    if event.message.text.strip().isdigit():
        new_qty = int(event.message.text.strip())
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ อัปเดตจำนวนใหม่เป็น {new_qty} เรียบร้อยแล้วครับ!")
        )
        return
        
    # 3. เช็กคำสั่งสรุปยอดเบื้องต้น
    if text.startswith("สรุป"):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📊 [ระบบกำลังจำลอง] แสดงสรุปยอดออเดอร์ทั้งหมดในรูปแบบ Carousel...")
        )

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    params = dict(item.split('=') for item in data.split('&'))
    action = params.get('action')
    store_name = params.get('store')
    
    # --- จัดการเรื่องคู่มือ (Guide Topics) ---
    if action == 'guide':
        topic = params.get('topic')
        if topic == 'summary':
            content = (
                "📊 [1. วิธีดูสรุปยอดออเดอร์]\n\n"
                "• พิมพ์ 'สรุป' : ดูยอดออเดอร์ทั้งหมดของวันนี้\n"
                "• พิมพ์ 'สรุป 16/11/2026' : ดูเฉพาะวันที่กำหนด\n"
                "• พิมพ์ 'สรุป ออเดอร์แล้ว' : กรองดูเฉพาะสถานะ\n"
                "• ปุ่มหัวการ์ด: กด [📦 ออเดอร์ทั้งหมด] หรือ [🟢 ส่งสลิปทั้งหมด] เพื่อเปลี่ยนสถานะยกกลุ่ม"
            )
        elif topic == 'input':
            content = (
                "📝 [2. วิธี Input ออเดอร์สินค้า]\n\n"
                "• รูปแบบ: [ชื่อร้าน] [รหัสสินค้า] [จำนวน]\n"
                "• ตัวอย่าง: สะออน L 2, M 5\n"
                "• ดูรหัสย่อสินค้าได้จากหมวดแคตตาล็อก"
            )
        elif topic == 'edit':
            content = (
                "✏️ [3. วิธีแก้ไขออเดอร์รายร้าน]\n\n"
                "1. กดปุ่ม '✏️ แก้ไขออเดอร์ร้านนี้' ที่การ์ดร้าน\n"
                "2. ฝั่งซ้าย [🔢 แก้ไขจำนวน] ➔ พิมพ์ตัวเลขใหม่ได้เลย\n"
                "3. ฝั่งขวา [📦 แก้ไขสินค้า] ➔ กดเลือกหมวดหมู่และสินค้าผ่านหน้าจอ"
            )
        elif topic == 'catalog':
            content = (
                "🍺 [4. แคตตาล็อกสินค้าทั้งหมด]\n\n"
                "• L : GTD LAGER 20L\n"
                "• R : GTD ROSE 20L\n"
                "• D : GTD DUNKEL\n"
                "• M : แก้ว (Mug)\n"
                "• J : เหยือก (Jug)\n"
                "• T : ทาวเวอร์ (Tower)\n"
                "• CO2 : CO2\n"
                "• supL : support GTD LAGER 20L\n"
                "• supแก้ว 0.3L : support แก้ว 0.3L"
            )
        else:
            content = "❌ ไม่พบหัวข้อคู่มือ"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=content))
        return

    # --- จัดการเรื่องการแก้ไขออเดอร์ (Edit Flow) ---
    if action == 'edit_menu':
        flex_msg = create_edit_choice_flex(store_name)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        
    elif action == 'start_edit_qty':
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"🔢 [โหมดแก้จำนวน: {store_name}]\nกรุณาพิมพ์ตัวเลขจำนวนใหม่ที่ต้องการได้เลยครับ (เช่น 3)")
        )
        
    elif action == 'select_category':
        flex_msg = create_category_flex(store_name)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        
    elif action == 'select_item':
        cat_key = params.get('cat')
        flex_msg = create_item_flex(store_name, cat_key)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        
    elif action == 'apply_new_item':
        sku = params.get('sku')
        full_name = get_full_product_name(sku)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"✅ เปลี่ยนสินค้าของร้าน '{store_name}' เป็น [{full_name}] เรียบร้อยแล้วครับ!")
        )

if __name__ == "__main__":
    app.run(port=5000)
