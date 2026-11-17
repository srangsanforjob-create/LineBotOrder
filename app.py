import os
import json
import re
import base64
import hashlib
import hmac
from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import Flask, request, abort
import requests
from supabase import create_client, Client

# --- CONFIG ---
SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TZ = ZoneInfo("Asia/Bangkok")
app = Flask(__name__)

# --- FULL PRODUCT DATABASE & MAPPINGS ---
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
    # Draft Beer
    "lager": "l", "ลาเกอร์": "l", "ลากิอร์": "l", "ลีโอ": "l", "เบียร์": "l", "l": "l",
    "rose": "r", "โรส": "r", "โรเซ่": "r", "r": "r",
    "dunkel": "d", "ดุงเกล": "d", "ดังก์เกล": "d", "ดำ": "d", "d": "d",
    # Glasses & Towers
    "mug": "m", "แก้วมัค": "m", "m": "m",
    "pine": "p", "ไพน์": "p", "ไพนต์": "p", "p": "p",
    "jug": "j", "เหยือก": "j", "j": "j",
    "tower": "t", "ทาวเวอร์": "t", "ทาว": "t", "t": "t",
    # Dispensers & Furniture
    "h40l": "h40l", "h40": "h40l", "40l": "h40l",
    "h90": "h90", "h90l": "h90", "90l": "h90",
    "h120": "h120", "h120l": "h120", "120l": "h120",
    "counter": "sct", "เคาน์เตอร์": "sct", "sct": "sct",
    "table": "st", "โต๊ะ": "st", "st": "st",
    # POSM
    "astand": "ast", "a-stand": "ast", "ast": "ast",
    "standee": "std", "สแตนดี้": "std", "std": "std",
    "aa5": "aa5", "a5": "aa5", "อะคริลิกa5": "aa5",
    "aa6": "aa6", "a6": "aa6", "อะคริลิกa6": "aa6",
    # Galaxy
    "galaxyแบน": "galf", "กาแล็กซี่แบน": "galf", "galf": "galf", "gal-f": "galf", "แบน": "galf",
    "galaxyกลม": "galr", "กาแล็กซี่กลม": "galr", "galr": "galr", "gal-r": "galr", "กลม": "galr",
    # Tendo & Kacha
    "tendo360": "tend3", "เทนโด360": "tend3", "เทนโดเล็ก": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "เทนโด700": "tend7", "เทนโดใหญ่": "tend7", "tend7": "tend7",
    "kacha": "kach", "คชา": "kach", "kach": "kach",
    # Soju
    "sojuyogurt": "sojy", "โซจูโยเกิร์ต": "sojy", "โซจโยเกิร์ต": "sojy", "โยเกิร์ต": "sojy", "sojy": "sojy",
    "sojupeach": "sojp", "โซจูพีช": "sojp", "โซจพีช": "sojp", "พีช": "sojp", "sojp": "sojp",
    "sojugrape": "sojg", "โซจูองุ่น": "sojg", "โซจองุ่น": "sojg", "องุ่น": "sojg", "sojg": "sojg",
    "sojugrapefruit": "sojf", "โซจูเกรปฟรุ๊ต": "sojf", "เกรปฟรุ๊ต": "sojf", "sojf": "sojf",
    "sojustrawberry": "sojs", "โซจูสตรอเบอรี่": "sojs", "โซจสตรอ": "sojs", "สตรอเบอรี่": "sojs", "sojs": "sojs"
}

