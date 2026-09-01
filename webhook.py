import os
import hashlib
import hmac
import base64
import json
import random
import string
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import logging
from fastapi import FastAPI, Request, Header, HTTPException
from supabase import create_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
APP_URL = "https://am24logbujoqctvut7bqmk.streamlit.app/"

SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_KEY         = os.environ["SUPABASE_KEY"]
LINE_GROUP_ID_CASUAL = os.environ.get("LINE_GROUP_ID_CASUAL", "")
LINE_GROUP_ID_MEMBER = os.environ.get("LINE_GROUP_ID_MEMBER", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def verify_signature(body: bytes, signature: str) -> bool:
    hash_ = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(hash_).decode()
    logger.info(f"Expected: {expected}, Got: {signature}, Match: {hmac.compare_digest(expected, signature)}")
    return hmac.compare_digest(expected, signature)

def reply_raw(reply_token: str, message: dict):
    resp = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [message],
        },
    )
    logger.info(f"Reply status: {resp.status_code}, body: {resp.text}")


def reply_message(reply_token: str, text: str, quick_reply: Optional[dict] = None):
    message = {"type": "text", "text": text}
    if quick_reply:
        message["quickReply"] = quick_reply
    reply_raw(reply_token, message)


def get_upcoming_session():
    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    rows = (
        supabase.table("sessions")
        .select("*")
        .gte("date", today)
        .order("date")
        .execute()
        .data
        or []
    )
    rows = [r for r in rows if not str(r.get("id", "")).startswith("_") and not r.get("cancelled")]
    return rows[0] if rows else None


def get_active_count(session_id: str) -> int:
    rows = (
        supabase.table("bookings")
        .select("count")
        .eq("session_id", session_id)
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    return sum(int(r["count"]) for r in rows)


WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]


def build_signup_flex(session: dict) -> dict:
    sid     = session["id"]
    s_date  = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd    = WEEKDAY_TW[s_date.weekday()]
    s_start = (session.get("start_time") or "")[:5]
    s_end   = (session.get("end_time") or "")[:5]
    s_label = session.get("label", "")
    quota   = session.get("total_quota") or 21
    used    = get_active_count(sid)
    remain  = max(quota - used, 0)

    buttons = []
    styles  = ["primary", "primary", "secondary", "secondary"]
    for i in range(1, 5):
        buttons.append({
            "type": "button",
            "style": styles[i - 1],
            "height": "sm",
            "action": {
                "type": "postback",
                "label": f"報名 {i} 人",
                "data": f"action=book&sid={sid}&count={i}",
                "displayText": f"我要報名 {i} 人",
            },
        })

    return {
        "type": "flex",
        "altText": f"🏸 {session['date']}（週{s_wd}）{s_label} 開放報名，快來按！",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": "🏸 信義羽球隊", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": f"{session['date']}（週{s_wd}）{s_label}", "size": "md", "wrap": True},
                    {"type": "text", "text": f"⏰ {s_start}–{s_end}", "size": "sm", "color": "#888888"},
                    {"type": "text", "text": f"目前 {used}/{quota} 人，剩餘 {remain} 人", "size": "sm", "color": "#888888", "margin": "md"},
                    {"type": "text", "text": "點下方按鈕直接報名，額滿自動候補", "size": "xs", "color": "#aaaaaa", "margin": "md", "wrap": True},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": buttons,
            },
        },
    }


def ask_payment_method(reply_token: str, session_id: str, count: int):
    """零打報名選完人數後，用 Quick Reply 追問簽卡/付現（同樣走 Reply API，免費）。"""
    quick_reply = {
        "items": [
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "💳 簽卡",
                    "data": f"action=pay&sid={session_id}&count={count}&pay=card",
                    "displayText": "簽卡付款",
                },
            },
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "💵 付現",
                    "data": f"action=pay&sid={session_id}&count={count}&pay=cash",
                    "displayText": "付現",
                },
            },
        ]
    }
    reply_message(reply_token, f"報名 {count} 人，付款方式是？", quick_reply=quick_reply)


