    # 3. Handle Order Input (ปรับปรุงการแยกข้อความให้ยืดหยุ่นขึ้น ไม่อ่านฟอร์แมตพลาด)
    lines = text.split("\n")
    success_count = 0
    error_messages = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # ตัดแบ่งแค่ช่องว่างแรก (ส่วนแรกเป็นวันที่ ส่วนที่เหลือคือชื่อร้านและรายการทั้งหมด)
        parts = line.split(" ", 1)
        if len(parts) >= 2:
            date_raw = parts[0]
            order_details = parts[1].strip() # ชื่อร้านและรายการสินค้าทั้งหมด
            
            try:
                order_date = parse_smart_date(date_raw)
            except ValueError:
                error_messages.append(f"❌ รูปแบบวันที่ไม่ถูกต้อง: '{date_raw}'")
                continue
            
            # ดึงชื่อร้านจากคำแรกของ order_details (หรือจะเก็บทั้งก้อนตามที่คุณต่อกับ Supabase ไว้ก็ได้ครับ)
            store_name = order_details.split(" ")[0] if order_details else "ร้านค้า"
            
            # บันทึกลง Supabase ของคุณตามเดิม (ไม่ไปยุ่งโครงสร้างเดิมครับ)
            if supabase:
                try:
                    supabase.table("orders").insert({
                        "store": store_name,
                        "order_date": order_date.strftime('%Y-%m-%d'),
                        "items_desc": order_details,
                        "status": "Pending"
                    }).execute()
                except Exception as e:
                    app.logger.error(f"Supabase Insert Error: {e}")
            
            success_count += 1
        else:
            error_messages.append(f"❌ รูปแบบไม่ถูกต้อง (ต้องระบุวันที่ด้วย): '{line}'")

    if success_count > 0:
        reply_text = f"✅ บันทึกออร์เดอร์สำเร็จทั้งหมด {success_count} รายการ"
        if error_messages:
            reply_text += "\n" + "\n".join(error_messages)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
