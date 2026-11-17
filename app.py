import base64
import hashlib
import hmac
import json
import os
import re
import threading
import traceback
from datetime import date, datetime
from difflib import get_close_matches
from zoneinfo import ZoneInfo

import requests
from flask import Flask, abort, request
from supabase import create_client, Client

SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TZ = ZoneInfo("Asia/Bangkok")

# ฐานข้อมูลรหัสและชื่อทางการ (ใช้ตัวพิมพ์เล็กทั้งหมดเป็นหลัก)
PRODUCTS_DB = {
    # Beer
    "l": "Lager", "r": "Rose", "d": "Dunkel",
    # Amenity
    "m": "MUG", "p": "PINE", "j": "JUG", "t": "TOWER",
    # อุปกรณ์
    "h40l": "Hoshizaki 40L", "h90": "Hoshizaki 90L", "h120": "Hoshizaki 120L",
    "sct": "Stanless Counter", "st": "Stanless Table",
    # POSM
    "ast": "A-Stand", "std": "Standee", "aa5": "อะคริลิก A5", "aa6": "อะคริลิก A6",
    # Other Alcohol
    "galf": "Galaxy แบน 350ml", "galr": "Galaxy กลม 700ml",
    "tend3": "Tendo 360ml", "tend7": "Tendo 700ml",
    "kach": "Kacha 375ml", "sojy": "Soju โยเกิร์ต", "sojp": "Soju พีช",
    "sojg": "Soju องุ่น", "sojf": "Soju เกรปฟรุ๊ต", "sojs": "Soju สตรอเบอรี่"
}

# คำค้นหาที่พบบ่อยและชื่อเล่น (Alias Map)
ALIAS_MAP = {
    "lager": "l", "larner": "l",
    "rose": "r",
    "dunkel": "d",
    "mug": "m", "pine": "p", "jug": "j", "tower": "t",
    "h40": "h40l", "h40lo": "h40l", "ceili": "h40l",
    "counter": "sct", "table": "st",
    "astand": "ast", "standee": "std",
    "galaxyแบน": "galf", "galf": "galf",
    "galaxyกลม": "galr", "galr": "galr", "galaxy": "galr", "กาแล็กซี": "galr", "กาแลaxy": "galr",
    "tendo360": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "tend7": "tend7",
    "kacha": "kach", "kach": "kach",
    "soju": "sojy"
}

CODES = list(PRODUCTS_DB.keys())
VALID_SEARCH_KWORDS = list(PRODUCTS_DB.values()) + list(ALIAS_MAP.keys())

STATUS_MAP = {
    "order": "ordered", "ordered": "ordered",
    "slipt": "slip", "slip": "slip",
    "credit": "credit",
    "over": "overdue", "overdue": "overdue",
    "limit": "limit", "short": "limit",
    "pending": "pending"
}

STATUSES = {
    "pending": ("⏳", "ยังไม่ได้ Order", "#FF9900"),
    "ordered": ("✅", "Order แล้ว", "#06C755"),
    "slip": ("👍", "อัปสลิปแล้ว", "#00B900"),
    "credit": ("💳", "Credit", "#0088CC"),
    "overdue": ("⚠️", "Overdue", "#FF334B"),
    "limit": ("❗", "วงเงินไม่พอ", "#FF334B"),
}

app = Flask(__name__)
LOCK = threading.Lock()
DATA = {"shops": [], "orders": [], "pending": []}


def num(v):
    try: return int(v)
    except: return 0


def load():
    global DATA
    try:
        shops_res = supabase.table("shops").select("*").execute()
        orders_res = supabase.table("orders").select("*").execute()
        pending_res = supabase.table("pending").select("*").execute()

        DATA["shops"] = shops_res.data or []
        DATA["orders"] = [{k: num(r[k]) if k in CODES else r[k] for k in r} for r in (orders_res.data or [])]
        DATA["pending"] = [{k: num(r[k]) if k in CODES else r[k] for k in r} for r in (pending_res.data or [])]
    except Exception as e:
        print(f"❌ Load Error: {e}")


INT_COLS = {"id", "shop_id", *CODES}


