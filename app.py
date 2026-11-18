import os
import re
import difflib
from datetime import datetime
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

# 📌 Master Product Mapping ครบถ้วนพร้อมชื่อเต็ม
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

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    
    # ── ระบบคู่มือแบบ Flex Message แสดงชื่อสินค้าเต็ม ──
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
                        ButtonComponent(style='primary', margin='sm', action=MessageAction(label='🏷️ รายการสินค้า (Draft & Amenity)', text='คู่มือ สินค้า 1'))
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
                        TextComponent(text="• พิมพ์ 'สรุป' เพื่อดูยอดของวันนี้\n• พิมพ์ 'สรุป [YYYY-MM-DD]' เพื่อดูยอดเฉพาะวันที่ต้องการ", wrap=True, size='sm', color='#555555'),
                        ButtonComponent(style='primary', margin='md', action=MessageAction(label='👉 ดูสรุปวันนี้เลย', text='สรุป'))
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return
    
    # คู่มือสินค้าแบบ Carousel แยกหมวดหมู่ แสดงชื่อเต็ม
    elif text.lower() in ["คู่มือ สินค้า 1", "คู่มือ สินค้า 2", "คู่มือ สินค้า 3"]:
        b1 = BubbleContainer(
            body=BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text="🏷️ คู่มือสินค้า (1/3) - Draft & Amenity", weight='bold', size='sm', color='#1DB446'),
                    SeparatorComponent(margin='md'),
                    TextComponent(text="• Draft Beer (หมวด d):\n  L : GTD LAGER 20L\n  R : GTD ROSE 20L\n  D : GTD DUNKEL\n• Amenity (หมวด amenity):\n  M/Mug/แก้ว : แก้ว (Mug)\n  J/Jug/เหยือก : เหยือก (Jug)\n  T/Tower/ทาวเวอร์ : ทาวเวอร์ (Tower)\n  CO2 : CO2", wrap=True, size='xs', color='#333333'),
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
                    TextComponent(text="• Install:\n  H40L : Hoshizaki 40L\n  H90 : Hoshizaki 90L\n  H120 : Hoshizaki 120L\n  CELLI : Celli\n  SCT : Standless Counter\n  TABLE : Standless Table\n• POSM:\n  AST : A-Stand\n  LEDA2V/A3V/ACLA5/MHD", wrap=True, size='xs', color='#333333'),
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
                    TextComponent(text="• OtherALC:\n  GALF : Galaxy แบน 350ml\n  GALR : Galaxy กลม 700ml\n  TEND3/TEND7/KACH/SOJY\n• Bottle/Cans Beer:\n  LB : CARABAO LAGER 620ml\n  DB/LC/DC/WC/RC/IPAC/PTYB/PTYC", wrap=True, size='xs', color='#333333'),
                    SeparatorComponent(margin='md'),
                    ButtonComponent(style='secondary', action=MessageAction(label='⬅️ กลับหน้า 1', text='คู่มือ สินค้า 1'))
                ]
            )
        )
        carousel = CarouselContainer(contents=[b1, b2, b3])
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="คู่มือรายการสินค้า", contents=carousel))
        return

    # ── คำสั่งสรุปประจำวัน ──
    if text.startswith("สรุป"):
        parts = text.split()
        target_date = parts[1] if len(parts) > 1 else datetime.now().strftime("%Y-%m-%d")
        
        res = supabase.table("orders").select("*").eq("order_date", target_date).execute()
        orders = res.data
        
        if not orders:
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"📭 ไม่พบออเดอร์ในวันที่ {target_date}"))
            return
            
        flex_msg = generate_summary_carousel(target_date, orders)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    # ── ดักจับปุ่ม Action / แก้ไขต่างๆ ──
    if text.startswith("action_") or text.startswith("edit_") or text.startswith("setqty_") or text.startswith("quickadd_"):
        handle_action_command(event, text)
        return

    # ── ระบบรับ Order รองรับหลายสินค้าในบรรทัดเดียวกัน (ข้อ 1) ──
    lines = text.split('\n')
    success_records = []
    current_year_month = datetime.now().strftime("%Y-%m")
    
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
            
        parts = line_str.split()
        if len(parts) >= 3:
            raw_date = parts[0]
            shop_name = parts[1]
            
            # แปลงวันที่
            if len(raw_date) <= 2:
                order_date = f"{current_year_month}-{raw_date.zfill(2)}"
            else:
                order_date = raw_date
                
            # ส่วนที่เหลือคือรายการสินค้าและสเตตัส
            remainder_tokens = parts[2:]
            
            # ค้นหารหัสสินค้าและจำนวนแบบหลายตัวในบรรทัดเดียวกัน
            # เช่น L1 R2 D5 หรือ l1 r2 pending
            i = 0
            while i < len(remainder_tokens):
                token = remainder_tokens[i]
                # ตรวจสอบว่าเป็นสถานะหรือไม่
                if token.lower() in ["pending", "order", "credit", "overdue", "วงเงินเต็ม", "อัพสลิปแล้ว"]:
                    i += 1
                    continue
                
                # แยก รหัสสินค้า กับ จำนวน (เช่น L1 หรือ L)
                match_token = re.match(r'^([a-zA-Z0-9\(\)]+?)(\d+)?$', token)
                if match_token:
                    sku_raw = match_token.group(1).upper()
                    if match_token.group(2):
                        qty = int(match_token.group(2))
                    else:
                        # ถ้าโทเคนนี้ไม่มีตัวเลขติดอยู่ ให้ดูโทเคนถัดไปว่าเป็นตัวเลขหรือไม่
                        if i + 1 < len(remainder_tokens) and remainder_tokens[i+1].isdigit():
                            qty = int(remainder_tokens[i+1])
                            i += 1
                        else:
                            qty = 1
                else:
                    sku_raw = token.upper()
                    qty = 1

                # ตรวจสอบ Support Item ('sup' / 'SUP')
                is_support = sku_raw.startswith("SUP")
                clean_sku = sku_raw.replace("SUP", "", 1) if is_support else sku_raw
                
                # ตรวจสอบ Product Mapping & Fuzzy Matching (ข้อ 2: ทำเป็น Flex Message ให้กดเลือกทันที)
                product_info = PRODUCT_MAP.get(clean_sku)
                if not product_info:
                    matches = difflib.get_close_matches(clean_sku, PRODUCT_MAP.keys(), n=3, cutoff=0.4)
                    if matches:
                        buttons = []
                        for m in matches:
                            # สร้างปุ่มกดเลือกสินค้าที่ถูกต้อง พร้อมส่ง Action กลับมาบันทึกอัตโนมัติ
                            buttons.append(ButtonComponent(
                                style='primary',
                                margin='sm',
                                action=MessageAction(label=f"{m}: {PRODUCT_MAP[m]['name']}", text=f"quickadd_{order_date}_{shop_name}_{m}_{qty}")
                            ))
                        flex_msg = FlexSendMessage(
                            alt_text="เลือกสินค้าที่ถูกต้อง",
                            contents=BubbleContainer(
                                body=BoxComponent(
                                    layout='vertical',
                                    contents=[
                                        TextComponent(text=f"⚠️ ไม่พบรหัสสินค้า '{sku_raw}'", weight='bold', size='md', color='#FF5555'),
                                        TextComponent(text="กรุณาเลือกสินค้าที่ใกล้เคียงด้านล่าง:", size='xs', color='#666666', margin='sm'),
                                        SeparatorComponent(margin='md')
                                    ] + buttons
                                )
                            )
                        )
                        line_bot_api.reply_message(event.reply_token, flex_msg)
                        return
                    else:
                        line_bot_api.reply_message(event.reply_token, TextMessage(text=f"⚠️ ไม่พบรหัสสินค้า '{sku_raw}' กรุณาตรวจสอบรหัสในคู่มือ"))
                        return
                    
                product_name = product_info["name"]
                category = product_info["category"]
                if is_support:
                    product_name = f"support({product_name})"

                record = {
                    "order_date": order_date,
                    "shop_name": shop_name,
                    "product_code": clean_sku,
                    "product_name": product_name,
                    "category": category,
                    "qty": qty,
                    "status": "pending",
                    "is_support": is_support
                }
                res = supabase.table("orders").insert(record).execute()
                if res.data:
                    success_records.append(res.data[0])
                i += 1

    if success_records:
        target_date = success_records[0]["order_date"]
        res = supabase.table("orders").select("*").eq("order_date", target_date).execute()
        flex_msg = generate_summary_carousel(target_date, res.data)
        line_bot_api.reply_message(event.reply_token, flex_msg)
    else:
        line_bot_api.reply_message(event.reply_token, TextMessage(text="⚠️ รูปแบบการสั่งซื้อไม่ถูกต้อง กรุณาพิมพ์ 'คู่มือ' เพื่อดูวิธีใช้งาน"))

