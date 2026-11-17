import os
import json
import re
import base64
import hashlib
from flask import Flask, request, abort
import requests

TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

app = Flask(__name__)

def send_text(reply_token, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    res = requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)
    print(f"DEBUG Reply Status: {res.status_code}, Body: {res.text}")

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    
    try:
        events = json.loads(body).get("events", [])
        for event in events:
            if event.get("type") == "message":
                msg = event["message"]
                if msg.get("type") == "text":
                    text = msg.get("text", "").strip()
                    reply_token = event["replyToken"]
                    print(f"📥 Received text: {text}")
                    send_text(reply_token, f"ได้รับข้อความแล้วจ้า: {text}")
    except Exception as e:
        print(f"❌ Error: {e}")

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
