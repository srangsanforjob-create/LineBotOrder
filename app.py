import os
import re
import math
import difflib
from datetime import datetime, timezone, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, FlexSendMessage,
    CarouselContainer, BubbleContainer, BoxComponent, TextComponent,
    ButtonComponent, SeparatorComponent, MessageAction
)
from supabase import create_client, Client

app = Flask(__name__)

# ตั้งค่า LINE Credentials
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ตั้งค่า Supabase Credentials
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MAX_SHOPS_PER_BUBBLE = 5
MAX_BUBBLES_PER_CAROUSEL = 3
BKK_TZ = timezone(timedelta(hours=7))

# 📌 Master Product Mapping ครบถ้วนพร้อมชื่อเต็ม (รวม Soju ครบ 5 รสชาติ + ที่รองแก้ว)
PRODUCT_MAP = {
    # Draft Beer (หมวด d)
    "L": {"name": "GTD LAGER 20L", "category": "d"},
    "R": {"name": "GTD ROSE 20L", "category": "d"},
    "D": {"name": "GTD DUNKEL", "category": "d"},
    
    # Amenity (หมวด amenity)
    "M": {"name": "แก้ว (Mug)", "category": "amenity"},
    "MUG": {"name": "แก้ว (Mug)", "category": "amenity"},
    "แก้ว": {"name": "แก้ว (Mug)", "category": "amenity"},
    "J": {"name": "เหยือก (Jug)", "category": "amenity"},
    "JUG": {"name": "เหยือก (Jug)", "category": "amenity"},
    "เหยือก": {"name": "เหยือก (Jug)", "category": "amenity"},
    "T": {"name": "ทาวเวอร์ (Tower)", "category": "amenity"},
    "TOWER": {"name": "ทาวเวอร์ (Tower)", "category": "amenity"},
    "ทาวเวอร์": {"name": "ทาวเวอร์ (Tower)", "category": "amenity"},
    "CO2": {"name": "CO2", "category": "amenity"},
    "COASTER": {"name": "ที่รองแก้ว (Coaster)", "category": "amenity"},
    "ที่รองแก้ว": {"name": "ที่รองแก้ว (Coaster)", "category": "amenity"},
    
    # Install (หมวด install)
    "H40L": {"name": "Hoshizaki 40L", "category": "install"},
    "HOSHIZAKI 40": {"name": "Hoshizaki 40L", "category": "install"},
    "H90": {"name": "Hoshizaki 90L", "category": "install"},
    "HOSHIZAKI 90": {"name": "Hoshizaki 90L", "category": "install"},
    "H120": {"name": "Hoshizaki 120L", "category": "install"},
    "HOSHIZAKI 120": {"name": "Hoshizaki 120L", "category": "install"},
    "CELLI": {"name": "Celli", "category": "install"},
    "SCT": {"name": "Standless Counter", "category": "install"},
    "COUNTER": {"name": "Standless Counter", "category": "install"},
    "TABLE": {"name": "Standless Table", "category": "install"},
    
    # POSM (หมวด posm)
    "AST": {"name": "A-Stand", "category": "posm"},
    "A-STAND": {"name": "A-Stand", "category": "posm"},
    "LEDA2V": {"name": "LED Signage A2 แนวตั้ง", "category": "posm"},
    "LEDA2L": {"name": "LED Signage A2 แนวนอน", "category": "posm"},
    "LEDA3V": {"name": "LED Signage A3 แนวตั้ง", "category": "posm"},
    "LEDA3L": {"name": "LED Signage A3 แนวนอน", "category": "posm"},
    "LEDA4V": {"name": "LED Signage A4 แนวตั้ง", "category": "posm"},
    "LEDA4L": {"name": "LED Signage A4 แนวนอน", "category": "posm"},
    "ACLA5": {"name": "อะคริลิกตั้งโต๊ะ A5", "category": "posm"},
    "A5": {"name": "อะคริลิกตั้งโต๊ะ A5", "category": "posm"},
    "ACLA6": {"name": "อะคริลิกตั้งโต๊ะ A6", "category": "posm"},
    "A6": {"name": "อะคริลิกตั้งโต๊ะ A6", "category": "posm"},
    "MHD": {"name": "ตัวหนีบเมนู / Menu Holder", "category": "posm"},
    
    # OtherALC (รวม Soju ครบทั้ง 5 รสชาติ)
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
    "LB": {"name": "CARABAO LAGER bottle 620ml", "category": "Bottle/Cans"},
    "DB": {"name": "CARABAO DUNKEL bottle 620ml", "category": "Bottle/Cans"},
    "LC": {"name": "CARABAO LAGER can 490ml", "category": "Bottle/Cans"},
    "DC": {"name": "CARABAO DUNKEL can 490ml", "category": "Bottle/Cans"},
    "WC": {"name": "TAWANDANG WEIZEN can 490ml", "category": "Bottle/Cans"},
    "RC": {"name": "TAWANDANG ROSE can 490ml", "category": "Bottle/Cans"},
    "IPAC": {"name": "TAWANDANG IPA can 490ml", "category": "Bottle/Cans"},
    "PTYB": {"name": "PATTAYA/PHUKET 320ml", "category": "Bottle/Cans"},
    "PTYC": {"name": "PATTAYA/PHUKET 490ml", "category": "Bottle/Cans"}
}

def get_today_str():
    return datetime.now(BKK_TZ).strftime("%Y-%m-%d")

def get_time_bucket(order_date, today_str=None):
    if today_str is None:
        today_str = get_today_str()
    if order_date < today_str:
        return "past"
    elif order_date == today_str:
        return "present"
    else:
        return "future"

def get_bucket_badge(order_date, today_str=None):
    bucket = get_time_bucket(order_date, today_str)
    if bucket == "past":
        return "⏪ อดีต"
    elif bucket == "present":
        return "📍 ปัจจุบัน"
    else:
        return "⏩ อนาคต"

