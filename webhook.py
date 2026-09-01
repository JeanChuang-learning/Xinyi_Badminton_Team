import os
import hashlib
import hmac
import base64
import json
from typing import Optional
from datetime import datetime, timedelta, date
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


def get_session_open_date(session_date_obj):
    """跟 app.py 的 get_session_open_date 邏輯一致：依場次星期幾回推零打開放日。"""
    wd = session_date_obj.weekday()  # 0=一 ... 6=日
    if wd == 4:      # 週五場 → 提前2天（週三）開放
        return session_date_obj - timedelta(days=2)
    elif wd == 6:    # 週日場 → 提前4天（週三）開放
        return session_date_obj - timedelta(days=4)
    elif wd == 0:    # 週一場 → 提前3天（週五）開放
        return session_date_obj - timedelta(days=3)
    else:
        return session_date_obj - timedelta(days=7)


def is_casual_open_for_signup(session_date_obj) -> bool:
    open_date   = get_session_open_date(session_date_obj)
    open_dt_utc = datetime(open_date.year, open_date.month, open_date.day, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    return datetime.now(ZoneInfo("UTC")) >= open_dt_utc


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
PAY_LABELS = {"card": "💳 簽卡", "cash": "💵 付現", "transfer": "🏦 轉帳"}


def _session_header_contents(session: dict) -> list:
    sid     = session["id"]
    s_date  = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd    = WEEKDAY_TW[s_date.weekday()]
    s_start = (session.get("start_time") or "")[:5]
    s_end   = (session.get("end_time") or "")[:5]
    s_label = session.get("label", "")
    quota   = session.get("total_quota") or 21
    used    = get_active_count(sid)
    remain  = max(quota - used, 0)
    return [
        {"type": "text", "text": "🏸 信義羽球隊", "weight": "bold", "size": "lg"},
        {"type": "text", "text": f"{session['date']}（週{s_wd}）{s_label}", "size": "md", "wrap": True},
        {"type": "text", "text": f"⏰ {s_start}–{s_end}", "size": "sm", "color": "#888888"},
        {"type": "text", "text": f"目前 {used}/{quota} 人，剩餘 {remain} 人", "size": "sm", "color": "#888888", "margin": "md"},
    ]


def build_signup_flex_member(session: dict) -> dict:
    sid = session["id"]
    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd   = WEEKDAY_TW[s_date.weekday()]

    buttons = []
    styles  = ["primary", "primary", "secondary"]
    for i in range(1, 4):
        buttons.append({
            "type": "button", "style": styles[i - 1], "height": "sm",
            "action": {
                "type": "postback",
                "label": f"報名 {i} 人",
                "data": f"action=book&sid={sid}&count={i}",
                "displayText": f"我要報名 {i} 人",
            },
        })

    return {
        "type": "flex",
        "altText": f"🏸 {session['date']}（週{s_wd}）{session.get('label','')} 開放報名，快來按！",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": _session_header_contents(session) + [
                    {"type": "text", "text": "點下方按鈕直接報名，額滿自動候補", "size": "xs", "color": "#aaaaaa", "margin": "md", "wrap": True},
                ],
            },
            "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": buttons},
        },
    }


def build_signup_flex_casual(session: dict) -> dict:
    """零打版：3（人數1~3）× 3（付款：簽卡/付現/轉帳）＝9 顆按鈕，一次點擊直接完成報名。"""
    sid = session["id"]
    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd   = WEEKDAY_TW[s_date.weekday()]

    pay_codes = ["card", "cash", "transfer"]
    rows = []
    for count in (1, 2, 3):
        row_buttons = [
            {
                "type": "button", "style": "secondary", "height": "sm", "flex": 1,
                "action": {
                    "type": "postback",
                    "label": PAY_LABELS[pay].split(" ")[-1],
                    "data": f"action=book&sid={sid}&count={count}&pay={pay}",
                    "displayText": f"我要報名 {count} 人（{PAY_LABELS[pay]}）",
                },
            }
            for pay in pay_codes
        ]
        rows.append({
            "type": "box", "layout": "horizontal", "spacing": "xs", "margin": "sm",
            "contents": [
                {"type": "text", "text": f"{count}人", "flex": 0, "gravity": "center", "size": "sm",
                 "color": "#555555", "wrap": False},
            ] + row_buttons,
        })

    return {
        "type": "flex",
        "altText": f"🏸 {session['date']}（週{s_wd}）{session.get('label','')} 開放報名，快來按！",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": _session_header_contents(session) + [
                    {"type": "text", "text": "選人數＋付款方式，一次點擊直接完成報名：", "size": "xs", "color": "#aaaaaa", "margin": "md", "wrap": True},
                ],
            },
            "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
        },
    }


