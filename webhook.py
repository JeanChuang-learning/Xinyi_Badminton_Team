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
from fastapi.responses import HTMLResponse, JSONResponse
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

# LIFF（報名網頁）相關設定
LIFF_ID                 = os.environ.get("LIFF_ID", "")
LINE_LOGIN_CHANNEL_ID   = os.environ.get("LINE_LOGIN_CHANNEL_ID", "")

# 排程任務端點用的密鑰，cron-job.org 呼叫 /tasks/... 時要帶這組 key 才會執行
CRON_SECRET          = os.environ.get("CRON_SECRET", "")

MSG_QUEUE_TABLE      = "msg_queue"
LOOKAHEAD_DAYS       = 7
TOTAL_QUOTA_DEFAULT  = 21
CASUAL_QUOTA_DEFAULT = 15

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
    sessions = get_upcoming_sessions(limit=1)
    return sessions[0] if sessions else None


def get_upcoming_sessions(limit: int = 3):
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
    return rows[:limit]


WEEKDAY_CHAR_TO_NUM = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}


def parse_yymmdd(s: str):
    """把 YYMMDD（例如 260907）解析成 date 物件，格式錯誤或日期不存在回傳 None。"""
    s = (s or "").strip()
    if len(s) != 6 or not s.isdigit():
        return None
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
    try:
        return date(2000 + yy, mm, dd)
    except ValueError:
        return None


def get_sessions_by_date(target: date) -> list:
    rows = (
        supabase.table("sessions")
        .select("*")
        .eq("date", target.isoformat())
        .execute()
        .data
        or []
    )
    return [r for r in rows if not str(r.get("id", "")).startswith("_")]


def get_upcoming_session_by_weekday(weekday_num: int):
    """找最近一場『星期幾＝weekday_num』的未取消場次（0=一...6=日）。"""
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
    for r in rows:
        if str(r.get("id", "")).startswith("_") or r.get("cancelled"):
            continue
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        if d.weekday() == weekday_num:
            return r
    return None


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


def _three_action_footer(sid: str, role: str) -> dict:
    """報名/修改/取消 三顆按鈕都導去同一頁——頁面會自動判斷這個人有沒有報名過，
    顯示報名表單還是修改/取消控制項，不管點哪一顆結果都一樣準確。"""
    def _btn(label, action, style):
        url = f"https://liff.line.me/{LIFF_ID}?sid={sid}&role={role}&action={action}"
        return {"type": "button", "style": style, "height": "sm",
                "action": {"type": "uri", "label": label, "uri": url}}
    return {
        "type": "box", "layout": "horizontal", "spacing": "xs",
        "contents": [
            _btn("📝 報名", "book", "primary"),
            _btn("✏️ 修改", "modify", "secondary"),
            _btn("❌ 取消", "cancel", "secondary"),
        ],
    }


def _member_bubble(session: dict) -> dict:
    sid = session["id"]
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": _session_header_contents(session) + [
                {"type": "text", "text": "點下方按鈕開啟報名頁面，額滿自動候補", "size": "xs", "color": "#aaaaaa", "margin": "md", "wrap": True},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [_three_action_footer(sid, "member")],
        },
    }


def build_signup_flex_member(sessions: list) -> dict:
    """sessions：最近幾場開放中的場次（列表），每場各自一張卡片，多場時組成可滑動的 carousel。"""
    bubbles = [_member_bubble(s) for s in sessions]
    contents = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles}
    n = len(sessions)
    alt = f"🏸 開放報名！最近 {n} 場快來按" if n > 1 else f"🏸 {sessions[0]['date']} {sessions[0].get('label','')} 開放報名，快來按！"
    return {"type": "flex", "altText": alt, "contents": contents}


def _casual_bubble(session: dict) -> dict:
    sid = session["id"]
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": _session_header_contents(session) + [
                {"type": "text", "text": "點下方按鈕開啟報名頁面，選人數＋付款方式", "size": "xs", "color": "#aaaaaa", "margin": "md", "wrap": True},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [_three_action_footer(sid, "casual")],
        },
    }


def build_signup_flex_casual(sessions: list) -> dict:
    """sessions：最近幾場開放中的場次（列表），每場各自一張卡片，多場時組成可滑動的 carousel。"""
    bubbles = [_casual_bubble(s) for s in sessions]
    contents = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles}
    n = len(sessions)
    alt = f"🏸 開放報名！最近 {n} 場快來按" if n > 1 else f"🏸 {sessions[0]['date']} {sessions[0].get('label','')} 開放報名，快來按！"
    return {"type": "flex", "altText": alt, "contents": contents}


def _checkin_bubble(session: dict) -> dict:
    sid = session["id"]
    url = f"https://liff.line.me/{LIFF_ID}?sid={sid}&mode=checkin"
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": _session_header_contents(session) + [
                {"type": "text", "text": "點下方按鈕開啟點名頁面", "size": "xs", "color": "#aaaaaa", "margin": "md", "wrap": True},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [{
                "type": "button", "style": "primary", "height": "sm",
                "action": {"type": "uri", "label": "📋 點名", "uri": url},
            }],
        },
    }


def build_checkin_flex(sessions: list) -> dict:
    bubbles = [_checkin_bubble(s) for s in sessions]
    contents = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles}
    n = len(sessions)
    alt = f"📋 點名！最近 {n} 場" if n > 1 else f"📋 {sessions[0]['date']} {sessions[0].get('label','')} 點名"
    return {"type": "flex", "altText": alt, "contents": contents}


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


def get_active_bookings_by_user(user_id: str, role: Optional[str] = None) -> list:
    """回傳這個 LINE 使用者目前所有『未來場次』的有效報名，並附上場次資訊。
    role 給定時只回傳該身份（member/casual）的報名，讓同一人在會員群/零打群的報名互不影響。"""
    query = (
        supabase.table("bookings")
        .select("*")
        .eq("line_user_id", user_id)
        .eq("status", "active")
    )
    if role:
        query = query.eq("role", role)
    rows = query.execute().data or []

    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    result = []
    for b in rows:
        session = get_session(b["session_id"])
        if session and session["date"] >= today and not session.get("cancelled"):
            b["_session"] = session
            result.append(b)
    return result