AMBIGUOUS_GROUPS = {
    "soju": ["sojy", "sojp", "sojg", "sojf", "sojs"],
    "โซจู": ["sojy", "sojp", "sojg", "sojf", "sojs"],
    "โซจ": ["sojy", "sojp", "sojg", "sojf", "sojs"],
    "galaxy": ["galf", "galr"],
    "กาแล็กซี่": ["galf", "galr"],
    "gal": ["galf", "galr"],
    "tendo": ["tend3", "tend7"],
    "เทนโด": ["tend3", "tend7"],
    "tend": ["tend3", "tend7"],
    "hoshizaki": ["h40l", "h90", "h120"],
    "โฮชิซากิ": ["h40l", "h90", "h120"],
    "ตู้": ["h40l", "h90", "h120"],
    "อะคริลิก": ["aa5", "aa6"],
    "acrylic": ["aa5", "aa6"],
    "สแตนเลส": ["sct", "st"],
    "stainless": ["sct", "st"],
    "เบียร์สด": ["l", "r", "d"],
    "draft": ["l", "r", "d"]
}

STATUSES = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"),
    "overdue": ("🚨", "เลยกำหนดชำระ / Overdue", "#FF334B"),
    "insufficient_credit": ("⚠️", "วงเงินไม่พอ / วงเงินเต็ม", "#FF334B")
}

def num(v):
    try:
        return int(v)
    except Exception:
        return 0

def fetch_fresh_data(target_date=None):
    try:
        shops_res = supabase.table("shops").select("*").execute()
        query = supabase.table("orders").select("*")
        if target_date:
            query = query.eq("ddate", target_date)
        orders_res = query.execute()
        
        shops = shops_res.data or []
        orders = [{k: num(r[k]) if k in CODES else r[k] for k in r} for r in (orders_res.data or [])]
        return shops, orders
    except Exception as e:
        print(f"❌ DB Fetch Error: {e}")
        return [], []

def get_or_create_shop(name):
    shops, _ = fetch_fresh_data()
    dn = name.strip()
    if not dn.startswith("ร้าน"):
        dn = "ร้าน " + dn
    s = next((s for s in shops if s["name"] == dn), None)
    if s:
        return s
    try:
        res = supabase.table("shops").insert({
            "name": dn, 
            "aliases": "", 
            "credit_limit": 50000, 
            "current_balance": 0
        }).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        print(f"❌ Shop Create Error: {e}")
    return None

def shop_by_id(sid, shops_cache):
    return next((s for s in shops_cache if str(s.get("id")) == str(sid)), None)

def dmy(iso):
    try:
        y, m, d = iso.split("-")
        return f"{int(d):02d}/{int(m):02d}/{y}"
    except Exception:
        return iso

def today():
    return datetime.now(TZ).date()

def resolve_date(day_val):
    t = today()
    try:
        return date(t.year, t.month, day_val).isoformat()
    except Exception:
        return t.isoformat()

def parse_target_date(text_arg):
    """แปลงข้อความวันที่ เช่น '18', '18/11', '18/11/2026' ให้เป็น ISO format (YYYY-MM-DD)"""
    t = today()
    parts = text_arg.strip().split('/')
    try:
        if len(parts) == 1 and parts[0].isdigit():
            d = int(parts[0])
            return date(t.year, t.month, d).isoformat()
        elif len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            d, m = int(parts[0]), int(parts[1])
            return date(t.year, m, d).isoformat()
        elif len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 2500:  # เผื่อกรอกปี ค.ศ.
                return date(y, m, d).isoformat()
            else:  # เผื่อกรอกปี พ.ศ.
                return date(y - 543, m, d).isoformat()
    except Exception as e:
        print(f"❌ Parse Date Error: {e}")
    return None

def send_reply(reply_token, messages):
    if not isinstance(messages, list):
        messages = [messages]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": messages
    }
    res = requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)
    print(f"DEBUG Reply Status: {res.status_code}, Body: {res.text}")

def find_matching_skus(term):
    t = term.lower().strip()
    if t in AMBIGUOUS_GROUPS:
        return AMBIGUOUS_GROUPS[t]
    if t in ALIAS_MAP:
        return [ALIAS_MAP[t]]
    matched = set()
    for alias, code in ALIAS_MAP.items():
        if len(t) >= 2 and (t in alias or alias in t):
            matched.add(code)
    for code, name in PRODUCTS_DB.items():
        if len(t) >= 2 and t in name.lower():
            matched.add(code)
    return list(matched)

