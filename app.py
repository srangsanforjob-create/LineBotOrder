import base64
import hashlib
import hmac
import json
import os
import re
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

PRODUCTS_DB = {
    "l": "Lager", "r": "Rose", "d": "Dunkel",
    "m": "MUG", "p": "PINE", "j": "JUG", "t": "TOWER",
    "h40l": "Hoshizaki 40L", "h90": "Hoshizaki 90L", "h120": "Hoshizaki 120L",
    "sct": "Stanless Counter", "st": "Stanless Table",
    "ast": "A-Stand", "std": "Standee", "aa5": "อะคริลิก A5", "aa6": "อะคริลิก A6",
    "galf": "Galaxy แบน 350ml", "galr": "Galaxy กลม 700ml",
    "tend3": "Tendo 360ml", "tend7": "Tendo 700ml",
    "kach": "Kacha 375ml",
    "sojy": "Soju โยเกิร์ต", "sojp": "Soju พีช",
    "sojg": "Soju องุ่น", "sojf": "Soju เกรปฟรุ๊ต", "sojs": "Soju สตรอเบอรี่"
}

GROUP_KEYWORDS = {
    "galaxy": ["galf", "galr"], "กาแล็กซี": ["galf", "galr"], "กาแล็กซี่": ["galf", "galr"],
    "กาแลaxy": ["galf", "galr"], "glx": ["galf", "galr"], "glax": ["galf", "galr"],
    "soju": ["sojy", "sojp", "sojg", "sojf", "sojs"], "โซจู": ["sojy", "sojp", "sojg", "sojf", "sojs"],
    "tendo": ["tend3", "tend7"], "เท็นโด": ["tend3", "tend7"],
}

ALIAS_MAP = {
    "lager": "l", "larner": "l", "l": "l",
    "rose": "r", "r": "r",
    "dunkel": "d", "d": "d",
    "mug": "m", "m": "m",
    "pine": "p", "p": "p",
    "jug": "j", "j": "j",
    "tower": "t", "t": "t",
    "h40": "h40l", "h40l": "h40l", "h40lo": "h40l", "ceili": "h40l",
    "h90": "h90", "h90l": "h90",
    "h120": "h120", "h120l": "h120",
    "counter": "sct", "sct": "sct",
    "table": "st", "st": "st",
    "astand": "ast", "ast": "ast",
    "standee": "std", "std": "std",
    "aa5": "aa5", "aa6": "aa6",
    "galaxyแบน": "galf", "galaxy350": "galf", "galaxy350ml": "galf", "galaxyเล็ก": "galf",
    "glxแบน": "galf", "glaxแบน": "galf", "glx350": "galf", "glax350": "galf",
    "glxเล็ก": "galf", "glaxเล็ก": "galf",
    "กาแล็กซีแบน": "galf", "กาแล็กซี่แบน": "galf", "กาแลaxyแบน": "galf", "galf": "galf",
    "galaxyกลม": "galr", "galaxy700": "galr", "galaxy700ml": "galr", "galaxyใหญ่": "galr",
    "glxกลม": "galr", "glaxกลม": "galr", "glx700": "galr", "glax700": "galr",
    "glxใหญ่": "galr", "glaxใหญ่": "galr",
    "กาแล็กซีกลม": "galr", "กาแล็กซี่กลม": "galr", "กาแลaxyกลม": "galr", "galr": "galr",
    "tendo360": "tend3", "tendo360ml": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "tendo700ml": "tend7", "tend7": "tend7",
    "kacha": "kach", "kacha375": "kach", "kach": "kach",
    "sojuโยเกิร์ต": "sojy", "sojuพีช": "sojp", "sojuองุ่น": "sojg", "sojuเกรปฟรุ๊ต": "sojf", "sojuสตรอเบอรี่": "sojs",
    "โซจูโยเกิร์ต": "sojy", "โซจูพีช": "sojp", "โซจูองุ่น": "sojg", "โซจูเกรปฟรุ๊ต": "sojf", "โซจูสตรอเบอรี่": "sojs",
    "sojy": "sojy", "sojp": "sojp", "sojg": "sojg", "sojf": "sojf", "sojs": "sojs"
}

CODES = list(PRODUCTS_DB.keys())

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


