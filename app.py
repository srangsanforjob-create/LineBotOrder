import os
import re
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, FlexSendMessage, BubbleContainer,
    CarouselContainer, BoxComponent, TextComponent,
    ButtonComponent, URIAction, PostbackAction
)
from supabase import create_client, Client
from fuzzywuzzy import process

app = Flask(__name__)

# --- CONFIG & CREDENTIALS ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_LINE_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_LINE_SECRET')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'YOUR_SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', 'YOUR_SUPABASE_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- PRODUCT CATALOG ---
PRODUCT_CATALOG = {
    # Draft Beer
    "L": {"name": "GTD LAGER 20L", "category": "Draft Beer"},
    "R": {"name": "GTD ROSE 20L", "category": "Draft Beer"},
    "D": {"name": "GTD DUNKEL", "category": "Draft Beer"},
    # Amenity
    "M": {"name": "แก้ว (Mug)", "category": "Amenity"},
    "J": {"name": "เหยือก (Jug)", "category": "Amenity"},
    "T": {"name": "ทาวเวอร์ (Tower)", "category": "Amenity"},
    "CO2": {"name": "CO2", "category": "Amenity"},
    # Install
    "H40L": {"name": "Hoshizaki 40L", "category": "Install"},
    "H90": {"name": "Hoshizaki 90L", "category": "Install"},
    "H120": {"name": "Hoshizaki 120L", "category": "Install"},
    "CELLI": {"name": "Celli", "category": "Install"},
    "SCT": {"name": "Standless Counter", "category": "Install"},
    "TABLE": {"name": "Standless Table", "category": "Install"},
    # POSM
    "AST": {"name": "A-Stand", "category": "POSM"},
    "LEDA2V": {"name": "LED Signage A2 แนวตั้ง", "category": "POSM"},
    "LEDA2L": {"name": "LED Signage A2 แนวนอน", "category": "POSM"},
    "LEDA3V": {"name": "LED Signage A3 แนวตั้ง", "category": "POSM"},
    "LEDA3L": {"name": "LED Signage A3 แนวนอน", "category": "POSM"},
    "LEDA4V": {"name": "LED Signage A4 แนวตั้ง", "category": "POSM"},
    "LEDA4L": {"name": "LED Signage A4 แนวนอน", "category": "POSM"},
    "ACLA5": {"name": "อะคริลิกตั้งโต๊ะ A5", "category": "POSM"},
    "ACLA6": {"name": "อะคริลิกตั้งโต๊ะ A6", "category": "POSM"},
    "MHD": {"name": "ตัวหนีบเมนู / Menu Holder", "category": "POSM"},
    # OtherALC
    "GALF": {"name": "Galaxy แบน 350ml", "category": "OtherALC"},
    "GALR": {"name": "Galaxy กลม 700ml", "category": "OtherALC"},
    "TEND3": {"name": "Tendo 360ml", "category": "OtherALC"},
    "TEND7": {"name": "Tendo 700ml", "category": "OtherALC"},
    "KACH": {"name": "Kacha 375ml", "category": "OtherALC"},
    "SOJY": {"name": "Soju โยเกิร์ต", "category": "OtherALC"},
    "SOJP": {"name": "Soju พีช", "category": "OtherALC"},
    "SOJG": {"name": "Soju องุ่น", "category": "OtherALC"},
    "SOJF": {"name": "Soju เกรปฟรุ๊ต", "category": "OtherALC"},
    "SOJS": {"name": "Soju สตรอเบอรี่", "category": "OtherALC"},
    # Bottle/Cans Beer
    "LB": {"name": "CARABAO LAGER bottle 620ml", "category": "Bottle/Cans Beer"},
    "DB": {"name": "CARABAO DUNKEL bottle 620ml", "category": "Bottle/Cans Beer"},
    "LC": {"name": "CARABAO LAGER can 490ml", "category": "Bottle/Cans Beer"},
    "DC": {"name": "CARABAO DUNKEL can 490ml", "category": "Bottle/Cans Beer"},
    "WC": {"name": "TAWANDANG WEIZEN can 490ml", "category": "Bottle/Cans Beer"},
    "RC": {"name": "TAWANDANG ROSE can 490ml", "category": "Bottle/Cans Beer"},
    "IPAC": {"name": "TAWANDANG IPA can 490ml", "category": "Bottle/Cans Beer"},
    "PTYB": {"name": "PATTAYA 320ml / PHUKET 320ml", "category": "Bottle/Cans Beer"},
    "PTYC": {"name": "PATTAYA 490ml / PHUKET 490ml", "category": "Bottle/Cans Beer"}
}

