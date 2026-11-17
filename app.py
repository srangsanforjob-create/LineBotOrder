import os
import json
import re
import base64
import hashlib
import hmac
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, abort
import requests
from supabase import create_client

# --- CONFIGURATION (strip() กันช่องว่าง/ขึ้นบรรทัดใหม่ที่ติดมาตอนก๊อปค่า) ---
SECRET = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

for _name, _val in [("LINE_CHANNEL_SECRET", SECRET), ("LINE_CHANNEL_ACCESS_TOKEN", TOKEN),
                    ("SUPABASE_URL", SUPABASE_URL), ("SUPABASE_KEY", SUPABASE_KEY)]:
    print(f"[config] {_name}: {'OK' if _val else '❌ MISSING'}", flush=True)

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    supabase = None
    print(f"[config] ❌ Supabase init failed: {e}", flush=True)

TZ = ZoneInfo("Asia/Bangkok")
app = Flask(__name__)

# --- PRODUCT DATABASE ---
PRODUCTS_DB = {
    "l": "Lager", "r": "Rose", "d": "Dunkel",
    "m": "MUG", "p": "PINE", "j": "JUG", "t": "TOWER",
    "h40l": "Hoshizaki 40L", "h90": "Hoshizaki 90L", "h120": "Hoshizaki 120L",
    "sct": "Stainless Counter", "st": "Stainless Table",
    "ast": "A-Stand", "std": "Standee", "aa5": "อะคริลิก A5", "aa6": "อะคริลิก A6",
    "galf": "Galaxy แบน 350ml", "galr": "Galaxy กลม 700ml",
    "tend3": "Tendo 360ml", "tend7": "Tendo 700ml",
    "kach": "Kacha 375ml",
    "sojy": "Soju โยเกิร์ต", "sojp": "Soju พีช",
    "sojg": "Soju องุ่น", "sojf": "Soju เกรปฟรุ๊ต", "sojs": "Soju สตรอเบอรี่"
}
CODES = list(PRODUCTS_DB.keys())

ALIAS_MAP = {
    "lager": "l", "ลาเกอร์": "l", "ลากิอร์": "l", "ลีโอ": "l", "เบียร์": "l", "l": "l",
    "rose": "r", "โรส": "r", "โรเซ่": "r", "r": "r",
    "dunkel": "d", "ดุงเกล": "d", "ดังก์เกล": "d", "ดำ": "d", "d": "d",
    "mug": "m", "แก้วมัค": "m", "มัค": "m", "m": "m",
    "pine": "p", "ไพน์": "p", "ไพนต์": "p", "p": "p",
    "jug": "j", "เหยือก": "j", "j": "j",
    "tower": "t", "ทาวเวอร์": "t", "ทาว": "t", "t": "t",
    "h40l": "h40l", "h40": "h40l", "40l": "h40l",
    "h90": "h90", "h90l": "h90", "90l": "h90",
    "h120": "h120", "h120l": "h120", "120l": "h120",
    "counter": "sct", "เคาน์เตอร์": "sct", "sct": "sct",
    "table": "st", "โต๊ะ": "st", "st": "st",
    "astand": "ast", "a-stand": "ast", "ast": "ast",
    "standee": "std", "สแตนดี้": "std", "std": "std",
    "aa5": "aa5", "a5": "aa5", "อะคริลิกa5": "aa5",
    "aa6": "aa6", "a6": "aa6", "อะคริลิกa6": "aa6",
    "galaxyแบน": "galf", "กาแล็กซี่แบน": "galf", "galf": "galf", "gal-f": "galf", "แบน": "galf",
    "galaxyกลม": "galr", "กาแล็กซี่กลม": "galr", "galr": "galr", "gal-r": "galr", "กลม": "galr",
    "tendo360": "tend3", "เทนโด360": "tend3", "เทนโดเล็ก": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "เทนโด700": "tend7", "เทนโดใหญ่": "tend7", "tend7": "tend7",
    "kacha": "kach", "คชา": "kach", "kach": "kach",
    "sojuyogurt": "sojy", "โซจูโยเกิร์ต": "sojy", "โซจโยเกิร์ต": "sojy", "โยเกิร์ต": "sojy", "sojy": "sojy",
    "sojupeach": "sojp", "โซจูพีช": "sojp", "โซจพีช": "sojp", "พีช": "sojp", "sojp": "sojp",
    "sojugrape": "sojg", "โซจูองุ่น": "sojg", "โซจองุ่น": "sojg", "องุ่น": "sojg", "sojg": "sojg",
    "sojugrapefruit": "sojf", "โซจูเกรปฟรุ๊ต": "sojf", "เกรปฟรุ๊ต": "sojf", "sojf": "sojf",
    "sojustrawberry": "sojs", "โซจูสตรอเบอรี่": "sojs", "โซจสตรอ": "sojs", "สตรอเบอรี่": "sojs", "sojs": "sojs"
}