def ask_payment_method(reply_token: str, session_id: str, count: int):
    """零打報名選完人數後，用 Quick Reply 追問付款方式（同樣走 Reply API，免費）。
    僅作為改版前已發出的舊按鈕之相容 fallback，新按鈕已經把人數＋付款方式合併一次選完。"""
    quick_reply = {
        "items": [
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": PAY_LABELS["card"],
                    "data": f"action=pay&sid={session_id}&count={count}&pay=card",
                    "displayText": "簽卡付款",
                },
            },
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": PAY_LABELS["cash"],
                    "data": f"action=pay&sid={session_id}&count={count}&pay=cash",
                    "displayText": "付現",
                },
            },
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": PAY_LABELS["transfer"],
                    "data": f"action=pay&sid={session_id}&count={count}&pay=transfer",
                    "displayText": "轉帳",
                },
            },
        ]
    }
    reply_message(reply_token, f"報名 {count} 人，付款方式是？", quick_reply=quick_reply)


def push_text(target_id: str, text: str):
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        json={"to": target_id, "messages": [{"type": "text", "text": text}]},
    )
    logger.info(f"[push_text] {target_id} -> {r.status_code} | {r.text[:200]}")


def compute_confirmed_ids(session: dict, rows: list) -> set:
    """回傳這個場次目前『有拿到（至少部分）名額』的 booking id 集合，用來比對取消/改人數前後誰被遞補。"""
    quota        = session.get("total_quota") or 21
    casual_quota = session.get("casual_quota") or 15
    running_total = running_casual = 0
    confirmed_ids = set()
    for b in rows:
        b_count = int(b["count"])
        if b.get("role") == "member":
            running_total += b_count
            confirmed_ids.add(b["id"])
        else:
            remain = min(quota - running_total, casual_quota - running_casual)
            take = min(max(remain, 0), b_count)
            if take > 0:
                confirmed_ids.add(b["id"])
            running_total  += take
            running_casual += take
    return confirmed_ids


def notify_promoted(session: dict, rows_after: list, promoted_ids: set):
    for b in rows_after:
        if b["id"] in promoted_ids and b.get("line_user_id") and b.get("role") == "casual":
            clean_name = b["name"].split("_🔑")[0] if "_🔑" in b["name"] else b["name"]
            push_text(
                b["line_user_id"],
                f"🎉 名額釋出！{session['date']} {session.get('label','')}\n"
                f"{clean_name}，你已從候補遞補為正取！",
            )


def get_active_bookings_by_user(user_id: str) -> list:
    """回傳這個 LINE 使用者目前所有『未來場次』的有效報名，並附上場次資訊。"""
    rows = (
        supabase.table("bookings")
        .select("*")
        .eq("line_user_id", user_id)
        .eq("status", "active")
        .execute()
        .data
        or []
    )
    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    result = []
    for b in rows:
        session = get_session(b["session_id"])
        if session and session["date"] >= today and not session.get("cancelled"):
            b["_session"] = session
            result.append(b)
    return result


