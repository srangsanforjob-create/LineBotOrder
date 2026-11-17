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
    "kach": "Kacha 375ml", 
    "sojy": "Soju โยเกิร์ต", "sojp": "Soju พีช",
    "sojg": "Soju องุ่น", "sojf": "Soju เกรปฟรุ๊ต", "sojs": "Soju สตรอเบอรี่"
}

GROUP_KEYWORDS = {
    "galaxy": ["galf", "galr"], "กาแล็กซี": ["galf", "galr"], "กาแลaxy": ["galf", "galr"],
    "soju": ["sojy", "sojp", "sojg", "sojf", "sojs"], "โซจู": ["sojy", "sojp", "sojg", "sojf", "sojs"],
    "tendo": ["tend3", "tend7"], "เท็นโด": ["tend3", "tend7"],
}

ALIAS_MAP = {
    "lager": "l", "larner": "l", "rose": "r", "dunkel": "d",
    "mug": "m", "pine": "p", "jug": "j", "tower": "t",
    "h40": "h40l", "h40lo": "h40l", "ceili": "h40l",
    "counter": "sct", "table": "st",
    "astand": "ast", "standee": "std",
    "galaxyแบน": "galf", "กาแล็กซีแบน": "galf", "galf": "galf",
    "galaxyกลม": "galr", "กาแล็กซีกลม": "galr", "galr": "galr",
    "tendo360": "tend3", "tend3": "tend3",
    "tendo700": "tend7", "tend7": "tend7",
    "kacha": "kach", "kach": "kach",
    "sojuโยเกิร์ต": "sojy", "sojuพีช": "sojp", "sojuองุ่น": "sojg", "sojuเกรปฟรุ๊ต": "sojf", "sojuสตรอเบอรี่": "sojs",
    "โซจูโยเกิร์ต": "sojy", "โซจูพีช": "sojp", "โซจูองุ่น": "sojg", "โซจูเกรปฟรุ๊ต": "sojf", "โซจูสตรอเบอรี่": "sojs"
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


def today(): return datetime.now(TZ).date()


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


def get_fallback_shop_id(resolved_dt):
    day_orders = [o for o in DATA["orders"] if o.get("ddate") == resolved_dt]
    if day_orders: return day_orders[-1]["shop_id"]
    if DATA["orders"]: return DATA["orders"][-1]["shop_id"]
    return get_or_create_shop("ร้านทั่วไป")


def normalize_tokens(raw_tokens):
    merged = []
    i = 0
    while i < len(raw_tokens):
        curr = raw_tokens[i].strip()
        if i + 1 < len(raw_tokens) and re.fullmatch(r"\d+", raw_tokens[i + 1].strip()) and re.search(r"[a-zA-Zเ-์]", curr) and not re.search(r"\d+$", curr):
            merged.append(f"{curr}{raw_tokens[i + 1].strip()}")
            i += 2
        else:
            merged.append(curr)
            i += 1
    return merged


def match_product_token(token):
    clean_token = token.lower().strip()
    
    # Check direct exact alias first (e.g. galaxyแบน, galaxyกลม, etc.)
    if clean_token in ALIAS_MAP:
        code = ALIAS_MAP[clean_token]
        return ("exact", code, 1, None)

    m_group = re.match(r"^([a-zเ-์]+)\s*(\d*)$", clean_token)
    if m_group:
        g_name = m_group.group(1)
        qty_str = m_group.group(2)
        qty = int(qty_str) if qty_str else 1
        
        if g_name in ALIAS_MAP:
            return ("exact", ALIAS_MAP[g_name], qty, None)
            
        if g_name in GROUP_KEYWORDS:
            return ("ambiguous", GROUP_KEYWORDS[g_name], qty, g_name)

    m = re.match(r"^([a-zเ-์0-9]+?)\s*(\d+)$", clean_token)
    if m:
        name_part = m.group(1)
        qty = int(m.group(2))
        
        if name_part in ALIAS_MAP:
            return ("exact", ALIAS_MAP[name_part], qty, None)
            
        if name_part in GROUP_KEYWORDS:
            return ("ambiguous", GROUP_KEYWORDS[name_part], qty, name_part)

        alias_code = ALIAS_MAP.get(name_part)
        if alias_code and alias_code in CODES:
            return ("exact", alias_code, qty, None)
        if name_part in CODES:
            return ("exact", name_part, qty, None)
            
        matching_codes = set()
        for c, full_name in PRODUCTS_DB.items():
            if name_part == c or name_part in full_name.lower().replace(" ", ""):
                matching_codes.add(c)
        
        if len(matching_codes) == 1:
            return ("exact", list(matching_codes)[0], qty, None)
        elif len(matching_codes) > 1:
            return ("ambiguous", list(matching_codes), qty, name_part)
            
        matches = get_close_matches(name_part, VALID_SEARCH_KWORDS, n=1, cutoff=0.65)
        if matches:
            matched_str = matches[0]
            matched_code = ALIAS_MAP.get(matched_str, [k for k,v in PRODUCTS_DB.items() if v.lower() == matched_str.lower()][0] if matched_str.lower() in [v.lower() for v in PRODUCTS_DB.values()] else None)
            if matched_code and matched_code in CODES:
                return ("exact", matched_code, qty, None)
                
    return ("none", None, 0, None)


def is_product_like_token(token):
    m_type, _, _, _ = match_product_token(token)
    return m_type in ("exact", "ambiguous")


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
                                {"type": "button", "style": "secondary", "color": "#1399FF", "height": "sm", "action": {"type": "postback", "label": "✏️ แก้ไขรายการ", "data": f"edit_menu|{order_id}"}},
                                {"type": "button", "style": "secondary", "color": "#DD3333", "height": "sm", "action": {"type": "postback", "label": "🗑️ ลบออเดอร์", "data": f"delete|{order_id}"}}
                            ]
                        }
                    ]
                }
            ]
        }
        order_blocks.append(block)

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
            "contents": order_blocks
        }
    }