def get_display_name(source: dict) -> str:
    """優先用群組成員資料 API（不需對方加好友），1:1 才退回 Get Profile。"""
    user_id = source.get("userId")
    try:
        if source.get("type") == "group" and source.get("groupId"):
            r = requests.get(
                f"https://api.line.me/v2/bot/group/{source['groupId']}/member/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
        else:
            r = requests.get(
                f"https://api.line.me/v2/bot/profile/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
        if r.status_code == 200:
            return r.json().get("displayName", "羽球隊員")
    except Exception as e:
        logger.error(f"get_display_name 失敗: {e}")
    return "羽球隊員"


def resolve_role(group_id: str) -> str:
    if group_id == LINE_GROUP_ID_MEMBER:
        return "member"
    return "casual"  # 預設當零打處理（含私訊測試等未知來源）


def already_booked(session_id: str, line_user_id: str) -> bool:
    rows = (
        supabase.table("bookings")
        .select("id")
        .eq("session_id", session_id)
        .eq("line_user_id", line_user_id)
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    return len(rows) > 0


def get_session(session_id: str):
    rows = supabase.table("sessions").select("*").eq("id", session_id).execute().data or []
    return rows[0] if rows else None


def compute_status_text(session: dict, new_count: int) -> str:
    """套用跟網站相同的正取/候補判斷邏輯，回傳這次報名結果的文字描述。"""
    quota        = session.get("total_quota") or 21
    casual_quota = session.get("casual_quota") or 15

    rows = (
        supabase.table("bookings")
        .select("*")
        .eq("session_id", session["id"])
        .eq("status", "active")
        .order("created_at")
        .execute()
        .data
        or []
    )

    running_total = running_casual = 0
    for b in rows:
        b_count = int(b["count"])
        if b.get("role") == "member":
            running_total += b_count
        else:
            remain = min(quota - running_total, casual_quota - running_casual)
            take = min(max(remain, 0), b_count)
            running_total  += take
            running_casual += take

    remain = quota - running_total
    if remain >= new_count:
        return "✅ 正取成功！"
    elif remain > 0:
        return f"⚠️ 正取 {remain} 人、候補 {new_count - remain} 人"
    else:
        return "⏳ 目前候補中，名額釋出會依序遞補"


def finalize_booking(reply_token, session, source, count, payment_method=None):
    user_id       = source.get("userId")
    display_name  = get_display_name(source)
    role          = resolve_role(source.get("groupId", ""))
    pwd           = "".join(random.choices(string.digits, k=4))
    full_name     = f"{display_name}_🔑{pwd}_🔄0"
    now_str       = datetime.now(ZoneInfo("UTC")).isoformat()

    status_text = compute_status_text(session, count)

    supabase.table("bookings").insert({
        "session_id":      session["id"],
        "name":            full_name,
        "role":            role,
        "count":           count,
        "status":          "active",
        "line_user_id":    user_id,
        "payment_method":  payment_method,
        "created_at":      now_str,
    }).execute()

    s_label   = session.get("label", "")
    pay_line  = ""
    if payment_method:
        pay_label = "💳 簽卡" if payment_method == "card" else "💵 付現"
        pay_line  = f"付款方式：{pay_label}\n"

    reply_message(
        reply_token,
        f"{status_text}\n"
        f"{display_name} ｜ {session['date']} {s_label} ｜ {count} 人\n"
        f"{pay_line}\n"
        f"🔑 修改密碼：{pwd}（之後要改人數或取消時，到報名網站輸入）",
    )


def handle_postback(event: dict):
    reply_token = event.get("replyToken")
    source      = event.get("source", {})
    data_str    = event.get("postback", {}).get("data", "")
    params      = dict(p.split("=") for p in data_str.split("&") if "=" in p)
    action      = params.get("action")

    if action not in ("book", "pay"):
        return

    session_id = params.get("sid")
    count      = int(params.get("count", 1))
    user_id    = source.get("userId")
    group_id   = source.get("groupId", "")

    if not user_id or not session_id:
        reply_message(reply_token, "❌ 報名資訊不完整，請重新點擊按鈕")
        return

    session = get_session(session_id)
    if not session or session.get("cancelled"):
        reply_message(reply_token, "❌ 這個場次已經取消或不存在了")
        return

    if already_booked(session_id, user_id):
        reply_message(
            reply_token,
            f"你已經報名過這個場次囉！如需調整人數或取消，請到報名網站：\n{APP_URL}",
        )
        return

    role = resolve_role(group_id)

    if action == "book":
        if role == "casual":
            # 零打群 → 先問付款方式，選完才真正寫入報名
            ask_payment_method(reply_token, session_id, count)
        else:
            # 會員群 → 不需要選付款方式，直接完成報名
            finalize_booking(reply_token, session, source, count)
        return

    if action == "pay":
        pay = params.get("pay")
        if pay not in ("card", "cash"):
            reply_message(reply_token, "❌ 付款方式有誤，請重新點擊報名按鈕")
            return
        finalize_booking(reply_token, session, source, count, payment_method=pay)

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
        if event.get("type") == "postback":
            logger.info(f"Postback: {event.get('postback', {})}, source: {event.get('source', {})}")
            try:
                handle_postback(event)
            except Exception as e:
                logger.error(f"handle_postback 失敗: {e}")
                reply_token = event.get("replyToken")
                if reply_token:
                    reply_message(reply_token, "❌ 系統忙碌，請稍後再試或到報名網站報名")
            continue

        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue

        text        = event["message"]["text"].strip()
        reply_token = event["replyToken"]
        logger.info(f"Text: {text}, Reply token: {reply_token}")

        if text == "報名":
            session = get_upcoming_session()
            if session:
                reply_raw(reply_token, build_signup_flex(session))
            else:
                reply_message(reply_token, f"目前沒有開放中的場次\n👉 {APP_URL}")

    return {"status": "ok"}

@app.get("/")
def health():
    return {"status": "ok"}