def sort_dates_past_present_future(date_list, today_str=None):
    if today_str is None:
        today_str = get_today_str()
    past_dates = sorted([d for d in date_list if d < today_str])        # เก่าสุด -> เมื่อวาน
    present_dates = sorted([d for d in date_list if d == today_str])     # วันนี้
    future_dates = sorted([d for d in date_list if d > today_str])      # พรุ่งนี้ -> ไกลสุด
    return past_dates + present_dates + future_dates

def get_status_color(status):
    s = status.lower()
    if "pending" in s:
        return "#ff8c00"
    elif "order" in s:
        return "#1DB446"
    elif "credit" in s:
        return "#3b82f6"
    elif "overdue" in s or "เต็ม" in s:
        return "#FF5555"
    else:
        return "#888888"

def get_source_id(event):
    source = event.source
    if hasattr(source, 'group_id') and source.group_id:
        return source.group_id
    elif hasattr(source, 'room_id') and source.room_id:
        return source.room_id
    elif hasattr(source, 'user_id') and source.user_id:
        return source.user_id
    return "default_chat"

def build_day_bubbles_capped_5_shops(order_date, orders, source_id, today_str=None):
    if today_str is None:
        today_str = get_today_str()

    shops_dict = {}
    for item in orders:
        s_name = item['shop_name']
        if s_name not in shops_dict:
            shops_dict[s_name] = []
        shops_dict[s_name].append(item)

    shops_list = list(shops_dict.items())
    shop_chunks = [shops_list[i:i + MAX_SHOPS_PER_BUBBLE] for i in range(0, len(shops_list), MAX_SHOPS_PER_BUBBLE)]
    if not shop_chunks:
        shop_chunks = [[]]

    bubbles = []
    total_day_chunks = len(shop_chunks)
    for c_idx, chunk in enumerate(shop_chunks):
        is_last_chunk_of_day = (c_idx == total_day_chunks - 1)
        bubbles.append(
            generate_single_day_bubble(
                order_date=order_date,
                orders=orders,
                source_id=source_id,
                shop_chunk=chunk,
                day_part_idx=c_idx + 1,
                day_part_total=total_day_chunks,
                show_day_summary=is_last_chunk_of_day,
                today_str=today_str
            )
        )
    return bubbles

def generate_all_days_summary_flex(source_id, page=1):
    res = supabase.table("orders").select("*").eq("source_id", source_id).execute()
    orders = res.data
    if not orders:
        return None

    today_str = get_today_str()
    dates_dict = {}
    for item in orders:
        d = item['order_date']
        if d not in dates_dict:
            dates_dict[d] = []
        dates_dict[d].append(item)

    ordered_dates = sort_dates_past_present_future(dates_dict.keys(), today_str=today_str)

    all_bubbles = []
    for d in ordered_dates:
        all_bubbles.extend(build_day_bubbles_capped_5_shops(d, dates_dict[d], source_id, today_str=today_str))

    if not all_bubbles:
        return None

    total_pages = max(1, math.ceil(len(all_bubbles) / MAX_BUBBLES_PER_CAROUSEL))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * MAX_BUBBLES_PER_CAROUSEL
    end_idx = start_idx + MAX_BUBBLES_PER_CAROUSEL
    page_bubbles = all_bubbles[start_idx:end_idx]

    if total_pages > 1:
        last_b = page_bubbles[-1]
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                ButtonComponent(
                    style='secondary',
                    height='sm',
                    action=MessageAction(label=f"⬅️ หน้า {page - 1}", text=f"สรุป หน้า {page - 1}")
                )
            )
            if page > 2:
                nav_buttons.append(
                    ButtonComponent(
                        style='secondary',
                        height='sm',
                        action=MessageAction(label="⏮️ กลับหน้าแรกสุด (หน้า 1)", text="สรุป หน้า 1")
                    )
                )
        if page < total_pages:
            nav_buttons.append(
                ButtonComponent(
                    style='primary',
                    height='sm',
                    action=MessageAction(label=f"ดูหน้าถัดไป (หน้า {page + 1}) ➡️", text=f"สรุป หน้า {page + 1}")
                )
            )
            if page + 1 < total_pages:
                nav_buttons.append(
                    ButtonComponent(
                        style='secondary',
                        height='sm',
                        action=MessageAction(label=f"ไปหน้าสุดท้าย (หน้า {total_pages}) ⏭️", text=f"สรุป หน้า {total_pages}")
                    )
                )
        if nav_buttons:
            last_b.body.contents.append(SeparatorComponent(margin='md'))
            last_b.body.contents.append(
                BoxComponent(
                    layout='vertical',
                    spacing='xs',
                    contents=nav_buttons
                )
            )

    alt_text = f"สรุปยอดออเดอร์ (หน้า {page}/{total_pages})"
    if len(page_bubbles) > 1:
        return FlexSendMessage(alt_text=alt_text, contents=CarouselContainer(contents=page_bubbles))
    else:
        return FlexSendMessage(alt_text=alt_text, contents=page_bubbles[0])

