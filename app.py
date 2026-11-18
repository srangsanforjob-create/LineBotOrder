import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, FlexSendMessage,
    CarouselContainer, BubbleContainer, BoxComponent, TextComponent,
    ButtonComponent, SeparatorComponent, MessageAction
)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 📌 Master Product Mapping ครบถ้วนทุกหมวดหมู่
PRODUCT_MAP = {
    # Draft Beer (เบียร์สด)
    "L": "GTD LAGER 20L",
    "R": "GTD ROSE 20L",
    "D": "GTD DUNKEL",
    
    # Amenity (อุปกรณ์เสริม / CO2)
    "M": "แก้ว (Mug)", "MUG": "แก้ว (Mug)", "แก้ว": "แก้ว (Mug)",
    "J": "เหยือก (Jug)", "JUG": "เหยือก (Jug)", "เหยือก": "เหยือก (Jug)",
    "T": "ทาวเวอร์ (Tower)", "TOWER": "ทาวเวอร์ (Tower)", "ทาวเวอร์": "ทาวเวอร์ (Tower)",
    "CO2": "CO2",
    
    # Install (อุปกรณ์ติดตั้ง)
    "H40L": "Hoshizaki 40L", "HOSHIZAKI 40": "Hoshizaki 40L",
    "H90": "Hoshizaki 90L", "HOSHIZAKI 90": "Hoshizaki 90L",
    "H120": "Hoshizaki 120L", "HOSHIZAKI 120": "Hoshizaki 120L",
    "CELLI": "Celli",
    "SCT": "Standless Counter", "COUNTER": "Standless Counter",
    "TABLE": "Standless Table",
    
    # POSM (สื่อส่งเสริมการขาย)
    "AST": "A-Stand", "A-STAND": "A-Stand", "ASTAND": "A-Stand",
    "LEDA2V": "LED Signage A2 แนวตั้ง", "A2 แนวตั้ง": "LED Signage A2 แนวตั้ง",
    "LEDA2L": "LED Signage A2 แนวนอน", "A2 แนวนอน": "LED Signage A2 แนวนอน",
    "LEDA3V": "LED Signage A3 แนวตั้ง", "A3 แนวตั้ง": "LED Signage A3 แนวตั้ง",
    "LEDA3L": "LED Signage A3 แนวนอน", "A3 แนวนอน": "LED Signage A3 แนวนอน",
    "LEDA4V": "LED Signage A4 แนวตั้ง", "A4 แนวตั้ง": "LED Signage A4 แนวตั้ง",
    "LEDA4L": "LED Signage A4 แนวนอน", "A4 แนวนอน": "LED Signage A4 แนวนอน",
    "ACLA5": "อะคริลิกตั้งโต๊ะ A5", "A5": "อะคริลิกตั้งโต๊ะ A5",
    "ACLA6": "อะคริลิกตั้งโต๊ะ A6", "A6": "อะคริลิกตั้งโต๊ะ A6",
    "MHD": "ตัวหนีบเมนู / Menu Holder", "MENU HOLDER": "ตัวหนีบเมนู / Menu Holder",
    
    # OtherALC (เครื่องดื่ม ALC อื่นๆ)
    "GALF": "Galaxy แบน 350ml",
    "GALR": "Galaxy กลม 700ml",
    "TEND3": "Tendo 360ml",
    "TEND7": "Tendo 700ml",
    "KACH": "Kacha 375ml",
    "SOJY": "Soju โยเกิร์ต",
    "SOJP": "Soju พีช",
    "SOJG": "Soju องุ่น",
    "SOJF": "Soju เกรปฟรุ๊ต",
    "SOJS": "Soju สตรอเบอรี่",
    
    # Bottle/Cans Beer
    "LB": "CARABAO LAGER bottle 620ml",
    "DB": "CARABAO DUNKEL bottle 620ml",
    "LC": "CARABAO LAGER can 490ml",
    "DC": "CARABAO DUNKEL can 490ml",
    "WC": "TAWANDANG WEIZEN can 490ml",
    "RC": "TAWANDANG ROSE can 490ml",
    "IPAC": "TAWANDANG IPA can 490ml",
    "PTYB": "PATTAYA 320ml / PHUKET 320ml",
    "PTYC": "PATTAYA 490ml / PHUKET 490ml"
}

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
    
    # 1. จัดการเปลี่ยนสถานะ
    if text.startswith("setStatus "):
        parts = text.split(" ", 2)
        if len(parts) == 3:
            item_id = parts[1]
            new_status = parts[2]
            line_bot_api.reply_message(
                event.reply_token,
                TextMessage(text=f"✅ อัปเดตสถานะเป็น '{new_status}' เรียบร้อยแล้วครับ")
            )
            return

    # 2. จัดการรับออเดอร์ (เช่น 19 สะออน L R CO2 H40L)
    parts = text.split()
    if len(parts) >= 3:
        order_date = parts[0]
        shop_name = parts[1]
        skus = parts[2:]
        
        items_data = []
        for sku in skus:
            sku_upper = sku.upper()
            full_name = PRODUCT_MAP.get(sku_upper, f"สินค้า {sku_upper}")
            items_data.append({
                "sku": sku_upper,
                "name": full_name,
                "qty": 1,
                "status": "pending"
            })
        
        flex_message = create_order_carousel_flex(shop_name, order_date, items_data)
        line_bot_api.reply_message(event.reply_token, flex_message)
        return

