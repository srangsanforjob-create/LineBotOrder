import os
from datetime import datetime, timedelta
import pytz
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage,
    BubbleContainer, BoxComponent, TextComponent, ButtonComponent, SeparatorComponent, CarouselContainer
)
from supabase import create_client, Client

app = Flask(__name__)

# ดึงค่า Environment Variables จาก Render
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ตั้งค่า Timezone ไทย
BANGKOK_TZ = pytz.timezone('Asia/Bangkok')
COMPLETED_STATUS = "upslip"  # สถานะที่ถือว่าจบงานแล้ว

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
    user_message = event.message.text.strip()
    now_bkk = datetime.now(BANGKOK_TZ)
    
    orders = []
    title_text = ""
    show_date_flag = False

    # 1. คำสั่ง "งานค้าง" (ดึงทุกสถานะ ยกเว้น upslip ไม่จำกัดวันที่ + แสดงวันที่ + แบ่งหน้า)
    if user_message.startswith("งานค้าง"):
        parts = user_message.split(" ")
        page = 1
        if len(parts) > 1 and parts[1].isdigit():
            page = int(parts[1])
            
        limit = 20  # จำนวนรายการต่อหน้า (แบ่งเป็น Bubble ละ 5 รายการ)
        offset = (page - 1) * limit

        response = supabase.table("orders").select("*", count="exact") \
            .neq("status", COMPLETED_STATUS) \
            .order("order_date", desc=False) \
            .range(offset, offset + limit - 1) \
            .execute()
        
        orders = response.data
        title_text = f"งานค้าง (หน้า {page})"
        show_date_flag = True

    # 2. คำสั่ง "สรุป" (ตั้งแต่วันย้อนหลัง 1 วัน ถึงอนาคต หรือระบุวัน)
    elif user_message.startswith("สรุป"):
        parts = user_message.split(" ")
        
        if len(parts) > 1 and not parts[1].isdigit():
            # กรณีระบุวันที่ เช่น "สรุป 11/11/2026"
            target_date = parts[1]
            response = supabase.table("orders").select("*") \
                .eq("order_date", target_date) \
                .execute()
            orders = response.data
            title_text = f"สรุปยอดวันที่ {target_date}"
        else:
            # กรณีพิมพ์ "สรุป" ปกติ (ย้อนหลัง 1 วัน ถึง อนาคต 30 วัน)
            yesterday_date = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
            future_date = (now_bkk + timedelta(days=30)).strftime("%Y-%m-%d")
            
            response = supabase.table("orders").select("*") \
                .gte("order_date", yesterday_date) \
                .lte("order_date", future_date) \
                .execute()
            orders = response.data
            title_text = "สรุปยอด (เมื่อวาน - อนาคต)"
            show_date_flag = True

    # ส่งข้อความกลับหาผู้ใช้ถ้ามีคำสั่งตรงกัน
    if orders or user_message.startswith("สรุป") or user_message.startswith("งานค้าง"):
        if not orders:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎉 ไม่พบข้อมูลออเดอร์ในช่วงเวลานี้ครับ")
            )
        else:
            flex_message = create_order_carousel(orders, title_text, show_date_flag)
            line_bot_api.reply_message(event.reply_token, flex_message)

def create_order_carousel(orders, title_prefix, show_date=False):
    """ สร้าง Flex Message Carousel แบ่ง Bubble ละไม่เกิน 5 รายการ ป้องกัน Payload เกิน 50 KB """
    bubbles = []
    chunk_size = 5  # 5 รายการต่อ 1 Bubble
    
    for i in range(0, len(orders), chunk_size):
        chunk = orders[i:i + chunk_size]
        bubble_index = (i // chunk_size) + 1
        
        contents_list = [
            TextComponent(text=f"{title_prefix} (ส่วนที่ {bubble_index})", weight="bold", size="md", color="#1DB446")
        ]
        
        for order in chunk:
            contents_list.append(SeparatorComponent(margin="md"))
            
            # ดึงข้อมูลจากฐานข้อมูล
            cust_name = order.get("customer_name", "ไม่ระบุชื่อ")
            status = order.get("status", "ยังไม่ได้ออเดอร์")
            order_date = order.get("order_date", "")
            
            # แสดงวันที่กำกับถ้าถูกเปิดใช้งาน (เช่น หน้างานค้าง หรือสรุปภาพรวม)
            if show_date and order_date:
                contents_list.append(TextComponent(text=f"📅 วันที่: {order_date}", size="xs", color="#888888", margin="sm"))
                
            contents_list.append(TextComponent(text=f"ลูกค้า: {cust_name} | สเตตัส: {status}", size="sm", wrap=True, margin="sm"))
            
            # ปุ่มเปลี่ยนสเตตัสทั้ง 6 แบบ (สามารถปรับ Action Postback ตามระบบเดิมของคุณได้เลย)
            # ตัวอย่างการใส่ปุ่มเปลี่ยนสถานะย่อๆ ในแต่ละรายการ
            contents_list.append(
                BoxComponent(
                    layout="baseline",
                    margin="sm",
                    contents=[
                        TextComponent(text=f"สถานะปัจจุบัน: {status}", size="xs", color="#555555", wrap=True)
                    ]
                )
            )

        bubble = BubbleContainer(
            body=BoxComponent(
                layout="vertical",
                contents=contents_list
            )
        )
        bubbles.append(bubble)
        
        # LINE Carousel รองรับสูงสุด 12 Bubbles ต่อ 1 Request เพื่อความปลอดภัย
        if len(bubbles) >= 12:
            break

    return FlexSendMessage(
        alt_text=title_prefix,
        contents=CarouselContainer(contents=bubbles)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