def num(v):
    try:
        return int(v)
    except Exception:
        return 0


def fetch_fresh_data():
    try:
        shops_res = supabase.table("shops").select("*").execute()
        orders_res = supabase.table("orders").select("*").execute()
        pending_res = supabase.table("pending").select("*").execute()

        shops = shops_res.data or []
        orders = [{k: num(r[k]) if k in CODES else r[k] for k in r} for r in (orders_res.data or [])]
        pending = [{k: num(r[k]) if k in CODES else r[k] for k in r} for r in (pending_res.data or [])]
        return shops, orders, pending
    except Exception as e:
        print(f"❌ Fetch Error: {e}")
        return [], [], []


def add(tab, d):
    payload = {k: v for k, v in d.items() if k != "_row"}
    if "id" in payload:
        payload.pop("id")
    res = supabase.table(tab).insert(payload).execute()
    if res.data:
        inserted = {k: num(res.data[0][k]) if k in CODES else res.data[0][k] for k in res.data[0]}
        return inserted
    return d


def update_db(tab, oid, payload):
    supabase.table(tab).update(payload).eq("id", oid).execute()


def delete_db(tab, oid):
    supabase.table(tab).delete().eq("id", oid).execute()


def delete_orders_by_date(target_date_str):
    supabase.table("orders").delete().eq("ddate", target_date_str).execute()


def update_status_by_date(target_date_str, new_status):
    supabase.table("orders").update({"status": new_status}).eq("ddate", target_date_str).execute()


def get_order_by_id(oid):
    _, orders, _ = fetch_fresh_data()
    return next((o for o in orders if str(o.get("id")) == str(oid)), None)


def shop_by_id(sid):
    shops, _, _ = fetch_fresh_data()
    return next((s for s in shops if str(s.get("id")) == str(sid)), None)


def dmy(iso):
    try:
        y, m, d = iso.split("-")
        return f"{int(d):02d}/{int(m):02d}/{y}"
    except Exception:
        return iso


def today():
    return datetime.now(TZ).date()


def resolve_date(day_val, month_val=None, year_val=None):
    t = today()
    try:
        if year_val:
            if year_val < 100:
                year_val += 2000
            return date(year_val, month_val or t.month, day_val).isoformat()
        if month_val:
            d = date(t.year, month_val, day_val)
            return d.isoformat() if d >= t else date(t.year + 1, month_val, day_val).isoformat()
        return date(t.year, t.month, day_val).isoformat()
    except Exception:
        return None


def get_or_create_shop(name):
    shops, _, _ = fetch_fresh_data()
    dn = name.strip()
    if not dn.startswith("ร้าน"):
        dn = "ร้าน " + dn
    s = next((s for s in shops if s["name"] == dn), None)
    if s:
        return s["id"]
    new_shop = add("shops", {"name": dn, "aliases": ""})
    return new_shop.get("id")


def normalize_tokens(raw_tokens):
    merged = []
    i = 0
    size_words = {"แบน", "กลม", "เล็ก", "ใหญ่", "350", "350ml", "700", "700ml", "360", "360ml",
                  "โยเกิร์ต", "พีช", "องุ่น", "เกรปฟรุ๊ต", "สตรอเบอรี่"}
    while i < len(raw_tokens):
        curr = raw_tokens[i].strip()
        if curr.lower() in STATUS_MAP:
            merged.append(curr)
            i += 1
            continue

        while i + 1 < len(raw_tokens):
            nxt = raw_tokens[i + 1].strip()
            nxt_no_num = re.sub(r"\d+$", "", nxt).lower()
            if nxt_no_num in size_words:
                curr = f"{curr}{nxt}"
                i += 1
            else:
                break

        if (
            i + 1 < len(raw_tokens)
            and re.fullmatch(r"\d+", raw_tokens[i + 1].strip())
            and re.search(r"[a-zA-Zเ-์]", curr)
            and not re.search(r"\d+$", curr)
        ):
            merged.append(f"{curr}{raw_tokens[i + 1].strip()}")
            i += 2
        else:
            merged.append(curr)
            i += 1
    return merged