VALID_STATUSES = ["pending", "Order แล้ว", "อัพสลิปแล้ว", "credit", "overdue", "วงเงินเต็ม"]

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- MESSAGE HANDLER ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    reply_token = event.reply_token

    if text == "คู่มือ":
        send_manual_flex(reply_token)
    elif text.startswith("สรุป"):
        handle_summary_command(reply_token, text)
    else:
        handle_order_input(reply_token, text)

# --- ORDER PARSING & PROCESSING ---
def handle_order_input(reply_token, text):
    lines = text.split('\n')
    success_count = 0
    target_date_str = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) < 3:
            continue

        # 1. Parse Date
        date_raw = parts[0]
        order_date = parse_date(date_raw)
        if not target_date_str:
            target_date_str = order_date.strftime("%Y-%m-%d")

        # 2. Parse Shop
        shop_name = parts[1]

        # 3. Parse Product & Qty & Status
        remaining = parts[2:]
        is_support = False
        if remaining[0].lower() in ["sup", "support"]:
            is_support = True
            remaining = remaining[1:]

        qty = 1
        status = "pending"
        
        if remaining[-1] in VALID_STATUSES or remaining[-1].lower() in [s.lower() for s in VALID_STATUSES]:
            status = remaining[-1]
            remaining = remaining[:-1]

        if remaining[-1].isdigit():
            qty = int(remaining[-1])
            remaining = remaining[:-1]

        prod_query = " ".join(remaining).upper()

        matched_code = match_product(prod_query)
        if not matched_code:
            send_fuzzy_picker(reply_token, order_date.strftime("%Y-%m-%d"), shop_name, prod_query, qty, status, is_support)
            return

        prod_info = PRODUCT_CATALOG[matched_code]
        final_prod_name = f"support({prod_info['name']})" if is_support else prod_info['name']

        supabase.table("orders").insert({
            "order_date": order_date.strftime("%Y-%m-%d"),
            "shop_name": shop_name,
            "product_code": matched_code,
            "product_name": final_prod_name,
            "category": prod_info['category'],
            "qty": qty,
            "status": status,
            "is_support": is_support
        }).execute()
        success_count += 1

    if success_count > 0 and target_date_str:
        send_daily_summary_carousel(reply_token, target_date_str)

def parse_date(date_str):
    now = datetime.now()
    if "/" in date_str:
        p = date_str.split("/")
        if len(p) == 2:
            day, month = int(p[0]), int(p[1])
            return datetime(now.year, month, day)
        elif len(p) == 3:
            day, month, year = int(p[0]), int(p[1]), int(p[2])
            if year < 2500: year += 43
            return datetime(year - 543, month, day)
    elif date_str.isdigit() and len(date_str) <= 2:
        return datetime(now.year, now.month, int(date_str))
    return now

def match_product(query):
    if query in PRODUCT_CATALOG:
        return query
    choices = {k: v['name'] for k, v in PRODUCT_CATALOG.items()}
    best_match = process.extractOne(query, list(choices.keys()) + list(choices.values()))
    if best_match and best_match[1] > 70:
        val = best_match[0]
        if val in PRODUCT_CATALOG:
            return val
        for k, v in choices.items():
            if v == val:
                return k
    return None

