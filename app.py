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

# 📌 Master Product Mapping (6 หมวดหมู่สมบูรณ์)
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
    "H90": {"name": "Hoshizaki 90L", "category": "install"},
    "H120": {"name": "Hoshizaki 120L", "category": "install"},
    "CELLI": {"name": "Celli", "category": "install"},
    "SCT": {"name": "Standless Counter", "category": "install"},
    "TABLE": {"name": "Standless Table", "category": "install"},
    
    # POSM (หมวด posm)
    "AST": {"name": "A-Stand", "category": "posm"},
    "LEDA2V": {"name": "LED Signage A2 แนวตั้ง", "category": "posm"},
    "LEDA2L": {"name": "LED Signage A2 แนวนอน", "category": "posm"},
    "LEDA3V": {"name": "LED Signage A3 แนวตั้ง", "category": "posm"},
    "LEDA3L": {"name": "LED Signage A3 แนวนอน", "category": "posm"},
    "LEDA4V": {"name": "LED Signage A4 แนวตั้ง", "category": "posm"},
    "LEDA4L": {"name": "LED Signage A4 แนวนอน", "category": "posm"},
    "ACLA5": {"name": "อะคริลิกตั้งโต๊ะ A5", "category": "posm"},
    "ACLA6": {"name": "อะคริลิกตั้งโต๊ะ A6", "category": "posm"},
    "MHD": {"name": "Menu Holder", "category": "posm"},
    
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
    
    # 2. จัดการคู่มือการใช้งานแบบ Flex Message (ข้อ 2)
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
                        ButtonComponent(style='primary', margin='sm', action=MessageAction(label='🏷️ รายการรหัสสินค้า', text='คู่มือ สินค้า'))
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
                        TextComponent(text="• พิมพ์: [วันที่] [ชื่อร้าน] [รหัสสินค้า] [จำนวน] [สเตตัส]\n• ตัวอย่าง: 18 GUZA L 1 pending\n• หากระบุแค่วัน (เช่น 18) จะนับเป็นเดือนปัจจุบัน\n• พิมพ์ sup หรือ SUP นำหน้ารหัสเพื่อทำสินค้า Support", wrap=True, size='sm', color='#555555')
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
    elif text.lower() == "คู่มือ สินค้า":
        flex_msg = FlexSendMessage(
            alt_text="คู่มือสินค้า",
            contents=BubbleContainer(
                body=BoxComponent(
                    layout='vertical',
                    contents=[
                        TextComponent(text="🏷️ หมวดหมู่สินค้าหลัก", weight='bold', size='md'),
                        SeparatorComponent(margin='md'),
                        TextComponent(text="1. Draft Beer: L, R, D\n2. Amenity: M, J, T, CO2\n3. Install: H40L, H90, Celli, Table\n4. POSM: AST, LEDA2V, ACLA5\n5. OtherALC: GALF, TEND3, SOJY\n6. Bottle/Cans: LB, DB, LC, IPAC", wrap=True, size='xs', color='#555555')
                    ]
                )
            )
        )
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    # คำสั่งสรุป (สรุป / สรุป [วันที่])
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

    # จัดการปุ่ม Action ต่างๆ (สถานะ, Bulk, แก้ไข)
    if text.startswith("action_") or text.startswith("edit_"):
        handle_action_command(event, text)
        return

    # 3. จัดการการ Order สินค้าแบบยืดหยุ่น (รองรับติดกันหรือเว้นวรรค) (ข้อ 3)
    lines = text.split('\n')
    success_records = []
    current_year_month = datetime.now().strftime("%Y-%m")
    
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
            
        # ใช้ Regex แยกส่วน: วันที่ (ตัวเลข 1-2 หลัก หรือ YYYY-MM-DD), ชื่อร้าน, สินค้า, จำนวน (ตัวเลขท้ายสุดหรือก่อนสถานะ), สเตตัส
        # ตัวอย่าง: 18 GUZA L1 pending หรือ 18 GUZA L 1
        parts = line_str.split()
        if len(parts) >= 3:
            raw_date = parts[0]
            shop_name = parts[1]
            
            # ตรวจสอบว่าพาร์ทที่ 3 ติดกันหรือไม่ เช่น L1 หรือ L 1
            remainder = " ".join(parts[2:])
            # ค้นหาจำนวนตัวเลขที่อยู่ท้ายสุด หรือก่อนสถานะ
            match_qty = re.search(r'\s+(\d+)(?:\s+(.*))?$', remainder)
            
            if match_qty:
                qty_str = match_qty.group(1)
                status_str = match_qty.group(2)
                sku_raw = remainder[:match_qty.start()].strip().upper()
                qty = int(qty_str)
                status = status_str.strip() if status_str else "pending"
            else:
                # กรณีไม่ได้ใส่จำนวน ให้ default เป็น 1
                sku_raw = parts[2].upper()
                qty = 1
                status = " ".join(parts[3:]) if len(parts) > 3 else "pending"

            # แปลงวันที่
            if len(raw_date) <= 2:
                order_date = f"{current_year_month}-{raw_date.zfill(2)}"
            else:
                order_date = raw_date
                
            # ตรวจสอบ Support Item ('sup' / 'SUP')
            is_support = sku_raw.startswith("SUP")
            clean_sku = sku_raw.replace("SUP", "", 1) if is_support else sku_raw
            
            # ตรวจสอบ Product Mapping & Fuzzy Matching
            product_info = PRODUCT_MAP.get(clean_sku)
            if not product_info:
                matches = difflib.get_close_matches(clean_sku, PRODUCT_MAP.keys(), n=3, cutoff=0.4)
                if matches:
                    options_text = ", ".join([f"'{m}' ({PRODUCT_MAP[m]['name']})" for m in matches])
                    line_bot_api.reply_message(event.reply_token, TextMessage(text=f"⚠️ ไม่พบรหัสสินค้า '{sku_raw}'\nคุณหมายถึงสินค้าเหล่านี้หรือไม่:\n{options_text}"))
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
                "status": status,
                "is_support": is_support
            }
            res = supabase.table("orders").insert(record).execute()
            if res.data:
                success_records.append(res.data[0])

    if success_records:
        target_date = success_records[0]["order_date"]
        res = supabase.table("orders").select("*").eq("order_date", target_date).execute()
        flex_msg = generate_summary_carousel(target_date, res.data)
        line_bot_api.reply_message(event.reply_token, flex_msg)
    else:
        line_bot_api.reply_message(event.reply_token, TextMessage(text="⚠️ รูปแบบการสั่งซื้อไม่ถูกต้อง กรุณาพิมพ์ 'คู่มือ' เพื่อดูวิธีใช้งาน"))