# 🟢 เพิ่ม Health Check Route ป้องกัน 404 เวลา Cloud เช็คสถานะเซิร์ฟเวอร์
@app.route("/", methods=['GET', 'HEAD'])
def index():
    return "LINE Bot Server is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    source_id = get_source_id(event)
    
    if text.lower() in ["คู่มือ", "help"]:
        flex_msg = FlexSendMessage(
            alt_text="คู่มือการใช้งาน",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text="📖 คู่มือการใช้งาน LINE Bot", weight='bold', size='lg', color='#1DB446'),
                        SeparatorComponent(margin='md'),
                        ButtonComponent(style='primary', margin='md', action=MessageAction(label='📝 วิธีการ Order', text='คู่มือ order')),
                        ButtonComponent(style='primary', margin='sm', action=MessageAction(label='📊 วิธีดูสรุป Order', text='คู่มือ สรุป')),
                        ButtonComponent(style='primary', margin='sm', action=MessageAction(label='🏷️ รายการสินค้า (1/3)', text='คู่มือ สินค้า 1'))
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return
    elif text.lower() == "คู่มือ order":
        flex_msg = FlexSendMessage(
            alt_text="คู่มือ Order",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text="📝 วิธีการ Order", weight='bold', size='md'),
                        SeparatorComponent(margin='md'),
                        TextComponent(text="• พิมพ์: [วันที่] [ชื่อร้าน] [รหัส+จำนวน...] [สเตตัส]\n• ตัวอย่าง: `18 GUZA L1 R2 D5` (สั่งหลายสินค้าในบรรทัดเดียวได้)\n• หากระบุแค่วัน จะนับเป็นเดือนปัจจุบัน\n• พิมพ์ `sup` นำหน้ารหัสเพื่อทำสินค้า Support", wrap=True, size='sm', color='#555555')
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return
    elif text.lower() == "คู่มือ สรุป":
        flex_msg = FlexSendMessage(
            alt_text="คู่มือสรุป",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text="📊 วิธีการดูสรุป Order", weight='bold', size='md'),
                        SeparatorComponent(margin='md'),
                        TextComponent(text="• พิมพ์ 'สรุป' เพื่อดูยอดเรียงตาม อดีต → ปัจจุบัน → อนาคต\n• พิมพ์ 'สรุป หน้า 2' เพื่อดูหน้าถัดไป\n• พิมพ์ 'สรุป [YYYY-MM-DD]' เพื่อดูยอดเฉพาะวันที่ต้องการ\n• พิมพ์ 'สรุป [status]' เช่น 'สรุป pending' เพื่อกรองตามสเตตัส", wrap=True, size='sm', color='#555555'),
                        ButtonComponent(style='primary', margin='md', action=MessageAction(label='👉 ดูสรุปทั้งหมดเลย', text='สรุป'))
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return
    
    elif text.lower() in ["คู่มือ สินค้า 1", "คู่มือ สินค้า 2", "คู่มือ สินค้า 3"]:
        b1 = BubbleContainer(
            body=BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text="🏷️ คู่มือสินค้า (1/3) - Draft & Amenity", weight='bold', size='sm', color='#1DB446'),
                    SeparatorComponent(margin='md'),
                    TextComponent(text="• Draft Beer (หมวด d):\n  L : GTD LAGER 20L\n  R : GTD ROSE 20L\n  D : GTD DUNKEL\n• Amenity (หมวด amenity):\n  M / Mug / แก้ว : แก้ว (Mug)\n  J / Jug / เหยือก : เหยือก (Jug)\n  T / Tower / ทาวเวอร์ : ทาวเวอร์ (Tower)\n  CO2 : CO2\n  COASTER / ที่รองแก้ว : ที่รองแก้ว (Coaster)", wrap=True, size='xs', color='#333333'),
                    SeparatorComponent(margin='md'),
                    ButtonComponent(style='secondary', action=MessageAction(label='➡️ ถัดไป (Install & POSM)', text='คู่มือ สินค้า 2'))
                ]
            )
        )
        b2 = BubbleContainer(
            body=BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text="🏷️ คู่มือสินค้า (2/3) - Install & POSM", weight='bold', size='sm', color='#1DB446'),
                    SeparatorComponent(margin='md'),
                    TextComponent(text="• Install (อุปกรณ์ติดตั้ง):\n  H40L / Hoshizaki 40 : Hoshizaki 40L\n  H90 / Hoshizaki 90 : Hoshizaki 90L\n  H120 / Hoshizaki 120 : Hoshizaki 120L\n  CELLI : Celli\n  SCT / Counter : Standless Counter\n  TABLE : Standless Table\n• POSM (สื่อส่งเสริมการขาย):\n  AST : A-Stand | LEDA2V / LEDA3V / ACLA5 / MHD", wrap=True, size='xs', color='#333333'),
                    SeparatorComponent(margin='md'),
                    ButtonComponent(style='secondary', action=MessageAction(label='➡️ ถัดไป (OtherALC & Bottle)', text='คู่มือ สินค้า 3'))
                ]
            )
        )
        b3 = BubbleContainer(
            body=BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text="🏷️ คู่มือสินค้า (3/3) - OtherALC & Bottle", weight='bold', size='sm', color='#1DB446'),
                    SeparatorComponent(margin='md'),
                    TextComponent(text="• OtherALC (เครื่องดื่ม/Soju 5 รส):\n  GALF/GALR (Galaxy) | TEND3/TEND7 (Tendo) | KACH (Kacha)\n  SOJY (โยเกิร์ต) | SOJP (พีช) | SOJG (องุ่น) | SOJF (เกรปฟรุ๊ต) | SOJS (สตรอเบอรี่)\n• Bottle/Cans Beer:\n  LB/DB (Bottle) | LC/DC/WC/RC/IPAC/PTYB/PTYC (Cans)", wrap=True, size='xs', color='#333333'),
                    SeparatorComponent(margin='md'),
                    ButtonComponent(style='secondary', action=MessageAction(label='⬅️ กลับหน้า 1', text='คู่มือ สินค้า 1'))
                ]
            )
        )
        carousel = CarouselContainer(contents=[b1, b2, b3])
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="คู่มือรายการสินค้า", contents=carousel))
        return

    if text.startswith("สรุป"):
        parts = text.split()
        if len(parts) > 1:
            page_match = re.match(r'^สรุป(?:[_\s]+หน้า[_\s]*(\d+))$', text, re.IGNORECASE)
            if page_match:
                target_page = int(page_match.group(1))
                flex_msg = generate_all_days_summary_flex(source_id, page=target_page)
                if not flex_msg:
                    line_bot_api.reply_message(event.reply_token, TextMessage(text="📭 ไม่พบข้อมูลออเดอร์ใดๆ ในระบบ"))
                    return
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return

            param = parts[1]
            is_date = re.match(r'^\d{4}-\d{2}-\d{2}$', param)
            
            if is_date:
                target_date = param
                res = supabase.table("orders").select("*").eq("source_id", source_id).eq("order_date", target_date).execute()
                orders = res.data
                if not orders:
                    line_bot_api.reply_message(event.reply_token, TextMessage(text=f"📭 ไม่พบออเดอร์ในวันที่ {target_date}"))
                    return
                flex_msg = generate_summary_carousel(target_date, orders, source_id)
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return
            else:
                status_query = " ".join(parts[1:])
                res = supabase.table("orders").select("*").eq("source_id", source_id).ilike("status", f"%{status_query}%").execute()
                orders = res.data
                if not orders:
                    line_bot_api.reply_message(event.reply_token, TextMessage(text=f"📭 ไม่พบออเดอร์ที่มีสถานะ '{status_query}'"))
                    return
                flex_msg = generate_status_summary_carousel(status_query, orders, source_id)
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return
        else:
            flex_msg = generate_all_days_summary_flex(source_id, page=1)
            if not flex_msg:
                line_bot_api.reply_message(event.reply_token, TextMessage(text="📭 ไม่พบข้อมูลออเดอร์ใดๆ ในระบบ"))
                return
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

    if text.startswith("action_") or text.startswith("edit_") or text.startswith("setqty_") or text.startswith("quickadd_") or text.startswith("editshop_"):
        handle_action_command(event, text, source_id)
        return

    # ── ระบบรับ Order รองรับหลายสินค้า + ผูก source_id ของแชทปัจจุบัน ──
    lines = text.split('\n')
    success_records = []
    current_year_month = datetime.now(BKK_TZ).strftime("%Y-%m")
    
    parsed_orders = []
    errors_list = []

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
            
        parts = line_str.split()
        if len(parts) >= 3:
            raw_date = parts[0]
            shop_name = parts[1]
            
            if len(raw_date) <= 2:
                order_date = f"{current_year_month}-{raw_date.zfill(2)}"
            else:
                order_date = raw_date
                
            remainder_tokens = parts[2:]
            
            line_status = "pending"
            joined_rem = " ".join(remainder_tokens).lower()
            if "อัพสลิปแล้ว" in joined_rem or "อัพสลิป" in joined_rem:
                line_status = "อัพสลิปแล้ว"
                if remainder_tokens and remainder_tokens[-1].lower() in ["แล้ว", "อัพสลิป", "อัพสลิปแล้ว"]:
                    remainder_tokens = remainder_tokens[:-1]
                    if remainder_tokens and remainder_tokens[-1].lower() in ["อัพ", "อัพสลิป"]:
                        remainder_tokens = remainder_tokens[:-1]
            elif "order แล้ว" in joined_rem:
                line_status = "Order แล้ว"
                if len(remainder_tokens) >= 2:
                    remainder_tokens = remainder_tokens[:-2]
            elif remainder_tokens and remainder_tokens[-1].lower() == "order":
                line_status = "Order แล้ว"
                remainder_tokens = remainder_tokens[:-1]
            elif remainder_tokens and remainder_tokens[-1].lower() in ["pending", "credit", "overdue", "วงเงินเต็ม"]:
                stat_token = remainder_tokens[-1].lower()
                if stat_token == "pending": line_status = "pending"
                elif stat_token == "credit": line_status = "credit"
                elif stat_token == "overdue": line_status = "overdue"
                elif stat_token == "วงเงินเต็ม": line_status = "วงเงินเต็ม"
                remainder_tokens = remainder_tokens[:-1]

            i = 0
            while i < len(remainder_tokens):
                token = remainder_tokens[i]
                if token.lower() in ["pending", "order", "credit", "overdue", "วงเงินเต็ม", "อัพสลิปแล้ว", "แล้ว"]:
                    i += 1
                    continue
                
                match_token = re.match(r'^([a-zA-Z0-9\(\)]+?)(\d+)?$', token)
                if match_token:
                    sku_raw = match_token.group(1).upper()
                    if match_token.group(2):
                        qty = int(match_token.group(2))
                    else:
                        if i + 1 < len(remainder_tokens) and remainder_tokens[i+1].isdigit():
                            qty = int(remainder_tokens[i+1])
                            i += 1
                        else:
                            qty = 1
                else:
                    sku_raw = token.upper()
                    qty = 1

                is_support = sku_raw.startswith("SUP")
                clean_sku = sku_raw.replace("SUP", "", 1) if is_support else sku_raw
                
                product_info = PRODUCT_MAP.get(clean_sku)
                if not product_info:
                    errors_list.append({
                        "sku": sku_raw,
                        "order_date": order_date,
                        "shop_name": shop_name,
                        "qty": qty,
                        "status": line_status
                    })
                    i += 1
                    continue
                
                product_name = product_info["name"]
                category = product_info["category"]
                if is_support:
                    product_name = f"support({product_name})"

                parsed_orders.append({
                    "order_date": order_date,
                    "shop_name": shop_name,
                    "product_code": clean_sku,
                    "product_name": product_name,
                    "category": category,
                    "qty": qty,
                    "status": line_status,
                    "is_support": is_support,
                    "source_id": source_id
                })
                i += 1

    for record in parsed_orders:
        res = supabase.table("orders").insert(record).execute()
        if res.data:
            success_records.append(res.data[0])

    if errors_list:
        err = errors_list[0]
        remaining_errors = errors_list[1:]
        
        rem_str = ""
        if remaining_errors:
            rem_parts = []
            for e in remaining_errors:
                rem_parts.append(f"{e['order_date']},{e['shop_name']},{e['sku']},{e['qty']},{e['status']}")
            rem_str = "||".join(rem_parts)

        matches = difflib.get_close_matches(err["sku"], PRODUCT_MAP.keys(), n=3, cutoff=0.4)
        if matches:
            buttons = []
            for m in matches:
                action_text = f"quickadd_{err['order_date']}_{err['shop_name']}_{m}_{err['qty']}_{err['status']}"
                if rem_str:
                    action_text += f"__{rem_str}"
                buttons.append(ButtonComponent(
                    style='primary',
                    margin='sm',
                    action=MessageAction(label=f"{m}: {PRODUCT_MAP[m]['name']}", text=action_text)
                ))
            
            total_err_count = len(errors_list)
            flex_msg = FlexSendMessage(
                alt_text="เลือกสินค้าที่ถูกต้อง",
                contents=BubbleContainer(
                    body=BoxComponent(
                        layout='vertical',
                        contents=[
                            TextComponent(text=f"⚠️ พบรหัสสินค้าไม่ถูกต้อง ({total_err_count} รายการ)", weight='bold', size='sm', color='#FF5555'),
                            TextComponent(text=f"กำลังแก้ไขรหัสผิด: '{err['sku']}'", size='xs', color='#333333', margin='sm', weight='bold'),
                            TextComponent(text="กรุณาเลือกสินค้าที่ใกล้เคียง:", size='xs', color='#666666', margin='xs'),
                            SeparatorComponent(margin='md')
                        ] + buttons
                    )
                )
            )
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"⚠️ บันทึกรายการอื่นแล้ว แต่ไม่พบรหัสสินค้า '{err['sku']}' กรุณาตรวจสอบรหัสในคู่มือ"))
            return

    if success_records:
        flex_msg = generate_all_days_summary_flex(source_id, page=1)
        if flex_msg:
            line_bot_api.reply_message(event.reply_token, flex_msg)
        else:
            line_bot_api.reply_message(event.reply_token, TextMessage(text="✅ บันทึกออเดอร์เรียบร้อยแล้ว"))
    else:
        line_bot_api.reply_message(event.reply_token, TextMessage(text="⚠️ รูปแบบการสั่งซื้อไม่ถูกต้อง กรุณาพิมพ์ 'คู่มือ' เพื่อดูวิธีใช้งาน"))