def match_product_token(token):
    clean_token = re.sub(r"\s+", "", token.lower().strip())

    if clean_token in ALIAS_MAP:
        return ("exact", ALIAS_MAP[clean_token], 1, token)

    m = re.match(r"^([a-zเ-์\-]+?(?:350ml|700ml|360ml|350|700|360|40l|90l|120l|40|90|120|a5|a6)?)(\d*)$", clean_token)
    if m and m.group(1):
        name_part = m.group(1)
        qty_part = m.group(2)
        qty = int(qty_part) if qty_part else 1
    else:
        m_fallback = re.match(r"^(.*?)(\d+)$", clean_token)
        if m_fallback and m_fallback.group(1):
            name_part = m_fallback.group(1)
            qty = int(m_fallback.group(2))
        else:
            name_part = clean_token
            qty = 1

    if qty <= 0:
        qty = 1

    if name_part in ALIAS_MAP:
        return ("exact", ALIAS_MAP[name_part], qty, name_part)

    if name_part in GROUP_KEYWORDS:
        return ("ambiguous", GROUP_KEYWORDS[name_part], qty, name_part)

    if any(k in name_part for k in ["galaxy", "glx", "glax", "กาแล"]):
        if any(k in name_part for k in ["แบน", "เล็ก", "350", "f"]):
            return ("exact", "galf", qty, name_part)
        if any(k in name_part for k in ["กลม", "ใหญ่", "700", "r"]):
            return ("exact", "galr", qty, name_part)
        return ("ambiguous", ["galf", "galr"], qty, name_part)

    all_keys = list(ALIAS_MAP.keys()) + list(GROUP_KEYWORDS.keys())
    matches = get_close_matches(name_part, all_keys, n=1, cutoff=0.45)
    if matches:
        matched_key = matches[0]
        if matched_key in GROUP_KEYWORDS:
            return ("ambiguous", GROUP_KEYWORDS[matched_key], qty, name_part)
        if matched_key in ALIAS_MAP:
            return ("exact", ALIAS_MAP[matched_key], qty, name_part)

    return ("ambiguous", ["galf", "galr"], qty, name_part)


def build_day_bubble(target_date_str, orders_list):
    order_blocks = []

    for ord_rec in orders_list:
        sh = shop_by_id(ord_rec["shop_id"])
        sh_name = sh["name"] if sh else "ร้านค้า"
        status_key = ord_rec.get("status", "pending")
        icon, status_label, status_color = STATUSES.get(status_key, ("⏳", "ยังไม่ได้ Order", "#FF9900"))
        order_id = ord_rec.get("id")

        item_rows = []
        for code in CODES:
            qty = num(ord_rec.get(code, 0))
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
                {"type": "separator", "color": "#E0E0E0", "margin": "md"},
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
                                {"type": "button", "style": "primary", "color": "#FF9900", "height": "sm", "action": {"type": "postback", "label": "⏳ Pending", "data": f"status|pending|{order_id}"}},
                                {"type": "button", "style": "primary", "color": "#06C755", "height": "sm", "action": {"type": "postback", "label": "✅ Order", "data": f"status|ordered|{order_id}"}},
                                {"type": "button", "style": "primary", "color": "#00B900", "height": "sm", "action": {"type": "postback", "label": "👍 Slip", "data": f"status|slip|{order_id}"}}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "xs",
                            "contents": [
                                {"type": "button", "style": "primary", "color": "#0088CC", "height": "sm", "action": {"type": "postback", "label": "💳 Credit", "data": f"status|credit|{order_id}"}},
                                {"type": "button", "style": "primary", "color": "#FF334B", "height": "sm", "action": {"type": "postback", "label": "⚠️ Overdue", "data": f"status|overdue|{order_id}"}},
                                {"type": "button", "style": "primary", "color": "#FF334B", "height": "sm", "action": {"type": "postback", "label": "❗ วงเงินไม่พอ", "data": f"status|limit|{order_id}"}}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "spacing": "xs",
                            "contents": [
                                {"type": "button", "style": "primary", "color": "#1399FF", "height": "sm", "action": {"type": "postback", "label": "✏️ แก้ไขรายการ", "data": f"edit_menu|{order_id}"}},
                                {"type": "button", "style": "primary", "color": "#DD3333", "height": "sm", "action": {"type": "postback", "label": "🗑️ ลบออเดอร์", "data": f"delete|{order_id}"}}
                            ]
                        }
                    ]
                }
            ]
        }
        order_blocks.append(block)

    day_action_box = {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "margin": "md",
        "contents": [
            {"type": "text", "text": "⚡ จัดการสถานะทั้งวัน", "size": "xs", "weight": "bold", "color": "#555555", "align": "center"},
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "xs",
                "contents": [
                    {"type": "button", "style": "primary", "color": "#06C755", "height": "sm", "action": {"type": "postback", "label": "✅ ออเดอร์ทั้งวัน", "data": f"day_status|ordered|{target_date_str}"}},
                    {"type": "button", "style": "primary", "color": "#00B900", "height": "sm", "action": {"type": "postback", "label": "👍 สลิปทั้งวัน", "data": f"day_status|slip|{target_date_str}"}}
                ]
            },
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "xs",
                "contents": [
                    {"type": "button", "style": "primary", "color": "#DD3333", "height": "sm", "action": {"type": "postback", "label": "🗑️ ลบออเดอร์ทั้งวัน", "data": f"day_delete_confirm|{target_date_str}"}}
                ]
            }
        ]
    }

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"วันที่ {dmy(target_date_str)}", "weight": "bold", "size": "xl", "color": "#111111"}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [day_action_box, {"type": "separator", "color": "#E0E0E0", "margin": "md"}, *order_blocks]
        }
    }


