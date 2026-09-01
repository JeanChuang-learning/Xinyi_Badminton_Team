"""
排程腳本：每天找出「尚未發過 Flex 快速報名通知」且還有名額的未來場次，
發送 Flex Message（報名 1/2/3/4 人按鈕）到零打＋會員兩個 LINE 群組。

由 GitHub Actions 排程觸發（cron: '0 0 * * *' → UTC 00:00 = 台灣時間 08:00）。

⚠️ 這是獨立於 msg_queue 的「快速報名」管道，直接 Push，不走訊息中心審核流程。
   複雜的候補調整/取消/改人數，使用者還是要到 Streamlit 網站處理（有密碼機制）。
"""
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from supabase import create_client

SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_KEY         = os.environ["SUPABASE_KEY"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_GROUP_ID_CASUAL = os.environ["LINE_GROUP_ID_CASUAL"]
LINE_GROUP_ID_MEMBER = os.environ["LINE_GROUP_ID_MEMBER"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]

# 未來幾天內的場次會被列入「開放快速報名」的通知範圍
LOOKAHEAD_DAYS = 7


def get_active_count(session_id):
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


def build_flex(session):
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


def push_flex(flex_message, target_ids):
    for gid in target_ids:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            },
            data=json.dumps({"to": gid, "messages": [flex_message]}, ensure_ascii=False),
        )
        print(f"[push_flex] {gid} -> {r.status_code} | {r.text[:200]}")
        if r.status_code != 200:
            return False
    return True


def main():
    tz = ZoneInfo("Asia/Taipei")
    today    = datetime.now(tz).date()
    end_date = today + timedelta(days=LOOKAHEAD_DAYS)

    sessions = (
        supabase.table("sessions")
        .select("*")
        .gte("date", today.isoformat())
        .lte("date", end_date.isoformat())
        .execute()
        .data
        or []
    )
    sessions = [
        s for s in sessions
        if not str(s.get("id", "")).startswith("_")
        and not s.get("cancelled")
        and not s.get("flex_sent")
    ]

    if not sessions:
        print("沒有需要發送 Flex 通知的場次")
        return

    for session in sessions:
        sid   = session["id"]
        quota = session.get("total_quota") or 21
        used  = get_active_count(sid)

        if used >= quota:
            print(f"場次 {sid}（{session['date']}）名額已滿，略過")
            continue

        flex = build_flex(session)
        ok = push_flex(flex, [LINE_GROUP_ID_CASUAL, LINE_GROUP_ID_MEMBER])

        if ok:
            supabase.table("sessions").update({"flex_sent": True}).eq("id", sid).execute()
            print(f"已發送 Flex 通知：場次 {sid}（{session['date']} {session.get('label','')}）")
        else:
            print(f"場次 {sid} 發送失敗，下次排程會重試")


if __name__ == "__main__":
    main()