def set_pending_action(user_id: str, action: str, booking_id, max_count: int, session_label: str):
    supabase.table("line_pending_action").upsert({
        "line_user_id":  user_id,
        "action":        action,
        "booking_id":    str(booking_id),
        "max_count":     max_count,
        "session_label": session_label,
        "created_at":    datetime.now(ZoneInfo("UTC")).isoformat(),
    }).execute()


def get_pending_action(user_id: str):
    rows = supabase.table("line_pending_action").select("*").eq("line_user_id", user_id).execute().data or []
    if not rows:
        return None
    row = rows[0]
    try:
        created = datetime.fromisoformat(row["created_at"])
    except Exception:
        return None
    if datetime.now(ZoneInfo("UTC")) - created > timedelta(minutes=10):
        clear_pending_action(user_id)
        return None
    return row


def clear_pending_action(user_id: str):
    supabase.table("line_pending_action").delete().eq("line_user_id", user_id).execute()


def handle_cancel_all(reply_token: str, user_id: str):
    """直接取消這個使用者名下全部（未來場次的）有效報名。"""
    bookings = get_active_bookings_by_user(user_id)
    if not bookings:
        reply_message(reply_token, "你目前沒有報名中的場次")
        return

    cancelled_labels = []
    for b in bookings:
        session = b["_session"]
        rows_before = (
            supabase.table("bookings").select("*")
            .eq("session_id", session["id"]).eq("status", "active")
            .order("created_at").execute().data or []
        )
        confirmed_before = compute_confirmed_ids(session, rows_before)

        supabase.table("bookings").update({"status": "cancelled"}).eq("id", b["id"]).execute()

        rows_after = [r for r in rows_before if r["id"] != b["id"]]
        confirmed_after = compute_confirmed_ids(session, rows_after)
        notify_promoted(session, rows_after, confirmed_after - confirmed_before)

        cancelled_labels.append(f"{session['date']} {session.get('label','')}")

    reply_message(reply_token, "✅ 已取消以下報名：\n" + "\n".join(cancelled_labels))


def handle_modify_request(reply_token: str, user_id: str):
    bookings = get_active_bookings_by_user(user_id)
    if not bookings:
        reply_message(reply_token, "你目前沒有報名中的場次")
        return

    if len(bookings) == 1:
        b = bookings[0]
        session = b["_session"]
        if int(b["count"]) <= 1:
            reply_message(reply_token, "目前只有 1 人，無法再減少，如需取消請輸入「取消」")
            return
        set_pending_action(user_id, "modify", b["id"], int(b["count"]) - 1, f"{session['date']} {session.get('label','')}")
        reply_message(reply_token, f"目前報名 {b['count']} 人，請輸入新的人數（需小於 {b['count']}，最少 1 人）")
        return

    items = []
    for b in bookings[:13]:
        session = b["_session"]
        label = f"{session['date']} {session.get('label','')}"[:20]
        items.append({
            "type": "action",
            "action": {
                "type": "postback",
                "label": label,
                "data": f"action=modify_pick&bid={b['id']}",
                "displayText": f"修改 {label}",
            },
        })
    reply_message(reply_token, "你有多筆報名，請選要修改哪一場：", quick_reply={"items": items})