def handle_action_command(event, text, source_id):
    parts = text.split("_")
    
    if parts[0] == "quickadd":
        order_date = parts[1]
        shop_name = parts[2]
        sku = parts[3]
        qty = int(parts[4])
        
        status_and_rem = parts[5] if len(parts) > 5 else "pending"
        if "__" in status_and_rem:
            item_status, rem_str = status_and_rem.split("__", 1)
        else:
            item_status = status_and_rem
            rem_str = ""

        prod_info = PRODUCT_MAP.get(sku)
        record = {
            "order_date": order_date,
            "shop_name": shop_name,
            "product_code": sku,
            "product_name": prod_info["name"],
            "category": prod_info["category"],
            "qty": qty,
            "status": item_status,
            "is_support": False,
            "source_id": source_id
        }
        supabase.table("orders").insert(record).execute()
        
        if rem_str:
            next_err_list = []
            for item_block in rem_str.split("||"):
                fields = item_block.split(",")
                if len(fields) == 5:
                    next_err_list.append({
                        "order_date": fields[0],
                        "shop_name": fields[1],
                        "sku": fields[2],
                        "qty": int(fields[3]),
                        "status": fields[4]
                    })
            
            if next_err_list:
                err = next_err_list[0]
                remaining_errors = next_err_list[1:]
                
                new_rem_str = ""
                if remaining_errors:
                    rem_parts = []
                    for e in remaining_errors:
                        rem_parts.append(f"{e['order_date']},{e['shop_name']},{e['sku']},{e['qty']},{e['status']}")
                    new_rem_str = "||".join(rem_parts)

                matches = difflib.get_close_matches(err["sku"], PRODUCT_MAP.keys(), n=3, cutoff=0.4)
                if matches:
                    buttons = []
                    for m in matches:
                        action_text = f"quickadd_{err['order_date']}_{err['shop_name']}_{m}_{err['qty']}_{err['status']}"
                        if new_rem_str:
                            action_text += f"__{new_rem_str}"
                        buttons.append(ButtonComponent(
                            style='primary',
                            margin='sm',
                            action=MessageAction(label=f"{m}: {PRODUCT_MAP[m]['name']}", text=action_text)
                        ))
                    
                    total_remaining = len(next_err_list)
                    flex_msg = FlexSendMessage(
                        alt_text="เลือกสินค้าที่ถูกต้อง",
                        contents=BubbleContainer(
                            body=BoxComponent(
                                layout='vertical',
                                contents=[
                                    TextComponent(text=f"⚠️ ยังมีรหัสผิดเหลืออีก {total_remaining} รายการ", weight='bold', size='sm', color='#FF5555'),
                                    TextComponent(text=f"กำลังแก้ไขรหัสผิด: '{err['sku']}'", size='xs', color='#333333', margin='sm', weight='bold'),
                                    TextComponent(text="กรุณาเลือกสินค้าที่ใกล้เคียง:", size='xs', color='#666666', margin='xs'),
                                    SeparatorComponent(margin='md')
                                ] + buttons
                            )
                        )
                    )
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                    return

        flex_msg = generate_all_days_summary_flex(source_id, page=1)
        if flex_msg:
            line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if parts[0] == "editshop":
        shop_name = parts[1]
        order_date = parts[2]
        
        items_res = supabase.table("orders").select("*").eq("source_id", source_id).eq("order_date", order_date).eq("shop_name", shop_name).execute()
        shop_items = items_res.data
        
        buttons = []
        for it in shop_items:
            buttons.append(ButtonComponent(
                style='secondary',
                margin='sm',
                action=MessageAction(label=f"แก้ {it['product_code']} ({it['qty']} ชิ้น)", text=f"edit_{it['id']}")
            ))
        
        flex_msg = FlexSendMessage(
            alt_text="จัดการออเดอร์ร้าน",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text=f"⚙️ จัดการร้าน: {shop_name}", weight='bold', size='md'),
                        SeparatorComponent(margin='md'),
                        TextComponent(text="เลือกรายการสินค้าที่ต้องการแก้ไข:", size='xs', color='#666666'),
                        SeparatorComponent(margin='sm')
                    ] + buttons
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if text.startswith("edit_"):
        record_id = parts[1]
        flex_msg = FlexSendMessage(
            alt_text="เลือกวิธีแก้ไข",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text="⚙️ เลือกรายการที่ต้องการแก้ไข", weight='bold', size='md'),
                        SeparatorComponent(margin='md'),
                        ButtonComponent(style='primary', action=MessageAction(label='✏️ แก้ไขจำนวน', text=f"action_editqtyprompt_{record_id}")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🏷️ เปลี่ยนสินค้า (เลือกหมวด)', text=f"action_editprodcats_{record_id}"))
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if parts[1] == "editqtyprompt":
        record_id = parts[2]
        line_bot_api.reply_message(event.reply_token, TextMessage(text=f"กรุณาพิมพ์จำนวนใหม่ในรูปแบบ: `setqty_{record_id}_[จำนวน]` (เช่น `setqty_{record_id}_5`)"))
        return
        
    if parts[1] == "setqty":
        record_id = parts[2]
        new_qty = int(parts[3])
        res = supabase.table("orders").update({"qty": new_qty}).eq("id", record_id).eq("source_id", source_id).execute()
        if res.data:
            flex_msg = generate_all_days_summary_flex(source_id, page=1)
            if flex_msg:
                line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if parts[1] == "editprodcats":
        record_id = parts[2]
        flex_msg = FlexSendMessage(
            alt_text="เลือกหมวดหมู่สินค้า",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text="📂 เลือกหมวดหมู่สินค้าใหม่", weight='bold', size='md'),
                        SeparatorComponent(margin='md'),
                        ButtonComponent(style='secondary', action=MessageAction(label='🍺 Draft Beer', text=f"action_pickcat_{record_id}_d")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🧊 Amenity / CO2', text=f"action_pickcat_{record_id}_amenity")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🛠️ Install', text=f"action_pickcat_{record_id}_install")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='📋 POSM', text=f"action_pickcat_{record_id}_posm")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🍾 OtherALC (รวม Soju 5 รส)', text=f"action_pickcat_{record_id}_OtherALC")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🍻 Bottle/Cans Beer', text=f"action_pickcat_{record_id}_Bottle/Cans"))
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if parts[1] == "pickcat":
        record_id = parts[2]
        cat_key = parts[3]
        prod_buttons = []
        for sku, info in PRODUCT_MAP.items():
            if info["category"] == cat_key:
                prod_buttons.append(ButtonComponent(style='link', action=MessageAction(label=f"{sku}: {info['name']}", text=f"action_setprod_{record_id}_{sku}")))
        
        flex_msg = FlexSendMessage(
            alt_text="เลือกสินค้า",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[TextComponent(text="🏷️ กรุณาเลือกสินค้า", weight='bold', size='md'), SeparatorComponent(margin='md')] + prod_buttons
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if parts[1] == "setprod":
        record_id = parts[2]
        new_sku = parts[3]
        prod_info = PRODUCT_MAP.get(new_sku)
        res = supabase.table("orders").update({
            "product_code": new_sku,
            "product_name": prod_info["name"],
            "category": prod_info["category"]
        }).eq("id", record_id).eq("source_id", source_id).execute()
        if res.data:
            flex_msg = generate_all_days_summary_flex(source_id, page=1)
            if flex_msg:
                line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    action_type = parts[1]
    if action_type == "status":
        record_id = parts[2]
        new_status = parts[3]
        
        curr_res = supabase.table("orders").select("order_date", "shop_name").eq("id", record_id).eq("source_id", source_id).execute()
        if not curr_res.data:
            return
        target_date = curr_res.data[0]["order_date"]
        shop_name = curr_res.data[0]["shop_name"]

        if new_status in ["อัพสลิปแล้ว", "อัพสลิป"]:
            supabase.table("orders").delete().eq("source_id", source_id).eq("order_date", target_date).eq("shop_name", shop_name).execute()
        else:
            supabase.table("orders").update({"status": new_status}).eq("source_id", source_id).eq("order_date", target_date).eq("shop_name", shop_name).execute()
            
        flex_msg = generate_all_days_summary_flex(source_id, page=1)
        if flex_msg:
            line_bot_api.reply_message(event.reply_token, flex_msg)
        else:
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"✅ อัปเดตสำเร็จ (ไม่มีออเดอร์เหลือในระบบแล้ว)"))
        
    elif action_type == "bulk":
        sub_action = parts[2]
        target_date = parts[3]
        if sub_action == "ordered":
            supabase.table("orders").update({"status": "Order แล้ว"}).eq("source_id", source_id).eq("order_date", target_date).execute()
            flex_msg = generate_all_days_summary_flex(source_id, page=1)
            if flex_msg:
                line_bot_api.reply_message(event.reply_token, flex_msg)
        elif sub_action == "uploaded":
            supabase.table("orders").delete().eq("source_id", source_id).eq("order_date", target_date).execute()
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"✅ อัปสลิปและลบข้อมูลออเดอร์วันที่ {target_date} ทั้งหมดเรียบร้อยแล้ว"))
        elif sub_action == "delete":
            supabase.table("orders").delete().eq("source_id", source_id).eq("order_date", target_date).execute()
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"✅ ลบข้อมูลออเดอร์วันที่ {target_date} ทั้งหมดเรียบร้อยแล้ว"))