def set_pending_action(user_id: str, action: str, booking_id, max_count: int, session_label: str, payment_method: Optional[str] = None):
    supabase.table("line_pending_action").upsert({
        "line_user_id":    user_id,
        "action":          action,
        "booking_id":      str(booking_id),
        "max_count":       max_count,
        "session_label":   session_label,
        "payment_method":  payment_method,
        "created_at":      datetime.now(ZoneInfo("UTC")).isoformat(),
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


def compute_max_new_count(session: dict, booking: dict):
    """
    算出這筆報名最多能改到幾人，以及『還有沒有名額可以往上加』。
    會員沒有名額硬性上限（比照網站慣例上限 10）；
    零打則要排除自己原本佔用的部分，重新計算場次還剩多少名額。
    """
    current = int(booking["count"])

    if booking.get("role") == "member":
        return max(current, 10), True

    quota        = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
    casual_quota = session.get("casual_quota") or CASUAL_QUOTA_DEFAULT

    rows = (
        supabase.table("bookings").select("*")
        .eq("session_id", session["id"]).eq("status", "active")
        .order("created_at").execute().data or []
    )
    running_total = running_casual = 0
    for b in rows:
        if b["id"] == booking["id"]:
            continue  # 排除自己，才能算出「扣掉自己之後」場次還剩多少名額
        b_count = int(b["count"])
        if b.get("role") == "member":
            running_total += b_count
        else:
            remain = min(quota - running_total, casual_quota - running_casual)
            take = min(max(remain, 0), b_count)
            running_total  += take
            running_casual += take

    remain_total  = quota - running_total
    remain_casual = casual_quota - running_casual
    remain        = max(min(remain_total, remain_casual), 0)

    capped_max = min(current + remain, 3)
    if capped_max > current:
        return capped_max, True
    return max(current - 1, 1), False


def prompt_modify_count(reply_token: str, user_id: str, booking: dict, session: dict):
    current = int(booking["count"])
    max_new, can_increase = compute_max_new_count(session, booking)

    if not can_increase and current <= 1:
        reply_message(reply_token, "目前只有 1 人，無法再減少，如需取消請輸入「取消」")
        return

    set_pending_action(user_id, "modify", booking["id"], max_new, f"{session['date']} {session.get('label','')}")

    if can_increase:
        reply_message(reply_token, f"目前報名 {current} 人，還有名額可以增加，請輸入新的人數（範圍 1～{max_new}）")
    else:
        reply_message(reply_token, f"目前報名 {current} 人，名額已滿，只能減少人數（範圍 1～{max_new}）")


def handle_cancel_all(reply_token: str, user_id: str, role: str):
    """取消這個使用者在『這個角色身份』下的全部（未來場次）有效報名。
    在會員群打取消只清會員身份的報名，在零打群打取消只清零打身份的報名，互不影響。"""
    bookings = get_active_bookings_by_user(user_id, role=role)
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


def handle_modify_request(reply_token: str, user_id: str, role: str):
    bookings = get_active_bookings_by_user(user_id, role=role)
    if not bookings:
        reply_message(reply_token, "你目前沒有報名中的場次")
        return

    if len(bookings) == 1:
        b = bookings[0]
        session = b["_session"]
        prompt_modify_count(reply_token, user_id, b, session)
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


ROLE_TO_ZH = {"member": "會員", "casual": "零打"}


def build_simple_roster_text(session: dict) -> str:
    """單一場次的簡化名單：只列姓名、身分、人數，不分正取/候補。"""
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

    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd   = WEEKDAY_TW[s_date.weekday()]
    s_label = session.get("label", "")

    lines = [f"📋 週{s_wd}名單（{session['date']} {s_label}）"]

    quota = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
    used  = sum(int(b.get("count", 0)) for b in rows)
    lines.append(f"名額：{used}/{quota} 人")

    if not rows:
        lines.append("\n目前尚無人報名")
    else:
        members = [b for b in rows if b.get("role") == "member"]
        casuals = [b for b in rows if b.get("role") != "member"]

        def _format_group(title: str, icon: str, group: list):
            if not group:
                return
            lines.append(f"\n{icon} {title}（{len(group)}）")

            for i, b in enumerate(group, 1):
                raw_name = b.get("name", "")
                name     = raw_name.split("_🔑")[0] if "_🔑" in raw_name else raw_name
                cnt      = b.get("count", 0)
                cnt_str  = f"{cnt}人".ljust(3, "　")  # 人數欄位固定寬度，姓名長短不齊放最後面
                lines.append(f"{i}. {cnt_str}{name}")

        _format_group("會員", "👥", members)
        _format_group("零打", "🏸", casuals)

    lines.append(f"\n👉 {APP_URL}")
    return "\n".join(lines)




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


def already_booked(session_id: str, line_user_id: str, role: str) -> bool:
    """同一個 LINE 帳號在會員群、零打群的報名視為不同筆，只擋『同一場次＋同一身份』的重複。"""
    rows = (
        supabase.table("bookings")
        .select("id")
        .eq("session_id", session_id)
        .eq("line_user_id", line_user_id)
        .eq("role", role)
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
        return "正取成功！"
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

    s_label   = session.get("label", "")

    if role == "member":
        reply_message(
            reply_token,
            f"✅ 報名成功！\n"
            f"{display_name} ｜ {session['date']} {s_label} ｜ {count} 人\n\n"
            f"之後要改人數或取消，直接在群組輸入「修改」或「取消」即可",
        )
        return

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


def finalize_booking_web(session: dict, user_id: str, display_name: str, role: str, count: int, payment_method=None) -> dict:
    """跟 finalize_booking 共用同一套寫入邏輯，差別是回傳結果給 LIFF 網頁顯示，不透過 LINE 訊息回覆。"""
    now_str = datetime.now(ZoneInfo("UTC")).isoformat()
    status_text = compute_status_text(session, count)

    supabase.table("bookings").insert({
        "session_id":      session["id"],
        "name":            display_name,
        "role":            role,
        "count":           count,
        "status":          "active",
        "line_user_id":    user_id,
        "payment_method":  payment_method,
        "created_at":      now_str,
    }).execute()

    return {
        "ok": True,
        "status_text": status_text,
        "session_label": f"{session['date']} {session.get('label','')}",
        "count": count,
        "payment_method": payment_method,
    }


def verify_liff_id_token(id_token: str):
    """呼叫 LINE 官方端點驗證 LIFF 送來的 ID Token，回傳 (userId, tokenName) 或 None（驗證失敗）。
    LIFF 有 profile 權限，Token 裡本來就帶真實姓名，直接用，不用再繞去查群組成員資料。"""
    try:
        r = requests.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": LINE_LOGIN_CHANNEL_ID},
        )
        if r.status_code != 200:
            logger.error(f"[verify_liff_id_token] 驗證失敗: {r.status_code} {r.text}")
            return None
        payload = r.json()
        return payload.get("sub"), payload.get("name")
    except Exception as e:
        logger.error(f"[verify_liff_id_token] 例外: {e}")
        return None


def resolve_role_liff(user_id: str, claimed_role: str = None) -> str:
    """
    用『點的是哪個 Flex（網址帶的 claimed_role，等於是從哪個群組點進來）』當主要依據，
    只在『宣稱是會員』時驗證是否真的是會員群成員（防止網址被竄改冒充會員）；
    宣稱零打（或來自任何其他有加 bot 的群組）一律直接當零打，**不會**反過來查會員群。

    這樣才能同時解決兩種情境：
    1. 同時是會員群+零打群成員的人，點零打群的 Flex 時，不會被誤判回會員
       （因為宣稱零打就不查會員群了）
    2. 只是單純會員、跑去其他群組點連結，也會正確視為零打
       （一樣不查會員群，不會因為他本來就是會員而被撈回會員）
    """
    if claimed_role == "member" and LINE_GROUP_ID_MEMBER:
        try:
            r = requests.get(
                f"https://api.line.me/v2/bot/group/{LINE_GROUP_ID_MEMBER}/member/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
            if r.status_code == 200:
                return "member"
        except Exception as e:
            logger.error(f"[resolve_role_liff] 例外: {e}")
        # 宣稱會員但驗證不過（網址被改過，或這個人根本不是會員）→ 當零打

    return "casual"


def resolve_display_name_liff(user_id: str, token_name: str, role: str) -> str:
    """姓名一律優先用 ID Token 裡的真實顯示名稱（LIFF 本來就有 profile 權限）；
    萬一 token 沒帶到姓名，才退回查對應群組的成員資料當備援，最後才用通用名稱。"""
    if token_name:
        return token_name

    group_id = LINE_GROUP_ID_MEMBER if role == "member" else LINE_GROUP_ID_CASUAL
    if group_id:
        try:
            r = requests.get(
                f"https://api.line.me/v2/bot/group/{group_id}/member/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
            if r.status_code == 200:
                return r.json().get("displayName", "羽球隊員")
        except Exception as e:
            logger.error(f"[resolve_display_name_liff] 例外: {e}")

    return "羽球隊員"


def handle_custom_count_booking(reply_token: str, user_id: str, source: dict, text: str, pending: dict) -> bool:
    """如果使用者正處於『等待輸入自訂報名人數』狀態，嘗試把這則文字當作人數處理。回傳是否有處理掉。"""
    if not text.isdigit():
        return False

    new_count = int(text)
    max_count = pending["max_count"]
    if new_count < 1 or new_count > max_count:
        reply_message(reply_token, f"人數要介於 1～{max_count} 之間，請重新輸入")
        return True

    session_id     = pending["booking_id"]  # 借用這個欄位存 session_id
    payment_method = pending.get("payment_method")

    session = get_session(session_id)
    if not session or session.get("cancelled"):
        clear_pending_action(user_id)
        reply_message(reply_token, "❌ 這個場次已經取消或不存在了")
        return True

    role = resolve_role(source.get("groupId", ""))

    if already_booked(session_id, user_id, role):
        clear_pending_action(user_id)
        reply_message(reply_token, "你已經報名過這個場次囉！如需調整人數或取消，請輸入「修改」或「取消」")
        return True

    if role == "casual":
        s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
        if not is_casual_open_for_signup(s_date):
            clear_pending_action(user_id)
            open_date = get_session_open_date(s_date)
            reply_message(reply_token, f"⏳ 零打報名還沒開放喔！\n開放時間：{open_date.isoformat()} 08:00 起")
            return True

    clear_pending_action(user_id)
    finalize_booking(reply_token, session, source, new_count, payment_method=payment_method)
    return True


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
        if not session:
            reply_message(reply_token, "❌ 找不到對應的場次")
            return
        prompt_modify_count(reply_token, user_id, booking, session)
        return

    session_id = params.get("sid")
    raw_count  = params.get("count", "1")

    if not session_id:
        reply_message(reply_token, "❌ 報名資訊不完整，請重新點擊按鈕")
        return

    session = get_session(session_id)
    if not session or session.get("cancelled"):
        reply_message(reply_token, "❌ 這個場次已經取消或不存在了")
        return

    role = resolve_role(group_id)

    if already_booked(session_id, user_id, role):
        reply_message(
            reply_token,
            f"你已經報名過這個場次囉！如需調整人數或取消，請輸入「修改」或「取消」",
        )
        return

    # 零打報名要檢查開放時間，會員不受此限制
    if role == "casual":
        s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
        if not is_casual_open_for_signup(s_date):
            open_date = get_session_open_date(s_date)
            reply_message(
                reply_token,
                f"⏳ 零打報名還沒開放喔！\n開放時間：{open_date.isoformat()} 08:00 起",
            )
            return

    if action == "book" and raw_count == "custom":
        pay = params.get("pay")  # 零打會有；會員沒有
        set_pending_action(
            user_id, "book_custom", session_id, 10,
            f"{session['date']} {session.get('label','')}",
            payment_method=pay,
        )
        reply_message(reply_token, "請輸入報名人數（1～10）")
        return

    count = int(raw_count)

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

def check_cron_secret(secret: str):
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


# ══════════════════════════════════════════════════════════
# 任務 1：處理 msg_queue（原本 send_queue.py，每 10 分鐘）
# ══════════════════════════════════════════════════════════

def send_line_direct_queue(msg_text: str, target_ids: list):
    got_quota = False
    got_error = False
    details = []
    for gid in target_ids:
        try:
            r = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
                data=json.dumps({"to": gid, "messages": [{"type": "text", "text": msg_text}]}),
            )
            details.append(f"{gid}: HTTP {r.status_code} {r.text[:200]}")
            if r.status_code == 429:
                got_quota = True
            elif r.status_code != 200:
                got_error = True
        except Exception as e:
            details.append(f"{gid}: 例外 {e}")
            got_error = True
    detail_str = " ｜ ".join(details)
    if got_quota:
        return "quota", detail_str
    if got_error:
        return "error", detail_str
    return "ok", detail_str


def run_process_queue():
    rows = (
        supabase.table(MSG_QUEUE_TABLE).select("*")
        .eq("status", "pending").order("created_at").execute().data or []
    )
    if not rows:
        return {"sent": 0, "quota": 0, "error": 0, "note": "無待發訊息"}

    sent = quota = error = 0
    for row in rows:
        rid = row["id"]
        now_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        try:
            target_ids = json.loads(row.get("target_ids") or "[]")
        except Exception:
            target_ids = []

        if not target_ids:
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "error", "error": "target_ids 為空", "sent_at": now_str}
            ).eq("id", rid).execute()
            error += 1
            continue

        result, detail = send_line_direct_queue(row["msg_text"], target_ids)
        if result == "ok":
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "sent", "sent_at": now_str, "error": None}
            ).eq("id", rid).execute()
            sent += 1
        elif result == "quota":
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "quota", "error": detail, "sent_at": now_str}
            ).eq("id", rid).execute()
            quota += 1
            break  # 配額用盡後停止，避免打爆剩餘配額
        else:
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "error", "error": detail, "sent_at": now_str}
            ).eq("id", rid).execute()
            error += 1

    return {"sent": sent, "quota": quota, "error": error}