def handle_action_command(event, text):
    parts = text.split("_")
    
    # 1. กดปุ่มแก้ไข (เลือกแก้จำนวน หรือแก้สินค้า) (ข้อ 1)
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

    # หน้าต่างบอกวิธีพิมพ์แก้จำนวน
    if parts[1] == "editqtyprompt":
        record_id = parts[2]
        line_bot_api.reply_message(event.reply_token, TextMessage(text=f"พิมพ์จำนวนใหม่สำหรับรายการนี้ได้เลย เช่น: `setqty_{record_id}_5`"))
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

    # แสดงหมวดหมู่สินค้าเพื่อให้เลือกเปลี่ยน
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

    # แสดงรายการสินค้าในหมวดนั้นๆ ให้กดเลือก
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

    # บันทึกสินค้าใหม่ที่เลือก
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

    # 2. จัดการเปลี่ยนสถานะ / ปุ่ม Bulk (ข้อ 4: กดปุ่มแล้วแสดง Flex สรุป Order เสมอ)
    action_type = parts[1]
    if action_type == "status":
        record_id = parts[2]
        new_status = parts[3]
        
        # ดึงวันที่ของรายการนี้ก่อนอัปเดตหรือลบ
        curr_res = supabase.table("orders").select("order_date").eq("id", record_id).execute()
        if not curr_res.data:
            return
        target_date = curr_res.data[0]["order_date"]

        if new_status == "อัพสลิปแล้ว":
            supabase.table("orders").delete().eq("id", record_id).execute()
        else:
            supabase.table("orders").update({"status": new_status}).eq("id", record_id).execute()
            
        # ดึงข้อมูลล่าสุดของวันนั้นมาแสดงเป็น Flex สรุป Order ทันที
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