# --- POSTBACK HANDLER (BUTTON CLICKS) ---
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    reply_token = event.reply_token
    params = dict(item.split('=') for item in data.split('&'))
    action = params.get('action')

    if action == 'set_status':
        order_id = params.get('id')
        new_status = params.get('status')
        if new_status == 'อัพสลิปแล้ว':
            supabase.table("orders").delete().eq("id", order_id).execute()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="✅ อัปสลิปแล้ว: ระบบได้ลบ Order นี้ออกให้อัตโนมัติเรียบร้อยครับ"))
        else:
            supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🔄 อัปเดตสถานะเป็น '{new_status}' เรียบร้อยครับ"))

    elif action == 'batch_status':
        date_str = params.get('date')
        batch_action = params.get('type')
        if batch_action == 'order_all':
            supabase.table("orders").update({"status": "Order แล้ว"}).eq("order_date", date_str).execute()
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🚀 เปลี่ยนสถานะทุก Order ของวันที่ {date_str} เป็น 'Order แล้ว' ทั้งหมดแล้ว"))
        elif batch_action == 'slip_all':
            supabase.table("orders").delete().eq("order_date", date_str).execute()
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🗑️ อัปสลิปแล้วทั้งหมด: ลบข้อมูล Order ของวันที่ {date_str} ทั้งหมดเรียบร้อย"))
        elif batch_action == 'delete_all':
            supabase.table("orders").delete().eq("order_date", date_str).execute()
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ ลบข้อมูล Order ของวันที่ {date_str} ทั้งหมดเรียบร้อยแล้ว"))

    elif action == 'cta_manual':
        topic = params.get('topic')
        if topic == 'order':
            msg = "📖 วิธีการ Order:\nพิมพ์รูปแบบ: [วันที่] [ชื่อร้าน] [รหัสสินค้า/ชื่อสินค้า] [จำนวน] [status]\nตัวอย่าง: 18 GUZA L1 order\n- รองรับพิมพ์หลายบรรทัดพร้อมกัน\n- ถ้าใส่ sup นำหน้าจะเป็นสินค้า Support"
        elif topic == 'summary':
            msg = "📖 วิธีการดูสรุป:\n- พิมพ์คำว่า 'สรุป' เพื่อดูยอดของวันนี้\n- พิมพ์ 'สรุป วัน/เดือน/ปี' เพื่อดูย้อนหลัง"
        elif topic == 'catalog':
            msg = "📖 รหัสสินค้าหลัก:\n- Draft Beer: L (GTD LAGER), R (GTD ROSE), D (GTD DUNKEL)\n- Amenity: M (แก้ว), T (ทาวเวอร์)\n(ดูรายการทั้งหมดในคู่มือเต็ม)"
        else:
            msg = "เลือกหัวข้อคู่มือเรียบร้อยครับ"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))

# --- FLEX MESSAGES & UI BUILDERS ---
def send_manual_flex(reply_token):
    bubble = BubbleContainer(
        body=BoxComponent(
            layout='vertical',
            contents=[
                TextComponent(text="📚 คู่มือการใช้งาน LINE Bot", weight='bold', size='lg', color='#1DB446'),
                TextComponent(text="กรุณาเลือกหัวข้อที่ต้องการทราบข้อมูลครับ", size='sm', color='#666666', margin='sm'),
                BoxComponent(
                    layout='vertical', margin='lg', spacing='sm',
                    contents=[
                        ButtonComponent(style='primary', color='#1DB446', action=PostbackAction(label="3.1 วิธีการ Order", data="action=cta_manual&topic=order")),
                        ButtonComponent(style='secondary', action=PostbackAction(label="3.2 วิธีการ ดูสรุป Order", data="action=cta_manual&topic=summary")),
                        ButtonComponent(style='secondary', action=PostbackAction(label="3.3 รายการและรหัสสินค้า", data="action=cta_manual&topic=catalog")),
                    ]
                )
            ]
        )
    )
    line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="คู่มือการใช้งาน", contents=bubble))