def add(tab, d):
    payload = {k: v for k, v in d.items() if k != "_row"}
    if "id" in payload: payload.pop("id")
    res = supabase.table(tab).insert(payload).execute()
    if res.data:
        inserted = {k: num(res.data[0][k]) if k in CODES else res.data[0][k] for k in res.data[0]}
        DATA[tab].append(inserted)
        return inserted
    return d


def update_db(tab, oid, payload):
    supabase.table(tab).update(payload).eq("id", oid).execute()
    for item in DATA[tab]:
        if item.get("id") == oid: item.update(payload)


def delete_db(tab, oid):
    supabase.table(tab).delete().eq("id", oid).execute()
    DATA[tab] = [item for item in DATA[tab] if item.get("id") != oid]


def shop_by_id(sid):
    return next((s for s in DATA["shops"] if s["id"] == sid), None)


def dmy(iso):
    try:
        y, m, d = iso.split("-")
        return f"{int(d):02d}/{int(m):02d}/{y}"
    except: return iso


def resolve_date(day_val, month_val=None, year_val=None):
    t = today()
    try:
        if year_val:
            if year_val < 100: year_val += 2000
            if month_val: return date(year_val, month_val, day_val).isoformat()
            return date(t.year, month_val or t.month, day_val).isoformat()
        if month_val:
            d = date(t.year, month_val, day_val)
            return d.isoformat() if d >= t else date(t.year + 1, month_val, day_val).isoformat()
        return date(t.year, t.month, day_val).isoformat()
    except: return None


def get_or_create_shop(name):
    dn = name.strip()
    if not dn.startswith("ร้าน"): dn = "ร้าน " + dn
    s = next((s for s in DATA["shops"] if s["name"] == dn), None)
    if s: return s["id"]
    new_shop = add("shops", {"name": dn, "aliases": ""})
    return new_shop["id"]


def today(): return datetime.now(TZ).date()


def match_product_token(token):
    clean_token = token.lower()
    m = re.match(r"^([a-zเ-์]+)(\d+)$", clean_token)
    if m:
        name_part = m.group(1)
        qty = int(m.group(2))
        
        # 1. เช็คจาก Alias หรือ Code ตรงๆ ก่อน
        code = ALIAS_MAP.get(name_part)
        if not code and name_part in PRODUCTS_DB:
            code = name_part
            
        if code in CODES:
            return ("exact", code, qty, None)
            
        # 2. ถ้าไม่ตรงเป๊ะ ให้หาคำใกล้เคียง หรือคำที่กำกวม (เช่น "galaxy" ที่ตรงกับทั้ง galf และ galr)
        matching_codes = []
        for c, full_name in PRODUCTS_DB.items():
            if name_part in full_name.lower() or name_part in c:
                matching_codes.append(c)
        
        if len(matching_codes) == 1:
            return ("exact", matching_codes[0], qty, None)
        elif len(matching_codes) > 1:
            # เจอหลายตัวเลือกที่มีความหมายคลุมเครือ ส่งกลับไปให้ผู้ใช้เลือก
            return ("ambiguous", matching_codes, qty, name_part)
            
        # 3. ลองใช้ get_close_matches เผื่อสะกดผิด
        matches = get_close_matches(name_part, VALID_SEARCH_KWORDS, n=1, cutoff=0.6)
        if matches:
            matched_str = matches[0]
            matched_code = ALIAS_MAP.get(matched_str, [k for k,v in PRODUCTS_DB.items() if v.lower() == matched_str][0] if matched_str in [v.lower() for v in PRODUCTS_DB.values()] else None)
            if matched_code:
                return ("exact", matched_code, qty, None)
                
    return ("none", None, 0, None)