def flex_confirm_delete_day(target_date_str):
    return {
        "type": "flex",
        "altText": "ยืนยันการลบออเดอร์ทั้งหมดในวันนั้น",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "⚠️ ยืนยันการลบ", "weight": "bold", "color": "#FF334B", "size": "lg", "align": "center"},
                    {"type": "text", "text": f"คุณต้องการลบออเดอร์ *ทั้งหมด* ในวันที่ {dmy(target_date_str)} ใช่หรือไม่?", "size": "sm", "color": "#333333", "margin": "md", "wrap": True, "align": "center"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "margin": "lg",
                        "contents": [
                            {"type": "button", "style": "primary", "color": "#DD3333", "height": "sm", "action": {"type": "postback", "label": "🗑️ ยืนยันลบทั้งหมด", "data": f"day_delete_do|{target_date_str}"}},
                            {"type": "button", "style": "primary", "color": "#888888", "height": "sm", "action": {"type": "postback", "label": "❌ ยกเลิก", "data": "cancel"}}
                        ]
                    }
                ]
            }
        }
    }


def flex_carousel_summary(days_data):
    bubbles = []
    for d_str, o_list in days_data.items():
        if len(o_list) > 0:
            bubbles.append(build_day_bubble(d_str, o_list))

    if not bubbles:
        return {"type": "text", "text": "📭 ยังไม่มีข้อมูลออเดอร์ในระบบ"}
        
    # LINE Carousel รองรับสูงสุด 12 Bubbles ต่อ 1 Carousel
    flex_messages = []
    for i in range(0, len(bubbles), 10):
        chunk = bubbles[i:i+10]
        flex_messages.append({
            "type": "flex",
            "altText": f"สรุปรายการจัดส่งรายวัน (ส่วนที่ {i//10 + 1})",
            "contents": {
                "type": "carousel",
                "contents": chunk
            }
        })
    return flex_messages


def send_reply_response(rt, res_obj):
    messages = []
    if isinstance(res_obj, list):
        messages = res_obj[:5]
    elif isinstance(res_obj, dict) and "type" in res_obj:
        messages = [res_obj]
    else:
        messages = [{"type": "text", "text": str(res_obj)}]

    if not messages:
        return

    print(f"DEBUG [send_reply_response]: Sending {len(messages)} message(s) with token {rt[:10]}...")
    res = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        json={"replyToken": rt, "messages": messages}
    )
    print(f"DEBUG [send_reply_response]: Status code = {res.status_code}, Response = {res.text}")
    if res.status_code != 200:
        print(f"❌ LINE Reply Error ({res.status_code}): {res.text}")


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
                "label": f"{p_name} ({qty})",
                "data": f"select|{target_date_str}|{shop_id}|{c}|{qty}"
            }
        })

    return {
        "type": "flex",
        "altText": "กรุณาเลือกประเภทสินค้า",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "🔍 กรุณาเลือกประเภทสินค้า", "weight": "bold", "color": "#FF9900", "size": "md"},
                    {"type": "text", "text": f"คำสั่ง '{orig_query}' จำนวน {qty} • {shop_name}", "size": "xs", "color": "#555555", "margin": "sm", "wrap": True},
                    {"type": "separator", "color": "#E0E0E0", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md", "contents": buttons}
                ]
            }
        }
    }