def split_product_qty(token):
    token_clean = token.lower().strip()
    if find_matching_skus(token_clean):
        return token_clean, None
    m = re.match(r"^([a-zA-Zก-๙\-]+?)(-?\d+)$", token_clean)
    if m and find_matching_skus(m.group(1)):
        return m.group(1), int(m.group(2))
    return token_clean, None

def parse_order_lines(raw_text):
    lines = [line.strip() for line in raw_text.strip().splitlines() if line.strip()]
    if not lines:
        return [], [], ["ไม่พบข้อความคำสั่ง"]

    global_date = today().isoformat()
    start_idx = 0

    if lines[0].isdigit():
        global_date = resolve_date(int(lines[0]))
        start_idx = 1

    parsed_orders = []
    ambiguous_requests = []
    errors = []

    for line in lines[start_idx:]:
        tokens = line.split()
        if not tokens:
            continue

        line_date = global_date
        idx = 0

        if tokens[0].isdigit():
            line_date = resolve_date(int(tokens[0]))
            idx = 1

        if idx >= len(tokens):
            continue

        shop_tokens = []
        while idx < len(tokens):
            p_name, _ = split_product_qty(tokens[idx])
            if find_matching_skus(p_name):
                break
            shop_tokens.append(tokens[idx])
            idx += 1

        if not shop_tokens:
            errors.append(f"❌ ไม่พบชื่อร้านในบรรทัด: '{line}'")
            continue

        shop_name = "".join(shop_tokens) if len(shop_tokens) == 1 else " ".join(shop_tokens)

        if idx >= len(tokens):
            errors.append(f"❌ ร้าน '{shop_name}' ยังไม่ได้ระบุรายการสินค้า")
            continue

        items = {}
        while idx < len(tokens):
            raw_tok = tokens[idx]
            p_name, attached_qty = split_product_qty(raw_tok)
            matched_codes = find_matching_skus(p_name)

            if not matched_codes:
                errors.append(f"❌ ไม่รู้จักสินค้า '{raw_tok}' (ร้าน {shop_name})")
                idx += 1
                continue

            if attached_qty is not None:
                qty = attached_qty
                idx += 1
            elif idx + 1 < len(tokens) and re.match(r"^-?\d+$", tokens[idx + 1]):
                qty = int(tokens[idx + 1])
                idx += 2
            else:
                qty = 1
                idx += 1

            if len(matched_codes) == 1:
                code = matched_codes[0]
                items[code] = items.get(code, 0) + qty
            else:
                ambiguous_requests.append({
                    "ddate": line_date,
                    "shop_name": shop_name,
                    "keyword": p_name,
                    "qty": qty,
                    "candidates": matched_codes
                })

        if items:
            parsed_orders.append({
                "ddate": line_date,
                "shop_name": shop_name,
                "items": items
            })

    return parsed_orders, ambiguous_requests, errors

def build_disambiguation_flex(ambiguous_list):
    bubbles = []
    for req in ambiguous_list[:10]:
        shop_obj = get_or_create_shop(req["shop_name"])
        shop_id = shop_obj["id"] if shop_obj else ""
        shop_display = shop_obj["name"] if shop_obj else req["shop_name"]
        ddate = req["ddate"]
        qty = req["qty"]
        keyword = req["keyword"]

        buttons = []
        for code in req["candidates"]:
            p_name = PRODUCTS_DB.get(code, code)
            buttons.append({
                "type": "button",
                "style": "primary",
                "height": "sm",
                "color": "#06C755",
                "margin": "sm",
                "action": {
                    "type": "postback",
                    "label": f"{p_name} ({qty})",
                    "data": f"action=pick_sku&sid={shop_id}&date={ddate}&code={code}&qty={qty}"
                }
            })

        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#FF9900",
                "contents": [
                    {"type": "text", "text": "🤔 เลือก SKU สินค้า", "weight": "bold", "size": "sm", "color": "#ffffff"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"{shop_display} ({dmy(ddate)})", "weight": "bold", "size": "md", "color": "#111111"},
                    {"type": "text", "text": f"คำว่า \"{keyword}\" จำนวน {qty} ตรงกับหลายรายการ กรุณาเลือก:", "size": "xs", "color": "#555555", "wrap": True, "margin": "xs"},
                    {"type": "box", "layout": "vertical", "margin": "md", "contents": buttons}
                ]
            }
        })

    return {
        "type": "flex",
        "altText": "กรุณาเลือก SKU สินค้าที่ต้องการ",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }

def upsert_order_items(shop_id, resolved_dt, items_dict):
    _, current_orders = fetch_fresh_data()
    existing = next((o for o in current_orders if str(o["shop_id"]) == str(shop_id) and o.get("ddate") == resolved_dt), None)

    if existing:
        oid = existing["id"]
        update_payload = {}
        for code, add_qty in items_dict.items():
            curr_q = num(existing.get(code, 0))
            new_q = max(0, curr_q + add_qty)
            update_payload[code] = new_q
        supabase.table("orders").update(update_payload).eq("id", oid).execute()
    else:
        insert_payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": "credit"}
        for code, qty in items_dict.items():
            if qty > 0:
                insert_payload[code] = qty
        if len(insert_payload) > 3:
            supabase.table("orders").insert(insert_payload).execute()

def build_summary_carousel(target_date=None):
    try:
        shops, orders = fetch_fresh_data(target_date)
        if not orders:
            msg = f"📭 ยังไม่มีข้อมูลออเดอร์ของวันที่ {dmy(target_date)}" if target_date else "📭 ยังไม่มีข้อมูลออเดอร์ในระบบ"
            return {"type": "text", "text": msg}

        grouped_by_date = {}
        for o in orders:
            dt = o.get("ddate", "ไม่ระบุ")
            if dt not in grouped_by_date:
                grouped_by_date[dt] = []
            grouped_by_date[dt].append(o)

        bubbles = []
        for date_str, date_orders in sorted(grouped_by_date.items()):
            shop_contents = []
            date_totals = {code: 0 for code in CODES}

            for idx, o in enumerate(date_orders):
                sh = shop_by_id(o["shop_id"], shops)
                shop_name = sh["name"] if sh else "ร้านค้า"
                order_id = o.get("id")
                status_key = o.get("status", "credit")
                icon, label, color = STATUSES.get(status_key, ("💳", "ซื้อเงินเชื่อ / เครดิต", "#0099FF"))

                item_rows = []
                for code in CODES:
                    q = num(o.get(code, 0))
                    if q > 0:
                        date_totals[code] += q
                        p_name = PRODUCTS_DB.get(code, code)
                        item_rows.append({
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": f"• {p_name}", "size": "sm", "color": "#333333", "flex": 4},
                                {"type": "text", "text": str(q), "size": "sm", "align": "end", "weight": "bold", "flex": 1}
                            ]
                        })
                if not item_rows:
                    item_rows.append({"type": "text", "text": "ไม่มีสินค้า", "size": "sm", "color": "#888888"})

                if idx > 0:
                    shop_contents.append({"type": "separator", "margin": "lg"})

                shop_contents.extend([
                    {"type": "text", "text": shop_name, "weight": "bold", "size": "md", "color": "#111111", "margin": "md"},
                    {"type": "text", "text": f"{icon} {label}", "size": "xs", "weight": "bold", "color": color, "margin": "xs"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": item_rows},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "Order ✅",
                                    "data": f"action=status&id={order_id}&status=ordered"
                                }
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "สลิป 👍",
                                    "data": f"action=status&id={order_id}&status=slip"
                                }
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "เครดิต 💳",
                                    "data": f"action=status&id={order_id}&status=credit"
                                }
                            }
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "xs",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "Overdue 🚨",
                                    "data": f"action=status&id={order_id}&status=overdue"
                                }
                            },
                            {
                                "type": "button",
                                "style": "secondary",
                                "height": "sm",
                                "action": {
                                    "type": "postback",
                                    "label": "วงเงินเต็ม ⚠️",
                                    "data": f"action=status&id={order_id}&status=insufficient_credit"
                                }
                            }
                        ]
                    }
                ])

            total_rows = []
            for code, total_qty in date_totals.items():
                if total_qty > 0:
                    p_name = PRODUCTS_DB.get(code, code)
                    total_rows.append({
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"• {p_name}", "size": "sm", "color": "#ffffff", "flex": 4},
                            {"type": "text", "text": str(total_qty), "size": "sm", "align": "end", "weight": "bold", "color": "#ffffff", "flex": 1}
                        ]
                    })

            if total_rows:
                shop_contents.append({"type": "separator", "margin": "xxl"})
                shop_contents.append({
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "paddingAll": "md",
                    "backgroundColor": "#222222",
                    "cornerRadius": "md",
                    "contents": [
                        {"type": "text", "text": "📊 รวมยอดสินค้าทั้งหมดของวันนี้", "weight": "bold", "size": "sm", "color": "#06C755", "margin": "xs"},
                        {"type": "separator", "margin": "sm"},
                        {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "sm", "contents": total_rows}
                    ]
                })

            bubbles.append({
                "type": "bubble",
                "size": "kilo",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": f"📅 สรุปยอดวันที่ {dmy(date_str)}", "weight": "bold", "size": "sm", "color": "#ffffff"},
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#1DB446",
                                    "action": {
                                        "type": "postback",
                                        "label": "ออเดอร์แล้วทั้งหมด ✅",
                                        "data": f"action=bulk_status&date={date_str}&status=ordered"
                                    }
                                },
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#00B900",
                                    "action": {
                                        "type": "postback",
                                        "label": "อัปสลิปแล้วทั้งหมด 👍",
                                        "data": f"action=bulk_status&date={date_str}&status=slip"
                                    }
                                }
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "height": "sm",
                                    "color": "#FF334B",
                                    "action": {
                                        "type": "postback",
                                        "label": "ยกเลิกทั้งหมด ❌",
                                        "data": f"action=bulk_cancel&date={date_str}"
                                    }
                                }
                            ]
                        }
                    ],
                    "backgroundColor": "#06C755"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": shop_contents
                }
            })

        return {
            "type": "flex",
            "altText": "สรุปรายการออเดอร์รายวัน",
            "contents": {
                "type": "carousel",
                "contents": bubbles[:10]
            }
        }
    except Exception as e:
        print(f"❌ Build Carousel Error: {e}")
        return {"type": "text", "text": f"❌ เกิดข้อผิดพลาดในการสร้างการ์ดสรุป: {str(e)}"}

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    if SECRET:
        h = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        if base64.b64encode(h).decode("utf-8") != signature:
            abort(400)

    try:
        events = json.loads(body).get("events", [])
        for event in events:
            if event.get("type") == "message":
                handle_message(event)
            elif event.get("type") == "postback":
                handle_postback(event)
    except Exception as e:
        print(f"❌ Callback Error: {e}")

    return "OK", 200