def flex_daily_summary(target_date_str, orders_list, suggestion_msg=None, parsed_info_msg=None):
    order_blocks = []
    
    for ord_rec in orders_list:
        sh = shop_by_id(ord_rec["shop_id"])
        sh_name = sh["name"] if sh else "ร้านค้า"
        status_key = ord_rec.get("status", "pending")
        icon, status_label, status_color = STATUSES.get(status_key, ("⏳", "ยังไม่ได้ Order", "#FF9900"))
        order_id = ord_rec.get("id")
        
        item_rows = []
        for code in CODES:
            qty = ord_rec.get(code, 0)
            if qty > 0:
                p_name = PRODUCTS_DB.get(code, code)
                item_rows.append({
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"• {p_name}", "size": "sm", "color": "#333333", "flex": 4},
                        {"type": "text", "text": str(qty), "size": "sm", "align": "end", "weight": "bold", "color": "#111111", "flex": 1}
                    ]
                })
        if not item_rows:
            item_rows.append({"type": "text", "text": "ไม่มีรายการสินค้า", "size": "sm", "color": "#888888"})

        block = {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "margin": "md",
            "contents": [
                {"type": "separator", "color": "#E0E0E0", "margin": "md"},
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": sh_name, "weight": "bold", "size": "md", "color": "#111111", "flex": 3},
                        {
                            "type": "text",
                            "text": f"{icon} {status_label}",
                            "size": "xs",
                            "weight": "bold",
                            "color": status_color,
                            "align": "end",
                            "flex": 2
                        }
                    ]
                },
                {"type": "box", "layout": "vertical", "spacing": "2px", "contents": item_rows},
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "margin": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "xs",
                            "contents": [
                                {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "⏳ Pending", "data": f"status|pending|{order_id}"}},
                                {"type": "button", "style": "primary", "color": "#06C755", "height": "sm", "action": {"type": "postback", "label": "✅ Order", "data": f"status|ordered|{order_id}"}},
                                {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "👍 Slip", "data": f"status|slip|{order_id}"}}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "xs",
                            "contents": [
                                {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "💳 Credit", "data": f"status|credit|{order_id}"}},
                                {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "postback", "label": "⚠️ Overdue", "data": f"status|overdue|{order_id}"}},
                                {"type": "button", "style": "secondary", "color": "#FF334B", "height": "sm", "action": {"type": "postback", "label": "❗ วงเงินไม่พอ", "data": f"status|limit|{order_id}"}}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "xs",
                            "contents": [
                                {"type": "button", "style": "secondary", "color": "#DD3333", "height": "sm", "action": {"type": "postback", "label": "🗑️ ลบออเดอร์", "data": f"delete|{order_id}"}}
                            ]
                        }
                    ]
                }
            ]
        }
        order_blocks.append(block)

    body_contents = []
    
    if parsed_info_msg:
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "paddingAll": "md",
            "backgroundColor": "#E8F5E9",
            "contents": [
                {"type": "text", "text": "📦 รายการที่อัปเดต/บันทึก:", "size": "xs", "color": "#2E7D32", "weight": "bold"},
                {"type": "text", "text": parsed_info_msg, "size": "sm", "color": "#333333", "wrap": True}
            ]
        })

    if suggestion_msg:
        body_contents.append({
            "type": "box",
            "layout": "vertical",
            "paddingAll": "md",
            "backgroundColor": "#FFF8E1",
            "contents": [
                {"type": "text", "text": "💡 ระบบช่วยเดาคำสั่งซื้อ:", "size": "xs", "color": "#F57C00", "weight": "bold"},
                {"type": "text", "text": suggestion_msg, "size": "sm", "color": "#333333", "wrap": True}
            ]
        })

    body_contents.extend(order_blocks)

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🍻 สรุปรายการจัดส่งประจำวัน", "weight": "bold", "color": "#1DB446", "size": "sm"},
                {"type": "text", "text": f"วันที่ {dmy(target_date_str)}", "weight": "bold", "size": "xl", "margin": "sm", "color": "#111111"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents
        }
    }

    return {"type": "flex", "altText": f"สรุปออเดอร์วันที่ {dmy(target_date_str)}", "contents": bubble}