STATUS_LABELS = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"),
    "overdue": ("🚨", "เลยกำหนดชำระ / Overdue", "#FF334B"),
    "insufficient_credit": ("⚠️", "วงเงินไม่พอ / วงเงินเต็ม", "#FF334B")
}

STATUS_KEYWORDS = {
    'pending': 'pending', 'รอดำเนินการ': 'pending', 'ยังไม่ได้ออเดอร์': 'pending', 'รอยืนยัน': 'pending',
    'order': 'ordered', 'ออเดอร์': 'ordered', 'สั่งแล้ว': 'ordered', 'ยืนยันออเดอร์': 'ordered',
    'slip': 'slip', 'สลิป': 'slip', 'จ่ายเงินแล้ว': 'slip', 'แนบสลิป': 'slip',
    'credit': 'credit', 'เครดิต': 'credit', 'เงินเชื่อ': 'credit',
    'overdue': 'overdue', 'เกินกำหนด': 'overdue',
    'insufficient_credit': 'insufficient_credit', 'วงเงินเต็ม': 'insufficient_credit'
}

SUMMARY_KEYWORDS = ["สรุป", "รายงาน", "ออเดอร์", "ดูยอด"]
HELP_KEYWORDS = ["คู่มือ", "ช่วยเหลือ", "help"]

DAYS_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
MONTHS_TH = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
]


def log(msg):
    print(msg, flush=True)


def format_thai_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"วัน{DAYS_TH[dt.weekday()]} ที่ {dt.day} {MONTHS_TH[dt.month - 1]} {dt.year + 543}"
    except Exception:
        return f"วันที่ {date_str}"


def safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def get_bangkok_date_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def resolve_date_token(token):
    now_bkk = datetime.now(TZ)
    m_full = re.match(r"^(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?$", token)
    if m_full:
        d = int(m_full.group(1))
        m = int(m_full.group(2))
        y = int(m_full.group(3)) if m_full.group(3) else now_bkk.year
        if y > 2500:
            y -= 543
        elif y < 100:
            y += 2000
        try:
            return datetime(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            return None

    if re.match(r"^\d{1,2}$", token):
        d = int(token)
        if 1 <= d <= 31:
            try:
                return now_bkk.replace(day=d).strftime("%Y-%m-%d")
            except ValueError:
                return None
    return None


def fetch_data(chat_id):
    """คืนค่า (shops, orders, error_message). ถ้า error จะไม่กลืนเงียบอีกต่อไป"""
    try:
        shops_res = supabase.table("shops").select("*").execute()
        orders_res = (supabase.table("orders").select("*").eq("chat_id", chat_id)
                      .order("ddate", desc=False).order("id", desc=False).execute())
        return shops_res.data or [], orders_res.data or [], None
    except Exception as e:
        log(f"[db] fetch_data error: {e}\n{traceback.format_exc()}")
        return [], [], str(e)


def get_or_create_shop(shop_name):
    clean_name = re.sub(r"^(?:วันที่\s*)?\d{1,2}(?:[/\-]\d{1,2})?\s+", "", shop_name.strip()).strip()
    if not clean_name:
        clean_name = "ร้านค้าทั่วไป"
    if not clean_name.startswith("ร้าน"):
        clean_name = f"ร้าน {clean_name}"
    existing = supabase.table("shops").select("*").eq("name", clean_name).execute()
    if existing.data:
        return existing.data[0]
    new_shop = supabase.table("shops").insert({
        "name": clean_name, "aliases": "", "credit_limit": 50000, "current_balance": 0
    }).execute()
    if new_shop.data:
        return new_shop.data[0]
    return None


def parse_order_text(raw_text):
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    parsed_items_list = []
    global_errors = []

    for line in lines:
        tokens = line.split()
        if not tokens:
            continue

        status = 'pending'
        last_word = tokens[-1].lower()
        if last_word in STATUS_KEYWORDS:
            status = STATUS_KEYWORDS[last_word]
            tokens.pop()

        if not tokens:
            continue

        order_date = get_bangkok_date_str()
        if tokens[0] in ["วันที่", "วัน"] and len(tokens) > 1:
            parsed_dt = resolve_date_token(tokens[1])
            if parsed_dt:
                order_date = parsed_dt
                tokens = tokens[2:]
        else:
            parsed_dt = resolve_date_token(tokens[0])
            if parsed_dt:
                order_date = parsed_dt
                tokens.pop(0)

        if not tokens:
            continue

        first_item_idx = -1
        for i, token in enumerate(tokens):
            clean_tok = token.lower().strip()
            if clean_tok in ALIAS_MAP or clean_tok in CODES:
                first_item_idx = i
                break
            m = re.match(r"^([a-zA-Zก-๙\-]+)(-?\d+)$", clean_tok)
            if m and m.group(1).lower() in ALIAS_MAP:
                first_item_idx = i
                break

        if first_item_idx == -1:
            global_errors.append(f"ไม่พบรายการสินค้าในบรรทัด: {line}")
            continue

        shop_name = " ".join(tokens[:first_item_idx]).strip() if first_item_idx > 0 else "ร้านค้าทั่วไป"
        item_tokens = tokens[first_item_idx:]

        items = {}
        i = 0
        while i < len(item_tokens):
            tok = item_tokens[i]
            clean_tok = tok.lower().strip()

            # ลองเป็นชื่อสินค้าเต็มก่อน (กัน h90 / h40l / aa5 ถูกตัดเป็น h + 90)
            if clean_tok in ALIAS_MAP:
                code = ALIAS_MAP[clean_tok]
                qty = 1
                if i + 1 < len(item_tokens) and re.match(r"^-?\d+$", item_tokens[i + 1]):
                    qty = safe_int(item_tokens[i + 1])
                    i += 1
                items[code] = items.get(code, 0) + qty
                i += 1
                continue

            m = re.match(r"^([a-zA-Zก-๙\-]+)(-?\d+)$", clean_tok)
            if m and m.group(1) in ALIAS_MAP:
                code = ALIAS_MAP[m.group(1)]
                items[code] = items.get(code, 0) + safe_int(m.group(2))
                i += 1
                continue

            global_errors.append(f"ไม่รู้จักสินค้า: {tok}")
            i += 1

        if items:
            parsed_items_list.append({
                "ddate": order_date,
                "shop_name": shop_name,
                "status": status,
                "items": items
            })

    return parsed_items_list, global_errors


def make_mini_btn(label, data, color, style="primary"):
    return {
        "type": "button",
        "action": {"type": "postback", "label": label, "data": data},
        "style": style,
        "color": color,
        "height": "sm",
        "margin": "xs"
    }


def group_orders_by_date(orders):
    grouped = {}
    for order in orders:
        ddate = str(order.get("ddate") or get_bangkok_date_str())
        grouped.setdefault(ddate, []).append(order)
    return grouped


def build_text_summary(chat_id):
    """สรุปแบบข้อความล้วน ใช้เป็น fallback เมื่อ Flex ส่งไม่ผ่าน"""
    shops, orders, err = fetch_data(chat_id)
    if err:
        return {"type": "text", "text": f"⚠️ อ่านฐานข้อมูลไม่ได้:\n{err[:300]}"}
    if not orders:
        return {"type": "text", "text": "ยังไม่มีรายการออเดอร์ในแชทนี้"}

    shop_map = {str(s["id"]): s for s in shops}
    grouped = group_orders_by_date(orders)
    out = []
    for ddate in sorted(grouped.keys())[-10:]:
        out.append(f"📅 {format_thai_date(ddate)}")
        totals = {}
        for idx, order in enumerate(grouped[ddate], 1):
            shop = shop_map.get(str(order.get("shop_id")))
            icon = STATUS_LABELS.get(order.get("status", "pending"), ("⏳",))[0]
            parts = []
            for code in CODES:
                q = safe_int(order.get(code))
                if q > 0:
                    totals[code] = totals.get(code, 0) + q
                    parts.append(f"{PRODUCTS_DB[code]} {q}")
            out.append(f"{idx}. {shop['name'] if shop else 'ร้านค้า'} {icon}\n   " + (", ".join(parts) or "ไม่มีสินค้า"))
        out.append("📦 รวม: " + ", ".join(f"{PRODUCTS_DB[c]} {q}" for c, q in totals.items()))
        out.append("")
    return {"type": "text", "text": "\n".join(out)[:4900]}


def build_carousel(chat_id):
    shops, orders, err = fetch_data(chat_id)
    if err:
        return {"type": "text", "text": f"⚠️ อ่านฐานข้อมูลไม่ได้:\n{err[:300]}"}
    if not orders:
        return {"type": "text", "text": "ยังไม่มีรายการออเดอร์ในแชทนี้"}

    shop_map = {str(s["id"]): s for s in shops}
    grouped_by_date = group_orders_by_date(orders)
    bubbles = []

    # เอา 10 วันล่าสุด (เดิมตัด [:10] จากวันเก่าสุด ทำให้วันใหม่ๆ หาย)
    for ddate in sorted(grouped_by_date.keys())[-10:]:
        date_orders = grouped_by_date[ddate]
        daily_totals = {code: 0 for code in CODES}

        content_blocks = [
            {"type": "text", "text": format_thai_date(ddate), "weight": "bold", "size": "md", "color": "#111111"},
            {
                "type": "box", "layout": "horizontal", "spacing": "xs", "margin": "md",
                "contents": [
                    make_mini_btn("Order ทั้งวัน", f"action=update_daily&date={ddate}&status=ordered", "#06C755"),
                    make_mini_btn("สลิปทั้งวัน", f"action=update_daily&date={ddate}&status=slip", "#00B900"),
                    make_mini_btn("ลบทั้งวัน", f"action=delete_daily&date={ddate}", "#FF334B", "secondary")
                ]
            },
            {"type": "separator", "margin": "lg"}
        ]

        for order in date_orders:
            o_id = order.get("id")
            shop_info = shop_map.get(str(order.get("shop_id")))
            shop_name = shop_info["name"] if shop_info else "ร้านค้า"
            order_status = order.get("status", "pending")
            icon, label, color = STATUS_LABELS.get(order_status, ("⏳", "ยังไม่ได้ Order", "#FF9900"))

            item_rows = []
            for code in CODES:
                q = safe_int(order.get(code))
                if q > 0:
                    daily_totals[code] += q
                    item_rows.append({
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"• {PRODUCTS_DB.get(code, code)}", "size": "sm", "color": "#333333", "flex": 4},
                            {"type": "text", "text": str(q), "size": "sm", "align": "end", "weight": "bold", "flex": 1}
                        ]
                    })
            if not item_rows:
                item_rows.append({"type": "text", "text": "ไม่มีสินค้า", "size": "sm", "color": "#888888"})

            row1 = {
                "type": "box", "layout": "horizontal", "spacing": "xs", "margin": "sm",
                "contents": [
                    make_mini_btn("Order", f"action=update_order&id={o_id}&status=ordered", "#06C755"),
                    make_mini_btn("สลิป", f"action=update_order&id={o_id}&status=slip", "#00B900"),
                    make_mini_btn("เครดิต", f"action=update_order&id={o_id}&status=credit", "#0099FF")
                ]
            }
            row2 = {
                "type": "box", "layout": "horizontal", "spacing": "xs", "margin": "xs",
                "contents": [
                    make_mini_btn("รอOrder", f"action=update_order&id={o_id}&status=pending", "#FF9900"),
                    make_mini_btn("เกินกำหนด", f"action=update_order&id={o_id}&status=overdue", "#E65100"),
                    make_mini_btn("ลบ", f"action=delete_order&id={o_id}", "#FF334B", "secondary")
                ]
            }

            content_blocks.append({
                "type": "box", "layout": "vertical", "margin": "md",
                "contents": [
                    {"type": "text", "text": shop_name, "weight": "bold", "size": "sm", "color": "#0066cc", "wrap": True},
                    {"type": "text", "text": f"{icon} {label}", "size": "xs", "weight": "bold", "color": color},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": item_rows},
                    row1, row2,
                    {"type": "separator", "margin": "md"}
                ]
            })

        summary_rows = []
        for code in CODES:
            tot = daily_totals[code]
            if tot > 0:
                summary_rows.append({
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"• {PRODUCTS_DB.get(code, code)}", "size": "sm", "color": "#ffffff", "flex": 4},
                        {"type": "text", "text": str(tot), "size": "sm", "align": "end", "weight": "bold", "color": "#ffffff", "flex": 1}
                    ]
                })

        if summary_rows:
            content_blocks.append({
                "type": "box", "layout": "vertical", "margin": "md", "paddingAll": "md",
                "backgroundColor": "#222222", "cornerRadius": "md",
                "contents": [
                    {"type": "text", "text": "📦 รวมยอดสินค้าประจำวันนี้", "weight": "bold", "size": "sm", "color": "#ffcc00"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": summary_rows}
                ]
            })

        bubbles.append({
            "type": "bubble", "size": "mega",
            "body": {"type": "box", "layout": "vertical", "contents": content_blocks}
        })

    return {
        "type": "flex",
        "altText": "สรุปรายการออเดอร์ตามวัน",
        "contents": {"type": "carousel", "contents": bubbles}
    }


def send_reply(reply_token, messages, chat_id=None):
    """ส่งข้อความตอบกลับ + log ผลจาก LINE ทุกครั้ง + fallback เป็นข้อความล้วนถ้า Flex ถูกปฏิเสธ"""
    if not reply_token or not messages:
        log("[reply] skipped: no reply_token or no messages")
        return
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=headers,
            json={"replyToken": reply_token, "messages": messages[:5]},
            timeout=10
        )
        log(f"[reply] LINE status={r.status_code} body={r.text[:500]}")
        if r.status_code != 200 and chat_id and any(m.get("type") == "flex" for m in messages):
            log("[reply] Flex rejected -> retry with text fallback")
            fallback = [m for m in messages if m.get("type") != "flex"] + [build_text_summary(chat_id)]
            r2 = requests.post(
                "https://api.line.me/v2/bot/message/reply",
                headers=headers,
                json={"replyToken": reply_token, "messages": fallback[:5]},
                timeout=10
            )
            log(f"[reply] fallback status={r2.status_code} body={r2.text[:500]}")
    except Exception as e:
        log(f"[reply] exception: {e}")