# ══════════════════════════════════════════════════════════
# 任務 2：賽前一天名單提醒（原本 send_daily_roster.py，每天 08:00）
# ══════════════════════════════════════════════════════════

def build_daily_roster_text(session: dict) -> str:
    quota        = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
    casual_quota = session.get("casual_quota") or CASUAL_QUOTA_DEFAULT

    rows = (
        supabase.table("bookings").select("*")
        .eq("session_id", session["id"]).eq("status", "active")
        .order("created_at").execute().data or []
    )

    running_total = running_casual = 0
    confirmed, waitlist = [], []
    for b in rows:
        b_count  = int(b["count"])
        raw_name = b.get("name", "")
        clean_name = raw_name.split("_🔑")[0] if "_🔑" in raw_name else raw_name
        if b.get("role") == "member":
            running_total += b_count
            confirmed.append((clean_name, b_count, "member"))
            continue
        total_remaining     = quota - running_total
        casual_remaining    = casual_quota - running_casual
        effective_remaining = min(total_remaining, casual_remaining)
        if effective_remaining <= 0:
            waitlist.append((clean_name, b_count, "casual"))
        elif b_count > effective_remaining:
            confirmed_part = effective_remaining
            waitlist_part  = b_count - confirmed_part
            running_casual += confirmed_part
            running_total  += confirmed_part
            confirmed.append((clean_name, confirmed_part, "casual"))
            waitlist.append((clean_name, waitlist_part, "casual"))
        else:
            running_casual += b_count
            running_total  += b_count
            confirmed.append((clean_name, b_count, "casual"))

    s_date  = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd    = WEEKDAY_TW[s_date.weekday()]
    s_start = (session.get("start_time") or "")[:5]
    s_end   = (session.get("end_time") or "")[:5]
    s_label = session.get("label", "")

    lines = [
        f"🏸【信義羽球隊】明天見！{session['date']}（週{s_wd}）{s_label} {s_start}–{s_end}",
        f"名額：{running_total}/{quota} 人",
        "",
    ]
    if confirmed:
        lines.append("✅ 正取名單")
        for i, (name, cnt, role) in enumerate(confirmed, 1):
            lines.append(f"  {i}. {name}（{cnt}人／{ROLE_TO_ZH.get(role, role)}）")
    if waitlist:
        lines.append("")
        lines.append("⏳ 候補名單")
        for i, (name, cnt, role) in enumerate(waitlist, 1):
            lines.append(f"  {i}. {name}（{cnt}人／{ROLE_TO_ZH.get(role, role)}）")
    lines += ["", f"👉 報名連結：{APP_URL}"]
    return "\n".join(lines)


def roster_already_queued(session_id: str, tag: str = "daily_roster") -> bool:
    rows = (
        supabase.table(MSG_QUEUE_TABLE).select("id")
        .eq("session_id", session_id).eq("tag", tag)
        .in_("status", ["pending", "sent", "quota"])
        .execute().data or []
    )
    return len(rows) > 0


def run_daily_roster():
    tomorrow = (datetime.now(ZoneInfo("Asia/Taipei")) + timedelta(days=1)).date().isoformat()
    sessions = supabase.table("sessions").select("*").eq("date", tomorrow).execute().data or []
    sessions = [s for s in sessions if not str(s.get("id", "")).startswith("_") and not s.get("cancelled")]

    if not sessions:
        return {"queued": 0, "note": f"{tomorrow} 沒有場次"}

    queued = 0
    for session in sessions:
        sid = session["id"]
        if roster_already_queued(sid):
            continue
        msg_text = build_daily_roster_text(session)
        now_str  = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        supabase.table(MSG_QUEUE_TABLE).insert({
            "msg_text":    msg_text,
            "notify_type": "schedule_change",
            "target_ids":  json.dumps([LINE_GROUP_ID_CASUAL, LINE_GROUP_ID_MEMBER], ensure_ascii=False),
            "tag":         "daily_roster",
            "session_id":  sid,
            "status":      "pending",
            "created_at":  now_str,
            "sent_at":     None,
            "error":       None,
        }).execute()
        queued += 1

    return {"queued": queued, "sessions_checked": len(sessions)}