def flex_edit_menu(order_id):
    ord_rec = get_order_by_id(order_id)
    if not ord_rec:
        return {
            "type": "flex",
            "altText": "ไม่พบข้อมูลออเดอร์",
            "contents": {
                "type": "bubble",
                "size": "kilo",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "⚠️ ไม่พบข้อมูลออเดอร์นี้", "weight": "bold", "color": "#FF334B", "size": "md"},
                        {"type": "text", "text": f"รหัสออเดอร์ #{order_id} อาจถูกลบไปแล้ว", "size": "xs", "color": "#666666", "margin": "sm", "wrap": True}
                    ]
                }
            }
        }

    sh = shop_by_id(ord_rec["shop_id"])
    sh_name = sh["name"] if sh else "ร้านค้า"

    item_sections = []
    for code in CODES:
        qty = num(ord_rec.get(code, 0))
        if qty > 0:
            p_name = PRODUCTS_DB.get(code, code)
            item_sections.append({
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": f"• {p_name} (จำนวน {qty})", "weight": "bold", "size": "sm", "color": "#111111"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "xs",
                        "contents": [
                            {
                                "type": "button", "style": "primary", "color": "#555555", "height": "sm",
                                "action": {"type": "postback", "label": "🔄 เปลี่ยนสินค้า", "data": f"edit_swap_menu|{order_id}|{code}|{qty}"}
                            },
                            {
                                "type": "button", "style": "primary", "color": "#555555", "height": "sm",
                                "action": {"type": "postback", "label": "🔢 ปรับจำนวน", "data": f"edit_qty_menu|{order_id}|{code}"}
                            }
                        ]
                    }
                ]
            })

    if not item_sections:
        item_sections.append({"type": "text", "text": "ไม่มีสินค้าในออเดอร์นี้", "size": "sm", "color": "#888888", "margin": "md"})

    item_sections.append({"type": "separator", "margin": "md"})
    item_sections.append({
        "type": "button", "style": "primary", "color": "#1399FF", "height": "sm", "margin": "md",
        "action": {"type": "postback", "label": "➕ เพิ่มสินค้าอื่นในออเดอร์", "data": f"edit_add_menu|{order_id}"}
    })

    return {
        "type": "flex",
        "altText": f"เมนูแก้ไข: {sh_name}",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"✏️ แก้ไข: {sh_name}", "weight": "bold", "color": "#1399FF", "size": "md"},
                    {"type": "text", "text": f"วันที่ {dmy(ord_rec.get('ddate', ''))} • #{order_id}", "size": "xs", "color": "#666666", "wrap": True},
                    {"type": "separator", "color": "#E0E0E0", "margin": "md"},
                    *item_sections
                ]
            }
        }
    }


def flex_swap_sku_menu(order_id, old_code, qty):
    old_name = PRODUCTS_DB.get(old_code, old_code)
    priority_codes = ["galf", "galr", "l", "r", "d", "tend3", "tend7", "kach", "sojy", "sojp", "sojg"]
    buttons = []
    for code in priority_codes:
        if code == old_code or code not in PRODUCTS_DB:
            continue
        p_name = PRODUCTS_DB[code]
        buttons.append({
            "type": "button", "style": "primary", "color": "#555555", "height": "sm",
            "action": {"type": "postback", "label": f"{p_name}", "data": f"edit_swap_do|{order_id}|{old_code}|{code}|{qty}"}
        })

    return {
        "type": "flex",
        "altText": "เลือกสินค้าใหม่แทนที่",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "🔄 เลือกสินค้าใหม่แทนที่", "weight": "bold", "color": "#1399FF", "size": "md"},
                    {"type": "text", "text": f"เปลี่ยนจาก: {old_name} ({qty})", "size": "xs", "color": "#555555", "margin": "xs", "wrap": True},
                    {"type": "separator", "color": "#E0E0E0", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": buttons[:10]}
                ]
            }
        }
    }