def process_webhook_event(event):
    source = event.get("source", {})
    chat_type = source.get("type", "user")
    if chat_type == "group":
        chat_id = source.get("groupId")
    elif chat_type == "room":
        chat_id = source.get("roomId")
    else:
        chat_id = source.get("userId", "user")

    reply_token = event.get("replyToken", "")
    etype = event.get("type")
    log(f"[event] type={etype} chat_type={chat_type} chat_id={chat_id}")

    if etype == "postback":
        data_str = event.get("postback", {}).get("data", "")
        qp = dict(p.split("=", 1) for p in data_str.split("&") if "=" in p)
        action = qp.get("action")

        if action == "update_daily" and qp.get("date"):
            supabase.table("orders").update({"status": qp.get("status", "pending")}) \
                .eq("chat_id", chat_id).eq("ddate", qp["date"]).execute()
        elif action == "delete_daily" and qp.get("date"):
            supabase.table("orders").delete().eq("chat_id", chat_id).eq("ddate", qp["date"]).execute()
        elif action == "update_order" and qp.get("id"):
            supabase.table("orders").update({"status": qp.get("status", "pending")}) \
                .eq("chat_id", chat_id).eq("id", qp["id"]).execute()
        elif action == "delete_order" and qp.get("id"):
            supabase.table("orders").delete().eq("chat_id", chat_id).eq("id", qp["id"]).execute()
        else:
            return
        send_reply(reply_token, [build_carousel(chat_id)], chat_id)
        return

    if etype == "message" and event.get("message", {}).get("type") == "text":
        text = event["message"]["text"].strip()
        log(f"[event] text={text!r}")

        if text.lower() in HELP_KEYWORDS:
            send_reply(reply_token, [{
                "type": "text",
                "text": "📖 วิธีใช้งาน:\n1. พิมพ์ [วันที่] [ชื่อร้าน] [สินค้า จำนวน] [สถานะ]\nตัวอย่าง: 19 แซ่บยโส L2 R1 order\n2. พิมพ์ 'สรุป' เพื่อดูรายการทั้งหมด"
            }])
            return

        if text in SUMMARY_KEYWORDS:
            send_reply(reply_token, [build_carousel(chat_id)], chat_id)
            return

        parsed_list, errors = parse_order_text(text)

        if not parsed_list:
            if errors and any(k in text.lower() for k in ALIAS_MAP.keys()):
                send_reply(reply_token, [{"type": "text", "text": "⚠️ รูปแบบไม่ถูกต้อง:\n" + "\n".join(errors)}])
            return

        inserted_count = 0
        db_errors = []
        for entry in parsed_list:
            try:
                shop = get_or_create_shop(entry["shop_name"])
                if not shop:
                    db_errors.append(f"สร้าง/หาร้านไม่ได้: {entry['shop_name']}")
                    continue
                payload = {
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "shop_id": shop["id"],
                    "ddate": entry["ddate"],
                    "status": entry["status"]
                }
                payload.update(entry["items"])
                supabase.table("orders").insert(payload).execute()
                inserted_count += 1
            except Exception as e:
                log(f"[db] insert error: {e}\n{traceback.format_exc()}")
                db_errors.append(str(e)[:300])

        msgs = []
        if errors:
            msgs.append({"type": "text", "text": "⚠️ บางบรรทัดไม่ถูกต้อง:\n" + "\n".join(errors)})
        if db_errors:
            msgs.append({"type": "text", "text": "❌ บันทึกลงฐานข้อมูลไม่สำเร็จ:\n" + "\n".join(db_errors)})
        if inserted_count > 0:
            msgs.append(build_carousel(chat_id))
        if msgs:
            send_reply(reply_token, msgs, chat_id)


def handle_webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    log(f"[webhook] received {len(body)} bytes")

    if SECRET:
        digest = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        if not hmac.compare_digest(expected, signature):
            log("[webhook] ❌ signature mismatch -> ตรวจ LINE_CHANNEL_SECRET")
            abort(400)

    try:
        events = json.loads(body).get("events", [])
    except Exception as e:
        log(f"[webhook] bad json: {e}")
        return "OK", 200

    for event in events:
        try:
            process_webhook_event(event)
        except Exception as e:
            log(f"[webhook] event error: {e}\n{traceback.format_exc()}")
            try:
                send_reply(event.get("replyToken", ""),
                           [{"type": "text", "text": f"❌ บอทเกิดข้อผิดพลาด:\n{str(e)[:300]}"}])
            except Exception:
                pass
    return "OK", 200


@app.route("/", methods=["GET"])
def health():
    return "Bot is running", 200


@app.route("/callback", methods=["POST"])
def callback():
    return handle_webhook()


@app.route("/LineBotWebhook/2.0", methods=["POST"])
def line_webhook_v2():
    return handle_webhook()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