def flex_selection_menu(target_date_str, shop_id, qty, matching_codes, orig_query):
    shop = shop_by_id(shop_id)
    shop_name = shop["name"] if shop else "ร้านค้า"
    
    buttons = []
    for c in matching_codes:
        p_name = PRODUCTS_DB.get(c, c)
        buttons.append({
            "type": "button",
            "style": "primary",
            "color": "#1DB446",
            "height": "sm",
            "action": {
                "type": "postback",
                "label": f"เลือก: {p_name} ({qty})",
                "data": f"select|{target_date_str}|{shop_id}|{c}|{qty}"
            }
        })

    bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🔍 พบสินค้าใกล้เคียงหลายรายการ", "weight": "bold", "color": "#FF9900", "size": "sm"},
                {"type": "text", "text": f"คุณพิมพ์คำว่า '{orig_query}{qty}' สำหรับ {shop_name}", "size": "xs", "color": "#555555", "margin": "sm", "wrap": True},
                {"type": "text", "text": "กรุณาเลือกประเภทสินค้าที่ต้องการครับ:", "size": "sm", "weight": "bold", "margin": "md", "wrap": True},
                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md", "contents": buttons}
            ]
        }
    }
    return {"type": "flex", "altText": "กรุณาเลือกรายการสินค้า", "contents": bubble}


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        if SECRET:
            h = hmac.new(SECRET.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).digest()
            if base64.b64encode(h).decode('utf-8') != signature: abort(400)
    except: abort(400)

    try:
        for event in json.loads(body).get("events", []):
            if event.get("type") == "message": handle_message(event)
            elif event.get("type") == "postback": handle_postback(event)
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
    return "OK", 200


def handle_message(event):
    msg_text = event["message"].get("text", "").strip()
    
    if any(k in msg_text.lower() for k in ["ขอรายการสินค้า", "รายการสินค้า", "รหัสสินค้า"]):
        product_list_str = "📋 รายการสินค้าและรหัสคีย์เวิร์ดทั้งหมด:\n\n"
        for code, name in PRODUCTS_DB.items():
            product_list_str += f"• [{code.upper()}] {name}\n"
        product_list_str += "\n💡 ตัวอย่างการสั่ง: 17 ร้าน ABC l2 r3 galaxy2"
        reply_text(event["replyToken"], product_list_str)
        return

    if msg_text.lower() == "ขอinput":
        reply_text(event["replyToken"], "พิมพ์: [วันที่] [ชื่อร้าน] [รายการสินค้าและจำนวน]\nเช่น: 17 ร้าน ABC Galaxy 2\n\nพิมพ์ 'ขอรายการสินค้า' เพื่อดูรหัสสินค้าทั้งหมด")
        return

    if msg_text.startswith("สรุป"):
        parts = msg_text.split()
        if len(parts) >= 2:
            date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2}))?$", parts[1])
            if date_match:
                resolved_dt = resolve_date(int(date_match.group(1)), int(date_match.group(2)) if date_match.group(2) else None)
                if resolved_dt:
                    matched = [o for o in DATA["orders"] if o.get("ddate") == resolved_dt]
                    if matched: reply_flex(event["replyToken"], flex_daily_summary(resolved_dt, matched))
                    else: reply_text(event["replyToken"], f"📅 ไม่พบออเดอร์วันที่ {dmy(resolved_dt)}")
                    return

    parts = msg_text.split()
    if len(parts) >= 3:
        date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2}))?$", parts[0])
        if date_match:
            resolved_dt = resolve_date(int(date_match.group(1)), int(date_match.group(2)) if date_match.group(2) else None)
            if resolved_dt:
                shop_name = parts[1]
                tokens = parts[2:]
                
                status_key = "pending"
                if tokens and tokens[-1].lower() in STATUS_MAP:
                    status_key = STATUS_MAP[tokens[-1].lower()]
                    tokens.pop()
                
                shop_id = get_or_create_shop(shop_name)
                order_items = {}
                parsed_details = []
                
                for token in tokens:
                    m_type, code_or_list, qty, orig_query = match_product_token(token)
                    if m_type == "exact":
                        order_items[code_or_list] = order_items.get(code_or_list, 0) + qty
                        prod_full_name = PRODUCTS_DB.get(code_or_list, code_or_list)
                        parsed_details.append(f"• {prod_full_name} ({code_or_list.upper()}): +{qty}")
                    elif m_type == "ambiguous":
                        # พบคำกำกวม ส่งการ์ดตัวเลือกให้ผู้ใช้กดเลือก
                        reply_flex(event["replyToken"], flex_selection_menu(resolved_dt, shop_id, qty, code_or_list, orig_query))
                        return

                if order_items:
                    existing_order = next((o for o in DATA["orders"] if o["shop_id"] == shop_id and o.get("ddate") == resolved_dt), None)
                    
                    if existing_order:
                        oid = existing_order["id"]
                        update_payload = {}
                        for c in CODES:
                            current_qty = existing_order.get(c, 0)
                            added_qty = order_items.get(c, 0)
                            if added_qty > 0:
                                update_payload[c] = current_qty + added_qty
                        
                        if update_payload:
                            update_db("orders", oid, update_payload)
                    else:
                        payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": status_key, **order_items}
                        add("orders", payload)
                        
                    matched = [o for o in DATA["orders"] if o.get("ddate") == resolved_dt]
                    parsed_str = "\n".join(parsed_details) if parsed_details else ""
                    reply_flex(event["replyToken"], flex_daily_summary(resolved_dt, matched, parsed_info_msg=parsed_str))
                    return

    reply_text(event["replyToken"], "ไม่พบรูปแบบคำสั่งที่ถูกต้อง พิมพ์ 'ขอรายการสินค้า' เพื่อดูรหัสสินค้า หรือพิมพ์ 'ขอInput' เพื่อดูวิธีใช้งานครับ")