def handle_pending_number(reply_token: str, user_id: str, text: str, pending: dict) -> bool:
    """如果使用者正處於『等待輸入新人數』狀態，嘗試把這則文字當作數字處理。回傳是否有處理掉。"""
    if not text.isdigit():
        return False

    new_count = int(text)
    max_count = pending["max_count"]
    if new_count < 1 or new_count > max_count:
        reply_message(reply_token, f"人數要介於 1～{max_count} 之間，請重新輸入")
        return True  # 已處理（但無效），不要再往下當一般訊息處理

    booking_id = pending["booking_id"]
    rows = supabase.table("bookings").select("*").eq("id", booking_id).execute().data or []
    if not rows:
        clear_pending_action(user_id)
        reply_message(reply_token, "❌ 找不到這筆報名，可能已經被取消了")
        return True
    booking = rows[0]
    session = get_session(booking["session_id"])
    if not session:
        clear_pending_action(user_id)
        reply_message(reply_token, "❌ 找不到對應的場次")
        return True

    rows_before = (
        supabase.table("bookings").select("*")
        .eq("session_id", session["id"]).eq("status", "active")
        .order("created_at").execute().data or []
    )
    confirmed_before = compute_confirmed_ids(session, rows_before)

    supabase.table("bookings").update({"count": new_count}).eq("id", booking_id).execute()

    rows_after = [{**r, "count": new_count} if r["id"] == booking_id else r for r in rows_before]
    confirmed_after = compute_confirmed_ids(session, rows_after)
    notify_promoted(session, rows_after, confirmed_after - confirmed_before)

    clear_pending_action(user_id)
    reply_message(reply_token, f"✅ 已將 {session['date']} {session.get('label','')} 的人數改為 {new_count} 人")
    return True


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
    role = "member" if group_id == LINE_GROUP_ID_MEMBER else "casual"
    logger.info(
        f"[resolve_role] group_id={group_id!r} "
        f"LINE_GROUP_ID_MEMBER={LINE_GROUP_ID_MEMBER!r} "
        f"LINE_GROUP_ID_CASUAL={LINE_GROUP_ID_CASUAL!r} -> role={role}"
    )
    return role


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
    now_str       = datetime.now(ZoneInfo("UTC")).isoformat()

    status_text = compute_status_text(session, count)

    supabase.table("bookings").insert({
        "session_id":      session["id"],
        "name":            display_name,  # 不再附加密碼，LINE 報名一律用 line_user_id 辨識身份
        "role":            role,
        "count":           count,
        "status":          "active",
        "line_user_id":    user_id,
        "payment_method":  payment_method,
        "created_at":      now_str,
    }).execute()

    if role == "member":
        # 會員只需要看到報名成功即可
        reply_message(reply_token, "✅ 報名成功！")
        return

    s_label   = session.get("label", "")
    pay_line  = ""
    if payment_method:
        pay_line = f"付款方式：{PAY_LABELS.get(payment_method, payment_method)}\n"

    reply_message(
        reply_token,
        f"{status_text}\n"
        f"{display_name} ｜ {session['date']} {s_label} ｜ {count} 人\n"
        f"{pay_line}\n"
        f"之後要改人數或取消，直接在群組輸入「修改」或「取消」即可",
    )