def create_order_carousel_flex(shop_name, order_date, items):
    bubbles = []
    total_items = len(items)
    chunk_size = 4
    item_chunks = [items[i:i + chunk_size] for i in range(0, total_items, chunk_size)]
    
    for chunk_idx, chunk in enumerate(item_chunks):
        is_last_page = (chunk_idx == len(item_chunks) - 1)
        contents = []
        
        # 📅 ส่วนหัว (วันที่เด่นชัดที่สุด ไม่มีหัวข้อข้อความรก)
        date_display = f"📅 วันที่ {order_date}" if chunk_idx == 0 else f"📅 วันที่ {order_date} (ต่อ)"
        contents.append(
            BoxComponent(
                layout='vertical',
                spacing='sm',
                contents=[
                    TextComponent(text=date_display, weight='bold', size='xl', color='#000000')
                ]
            )
        )
        contents.append(SeparatorComponent(margin='md'))
        
        # รายการสินค้า
        for idx, item in enumerate(chunk):
            absolute_idx = (chunk_idx * chunk_size) + idx
            contents.append(
                BoxComponent(
                    layout='vertical',
                    margin='md',
                    spacing='sm',
                    contents=[
                        TextComponent(text=f"🛒 {shop_name} | {item['sku']} ({item['name']})", weight='bold', size='sm', color='#333333'),
                        TextComponent(text=f"จำนวน: {item['qty']} ชิ้น | สถานะ: {item['status']}", size='xs', color='#666666')
                    ]
                )
            )
            
            # 🎛️ ปุ่ม 6 สเตตัส (2 แถว แถวละ 3 ปุ่ม)
            status_row_1 = BoxComponent(
                layout='horizontal',
                spacing='xs',
                margin='sm',
                contents=[
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='pending', text=f"setStatus {absolute_idx} pending")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='ordered', text=f"setStatus {absolute_idx} ordered")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='uploaded', text=f"setStatus {absolute_idx} uploaded"))
                ]
            )
            status_row_2 = BoxComponent(
                layout='horizontal',
                spacing='xs',
                margin='sm',
                contents=[
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='credit', text=f"setStatus {absolute_idx} credit")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='overdue', text=f"setStatus {absolute_idx} overdue")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='วงเงินไม่พอ', text=f"setStatus {absolute_idx} วงเงินไม่พอ"))
                ]
            )
            contents.append(status_row_1)
            contents.append(status_row_2)
            contents.append(SeparatorComponent(margin='md'))

        # 📦 ส่วนสรุปด้านล่าง (เฉพาะหน้าสุดท้าย)
        if is_last_page:
            summary_contents = [
                TextComponent(text=f"📦 รวมจำนวนสินค้าทั้งหมด: {total_items} ชิ้น", weight='bold', size='sm', color='#000000')
            ]
            for item in items:
                percentage = (1 / total_items) * 100
                summary_contents.append(
                    TextComponent(text=f"  • {item['sku']} : 1 ชิ้น ({percentage:.1f}%)", size='xs', color='#555555')
                )
            contents.append(BoxComponent(layout='vertical', margin='md', spacing='xs', contents=summary_contents))
            contents.append(SeparatorComponent(margin='md'))
            
            action_buttons = BoxComponent(
                layout='horizontal',
                spacing='sm',
                contents=[
                    ButtonComponent(style='primary', color='#1DB446', height='sm', action=MessageAction(label='Orderทั้งหมด', text="Orderทั้งหมด")),
                    ButtonComponent(style='primary', color='#FF5555', height='sm', action=MessageAction(label='ลบทั้งหมด', text="ลบทั้งหมด"))
                ]
            )
            contents.append(action_buttons)

        bubbles.append(BubbleContainer(body=BoxComponent(layout='vertical', contents=contents)))

    if len(bubbles) > 1:
        return FlexSendMessage(alt_text='สรุปยอด Order ประจำวัน', contents=CarouselContainer(contents=bubbles))
    else:
        return FlexSendMessage(alt_text='สรุปยอด Order ประจำวัน', contents=bubbles[0])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