def flex_qty_menu(order_id, code):
    ord_rec = get_order_by_id(order_id)
    curr_qty = num(ord_rec.get(code, 0)) if ord_rec else 0
    p_name = PRODUCTS_DB.get(code, code)

    dec_qty = max(0, curr_qty - 1)
    inc_qty = curr_qty + 1

    preset_rows = [
        [
            {"label": f"➖ ลด (-1) → {dec_qty}", "val": dec_qty},
            {"label": f"➕ เพิ่ม (+1) → {inc_qty}", "val": inc_qty},
        ],
        [
            {"label": "ตั้งเป็น 1", "val": 1},
            {"label": "ตั้งเป็น 2", "val": 2},
            {"label": "ตั้งเป็น 3", "val": 3},
        ],
        [
            {"label": "ตั้งเป็น 4", "val": 4},
            {"label": "ตั้งเป็น 5", "val": 5},
            {"label": "ตั้งเป็น 10", "val": 10},
        ],
        [
            {"label": "ตั้งเป็น 20", "val": 20},
            {"label": "🗑️ ลบรายการนี้ (0)", "val": 0},
        ],
    ]

    rows_box = []
    for row in preset_rows:
        btns = []
        for item in row:
            btns.append({
                "type": "button", "style": "primary", "color": "#555555", "height": "sm",
                "action": {"type": "postback", "label": item["label"], "data": f"edit_qty_set|{order_id}|{code}|{item['val']}"}
            })
        rows_box.append({"type": "box", "layout": "horizontal", "spacing": "xs", "contents": btns})

    return {
        "type": "flex",
        "altText": f"ปรับจำนวน: {p_name}",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"🔢 ปรับจำนวน: {p_name}", "weight": "bold", "color": "#1399FF", "size": "md"},
                    {"type": "text", "text": f"จำนวนปัจจุบัน: {curr_qty}", "size": "xs", "color": "#555555", "margin": "xs", "wrap": True},
                    {"type": "separator", "color": "#E0E0E0", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": rows_box}
                ]
            }
        }
    }


def flex_add_item_menu(order_id):
    priority_codes = ["galf", "galr", "l", "r", "d", "tend3", "tend7", "kach", "sojy", "sojp"]
    buttons = []
    for code in priority_codes:
        if code not in PRODUCTS_DB:
            continue
        p_name = PRODUCTS_DB[code]
        buttons.append({
            "type": "button", "style": "primary", "color": "#555555", "height": "sm",
            "action": {"type": "postback", "label": f"+ {p_name} (1)", "data": f"edit_qty_set|{order_id}|{code}|1"}
        })

    return {
        "type": "flex",
        "altText": "เพิ่มสินค้าในออเดอร์",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "➕ เพิ่มสินค้าในออเดอร์", "weight": "bold", "color": "#1399FF", "size": "md"},
                    {"type": "text", "text": "เลือกสินค้า (เพิ่มทีละ 1 จากนั้นปรับจำนวนได้)", "size": "xs", "color": "#555555", "margin": "xs", "wrap": True},
                    {"type": "separator", "color": "#E0E0E0", "margin": "md"},
                    {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": buttons[:10]}
                ]
            }
        }
    }


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        if SECRET:
            h = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
            if base64.b64encode(h).decode("utf-8") != signature:
                abort(400)
    except Exception:
        abort(400)

    try:
        for event in json.loads(body).get("events", []):
            if event.get("type") == "message":
                handle_message(event)
            elif event.get("type") == "postback":
                handle_postback(event)
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
    return "OK", 200


def get_all_valid_days_data():
    _, orders, _ = fetch_fresh_data()
    all_dates = set(o.get("ddate") for o in orders if o.get("ddate"))
    sorted_dates = sorted(list(all_dates))
    return {sd: [o for o in orders if o.get("ddate") == sd] for sd in sorted_dates}


