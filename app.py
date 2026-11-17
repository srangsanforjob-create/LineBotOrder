import re

def parse_order_message(text):
    """
    วิเคราะห์ข้อความจาก LINE เพื่อแยกเนื้อหาออเดอร์และสถานะ (Status)
    รองรับคำต่อท้ายสถานะทั้งภาษาไทยและภาษาอังกฤษ (เช่น order, ออเดอร์, slip, สลิป ฯลฯ)
    """
    # กำหนดคำสำคัญและสถานะที่ต้องการเทียบเคียง (รองรับทั้งภาษาไทยและอังกฤษ)
    status_mapping = {
        # Pending / รอดำเนินการ / ยังไม่ได้ออเดอร์
        'pending': 'pending',
        'รอออเดอร์': 'pending',
        'ยังไม่ได้ออเดอร์': 'pending',
        
        # Order / ออเดอร์ / สั่งแล้ว
        'order': 'order',
        'ออเดอร์': 'order',
        'สั่ง': 'order',
        
        # Slip / สลิป / ชำระเงินแล้ว
        'slip': 'slip',
        'สลิป': 'slip',
        'จ่ายเงิน': 'slip',
        
        # Credit / เครดิต / เงินเชื่อ
        'credit': 'credit',
        'เครดิต': 'credit',
        'เงินเชื่อ': 'credit',
    }
    
    # แยกบรรทัดหรือตรวจจับคำต่อท้าย (ตัวอย่างเช่น เช็คคำสุดท้ายในข้อความหรือรูปแบบที่กำหนด)
    lines = text.strip().split('\n')
    status = 'pending'  # ตั้งค่า Default เริ่มต้นเป็น pending ตามที่ตกลงกัน
    cleaned_lines = []
    
    for line in lines:
        words = line.strip().split()
        if words:
            # ตรวจสอบว่าคำสุดท้ายตรงกับ Keyword สถานะหรือไม่ (ไม่สนตัวพิมพ์เล็กใหญ่)
            last_word = words[-1].lower()
            if last_word in status_mapping:
                status = status_mapping[last_word]
                # ตัดคำสถานะออก ให้เหลือแต่เนื้อหาออเดอร์
                content_line = " ".join(words[:-1])
                if content_line:
                    cleaned_lines.append(content_line)
            else:
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)
            
    order_content = "\n".join(cleaned_lines).strip()
    return {
        "content": order_content,
        "status": status
    }

# --- ตัวอย่างการใช้งาน ---
# test_text_1 = "Lager 2 \n Rose 1 order"  -> status จะได้เป็น 'order'
# test_text_2 = "Lager 2 \n Rose 1"        -> status จะได้เป็น 'pending' (Default)
# test_text_3 = "Lager 2 slip"           -> status จะได้เป็น 'slip'