# ══════════════════════════════════════════════════════════
# 任務 3：每日 Flex 快速報名通知（原本 send_daily_flex.py，每天 08:00）
# ══════════════════════════════════════════════════════════

def push_flex_message(flex_message: dict, target_id: str) -> bool:
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        data=json.dumps({"to": target_id, "messages": [flex_message]}, ensure_ascii=False),
    )
    logger.info(f"[push_flex] {target_id} -> {r.status_code} | {r.text[:200]}")
    return r.status_code == 200


def run_daily_flex():
    tz       = ZoneInfo("Asia/Taipei")
    today    = datetime.now(tz).date()
    end_date = today + timedelta(days=LOOKAHEAD_DAYS)

    sessions = (
        supabase.table("sessions").select("*")
        .gte("date", today.isoformat()).lte("date", end_date.isoformat())
        .execute().data or []
    )
    sessions = [
        s for s in sessions
        if not str(s.get("id", "")).startswith("_") and not s.get("cancelled") and not s.get("flex_sent")
    ]

    if not sessions:
        return {"sent": 0, "note": "沒有需要發送的場次"}

    sent = 0
    detail = []
    for session in sessions:
        sid   = session["id"]
        quota = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
        used  = get_active_count(sid)
        if used >= quota:
            detail.append(f"{sid}: 已滿略過")
            continue

        ok_member = push_flex_message(build_signup_flex_member([session]), LINE_GROUP_ID_MEMBER)
        ok_casual = push_flex_message(build_signup_flex_casual([session]), LINE_GROUP_ID_CASUAL)

        if ok_member and ok_casual:
            supabase.table("sessions").update({"flex_sent": True}).eq("id", sid).execute()
            sent += 1
            detail.append(f"{sid}: 已發送")
        else:
            detail.append(f"{sid}: 發送失敗（會員:{ok_member} 零打:{ok_casual}）")

    return {"sent": sent, "detail": detail}


# ══════════════════════════════════════════════════════════
# 任務 4~8：每週固定通知（開放通知 / 剩餘名額通知，一律只發零打群；
#           名單、報名按鈕發給零打＋會員兩群）
# ══════════════════════════════════════════════════════════

def already_sent_today(tag: str) -> bool:
    """避免同一天被觸發兩次時重複發送（例如排程誤觸發或手動重跑）。"""
    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    rows = (
        supabase.table(MSG_QUEUE_TABLE).select("id, created_at")
        .eq("tag", tag)
        .in_("status", ["pending", "sent", "quota"])
        .execute().data or []
    )
    for r in rows:
        try:
            created_taipei = datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        except Exception:
            continue
        if created_taipei == today:
            return True
    return False


def _queue_casual_only_text(msg_text: str, tag: str, session_id: str):
    """純文字通知，只發零打群，走 msg_queue（讓 process-queue 排程實際送出）。"""
    now_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    supabase.table(MSG_QUEUE_TABLE).insert({
        "msg_text":    msg_text,
        "notify_type": "open_notice",
        "target_ids":  json.dumps([LINE_GROUP_ID_CASUAL], ensure_ascii=False),
        "tag":         tag,
        "session_id":  session_id,
        "status":      "pending",
        "created_at":  now_str,
        "sent_at":     None,
        "error":       None,
    }).execute()


def _queue_both_groups_text(msg_text: str, tag: str, session_id: str):
    """純文字通知，發零打＋會員兩群，走 msg_queue。"""
    now_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    supabase.table(MSG_QUEUE_TABLE).insert({
        "msg_text":    msg_text,
        "notify_type": "schedule_change",
        "target_ids":  json.dumps([LINE_GROUP_ID_CASUAL, LINE_GROUP_ID_MEMBER], ensure_ascii=False),
        "tag":         tag,
        "session_id":  session_id,
        "status":      "pending",
        "created_at":  now_str,
        "sent_at":     None,
        "error":       None,
    }).execute()


def _push_signup_flex_both(sessions: list) -> dict:
    """報名按鈕（Flex）沒辦法存進 msg_queue，直接 Push 給兩群。"""
    ok_member = push_flex_message(build_signup_flex_member(sessions), LINE_GROUP_ID_MEMBER)
    ok_casual = push_flex_message(build_signup_flex_casual(sessions), LINE_GROUP_ID_CASUAL)
    return {"member": ok_member, "casual": ok_casual}


# ── 任務 4：每週三 08:00 — 零打開放（週五＋週日合併一則）＋ 兩群報名按鈕 ──
def run_notice_wed():
    tag = "notice_wed_open"
    if already_sent_today(tag):
        return {"note": "今天已經發送過，略過"}

    fri = get_upcoming_session_by_weekday(4)
    sun = get_upcoming_session_by_weekday(6)
    sessions = [s for s in (fri, sun) if s]
    if not sessions:
        return {"note": "找不到週五或週日的場次"}

    lines = ["🟢 零打開放報名！"]
    for s in sessions:
        s_date  = datetime.strptime(s["date"], "%Y-%m-%d").date()
        s_wd    = WEEKDAY_TW[s_date.weekday()]
        s_start = (s.get("start_time") or "")[:5]
        s_end   = (s.get("end_time") or "")[:5]
        quota   = s.get("total_quota") or TOTAL_QUOTA_DEFAULT
        used    = get_active_count(s["id"])
        lines.append(f"\n📅 {s['date']}（週{s_wd}）{s.get('label','')} {s_start}–{s_end}")
        lines.append(f"目前 {used}/{quota} 人")
    lines.append(f"\n👉 {APP_URL}")

    _queue_casual_only_text("\n".join(lines), tag, sessions[0]["id"])
    flex_result = _push_signup_flex_both(sessions)

    return {
        "notice_queued": True,
        "flex_pushed": flex_result,
        "sessions": [f"{s['date']} {s.get('label','')}" for s in sessions],
    }


# ── 任務 5：每週五 08:00 — 零打開放（週一）＋ 兩群報名按鈕 ──
def run_notice_fri():
    tag = "notice_fri_open"
    if already_sent_today(tag):
        return {"note": "今天已經發送過，略過"}

    session = get_upcoming_session_by_weekday(0)  # 週一
    if not session:
        return {"note": "找不到週一的場次"}

    s_date  = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd    = WEEKDAY_TW[s_date.weekday()]
    s_start = (session.get("start_time") or "")[:5]
    s_end   = (session.get("end_time") or "")[:5]
    quota   = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
    used    = get_active_count(session["id"])

    notice_text = (
        f"🟢 零打開放報名！\n"
        f"📅 {session['date']}（週{s_wd}）{session.get('label','')} {s_start}–{s_end}\n"
        f"目前 {used}/{quota} 人\n\n"
        f"👉 {APP_URL}"
    )
    _queue_casual_only_text(notice_text, tag, session["id"])
    flex_result = _push_signup_flex_both([session])

    return {
        "notice_queued": True,
        "flex_pushed": flex_result,
        "session": f"{session['date']} {session.get('label','')}",
    }


