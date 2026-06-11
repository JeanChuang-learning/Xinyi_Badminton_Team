import os
import hashlib
import hmac
import base64
import requests
import logging
from fastapi import FastAPI, Request, Header, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
APP_URL = "https://am24logbujoqctvut7bqmk.streamlit.app/"

def verify_signature(body: bytes, signature: str) -> bool:
    hash_ = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(hash_).decode()
    logger.info(f"Expected: {expected}, Got: {signature}, Match: {hmac.compare_digest(expected, signature)}")
    return hmac.compare_digest(expected, signature)

def reply_message(reply_token: str, text: str):
    resp = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text}],
        },
    )
    logger.info(f"Reply status: {resp.status_code}, body: {resp.text}")

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(...)):
    body = await request.body()
    logger.info(f"Received webhook, signature: {x_line_signature}")

    if not verify_signature(body, x_line_signature):
        logger.error("Signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = await request.json()
    logger.info(f"Events: {data.get('events', [])}")

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue

        text        = event["message"]["text"].strip()
        reply_token = event["replyToken"]
        logger.info(f"Text: {text}, Reply token: {reply_token}")

        if text == "報名":
            reply_message(reply_token, f"🏸 信義羽球隊報名系統\n👉 {APP_URL}")
        elif text == "名單":
            reply_message(reply_token, f"🏸 信義羽球隊報名系統\n👉 {APP_URL}")        

    return {"status": "ok"}

@app.get("/")
def health():
    return {"status": "ok"}