def generate_single_day_bubble(
    order_date,
    orders,
    source_id,
    shop_chunk=None,
    day_part_idx=1,
    day_part_total=1,
    show_day_summary=True,
    today_str=None
):
    if today_str is None:
        today_str = get_today_str()

    total_qty = sum(item["qty"] for item in orders)

    if shop_chunk is None:
        shops_dict = {}
        for item in orders:
            s_name = item['shop_name']
            if s_name not in shops_dict:
                shops_dict[s_name] = []
            shops_dict[s_name].append(item)
        shop_chunk = list(shops_dict.items())[:MAX_SHOPS_PER_BUBBLE]

    badge_text = get_bucket_badge(order_date, today_str=today_str)
    part_label = f" ({day_part_idx}/{day_part_total})" if day_part_total > 1 else ""

    contents = [
        BoxComponent(
            layout='vertical',
            contents=[
                TextComponent(text=badge_text, weight='bold', size='xs', color='#1DB446'),
                TextComponent(text=f"📅 วันที่ {order_date}{part_label}", weight='bold', size='xl', color='#000000')
            ]
        ),
        SeparatorComponent(margin='md')
    ]
    
    for shop_name, shop_items in shop_chunk:
        shop_status = shop_items[0]['status'] if shop_items else 'pending'
        first_item_id = shop_items[0]['id'] if shop_items else ''
        status_color = get_status_color(shop_status)
        
        shop_contents = [
            BoxComponent(
                layout='horizontal',
                contents=[
                    TextComponent(text=f"🛒 {shop_name}", weight='bold', size='sm', color='#1DB446', flex=3),
                    TextComponent(text=f"[{shop_status}]", size='xs', color=status_color, align='center', flex=2, weight='bold'),
                    ButtonComponent(style='link', height='sm', action=MessageAction(label='✏️จัดการ', text=f"editshop_{shop_name}_{order_date}"), flex=2)
                ]
            ),
            SeparatorComponent(margin='xs')
        ]
        
        for item in shop_items:
            shop_contents.append(
                BoxComponent(
                    layout='horizontal',
                    margin='xs',
                    contents=[
                        TextComponent(text=f"• {item['product_code']} ({item['product_name']})", size='xs', color='#333333', flex=4, wrap=True),
                        TextComponent(text=f"{item['qty']} ชิ้น", size='xs', color='#666666', align='end', flex=2)
                    ]
                )
            )
        
        shop_contents.append(SeparatorComponent(margin='sm'))
        shop_contents.append(
            BoxComponent(
                layout='vertical',
                spacing='xs',
                contents=[
                    BoxComponent(
                        layout='horizontal', spacing='xs',
                        contents=[
                            ButtonComponent(style='secondary', height='sm', action=MessageAction(label='pending', text=f"action_status_{first_item_id}_pending")),
                            ButtonComponent(style='secondary', height='sm', action=MessageAction(label='Orderแล้ว', text=f"action_status_{first_item_id}_Order แล้ว")),
                            ButtonComponent(style='secondary', height='sm', action=MessageAction(label='อัพสลิป', text=f"action_status_{first_item_id}_อัพสลิปแล้ว"))
                        ]
                    ),
                    BoxComponent(
                        layout='horizontal', spacing='xs',
                        contents=[
                            ButtonComponent(style='secondary', height='sm', action=MessageAction(label='credit', text=f"action_status_{first_item_id}_credit")),
                            ButtonComponent(style='secondary', height='sm', action=MessageAction(label='overdue', text=f"action_status_{first_item_id}_overdue")),
                            ButtonComponent(style='secondary', height='sm', action=MessageAction(label='วงเงินเต็ม', text=f"action_status_{first_item_id}_วงเงินเต็ม"))
                        ]
                    )
                ]
            )
        )

        contents.append(
            BoxComponent(
                layout='vertical',
                margin='md',
                spacing='sm',
                contents=shop_contents
            )
        )
        contents.append(SeparatorComponent(margin='md'))

    if show_day_summary:
        agg_products = {}
        for item in orders:
            p_name = item['product_name']
            if p_name not in agg_products:
                agg_products[p_name] = 0
            agg_products[p_name] += item['qty']

        summary_box = [
            TextComponent(text=f"📦 รวมจำนวนสินค้าทั้งหมด: {total_qty} ชิ้น", weight='bold', size='sm', color='#000000')
        ]
        for p_name, qty in agg_products.items():
            pct = (qty / total_qty * 100) if total_qty > 0 else 0
            summary_box.append(TextComponent(text=f"  • {p_name} : {qty} ชิ้น ({pct:.1f}%)", size='xs', color='#555555'))
        
        contents.append(BoxComponent(layout='vertical', margin='md', spacing='xs', contents=summary_box))
        contents.append(SeparatorComponent(margin='md'))
        
        contents.append(BoxComponent(
            layout='vertical', spacing='sm',
            contents=[
                ButtonComponent(style='primary', color='#1DB446', height='sm', action=MessageAction(label='🟢 Orderแล้วทั้งหมด', text=f"action_bulk_ordered_{order_date}")),
                ButtonComponent(style='primary', color='#3b82f6', height='sm', action=MessageAction(label='🔵 อัพสลิปแล้วทั้งหมด', text=f"action_bulk_uploaded_{order_date}")),
                ButtonComponent(style='primary', color='#FF5555', height='sm', action=MessageAction(label='🔴 ลบทั้งหมด', text=f"action_bulk_delete_{order_date}"))
            ]
        ))
    
    return BubbleContainer(body=BoxComponent(layout='vertical', contents=contents))