def handle_action_command(event, text):
    parts = text.split("_")
    
    # ── Quick Add เมื่อกดเลือกสินค้าที่แนะนำจาก Fuzzy Matching ──
    if parts[0] == "quickadd":
        # quickadd_[date]_[shop]_[sku]_[qty]
        order_date = parts[1]
        shop_name = parts[2]
        sku = parts[3]
        qty = int(parts[4])
        prod_info = PRODUCT_MAP.get(sku)
        
        record = {
            "order_date": order_date,
            "shop_name": shop_name,
            "product_code": sku,
            "product_name": prod_info["name"],
            "category": prod_info["category"],
            "qty": qty,
            "status": "pending",
            "is_support": False
        }
        supabase.table("orders").insert(record).execute()
        all_orders = supabase.table("orders").select("*").eq("order_date", order_date).execute().data
        line_bot_api.reply_message(event.reply_token, generate_summary_carousel(order_date, all_orders))
        return

    # ── ปุ่มแก้ไขสินค้า ──
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
        res = supabase.table("orders").update({"qty": new_qty}).eq("id", record_id).execute()
        if res.data:
            target_date = res.data[0]["order_date"]
            all_orders = supabase.table("orders").select("*").eq("order_date", target_date).execute().data
            line_bot_api.reply_message(event.reply_token, generate_summary_carousel(target_date, all_orders))
        return

    # แสดงหมวดหมู่สินค้าก่อน (ข้อ 2)
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
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🍾 OtherALC', text=f"action_pickcat_{record_id}_OtherALC")),
                        ButtonComponent(style='secondary', margin='sm', action=MessageAction(label='🍻 Bottle/Cans Beer', text=f"action_pickcat_{record_id}_Bottle/Cans"))
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    # แสดงรายการสินค้าในหมวดนั้นๆ (ข้อ 2)
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
                    contents=[TextComponent(text="🏷️ กรุณาเลือกสินค้า", weight='bold', size='md'), SeparatorComponent(margin='md')] + prod_buttons[:10]
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
        }).eq("id", record_id).execute()
        if res.data:
            target_date = res.data[0]["order_date"]
            all_orders = supabase.table("orders").select("*").eq("order_date", target_date).execute().data
            line_bot_api.reply_message(event.reply_token, generate_summary_carousel(target_date, all_orders))
        return

    # ── จัดการสถานะและ Bulk Action (ข้อ 4: แสดง Flex สรุปทันที) ──
    action_type = parts[1]
    if action_type == "status":
        record_id = parts[2]
        new_status = parts[3]
        
        curr_res = supabase.table("orders").select("order_date").eq("id", record_id).execute()
        if not curr_res.data:
            return
        target_date = curr_res.data[0]["order_date"]

        if new_status == "อัพสลิปแล้ว":
            supabase.table("orders").delete().eq("id", record_id).execute()
        else:
            supabase.table("orders").update({"status": new_status}).eq("id", record_id).execute()
            
        updated_orders = supabase.table("orders").select("*").eq("order_date", target_date).execute().data
        if updated_orders:
            flex_msg = generate_summary_carousel(target_date, updated_orders)
            line_bot_api.reply_message(event.reply_token, flex_msg)
        else:
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"✅ อัปเดตสำเร็จ (ไม่มีออเดอร์เหลือในวันที่ {target_date})"))
        
    elif action_type == "bulk":
        sub_action = parts[2]
        target_date = parts[3]
        if sub_action == "ordered":
            supabase.table("orders").update({"status": "Order แล้ว"}).eq("order_date", target_date).execute()
            updated_orders = supabase.table("orders").select("*").eq("order_date", target_date).execute().data
            flex_msg = generate_summary_carousel(target_date, updated_orders)
            line_bot_api.reply_message(event.reply_token, flex_msg)
        elif sub_action in ["uploaded", "delete"]:
            supabase.table("orders").delete().eq("order_date", target_date).execute()
            line_bot_api.reply_message(event.reply_token, TextMessage(text=f"✅ ลบข้อมูลออเดอร์วันที่ {target_date} ทั้งหมดเรียบร้อยแล้ว"))