def _run_remaining_slots_notice(weekday_num: int, tag: str) -> dict:
    """
    週四／週六／週日共用邏輯：如果還沒額滿 → 零打群發剩餘名額通知，
    並且兩群都發「名單」＋「報名按鈕」。已額滿當天則整組都不發。
    """
    if already_sent_today(tag):
        return {"note": "今天已經發送過，略過"}

    session = get_upcoming_session_by_weekday(weekday_num)
    if not session:
        return {"note": f"找不到星期 {weekday_num} 的場次"}

    quota = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
    used  = get_active_count(session["id"])
    label = f"{session['date']} {session.get('label','')}"

    if used >= quota:
        return {"note": f"{label} 已額滿，今天不發送", "session": label, "is_full": True}

    s_date  = datetime.strptime(session["date"], "%Y-%m-%d").date()
    s_wd    = WEEKDAY_TW[s_date.weekday()]
    s_start = (session.get("start_time") or "")[:5]
    s_end   = (session.get("end_time") or "")[:5]
    remain  = max(quota - used, 0)

    notice_text = (
        f"🟢 零打開放名額！\n"
        f"📅 {session['date']}（週{s_wd}）{session.get('label','')} {s_start}–{s_end}\n"
        f"目前 {used}/{quota} 人，剩餘 {remain} 人\n\n"
        f"👉 {APP_URL}"
    )
    _queue_casual_only_text(notice_text, tag, session["id"])

    roster_text = build_simple_roster_text(session)
    _queue_both_groups_text(roster_text, tag + "_roster", session["id"])

    flex_result = _push_signup_flex_both([session])

    return {
        "is_full": False,
        "remaining_notice_queued": True,
        "roster_queued": True,
        "flex_pushed": flex_result,
        "session": label,
    }


# ── 任務 6：每週四 08:00 — 週五剩餘名額（未額滿才發）＋ 名單五＋報名 ──
def run_notice_thu():
    return _run_remaining_slots_notice(4, "notice_thu_remain")


# ── 任務 7：每週六 08:00 — 週日剩餘名額（未額滿才發）＋ 名單日＋報名 ──
def run_notice_sat():
    return _run_remaining_slots_notice(6, "notice_sat_remain")


# ── 任務 8：每週日 08:00 — 週一剩餘名額（未額滿才發）＋ 名單一＋報名 ──
def run_notice_sun():
    return _run_remaining_slots_notice(0, "notice_sun_remain")


# ══════════════════════════════════════════════════════════
# 排程端點：給 cron-job.org 打的入口
# ══════════════════════════════════════════════════════════

@app.get("/tasks/process-queue")
def task_process_queue(secret: str = ""):
    check_cron_secret(secret)
    return run_process_queue()


@app.get("/tasks/daily-roster")
def task_daily_roster(secret: str = ""):
    check_cron_secret(secret)
    return run_daily_roster()


@app.get("/tasks/daily-flex")
def task_daily_flex(secret: str = ""):
    check_cron_secret(secret)
    return run_daily_flex()


@app.get("/tasks/weekly-casual-notice")
def task_weekly_casual_notice(secret: str = ""):
    """相容舊網址，等同週三任務。"""
    check_cron_secret(secret)
    return run_notice_wed()


@app.get("/tasks/daily-announcements")
def task_daily_announcements(secret: str = ""):
    """
    cron-job.org 只要每天 08:00（台灣時間）打這一個端點就好，
    內部自己判斷今天星期幾，決定要生成哪些「公告」內容塞進 msg_queue。
    候補→正取的「通知」是事件觸發（取消/改人數當下直接 Push），不歸這裡管。
    """
    check_cron_secret(secret)

    result = {"roster": run_daily_roster()}  # 賽前一天提醒，每天都要跑

    today_wd = datetime.now(ZoneInfo("Asia/Taipei")).weekday()  # 0=一 ... 6=日
    weekday_task_map = {
        2: ("wed", run_notice_wed),   # 週三
        3: ("thu", run_notice_thu),   # 週四
        4: ("fri", run_notice_fri),   # 週五
        5: ("sat", run_notice_sat),   # 週六
        6: ("sun", run_notice_sun),   # 週日
    }
    if today_wd in weekday_task_map:
        name, fn = weekday_task_map[today_wd]
        result[f"notice_{name}"] = fn()
    else:
        result["notice"] = "今天沒有安排的公告任務（只有週一/週二沒有）"

    logger.info(f"[task] daily-announcements result: {result}")
    return result


@app.get("/tasks/notice-wed")
def task_notice_wed(secret: str = ""):
    check_cron_secret(secret)
    return run_notice_wed()


@app.get("/tasks/notice-fri")
def task_notice_fri(secret: str = ""):
    check_cron_secret(secret)
    return run_notice_fri()


@app.get("/tasks/notice-thu")
def task_notice_thu(secret: str = ""):
    check_cron_secret(secret)
    return run_notice_thu()


@app.get("/tasks/notice-sat")
def task_notice_sat(secret: str = ""):
    check_cron_secret(secret)
    return run_notice_sat()


@app.get("/tasks/notice-sun")
def task_notice_sun(secret: str = ""):
    check_cron_secret(secret)
    return run_notice_sun()


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
            elif pending and pending.get("action") == "book_custom":
                if handle_custom_count_booking(reply_token, user_id, source, text, pending):
                    continue

        if text in ("指令", "說明", "幫助", "help"):
            reply_message(
                reply_token,
                "📋 可用指令一覽\n\n"
                "【報名】\n"
                "報名 → 開啟報名頁面（最近3場，選人數／付款方式，額滿自動候補）\n"
                "取消 → 取消你在這個身份下的報名\n"
                "修改 → 修改你已報名的人數\n\n"
                "【查詢名單】\n"
                "名單一 → 最近一場週一的名單\n"
                "名單五 → 最近一場週五的名單\n"
                "名單日 → 最近一場週日的名單\n\n"
                "【點名】\n"
                "點名 → 開啟點名頁面（記錄出席狀態）\n\n"
                "【歷史紀錄】\n"
                "紀錄 → 查詢過去三個月內指定日期的報名情況\n\n"
                "【其他】\n"
                "指令 → 顯示這份說明",
            )
            continue

        if text in ("紀錄", "記錄", "歷史紀錄", "查詢紀錄"):
            liff_url = f"https://liff.line.me/{LIFF_ID}?mode=history"
            reply_raw(reply_token, {
                "type": "flex",
                "altText": "🏸 查詢歷史報名紀錄",
                "contents": {
                    "type": "bubble",
                    "body": {
                        "type": "box", "layout": "vertical", "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": "🏸 歷史報名查詢", "weight": "bold", "size": "lg"},
                            {"type": "text", "text": "輸入日期（YYMMDD）查詢過去三個月內的報名情況", "size": "sm", "color": "#888888", "wrap": True},
                        ],
                    },
                    "footer": {
                        "type": "box", "layout": "vertical",
                        "contents": [
                            {"type": "button", "style": "primary", "action": {
                                "type": "uri", "label": "📅 查詢紀錄", "uri": liff_url,
                            }},
                        ],
                    },
                },
            })
            continue

        if text == "報名":
            sessions = get_upcoming_sessions(limit=3)
            if sessions:
                role = resolve_role(source.get("groupId", ""))
                flex = build_signup_flex_member(sessions) if role == "member" else build_signup_flex_casual(sessions)
                reply_raw(reply_token, flex)
            else:
                reply_message(reply_token, f"目前沒有開放中的場次\n👉 {APP_URL}")
            continue

        if text in ("取消", "取消報名") and user_id:
            role = resolve_role(source.get("groupId", ""))
            handle_cancel_all(reply_token, user_id, role)
            continue

        if text in ("修改", "改人數", "修改人數") and user_id:
            role = resolve_role(source.get("groupId", ""))
            handle_modify_request(reply_token, user_id, role)
            continue

        if text in ("名單五", "名單日", "名單一"):
            wd_char = text[-1]
            wd_num  = WEEKDAY_CHAR_TO_NUM[wd_char]
            session = get_upcoming_session_by_weekday(wd_num)
            if session:
                reply_message(reply_token, build_simple_roster_text(session))
            else:
                reply_message(reply_token, f"目前沒有週{wd_char}的開放場次")
            continue

        if text == "點名":
            sessions = get_upcoming_sessions(limit=3)
            if sessions:
                reply_raw(reply_token, build_checkin_flex(sessions))
            else:
                reply_message(reply_token, "目前沒有開放中的場次")
            continue

    return {"status": "ok"}