def generate_summary_carousel(order_date, orders, source_id):
    bubbles = build_day_bubbles_capped_5_shops(order_date, orders, source_id)
    if len(bubbles) > 1:
        return FlexSendMessage(alt_text=f'สรุปยอด Order ประจำวันที่ {order_date}', contents=CarouselContainer(contents=bubbles))
    return FlexSendMessage(alt_text=f'สรุปยอด Order ประจำวันที่ {order_date}', contents=bubbles[0])

def generate_status_summary_carousel(status_name, orders, source_id):
    total_qty = sum(item["qty"] for item in orders)
    
    shops_dict = {}
    for item in orders:
        key = (item['shop_name'], item['order_date'])
        if key not in shops_dict:
            shops_dict[key] = []
        shops_dict[key].append(item)
    
    shops_list = list(shops_dict.items())
    chunk_size = MAX_SHOPS_PER_BUBBLE  # 📌 กำหนดแสดง 5 ร้านค้าต่อ 1 Bubble
    shop_chunks = [shops_list[i:i + chunk_size] for i in range(0, len(shops_list), chunk_size)]
    if not shop_chunks:
        shop_chunks = [[]]
        
    bubbles = []
    for idx, chunk in enumerate(shop_chunks):
        is_last = (idx == len(shop_chunks) - 1)
        
        contents = [
            BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text=f"📌 สรุปรายการสถานะ: {status_name}", weight='bold', size='lg', color='#1DB446')
                ]
            ),
            SeparatorComponent(margin='md')
        ]
        
        for (shop_name, order_date), shop_items in chunk:
            shop_status = shop_items[0]['status'] if shop_items else status_name
            first_item_id = shop_items[0]['id'] if shop_items else ''
            status_color = get_status_color(shop_status)
            
            shop_contents = [
                BoxComponent(
                    layout='vertical',
                    spacing='xs',
                    contents=[
                        TextComponent(text=f"📅 วันที่: {order_date}", size='xs', color='#888888', weight='bold'),
                        BoxComponent(
                            layout='horizontal',
                            contents=[
                                TextComponent(text=f"🛒 {shop_name}", weight='bold', size='sm', color='#1DB446', flex=3),
                                TextComponent(text=f"[{shop_status}]", size='xs', color=status_color, align='center', flex=2, weight='bold'),
                                ButtonComponent(style='link', height='sm', action=MessageAction(label='✏️จัดการ', text=f"editshop_{shop_name}_{order_date}"), flex=2)
                            ]
                        )
                    ]
                ),
                SeparatorComponent(margin='xs')
            ]
            
            for item in shop_items:
                shop_contents.append(
                    BoxComponent(
                        layout='horizontal',
                        margin='xs',
                        contents=[
                            TextComponent(text=f"• {item['product_code']} ({item['product_name']})", size='xs', color='#333333', flex=4, wrap=True),
                            TextComponent(text=f"{item['qty']} ชิ้น", size='xs', color='#666666', align='end', flex=2)
                        ]
                    )
                )
            
            shop_contents.append(SeparatorComponent(margin='sm'))
            shop_contents.append(
                BoxComponent(
                    layout='vertical',
                    spacing='xs',
                    contents=[
                        BoxComponent(
                            layout='horizontal', spacing='xs',
                            contents=[
                                ButtonComponent(style='secondary', height='sm', action=MessageAction(label='pending', text=f"action_status_{first_item_id}_pending")),
                                ButtonComponent(style='secondary', height='sm', action=MessageAction(label='Orderแล้ว', text=f"action_status_{first_item_id}_Order แล้ว")),
                                ButtonComponent(style='secondary', height='sm', action=MessageAction(label='อัพสลิป', text=f"action_status_{first_item_id}_อัพสลิปแล้ว"))
                            ]
                        ),
                        BoxComponent(
                            layout='horizontal', spacing='xs',
                            contents=[
                                ButtonComponent(style='secondary', height='sm', action=MessageAction(label='credit', text=f"action_status_{first_item_id}_credit")),
                                ButtonComponent(style='secondary', height='sm', action=MessageAction(label='overdue', text=f"action_status_{first_item_id}_overdue")),
                                ButtonComponent(style='secondary', height='sm', action=MessageAction(label='วงเงินเต็ม', text=f"action_status_{first_item_id}_วงเงินเต็ม"))
                            ]
                        )
                    ]
                )
            )

            contents.append(
                BoxComponent(
                    layout='vertical',
                    margin='md',
                    spacing='sm',
                    contents=shop_contents
                )
            )
            contents.append(SeparatorComponent(margin='md'))

        if is_last:
            agg_products_status = {}
            for item in orders:
                p_name = item['product_name']
                if p_name not in agg_products_status:
                    agg_products_status[p_name] = 0
                agg_products_status[p_name] += item['qty']

            summary_box = [
                TextComponent(text=f"📦 รวมจำนวนสินค้าทั้งหมด: {total_qty} ชิ้น", weight='bold', size='sm', color='#000000')
            ]
            for p_name, qty in agg_products_status.items():
                pct = (qty / total_qty * 100) if total_qty > 0 else 0
                summary_box.append(TextComponent(text=f"  • {p_name} : {qty} ชิ้น ({pct:.1f}%)", size='xs', color='#555555'))
            contents.append(BoxComponent(layout='vertical', margin='md', spacing='xs', contents=summary_box))

        contents.append(TextComponent(text=f"หน้าที่ {idx+1}/{len(shop_chunks)}", size='xxs', color='#aaaaaa', align='center', margin='md'))
        bubbles.append(BubbleContainer(body=BoxComponent(layout='vertical', contents=contents)))

    if len(bubbles) > 1:
        return FlexSendMessage(alt_text=f'สรุปยอดสถานะ {status_name}', contents=CarouselContainer(contents=bubbles))
    else:
        return FlexSendMessage(alt_text=f'สรุปยอดสถานะ {status_name}', contents=bubbles[0])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