def generate_summary_carousel(order_date, orders):
    bubbles = []
    total_items = len(orders)
    total_qty = sum(item["qty"] for item in orders)
    
    chunk_size = 5
    item_chunks = [orders[i:i + chunk_size] for i in range(0, total_items, chunk_size)]
    if not item_chunks:
        item_chunks = [[]]
        
    for idx, chunk in enumerate(item_chunks):
        is_last = (idx == len(item_chunks) - 1)
        
        contents = [
            BoxComponent(
                layout='vertical',
                contents=[
                    TextComponent(text=f"📅 วันที่ {order_date}", weight='bold', size='xl', color='#000000')
                ]
            ),
            SeparatorComponent(margin='md')
        ]
        
        for item in chunk:
            contents.append(
                BoxComponent(
                    layout='vertical',
                    margin='md',
                    spacing='sm',
                    contents=[
                        TextComponent(text=f"🛒 {item['shop_name']} | {item['product_code']} ({item['product_name']})", weight='bold', size='sm', color='#333333'),
                        TextComponent(text=f"จำนวน: {item['qty']} ชิ้น | สถานะ: {item['status']}", size='xs', color='#666666')
                    ]
                )
            )
            contents.append(BoxComponent(
                layout='horizontal', spacing='xs', margin='sm',
                contents=[
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='pending', text=f"action_status_{item['id']}_pending")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='Orderแล้ว', text=f"action_status_{item['id']}_Order แล้ว")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='อัพสลิป', text=f"action_status_{item['id']}_อัพสลิปแล้ว"))
                ]
            ))
            contents.append(BoxComponent(
                layout='horizontal', spacing='xs', margin='sm',
                contents=[
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='credit', text=f"action_status_{item['id']}_credit")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='overdue', text=f"action_status_{item['id']}_overdue")),
                    ButtonComponent(style='secondary', height='sm', action=MessageAction(label='วงเงินเต็ม', text=f"action_status_{item['id']}_วงเงินเต็ม"))
                ]
            ))
            contents.append(BoxComponent(
                layout='horizontal', spacing='xs', margin='sm',
                contents=[
                    ButtonComponent(style='link', height='sm', action=MessageAction(label='✏️ แก้ไข', text=f"edit_{item['id']}")),
                    ButtonComponent(style='link', height='sm', action=MessageAction(label='❌ ลบ', text=f"action_status_{item['id']}_อัพสลิปแล้ว"))
                ]
            ))
            contents.append(SeparatorComponent(margin='md'))

        if is_last:
            summary_box = [
                TextComponent(text=f"📦 รวมจำนวนสินค้าทั้งหมด: {total_qty} ชิ้น", weight='bold', size='sm', color='#000000')
            ]
            for item in orders:
                pct = (item["qty"] / total_qty * 100) if total_qty > 0 else 0
                summary_box.append(TextComponent(text=f"  • {item['product_code']} : {item['qty']} ชิ้น ({pct:.1f}%)", size='xs', color='#555555'))
            
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

        contents.append(TextComponent(text=f"หน้าที่ {idx+1}/{len(item_chunks)}", size='xxs', color='#aaaaaa', align='center', margin='md'))
        bubbles.append(BubbleContainer(body=BoxComponent(layout='vertical', contents=contents)))

    if len(bubbles) > 1:
        return FlexSendMessage(alt_text='สรุปยอด Order ประจำวัน', contents=CarouselContainer(contents=bubbles))
    else:
        return FlexSendMessage(alt_text='สรุปยอด Order ประจำวัน', contents=bubbles[0])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