LIFF_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>信義羽球隊｜報名</title>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Microsoft JhengHei", sans-serif;
    background: #f4f6f5; color: #1a1a1a; padding: 16px;
  }
  .card { background: #fff; border-radius: 16px; padding: 18px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 14px; }
  h1 { font-size: 16px; margin: 0 0 12px; }
  h2 { font-size: 17px; margin: 0 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 2px; }
  .quota { color: #2e7d32; font-weight: 600; margin: 8px 0 14px; font-size: 14px; }
  .section-title { font-size: 12px; color: #888; margin: 14px 0 8px; }
  .btn-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .opt-btn {
    flex: 1 1 auto; min-width: 60px; padding: 11px 8px; border-radius: 10px; border: 2px solid #ddd;
    background: #fff; font-size: 14px; text-align: center; cursor: pointer; transition: 0.15s;
  }
  .opt-btn.selected { border-color: #2ecc71; background: #eafaf1; font-weight: 600; }
  input[type=number] {
    width: 100%; padding: 11px; border-radius: 10px; border: 2px solid #ddd; font-size: 15px; margin-top: 8px;
  }
  .primary-btn, .danger-btn, .secondary-btn {
    width: 100%; margin-top: 14px; padding: 13px; border: none; border-radius: 12px;
    font-size: 15px; font-weight: 600; cursor: pointer;
  }
  .primary-btn { background: #2ecc71; color: #fff; }
  .danger-btn { background: #fdecea; color: #b3261e; }
  .secondary-btn { background: #eef1f0; color: #333; margin-top: 8px; }
  button:disabled { opacity: 0.5; }
  .msg { margin-top: 10px; padding: 10px 12px; border-radius: 10px; font-size: 13px; line-height: 1.6; white-space: pre-line; }
  .msg.ok { background: #eafaf1; color: #1e7d3c; }
  .msg.err { background: #fdecea; color: #b3261e; }
  .loading { text-align: center; color: #999; padding: 40px 0; }
  .hidden { display: none; }
  .booked-box { background: #f5f9f7; border-radius: 10px; padding: 12px; margin-top: 10px; }
  .booked-box .count { font-weight: 600; font-size: 15px; }
  .pending-badge { display: inline-block; background: #fff3cd; color: #8a6d00; font-size: 11px; padding: 2px 8px; border-radius: 8px; margin-left: 6px; }
  .top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
  .top-bar .name { font-size: 13px; color: #555; }
</style>
</head>
<body>
  <div id="app"><div class="loading">載入中...</div></div>

<script>
const LIFF_ID = "__LIFF_ID__";
const params  = new URLSearchParams(location.search);
const urlRole = params.get("role");
const urlSid  = params.get("sid");
const urlMode = params.get("mode");

let PAGE_DATA = null;
const draft = {};  // sid -> { count, pay }

async function main() {
  await liff.init({ liffId: LIFF_ID });
  if (!liff.isLoggedIn()) { liff.login(); return; }
  if (urlMode === "checkin") { await loadCheckin(); return; }
  if (urlMode === "history") { renderHistoryForm(); return; }
  await load();
}

function renderHistoryForm() {
  document.getElementById("app").innerHTML = `
    <div class="card">
      <h1>🏸 歷史報名查詢</h1>
      <div class="sub">查詢過去三個月內指定日期的報名情況</div>
      <div class="section-title">日期（YYMMDD，例如 260907）</div>
      <input type="text" id="historyDate" maxlength="6" placeholder="YYMMDD" inputmode="numeric">
      <button class="primary-btn" id="historySubmit">查詢</button>
      <div id="historyResult"></div>
    </div>
  `;
  document.getElementById("historySubmit").onclick = submitHistoryQuery;
}

async function submitHistoryQuery() {
  const dateStr = document.getElementById("historyDate").value.trim();
  const box = document.getElementById("historyResult");
  box.innerHTML = "";
  const resp = await postJson("/liff/history-query", { idToken: liff.getIDToken(), date: dateStr });
  const div = document.createElement("div");
  div.className = "msg " + (resp.ok ? "ok" : "err");
  div.textContent = resp.ok ? resp.text : (resp.message || "查詢失敗");
  box.appendChild(div);
}

async function loadCheckin() {
  const resp = await postJson("/liff/checkin-list", { idToken: liff.getIDToken(), sid: urlSid });
  if (!resp.ok) { renderError(resp.message || "載入失敗"); return; }
  renderCheckin(resp);
}

function renderCheckin(data) {
  const rows = data.people.map(p => `
    <div class="opt-btn checkin-row ${p.checked_in ? "selected" : ""}" data-bid="${p.booking_id}">
      <span>${p.checked_in ? "✅" : "⬜️"} ${escapeHtml(p.name)}（${p.role}）${p.count}人</span>
    </div>
  `).join("");

  document.getElementById("app").innerHTML = `
    <div class="card">
      <h1>📋 點名</h1>
      <div class="sub">${escapeHtml(data.session_label)}</div>
      <div class="section-title">點姓名切換出席狀態</div>
      <div class="btn-row" style="flex-direction:column;" id="checkinList">
        ${rows || "<div class='sub'>目前沒有人報名</div>"}
      </div>
    </div>
  `;

  document.querySelectorAll("#checkinList .checkin-row").forEach(el => {
    el.onclick = async () => {
      const bid = el.dataset.bid;
      const nowChecked = !el.classList.contains("selected");
      el.style.opacity = "0.5";
      const resp = await postJson("/liff/checkin-toggle", {
        idToken: liff.getIDToken(), sid: urlSid, bookingId: bid, checked: nowChecked,
      });
      el.style.opacity = "1";
      if (resp.ok) {
        el.classList.toggle("selected", nowChecked);
        const span = el.querySelector("span");
        span.textContent = (nowChecked ? "✅ " : "⬜️ ") + span.textContent.replace(/^(✅|⬜️)\\s*/, "");
      }
    };
  });
}

async function load() {
  const data = await postJson("/liff/init", { idToken: liff.getIDToken(), role: urlRole, sid: urlSid });
  if (!data || data.ok === false || !data.sessions) {
    renderError((data && data.message) || "載入失敗，請重新開啟頁面");
    return;
  }
  PAGE_DATA = data;
  render();
}

function renderError(text) {
  document.getElementById("app").innerHTML = `<div class="card"><div class="msg err">${escapeHtml(text)}</div></div>`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function render() {
  const { role, display_name, sessions } = PAGE_DATA;
  const roleLabel = role === "member" ? "會員" : "零打";

  let html = `
    <div class="card">
      <div class="top-bar">
        <h1>🏸 信義羽球隊</h1>
        <div class="name">${escapeHtml(display_name)}（${roleLabel}）</div>
      </div>
    </div>
  `;

  if (!sessions || sessions.length === 0) {
    html += `<div class="card">目前沒有開放中的場次</div>`;
  } else {
    sessions.forEach(s => { html += renderSessionCard(s, role); });
  }

  document.getElementById("app").innerHTML = html;
  sessions.forEach(s => attachHandlers(s, role));
}

function renderSessionCard(s, role) {
  const isCasual = role === "casual";
  const mb = s.my_booking;

  let body = `
    <h2>${s.date}（週${s.weekday}）${escapeHtml(s.label)}</h2>
    <div class="sub">⏰ ${s.start_time}–${s.end_time}</div>
    <div class="quota">目前 ${s.used}/${s.quota} 人，剩餘 ${s.remaining} 人</div>
  `;

  if (mb) {
    const payLabel = { card: "💳 簽卡", cash: "💵 付現", transfer: "🏦 轉帳" }[mb.payment_method] || "";
    body += `
      <div class="booked-box">
        <div class="count">✅ 你已報名 ${mb.count} 人 ${payLabel}</div>
        <div class="section-title">修改人數（${mb.can_increase ? "1～" + mb.max_count : "已額滿，只能減少，1～" + mb.max_count}）</div>
        <input type="number" id="modifyInput_${s.id}" min="1" max="${mb.max_count}" value="${mb.count}">
        <button class="secondary-btn" data-action="modify" data-sid="${s.id}" data-bid="${mb.booking_id}">更新人數</button>
        <button class="danger-btn" data-action="cancel" data-sid="${s.id}" data-bid="${mb.booking_id}">取消這筆報名</button>
      </div>
      <div id="msg_${s.id}"></div>
    `;
  } else if (isCasual && !s.casual_open) {
    body += `<div class="msg err">⏳ 零打報名還沒開放，開放時間：${s.casual_open_date} 08:00 起</div>`;
  } else {
    body += `
      <div class="section-title">報名人數</div>
      <div class="btn-row" id="countRow_${s.id}">
        ${isCasual ? `
          <div class="opt-btn selected" data-count="1">1 人</div>
          <div class="opt-btn" data-count="2">2 人</div>
          <div class="opt-btn" data-count="3">3 人</div>
        ` : `
          <div class="opt-btn selected" data-count="1">1 人</div>
          <div class="opt-btn" data-count="2">2 人</div>
          <div class="opt-btn" data-count="custom">自訂</div>
        `}
      </div>
      <input type="number" id="customCount_${s.id}" class="hidden" min="1" max="20" placeholder="輸入人數">
      ${isCasual ? `
        <div class="section-title">付款方式</div>
        <div class="btn-row" id="payRow_${s.id}">
          <div class="opt-btn" data-pay="card">💳 簽卡</div>
          <div class="opt-btn" data-pay="cash">💵 付現</div>
          <div class="opt-btn" data-pay="transfer">🏦 轉帳</div>
        </div>
      ` : ""}
      <button class="primary-btn" data-action="book" data-sid="${s.id}">送出報名</button>
      <div id="msg_${s.id}"></div>
    `;
    draft[s.id] = { count: "1", pay: null };
  }

  return `<div class="card">${body}</div>`;
}

function attachHandlers(s, role) {
  const isCasual = role === "casual";
  const mb = s.my_booking;

  if (!mb) {
    const countRow = document.getElementById(`countRow_${s.id}`);
    if (countRow) {
      countRow.querySelectorAll(".opt-btn").forEach(el => {
        el.onclick = () => {
          countRow.querySelectorAll(".opt-btn").forEach(x => x.classList.remove("selected"));
          el.classList.add("selected");
          draft[s.id].count = el.dataset.count;
          document.getElementById(`customCount_${s.id}`).classList.toggle("hidden", el.dataset.count !== "custom");
        };
      });
    }
    const payRow = document.getElementById(`payRow_${s.id}`);
    if (payRow) {
      payRow.querySelectorAll(".opt-btn").forEach(el => {
        el.onclick = () => {
          payRow.querySelectorAll(".opt-btn").forEach(x => x.classList.remove("selected"));
          el.classList.add("selected");
          draft[s.id].pay = el.dataset.pay;
        };
      });
    }
  }

  document.querySelectorAll(`[data-sid="${s.id}"]`).forEach(btn => {
    btn.onclick = () => {
      const action = btn.dataset.action;
      if (action === "book") submitBooking(s, isCasual, btn);
      else if (action === "cancel") submitCancel(s, btn.dataset.bid, btn);
      else if (action === "modify") submitModify(s, btn.dataset.bid, btn);
    };
  });
}

function setBusy(btn, text) {
  if (!btn) return;
  btn.dataset.originalText = btn.textContent;
  btn.textContent = text;
  btn.disabled = true;
}

function clearBusy(btn) {
  if (!btn) return;
  btn.disabled = false;
  if (btn.dataset.originalText) btn.textContent = btn.dataset.originalText;
}

async function submitBooking(s, isCasual, btn) {
  const d = draft[s.id];
  let count = d.count;
  if (count === "custom") {
    const v = parseInt(document.getElementById(`customCount_${s.id}`).value, 10);
    if (!v || v < 1 || v > 20) { showMsg(s.id, "請輸入 1～20 之間的人數", false); return; }
    count = v;
  } else {
    count = parseInt(count, 10);
  }
  if (isCasual && !d.pay) { showMsg(s.id, "請選擇付款方式", false); return; }

  setBusy(btn, "送出中...");
  showMsg(s.id, "⏳ 處理中，請稍候...", true);

  const resp = await postJson("/liff/submit-booking", {
    idToken: liff.getIDToken(), sid: s.id, count, role: urlRole,
    payment_method: isCasual ? d.pay : null,
  });
  await handleActionResult(s.id, resp, btn, resp.status_text);
}

async function submitCancel(s, bookingId, btn) {
  if (!confirm("確定要取消這筆報名嗎？")) return;
  setBusy(btn, "取消中...");
  showMsg(s.id, "⏳ 處理中，請稍候...", true);
  const resp = await postJson("/liff/cancel-booking", { idToken: liff.getIDToken(), bookingId });
  await handleActionResult(s.id, resp, btn);
}

async function submitModify(s, bookingId, btn) {
  const v = parseInt(document.getElementById(`modifyInput_${s.id}`).value, 10);
  if (!v || v < 1) { showMsg(s.id, "請輸入有效的人數", false); return; }
  setBusy(btn, "更新中...");
  showMsg(s.id, "⏳ 處理中，請稍候...", true);
  const resp = await postJson("/liff/modify-booking", { idToken: liff.getIDToken(), bookingId, newCount: v });
  await handleActionResult(s.id, resp, btn);
}

async function postJson(url, payload) {
  try {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await r.json();
  } catch (e) {
    return { ok: false, message: "網路異常，請稍後再試" };
  }
}

async function handleActionResult(sid, data, btn, fallbackText) {
  if (data.ok) {
    showMsg(sid, "✅ " + (data.message || fallbackText || "操作成功"), true);
    await new Promise(r => setTimeout(r, 1000));  // 讓使用者先看清楚成功訊息，再重新整理畫面
    await load();
  } else {
    clearBusy(btn);
    showMsg(sid, data.message || "操作失敗，請稍後再試", false);
  }
}

function showMsg(sid, text, ok) {
  const box = document.getElementById(`msg_${sid}`);
  if (!box) return;
  box.innerHTML = "";
  const div = document.createElement("div");
  div.className = "msg " + (ok ? "ok" : "err");
  div.textContent = text;
  box.appendChild(div);
}

main().catch(e => renderError("載入失敗：" + e.message));
</script>
</body>
</html>
"""


@app.get("/liff/book")
def liff_book_page():
    html = LIFF_PAGE_HTML.replace("__LIFF_ID__", LIFF_ID)
    return HTMLResponse(content=html)


@app.post("/liff/init")
async def liff_init(request: Request):
    """回傳這個人看到的場次資料，每場都附上『這個人自己的報名狀態』（有的話）。
    有帶 sid（從特定場次的 Flex 按鈕點進來）就只回那一場；沒帶就回最近三場。"""
    body = await request.json()
    id_token     = body.get("idToken", "")
    claimed_role = body.get("role")
    sid_filter   = body.get("sid")

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})
    user_id, token_name = verified

    role = resolve_role_liff(user_id, claimed_role)
    display_name = resolve_display_name_liff(user_id, token_name, role)

    if sid_filter:
        one = get_session(sid_filter)
        sessions = [one] if one and not one.get("cancelled") else []
    else:
        sessions = get_upcoming_sessions(limit=3)

    my_bookings = get_active_bookings_by_user(user_id, role=role)
    my_by_sid = {b["session_id"]: b for b in my_bookings}

    session_list = []
    for s in sessions:
        sid    = s["id"]
        quota  = s.get("total_quota") or TOTAL_QUOTA_DEFAULT
        used   = get_active_count(sid)
        s_date = datetime.strptime(s["date"], "%Y-%m-%d").date()

        item = {
            "id": sid,
            "date": s["date"],
            "weekday": WEEKDAY_TW[s_date.weekday()],
            "label": s.get("label", ""),
            "start_time": (s.get("start_time") or "")[:5],
            "end_time": (s.get("end_time") or "")[:5],
            "quota": quota,
            "used": used,
            "remaining": max(quota - used, 0),
            "casual_open": is_casual_open_for_signup(s_date) if role == "casual" else True,
            "casual_open_date": get_session_open_date(s_date).isoformat(),
            "my_booking": None,
        }

        b = my_by_sid.get(sid)
        if b:
            max_count, can_increase = compute_max_new_count(s, b)
            item["my_booking"] = {
                "booking_id": b["id"],
                "count": int(b["count"]),
                "payment_method": b.get("payment_method"),
                "max_count": max_count,
                "can_increase": can_increase,
            }
        session_list.append(item)

    return JSONResponse({"role": role, "display_name": display_name, "sessions": session_list})


@app.post("/liff/submit-booking")
async def liff_submit_booking(request: Request):
    body = await request.json()
    id_token       = body.get("idToken", "")
    sid            = body.get("sid", "")
    raw_count      = body.get("count", 1)
    payment_method = body.get("payment_method")
    claimed_role   = body.get("role")

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})
    user_id, token_name = verified

    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "message": "人數格式錯誤"})
    if count < 1 or count > 20:
        return JSONResponse({"ok": False, "message": "人數要介於 1～20 之間"})

    if not sid:
        return JSONResponse({"ok": False, "message": "缺少場次資訊，請重新開啟頁面"})

    session = get_session(sid)
    if not session or session.get("cancelled"):
        return JSONResponse({"ok": False, "message": "這個場次已經取消或不存在了"})

    role = resolve_role_liff(user_id, claimed_role)
    display_name = resolve_display_name_liff(user_id, token_name, role)

    if already_booked(sid, user_id, role):
        return JSONResponse({
            "ok": False,
            "message": "你已經報名過這個場次囉！可以直接在下方修改人數或取消",
        })

    if role == "casual":
        if count > 3:
            return JSONResponse({"ok": False, "message": "零打單次報名最多 3 人"})
        s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
        if not is_casual_open_for_signup(s_date):
            open_date = get_session_open_date(s_date)
            return JSONResponse({
                "ok": False,
                "message": f"零打報名還沒開放喔！開放時間：{open_date.isoformat()} 08:00 起",
            })
        if payment_method not in ("card", "cash", "transfer"):
            return JSONResponse({"ok": False, "message": "請選擇付款方式"})
    else:
        payment_method = None  # 會員不需要付款方式，即使前端傳了也忽略

    result = finalize_booking_web(session, user_id, display_name, role, count, payment_method)
    return JSONResponse(result)


@app.post("/liff/cancel-booking")
async def liff_cancel_booking(request: Request):
    body = await request.json()
    id_token   = body.get("idToken", "")
    booking_id = body.get("bookingId", "")

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})
    user_id, _ = verified

    rows = supabase.table("bookings").select("*").eq("id", booking_id).execute().data or []
    if not rows or rows[0].get("line_user_id") != user_id or rows[0].get("status") != "active":
        return JSONResponse({"ok": False, "message": "找不到這筆報名，或不是你本人的報名"})

    booking = rows[0]
    session = get_session(booking["session_id"])
    if not session:
        return JSONResponse({"ok": False, "message": "找不到對應的場次"})

    rows_before = (
        supabase.table("bookings").select("*")
        .eq("session_id", session["id"]).eq("status", "active")
        .order("created_at").execute().data or []
    )
    confirmed_before = compute_confirmed_ids(session, rows_before)

    supabase.table("bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()

    rows_after = [r for r in rows_before if r["id"] != booking_id]
    confirmed_after = compute_confirmed_ids(session, rows_after)
    notify_promoted(session, rows_after, confirmed_after - confirmed_before)

    return JSONResponse({"ok": True, "message": "已取消報名"})


@app.post("/liff/modify-booking")
async def liff_modify_booking(request: Request):
    body = await request.json()
    id_token   = body.get("idToken", "")
    booking_id = body.get("bookingId", "")
    raw_count  = body.get("newCount")

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})
    user_id, _ = verified

    rows = supabase.table("bookings").select("*").eq("id", booking_id).execute().data or []
    if not rows or rows[0].get("line_user_id") != user_id or rows[0].get("status") != "active":
        return JSONResponse({"ok": False, "message": "找不到這筆報名，或不是你本人的報名"})

    booking = rows[0]
    session = get_session(booking["session_id"])
    if not session:
        return JSONResponse({"ok": False, "message": "找不到對應的場次"})

    try:
        new_count = int(raw_count)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "message": "人數格式錯誤"})

    max_count, can_increase = compute_max_new_count(session, booking)
    if new_count < 1 or new_count > max_count:
        return JSONResponse({"ok": False, "message": f"人數要介於 1～{max_count} 之間"})

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

    return JSONResponse({"ok": True, "message": f"已改為 {new_count} 人"})


@app.post("/liff/checkin-list")
async def liff_checkin_list(request: Request):
    """回傳這場的完整名單＋目前簽到狀態，給點名頁面用。"""
    body = await request.json()
    id_token = body.get("idToken", "")
    sid      = body.get("sid", "")

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})
    user_id, _ = verified

    session = get_session(sid)
    if not session:
        return JSONResponse({"ok": False, "message": "找不到這個場次"})

    rows = (
        supabase.table("bookings").select("*")
        .eq("session_id", sid).eq("status", "active")
        .order("created_at").execute().data or []
    )
    checkin_rows = supabase.table("checkins").select("booking_id").eq("session_id", sid).execute().data or []
    checked_ids = {r["booking_id"] for r in checkin_rows}

    people = []
    for b in rows:
        raw_name = b.get("name", "")
        name     = raw_name.split("_🔑")[0] if "_🔑" in raw_name else raw_name
        people.append({
            "booking_id": b["id"],
            "name": name,
            "role": ROLE_TO_ZH.get(b.get("role"), b.get("role", "")),
            "count": int(b.get("count", 0)),
            "checked_in": b["id"] in checked_ids,
        })

    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    return JSONResponse({
        "ok": True,
        "session_label": f"{session['date']}（週{WEEKDAY_TW[s_date.weekday()]}）{session.get('label','')}",
        "people": people,
    })


@app.post("/liff/checkin-toggle")
async def liff_checkin_toggle(request: Request):
    """切換某一筆報名的簽到狀態（有記錄＝已簽到，沒記錄＝未簽到），跟網站共用同一張 checkins 表。"""
    body = await request.json()
    id_token   = body.get("idToken", "")
    sid        = body.get("sid", "")
    booking_id = body.get("bookingId", "")
    checked    = bool(body.get("checked"))

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})
    user_id, _ = verified

    if not sid or not booking_id:
        return JSONResponse({"ok": False, "message": "缺少必要參數"})

    try:
        if checked:
            supabase.table("checkins").upsert({
                "session_id": sid,
                "booking_id": booking_id,
            }).execute()
        else:
            supabase.table("checkins").delete() \
                .eq("session_id", sid).eq("booking_id", booking_id).execute()
    except Exception as e:
        logger.error(f"[liff_checkin_toggle] 例外: {e}")
        return JSONResponse({"ok": False, "message": "簽到寫入失敗，請稍後再試"})

    return JSONResponse({"ok": True})


@app.post("/liff/history-query")
async def liff_history_query(request: Request):
    """查詢過去三個月內指定日期（YYMMDD）的報名情況，跟名單指令用同一套簡化格式。"""
    body = await request.json()
    id_token = body.get("idToken", "")
    date_str = body.get("date", "")

    verified = verify_liff_id_token(id_token)
    if not verified:
        return JSONResponse({"ok": False, "message": "登入驗證失敗，請重新開啟頁面"})

    target = parse_yymmdd(date_str)
    if not target:
        return JSONResponse({"ok": False, "message": "日期格式錯誤，請輸入6碼，例如 260907"})

    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    if target > today:
        return JSONResponse({"ok": False, "message": "只能查詢過去的日期"})
    if (today - target).days > 92:
        return JSONResponse({"ok": False, "message": "只能查詢最近三個月內的紀錄"})

    sessions = get_sessions_by_date(target)
    if not sessions:
        return JSONResponse({"ok": False, "message": f"{target.isoformat()} 沒有場次紀錄"})

    texts = [build_simple_roster_text(s) for s in sessions]
    return JSONResponse({"ok": True, "text": "\n\n".join(texts)})


@app.get("/")
def health():
    return {"status": "ok"}