def flex_carousel_summary(days_data, extra_bubble=None):
    bubbles = []
    if extra_bubble:
        bubbles.append(extra_bubble)
    for d_str, o_list in days_data.items():
        if len(o_list) > 0:
            bubbles.append(build_day_bubble(d_str, o_list))
            
    if not bubbles:
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "ไม่มีข้อมูลออเดอร์ในช่วงนี้", "align": "center", "margin": "lg"}]}
        })
    return {"type": "flex", "altText": "สรุปรายการจัดส่งรายวัน", "contents": {"type": "carousel", "contents": bubbles}}


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
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🔍 เลือกรายการสินค้า (SKU)", "weight": "bold", "color": "#FF9900", "size": "md"},
                {"type": "text", "text": f"คำสั่ง '{orig_query} {qty}' • {shop_name}", "size": "xs", "color": "#555555", "margin": "sm", "wrap": True},
                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "md", "contents": buttons}
            ]
        }
    }


def flex_edit_menu(order_id):
    ord_rec = next((o for o in DATA["orders"] if o.get("id") == order_id), None)
    if not ord_rec:
        return None
    
    sh = shop_by_id(ord_rec["shop_id"])
    sh_name = sh["name"] if sh else "ร้านค้า"
    
    item_sections = []
    for code in CODES:
        qty = ord_rec.get(code, 0)
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
                                "type": "button", "style": "secondary", "height": "sm",
                                "action": {"type": "postback", "label": "🔄 เปลี่ยนสินค้า", "data": f"edit_swap_menu|{order_id}|{code}|{qty}"}
                            },
                            {
                                "type": "button", "style": "secondary", "height": "sm",
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
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"✏️ แก้ไข: {sh_name}", "weight": "bold", "color": "#1399FF", "size": "md"},
                {"type": "text", "text": f"รหัสออเดอร์ #{order_id}", "size": "xs", "color": "#666666", "wrap": True},
                *item_sections
            ]
        }
    }


def flex_swap_sku_menu(order_id, old_code, qty):
    old_name = PRODUCTS_DB.get(old_code, old_code)
    buttons = []
    for code, p_name in PRODUCTS_DB.items():
        if code == old_code: continue
        buttons.append({
            "type": "button", "style": "secondary", "height": "sm",
            "action": {"type": "postback", "label": f"{p_name}", "data": f"edit_swap_do|{order_id}|{old_code}|{code}|{qty}"}
        })

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🔄 เลือกสินค้าใหม่แทนที่", "weight": "bold", "color": "#1399FF", "size": "md"},
                {"type": "text", "text": f"เปลี่ยนจาก: {old_name} ({qty})", "size": "xs", "color": "#555555", "margin": "xs", "wrap": True},
                {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": buttons[:11]}
            ]
        }
    }