def send_daily_summary_carousel(reply_token, date_str):
    res = supabase.table("orders").select("*").eq("order_date", date_str).execute()
    orders = res.data
    if not orders:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"📅 วันที่ {date_str}: ยังไม่มีรายการ Order ในระบบครับ"))
        return

    total_qty = sum(o['qty'] for o in orders)
    bubbles = []
    chunked_orders = [orders[i:i + 5] for i in range(0, len(orders), 5)]
    total_pages = len(chunked_orders)

    for page_idx, page_items in enumerate(chunked_orders):
        is_last_page = (page_idx == total_pages - 1)
        contents = [
            TextComponent(text=f"📊 สรุปยอด Order ประจำวัน", weight='bold', size='md', color='#1DB446'),
            TextComponent(text=f"📅 วันที่: {date_str} (หน้า {page_idx+1}/{total_pages})", size='xs', color='#aaaaaa', margin='sm')
        ]

        for o in page_items:
            pct = round((o['qty'] / total_qty) * 100, 1) if total_qty > 0 else 0
            contents.append(BoxComponent(
                layout='vertical', margin='md', paddingAll='sm', backgroundColor='#f9f9f9', cornerRadius='md',
                contents=[
                    TextComponent(text=f"🏪 {o['shop_name']} | 📦 {o['product_name']}", weight='bold', size='sm'),
                    TextComponent(text=f"จำนวน: {o['qty']} ชิ้น ({pct}%) | สถานะ: {o['status']}", size='xs', color='#555555', margin='xs'),
                    BoxComponent(
                        layout='horizontal', margin='sm', spacing='xs',
                        contents=[
                            ButtonComponent(style='link', height='sm', action=PostbackAction(label="Order", data=f"action=set_status&id={o['id']}&status=Order แล้ว")),
                            ButtonComponent(style='link', height='sm', action=PostbackAction(label="สลิป", data=f"action=set_status&id={o['id']}&status=อัพสลิปแล้ว")),
                            ButtonComponent(style='link', height='sm', action=PostbackAction(label="Overdue", data=f"action=set_status&id={o['id']}&status=overdue")),
                        ]
                    )
                ]
            ))

        if is_last_page:
            contents.append(BoxComponent(
                layout='vertical', margin='lg', paddingTop='md', borderTop='pixel', borderColor='#eeeeee',
                contents=[
                    TextComponent(text=f"📌 รวมจำนวนสินค้าทั้งหมด: {total_qty} ชิ้น (100%)", weight='bold', size='sm', color='#333333'),
                    BoxComponent(
                        layout='horizontal', margin='md', spacing='sm',
                        contents=[
                            ButtonComponent(style='primary', color='#1DB446', height='sm', action=PostbackAction(label="Orderทั้งหมด", data=f"action=batch_status&date={date_str}&type=order_all")),
                            ButtonComponent(style='primary', color='#ff6b6b', height='sm', action=PostbackAction(label="ลบทั้งหมด", data=f"action=batch_status&date={date_str}&type=delete_all")),
                        ]
                    )
                ]
            ))

        bubbles.append(BubbleContainer(body=BoxComponent(layout='vertical', contents=contents)))

    if len(bubbles) > 1:
        carousel = CarouselContainer(contents=bubbles)
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="สรุป Order ประจำวัน", contents=carousel))
    else:
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="สรุป Order ประจำวัน", contents=bubbles[0]))

def handle_summary_command(reply_token, text):
    parts = text.split()
    if len(parts) > 1:
        target_date = parse_date(parts[1]).strftime("%Y-%m-%d")
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")
    send_daily_summary_carousel(reply_token, target_date)

def send_fuzzy_picker(reply_token, date, shop, query, qty, status, is_support):
    line_bot_api.reply_message(reply_token, TextSendMessage(text=f"⚠️ ไม่พบรหัสสินค้า '{query}' กรุณาตรวจสอบรหัสในคู่มือ (พิมพ์ 'คู่มือ')"))

if __name__ == "__main__":
    app.run(port=5000)