def handle_postback(event: dict):
    reply_token = event.get("replyToken")
    source      = event.get("source", {})
    data_str    = event.get("postback", {}).get("data", "")
    params      = dict(p.split("=") for p in data_str.split("&") if "=" in p)
    action      = params.get("action")

    if action not in ("book", "pay", "modify_pick"):
        return

    user_id  = source.get("userId")
    group_id = source.get("groupId", "")

    if not user_id:
        reply_message(reply_token, "❌ 無法辨識身份，請重新點擊按鈕")
        return

    if action == "modify_pick":
        bid = params.get("bid")
        rows = supabase.table("bookings").select("*").eq("id", bid).execute().data or []
        if not rows or rows[0].get("line_user_id") != user_id or rows[0].get("status") != "active":
            reply_message(reply_token, "❌ 找不到這筆報名，或不是你本人的報名")
            return
        booking = rows[0]
        session = get_session(booking["session_id"])
        if int(booking["count"]) <= 1:
            reply_message(reply_token, "目前只有 1 人，無法再減少，如需取消請輸入「取消」")
            return
        set_pending_action(
            user_id, "modify", booking["id"], int(booking["count"]) - 1,
            f"{session['date']} {session.get('label','')}" if session else "",
        )
        reply_message(reply_token, f"目前報名 {booking['count']} 人，請輸入新的人數（需小於 {booking['count']}，最少 1 人）")
        return

    session_id = params.get("sid")
    count      = int(params.get("count", 1))

    if not session_id:
        reply_message(reply_token, "❌ 報名資訊不完整，請重新點擊按鈕")
        return

    session = get_session(session_id)
    if not session or session.get("cancelled"):
        reply_message(reply_token, "❌ 這個場次已經取消或不存在了")
        return

    if already_booked(session_id, user_id):
        reply_message(
            reply_token,
            f"你已經報名過這個場次囉！如需調整人數或取消，請輸入「修改」或「取消」",
        )
        return

    role = resolve_role(group_id)

    # 零打報名要檢查開放時間，會員不受此限制
    if role == "casual":
        s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
        if not is_casual_open_for_signup(s_date):
            open_date = get_session_open_date(s_date)
            reply_message(
                reply_token,
                f"⏳ 零打報名還沒開放喔！\n開放時間：{open_date.isoformat()} 00:00 起",
            )
            return

    if action == "book":
        pay = params.get("pay")
        if role == "casual":
            if pay in ("card", "cash", "transfer"):
                # 新版按鈕：人數＋付款方式一次選完，直接完成報名
                finalize_booking(reply_token, session, source, count, payment_method=pay)
            else:
                # 舊版按鈕相容（改版前已發出、尚未點擊的訊息）：先問付款方式
                ask_payment_method(reply_token, session_id, count)
        else:
            # 會員群 → 不需要選付款方式，直接完成報名
            finalize_booking(reply_token, session, source, count)
        return

    if action == "pay":
        pay = params.get("pay")
        if pay not in ("card", "cash", "transfer"):
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
        source      = event.get("source", {})
        user_id     = source.get("userId")
        logger.info(f"Text: {text}, Reply token: {reply_token}, source: {source}")

        if user_id:
            pending = get_pending_action(user_id)
            if pending and pending.get("action") == "modify":
                if handle_pending_number(reply_token, user_id, text, pending):
                    continue  # 已經當成人數處理掉了，不要再往下比對指令

        if text == "報名":
            session = get_upcoming_session()
            if session:
                role = resolve_role(source.get("groupId", ""))
                flex = build_signup_flex_member(session) if role == "member" else build_signup_flex_casual(session)
                reply_raw(reply_token, flex)
            else:
                reply_message(reply_token, f"目前沒有開放中的場次\n👉 {APP_URL}")
            continue

        if text == "名單":
            s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
            s_wd    = WEEKDAY_TW[s_date.weekday()]
            s_start = session.get("start_time","")[:5]
            s_end   = session.get("end_time","")[:5]
            s_label = session.get("label","")
            lines   = [
                f"🏸【信義羽球隊】{session['date']}（週{s_wd}）{s_label} {s_start}–{s_end}",
                f"名額：{current_total}/{quota} 人",
                "",
            ]
            # 正取
            confirmed = [it for it in list_to_show if not it["is_waitlist"]]
            if confirmed:
                lines.append("✅ 正取名單")
                for i, it in enumerate(confirmed, 1):
                    b    = it["data"]
                    name = it["clean_name"]
                    zh_r = ROLE_TO_ZH.get(b["role"], b["role"])
                    lines.append(f"  {i}. {name}（{b['count']}人／{zh_r}）")
            # 候補
            waitlist = [it for it in list_to_show if it["is_waitlist"]]
            if waitlist:
                lines.append("")
                lines.append("⏳ 候補名單")
                for i, it in enumerate(waitlist, 1):
                    b    = it["data"]
                    name = it["clean_name"]
                    zh_r = ROLE_TO_ZH.get(b["role"], b["role"])
                    lines.append(f"  {i}. {name}（{b['count']}人／{zh_r}）")
            lines += [
                "",
                f"👉 報名連結：{web_url}",
            ]
            reply_message(
            reply_token,
            lines,
            )

        if text in ("取消", "取消報名") and user_id:
            handle_cancel_all(reply_token, user_id)
            continue

        if text in ("修改", "改人數", "修改人數") and user_id:
            handle_modify_request(reply_token, user_id)
            continue

    return {"status": "ok"}

@app.get("/")
def health():
    return {"status": "ok"}