def flex_qty_menu(order_id, code):
    ord_rec = next((o for o in DATA["orders"] if o.get("id") == order_id), None)
    curr_qty = ord_rec.get(code, 0) if ord_rec else 0
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
            {"label": "ตั้งเป็น 5", "val": 5},
            {"label": "ตั้งเป็น 10", "val": 10},
            {"label": "🗑️ ลบ (0)", "val": 0},
        ],
    ]

    rows_box = []
    for row in preset_rows:
        btns = []
        for item in row:
            btns.append({
                "type": "button", "style": "secondary", "height": "sm",
                "action": {"type": "postback", "label": item["label"], "data": f"edit_qty_set|{order_id}|{code}|{item['val']}"}
            })
        rows_box.append({"type": "box", "layout": "horizontal", "spacing": "xs", "contents": btns})

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"🔢 ปรับจำนวน: {p_name}", "weight": "bold", "color": "#1399FF", "size": "md"},
                {"type": "text", "text": f"จำนวนปัจจุบัน: {curr_qty}", "size": "xs", "color": "#555555", "margin": "xs", "wrap": True},
                {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": rows_box}
            ]
        }
    }


def flex_add_item_menu(order_id):
    buttons = []
    for code, p_name in PRODUCTS_DB.items():
        buttons.append({
            "type": "button", "style": "secondary", "height": "sm",
            "action": {"type": "postback", "label": f"+ {p_name} (1)", "data": f"edit_qty_set|{order_id}|{code}|1"}
        })

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "➕ เพิ่มสินค้าในออเดอร์", "weight": "bold", "color": "#1399FF", "size": "md"},
                {"type": "text", "text": "เลือกสินค้า (เพิ่มทีละ 1 จากนั้นกดปรับจำนวนได้)", "size": "xs", "color": "#555555", "margin": "xs", "wrap": True},
                {"type": "box", "layout": "vertical", "spacing": "xs", "margin": "md", "contents": buttons[:11]}
            ]
        }
    }


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        if SECRET:
            h = hmac.new(SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
            if base64.b64encode(h).decode("utf-8") != signature: abort(400)
    except: abort(400)

    try:
        for event in json.loads(body).get("events", []):
            if event.get("type") == "message": handle_message(event)
            elif event.get("type") == "postback": handle_postback(event)
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
    return "OK", 200


def get_all_valid_days_data():
    all_dates = set(o.get("ddate") for o in DATA["orders"] if o.get("ddate"))
    sorted_dates = sorted(list(all_dates))
    return {sd: [o for o in DATA["orders"] if o.get("ddate") == sd] for sd in sorted_dates}


def handle_message(event):
    msg_text = event["message"].get("text", "").strip()
    
    if any(k in msg_text.lower() for k in ["ขอรายการสินค้า", "รายการสินค้า", "รหัสสินค้า"]):
        product_list_str = "📋 รายการสินค้าและรหัสคีย์เวิร์ดทั้งหมด:\n\n"
        for code, name in PRODUCTS_DB.items():
            product_list_str += f"• [{code.upper()}] {name}\n"
        product_list_str += "\n💡 ตัวอย่างการสั่ง: 17 ร้าน ABC l2 r3 galaxyแบน 2"
        reply_text(event["replyToken"], product_list_str)
        return

    if msg_text.lower() == "ขอinput":
        reply_text(event["replyToken"], "พิมพ์: [วันที่] [ชื่อร้าน] [รายการสินค้าและจำนวน]\nเช่น: 17 ร้าน ABC Galaxyแบน 2\n\nพิมพ์ 'ขอรายการสินค้า' เพื่อดูรหัสสินค้าทั้งหมด")
        return

    m_edit = re.match(r"^(?:แก้|แก้ไข)\s+(\d+)\s+([a-zA-Zเ-์0-9]+)\s+(\d+)$", msg_text)
    if m_edit:
        oid = int(m_edit.group(1))
        raw_sku = m_edit.group(2).lower()
        new_qty = int(m_edit.group(3))
        ord_rec = next((o for o in DATA["orders"] if o.get("id") == oid), None)
        if ord_rec:
            target_code = raw_sku if raw_sku in CODES else ALIAS_MAP.get(raw_sku)
            if target_code and target_code in CODES:
                update_db("orders", oid, {target_code: new_qty})
                reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))
                return

    if msg_text.startswith("สรุป"):
        parts = msg_text.split()
        days_data = {}
        if len(parts) >= 2:
            date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2}))?$", parts[1])
            if date_match:
                dt = resolve_date(int(date_match.group(1)), int(date_match.group(2)) if date_match.group(2) else None)
                if dt:
                    matched = [o for o in DATA["orders"] if o.get("ddate") == dt]
                    if matched: days_data[dt] = matched
        
        if not days_data:
            days_data = get_all_valid_days_data()
                
        reply_flex(event["replyToken"], flex_carousel_summary(days_data))
        return

    parts = msg_text.split()
    if len(parts) >= 2:
        date_match = re.match(r"^(\d{1,2})(?:/(\d{1,2}))?$", parts[0])
        if date_match:
            resolved_dt = resolve_date(int(date_match.group(1)), int(date_match.group(2)) if date_match.group(2) else None)
            if resolved_dt:
                merged_after_date = normalize_tokens(parts[1:])
                if is_product_like_token(merged_after_date[0]):
                    shop_id = get_fallback_shop_id(resolved_dt)
                    tokens = merged_after_date
                else:
                    shop_name = parts[1]
                    shop_id = get_or_create_shop(shop_name)
                    tokens = normalize_tokens(parts[2:])
                
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
                        sel_bubble = flex_selection_menu(resolved_dt, shop_id, qty, code_or_list, orig_query)
                        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data(), extra_bubble=sel_bubble))
                        return

                if order_items:
                    existing_order = next((o for o in DATA["orders"] if o["shop_id"] == shop_id and o.get("ddate") == resolved_dt), None)
                    if existing_order:
                        oid = existing_order["id"]
                        update_payload = {c: existing_order.get(c, 0) + order_items.get(c, 0) for c in CODES if order_items.get(c, 0) > 0}
                        if update_payload: update_db("orders", oid, update_payload)
                    else:
                        payload = {"shop_id": shop_id, "ddate": resolved_dt, "status": status_key, **order_items}
                        add("orders", payload)
                        
                    reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))
                    return

    reply_text(event["replyToken"], "ไม่พบรูปแบบคำสั่งที่ถูกต้อง พิมพ์ 'ขอรายการสินค้า' เพื่อดูรหัสสินค้า หรือพิมพ์ 'ขอInput' เพื่อดูวิธีใช้งานครับ")