def handle_postback(event):
    reply_token = event["replyToken"]
    data = event.get("postback", {}).get("data", "")
    
    params = dict(item.split("=") for item in data.split("&") if "=" in item)
    action = params.get("action")
    
    try:
        if action == "pick_sku":
            shop_id = params.get("sid")
            target_date = params.get("date")
            code = params.get("code")
            qty = num(params.get("qty"))
            if shop_id and target_date and code:
                upsert_order_items(shop_id, target_date, {code: qty})

        elif action == "status":
            order_id = params.get("id")
            new_status = params.get("status")
            supabase.table("orders").update({"status": new_status}).eq("id", order_id).execute()
            
        elif action == "bulk_status":
            target_date = params.get("date")
            new_status = params.get("status")
            supabase.table("orders").update({"status": new_status}).eq("ddate", target_date).execute()
            
        elif action == "bulk_cancel":
            target_date = params.get("date")
            supabase.table("orders").delete().eq("ddate", target_date).execute()
            
    except Exception as e:
        print(f"❌ Postback Action Error: {e}")
        send_reply(reply_token, {"type": "text", "text": f"❌ เกิดข้อผิดพลาดในการจัดการระบบ: {e}"})
        return

    res_obj = build_summary_carousel()
    send_reply(reply_token, res_obj)