def handle_postback(event):
    parts = event["postback"]["data"].split("|")
    if parts[0] == "status" and len(parts) == 3:
        order_id = int(parts[2])
        update_db("orders", order_id, {"status": parts[1]})
        ord_rec = next((o for o in DATA["orders"] if o["id"] == order_id), None)
        if ord_rec:
            matched = [o for o in DATA["orders"] if o.get("ddate") == ord_rec["ddate"]]
            reply_flex(event["replyToken"], flex_daily_summary(ord_rec["ddate"], matched))
    elif parts[0] == "delete" and len(parts) == 2:
        order_id = int(parts[1])
        ord_rec = next((o for o in DATA["orders"] if o["id"] == order_id), None)
        dd = ord_rec["ddate"] if ord_rec else None
        delete_db("orders", order_id)
        if dd:
            matched = [o for o in DATA["orders"] if o.get("ddate") == dd]
            if matched:
                reply_flex(event["replyToken"], flex_daily_summary(dd, matched))
                return
            else:
                reply_text(event["replyToken"], f"🗑️ ลบออเดอร์เรียบร้อย (ไม่เหลือออเดอร์ในวันนี้แล้ว)")
                return
        reply_text(event["replyToken"], f"🗑️ ลบออเดอร์เรียบร้อย")
    elif parts[0] == "select" and len(parts) == 5:
        # กดเลือกจากปุ่มตัวเลือกสินค้ากำกวม
        resolved_dt = parts[1]
        shop_id = int(parts[2])
        code = parts[3]
        qty = int(parts[4])
        
        existing_order = next((o for o in DATA["orders"] if o["shop_id"] == shop_id and o.get("ddate") == resolved_dt), None)
        if existing_order:
            oid = existing_order["id"]
            current_qty = existing_order.get(code, 0)
            update_db("orders", oid, {code: current_qty + qty})
        else:
            payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": "pending", code: qty}
            add("orders", payload)
            
        matched = [o for o in DATA["orders"] if o.get("ddate") == resolved_dt]
        p_name = PRODUCTS_DB.get(code, code)
        parsed_str = f"• เลือก: {p_name} ({code.upper()}): +{qty}"
        reply_flex(event["replyToken"], flex_daily_summary(resolved_dt, matched, parsed_info_msg=parsed_str))


def reply_text(rt, text):
    requests.post("https://api.line.me/v2/bot/message/reply", headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, json={"replyToken": rt, "messages": [{"type": "text", "text": text}]})


def reply_flex(rt, flex):
    requests.post("https://api.line.me/v2/bot/message/reply", headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}, json={"replyToken": rt, "messages": [flex]})


if __name__ == "__main__":
    load()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