def handle_postback(event):
    parts = event["postback"]["data"].split("|")
    action = parts[0]
    
    if action == "status" and len(parts) == 3:
        order_id = int(parts[2])
        update_db("orders", order_id, {"status": parts[1]})
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))
        
    elif action == "delete" and len(parts) == 2:
        order_id = int(parts[1])
        delete_db("orders", order_id)
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))
        
    elif action == "edit_menu" and len(parts) == 2:
        order_id = int(parts[1])
        edit_bubble = flex_edit_menu(order_id)
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data(), extra_bubble=edit_bubble))
        
    elif action == "edit_swap_menu" and len(parts) == 4:
        order_id = int(parts[1])
        old_code = parts[2]
        qty = int(parts[3])
        swap_bubble = flex_swap_sku_menu(order_id, old_code, qty)
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data(), extra_bubble=swap_bubble))
        
    elif action == "edit_swap_do" and len(parts) == 5:
        order_id = int(parts[1])
        old_code = parts[2]
        new_code = parts[3]
        qty = int(parts[4])
        ord_rec = next((o for o in DATA["orders"] if o.get("id") == order_id), None)
        if ord_rec:
            existing_new_qty = ord_rec.get(new_code, 0)
            update_db("orders", order_id, {old_code: 0, new_code: existing_new_qty + qty})
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))
        
    elif action == "edit_qty_menu" and len(parts) == 3:
        order_id = int(parts[1])
        code = parts[2]
        qty_bubble = flex_qty_menu(order_id, code)
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data(), extra_bubble=qty_bubble))
        
    elif action == "edit_qty_set" and len(parts) == 4:
        order_id = int(parts[1])
        code = parts[2]
        new_qty = int(parts[3])
        update_db("orders", order_id, {code: new_qty})
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))
        
    elif action == "edit_add_menu" and len(parts) == 2:
        order_id = int(parts[1])
        add_bubble = flex_add_item_menu(order_id)
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data(), extra_bubble=add_bubble))
        
    elif action == "select" and len(parts) == 5:
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
            
        reply_flex(event["replyToken"], flex_carousel_summary(get_all_valid_days_data()))


def reply_text(rt, text):
    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        json={"replyToken": rt, "messages": [{"type": "text", "text": text}]}
    )


def reply_flex(rt, flex):
    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        json={"replyToken": rt, "messages": [flex]}
    )


if __name__ == "__main__":
    load()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