def handle_message(event):
    msg = event["message"]
    if msg.get("type") != "text":
        return
    text = msg.get("text", "").strip()
    reply_token = event["replyToken"]

    text_lower = text.lower()

    # ตรวจสอบคำสั่งเรียกสรุปเฉพาะวัน เช่น "สรุป 18" หรือ "สรุป 18/11"
    if text_lower.startswith("สรุป") or text_lower.startswith("ยอด") or text_lower == "list":
        parts = text.split()
        if len(parts) >= 2:
            date_arg = parts[1]
            iso_date = parse_target_date(date_arg)
            if iso_date:
                res_obj = build_summary_carousel(iso_date)
                send_reply(reply_token, res_obj)
                return
            else:
                send_reply(reply_token, {"type": "text", "text": f"❌ รูปแบบวันที่ไม่ถูกต้อง: '{date_arg}' (ตัวอย่าง: สรุป 18 หรือ สรุป 18/11)"})
                return
        else:
            res_obj = build_summary_carousel()
            send_reply(reply_token, res_obj)
            return

    if text_lower in ["คู่มือ", "ช่วยเหลือ", "help"]:
        help_text = (
            "📖 วิธีการใช้งานบอทสั่งของ:\n\n"
            "1️⃣ สั่งออเดอร์:\n"
            "• เจ๊โน แบน 2\n"
            "• 18 เจ๊โน โซจู 2 (ระบุวันได้)\n\n"
            "2️⃣ เรียกดูสรุปยอด:\n"
            "• พิมพ์ 'สรุป' (ดูทั้งหมด)\n"
            "• พิมพ์ 'สรุป 18' (ดูเฉพาะวันที่ 18 เดือนนี้)\n"
            "• พิมพ์ 'สรุป 18/11' (ดูเฉพาะวันที่ 18 พ.ย.)\n\n"
            "📌 พิมพ์ 'ดูรหัส' ดูชื่อย่อสินค้า"
        )
        send_reply(reply_token, {"type": "text", "text": help_text})
        return

    if text == "ดูรหัส":
        product_list = "\n".join([f"- {k}: {v}" for k, v in PRODUCTS_DB.items()])
        send_reply(reply_token, {"type": "text", "text": f"📋 รหัส/คำย่อสินค้า:\n{product_list}"})
        return

    parsed_orders, ambiguous_requests, errors = parse_order_lines(text)

    if not parsed_orders and not ambiguous_requests:
        err_msg = "\n".join(errors) if errors else "💡 ไม่เข้าใจคำสั่ง พิมพ์ 'คู่มือ' เพื่อดูวิธีสั่งซื้อครับ"
        send_reply(reply_token, {"type": "text", "text": err_msg})
        return

    for order_data in parsed_orders:
        shop = get_or_create_shop(order_data["shop_name"])
        if not shop:
            errors.append(f"❌ ไม่สามารถสร้างหรือหาร้าน '{order_data['shop_name']}' ได้")
            continue
        try:
            upsert_order_items(shop["id"], order_data["ddate"], order_data["items"])
        except Exception as db_err:
            print(f"❌ DB Error: {db_err}")
            errors.append(f"❌ บันทึกร้าน '{order_data['shop_name']}' ไม่สำเร็จ: {db_err}")

    messages = []
    if errors:
        messages.append({"type": "text", "text": "⚠️ แจ้งเตือนบางรายการ:\n" + "\n".join(errors)})

    if ambiguous_requests:
        messages.append(build_disambiguation_flex(ambiguous_requests))
    else:
        messages.append(build_summary_carousel())

    send_reply(reply_token, messages)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