def get_specific_day_data(date_str):
    _, orders, _ = fetch_fresh_data()
    day_orders = [o for o in orders if o.get("ddate") == date_str]
    if day_orders:
        return {date_str: day_orders}
    return {}


def handle_message(event):
    if event["message"].get("type") != "text":
        return
    msg_text = event["message"].get("text", "").strip()
    clean_msg = re.sub(r"\s+", "", msg_text).lower()

    if clean_msg == "สรุป":
        all_data = get_all_valid_days_data()
        res_obj = flex_carousel_summary(all_data)
        send_reply_response(event["replyToken"], res_obj)
        return

    clean_sum_text = re.sub(r"^สรุป\s*", "", msg_text).strip()
    date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2})(?:/(\d{2,4}))?)?$", clean_sum_text)
    
    if date_match and len(msg_text.split()) <= 2 and not any(k in msg_text for k in ["ร้าน", "ออเดอร์", "กลม", "แบน", "l", "r", "d"]):
        d_val = int(date_match.group(1))
        m_val = int(date_match.group(2)) if date_match.group(2) else None
        y_val = int(date_match.group(3)) if date_match.group(3) else None
        
        resolved_dt = resolve_date(d_val, m_val, y_val)
        if resolved_dt:
            day_data = get_specific_day_data(resolved_dt)
            res_obj = flex_carousel_summary(day_data)
            send_reply_response(event["replyToken"], res_obj)
            return

    if any(k in clean_msg for k in ["ขอรายการสินค้า", "รายการสินค้า", "รหัสสินค้า"]):
        product_list_str = "📋 รายการสินค้าและรหัสคีย์เวิร์ดทั้งหมด:\n\n"
        for code, name in PRODUCTS_DB.items():
            product_list_str += f"• [{code.upper()}] {name}\n"
        product_list_str += "\n💡 ตัวอย่าง: 18 ข้าวใหม่ galaxyแบน 2"
        send_reply_response(event["replyToken"], {"type": "text", "text": product_list_str})
        return

    if clean_msg == "ขอinput":
        send_reply_response(event["replyToken"], {"type": "text", "text": "พิมพ์: [วันที่] [ชื่อร้าน] [สินค้า จำนวน]\nเช่น: 18 ข้าวใหม่ galaxyแบน 2"})
        return

    parts = msg_text.split()
    if len(parts) >= 2:
        date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2})(?:/(\d{2,4}))?)?$", parts[0])
        if date_match:
            d_val = int(date_match.group(1))
            m_val = int(date_match.group(2)) if date_match.group(2) else None
            y_val = int(date_match.group(3)) if date_match.group(3) else None
            
            resolved_dt = resolve_date(d_val, m_val, y_val)
            if resolved_dt:
                if parts[1] == "ร้าน" and len(parts) >= 4:
                    shop_name = f"ร้าน {parts[2]}"
                    raw_item_tokens = parts[3:]
                else:
                    shop_name = parts[1]
                    raw_item_tokens = parts[2:]

                tokens = normalize_tokens(raw_item_tokens)
                shop_id = get_or_create_shop(shop_name)

                status_key = "pending"
                if tokens and tokens[-1].lower() in STATUS_MAP:
                    status_key = STATUS_MAP[tokens[-1].lower()]
                    tokens.pop()

                order_items = {}
                for token in tokens:
                    m_type, code_or_list, qty, orig_query = match_product_token(token)
                    if m_type == "exact":
                        order_items[code_or_list] = order_items.get(code_or_list, 0) + qty
                    elif m_type == "ambiguous":
                        sel_flex = flex_selection_menu(resolved_dt, shop_id, qty, code_or_list, orig_query)
                        send_reply_response(event["replyToken"], sel_flex)
                        return

                if order_items:
                    _, current_orders, _ = fetch_fresh_data()
                    existing_order = next((o for o in current_orders if str(o["shop_id"]) == str(shop_id) and o.get("ddate") == resolved_dt), None)
                    if existing_order:
                        oid = existing_order["id"]
                        update_payload = {c: num(existing_order.get(c, 0)) + order_items.get(c, 0) for c in CODES if order_items.get(c, 0) > 0}
                        if update_payload:
                            update_db("orders", oid, update_payload)
                    else:
                        payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": status_key, **order_items}
                        add("orders", payload)

                    res_obj = flex_carousel_summary(get_all_valid_days_data())
                    send_reply_response(event["replyToken"], res_obj)
                    return

    send_reply_response(event["replyToken"], {"type": "text", "text": "ไม่พบรูปแบบคำสั่ง พิมพ์ 'สรุป', 'ขอรายการสินค้า' หรือ 'ขอInput' เพื่อดูวิธีใช้งานครับ"})


def handle_postback(event):
    data_str = event["postback"].get("data", "")
    print(f"DEBUG [handle_postback]: Received postback data: {data_str}")
    parts = data_str.split("|")
    action = parts[0]

    def reply_after_action():
        print(f"DEBUG [reply_after_action]: Generating summary after action '{action}'")
        res_obj = flex_carousel_summary(get_all_valid_days_data())
        send_reply_response(event["replyToken"], res_obj)

    if action == "status" and len(parts) == 3:
        order_id = int(parts[2])
        update_db("orders", order_id, {"status": parts[1]})
        reply_after_action()

    elif action == "day_status" and len(parts) == 3:
        new_status = parts[1]
        target_date_str = parts[2]
        update_status_by_date(target_date_str, new_status)
        reply_after_action()

    elif action == "day_delete_confirm" and len(parts) == 2:
        target_date_str = parts[1]
        confirm_flex = flex_confirm_delete_day(target_date_str)
        send_reply_response(event["replyToken"], confirm_flex)

    elif action == "day_delete_do" and len(parts) == 2:
        target_date_str = parts[1]
        delete_orders_by_date(target_date_str)
        reply_after_action()

    elif action == "cancel":
        reply_after_action()

    elif action == "delete" and len(parts) == 2:
        order_id = int(parts[1])
        delete_db("orders", order_id)
        reply_after_action()

    elif action == "edit_menu" and len(parts) == 2:
        order_id = int(parts[1])
        edit_flex = flex_edit_menu(order_id)
        send_reply_response(event["replyToken"], edit_flex)

    elif action == "edit_swap_menu" and len(parts) == 4:
        order_id = int(parts[1])
        old_code = parts[2]
        qty = int(parts[3])
        swap_flex = flex_swap_sku_menu(order_id, old_code, qty)
        send_reply_response(event["replyToken"], swap_flex)

    elif action == "edit_swap_do" and len(parts) == 5:
        order_id = int(parts[1])
        old_code = parts[2]
        new_code = parts[3]
        qty = int(parts[4])
        ord_rec = get_order_by_id(order_id)
        if ord_rec:
            existing_new_qty = num(ord_rec.get(new_code, 0))
            update_db("orders", order_id, {old_code: 0, new_code: existing_new_qty + qty})
        reply_after_action()

    elif action == "edit_qty_menu" and len(parts) == 3:
        order_id = int(parts[1])
        code = parts[2]
        qty_flex = flex_qty_menu(order_id, code)
        send_reply_response(event["replyToken"], qty_flex)

    elif action == "edit_qty_set" and len(parts) == 4:
        order_id = int(parts[1])
        code = parts[2]
        new_qty = int(parts[3])
        update_db("orders", order_id, {code: new_qty})
        reply_after_action()

    elif action == "edit_add_menu" and len(parts) == 2:
        order_id = int(parts[1])
        add_flex = flex_add_item_menu(order_id)
        send_reply_response(event["replyToken"], add_flex)

    elif action == "select" and len(parts) == 5:
        resolved_dt = parts[1]
        shop_id = int(parts[2])
        code = parts[3]
        qty = int(parts[4])
        print(f"DEBUG [select action]: date={resolved_dt}, shop_id={shop_id}, code={code}, qty={qty}")

        _, current_orders, _ = fetch_fresh_data()
        existing_order = next((o for o in current_orders if str(o["shop_id"]) == str(shop_id) and o.get("ddate") == resolved_dt), None)
        if existing_order:
            oid = existing_order["id"]
            current_qty = num(existing_order.get(code, 0))
            update_db("orders", oid, {code: current_qty + qty})
        else:
            payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": "pending", code: qty}
            add("orders", payload)

        reply_after_action()
    else:
        print(f"⚠️ Unhandled postback action: {action}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
