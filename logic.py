"""
logic.py —— 業務規則層：場地資訊、公告、開放時間規則、自動產生固定場次、
候補遞補通知、零打名額自動釋出。

純資料存取請用 db.py；LINE 推播/佇列請用 notify.py。

⚠️ get_session_open_date / is_casual_open_for_signup 已搬到根目錄的
shared_logic.py（webhook.py 也 import 同一份），這裡只是重新 export 方便
其他模組沿用 `from logic import is_casual_open_for_signup` 的舊寫法。
"""

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from supabase_client import supabase

from config import FIXED_RULES, Quota_7, Limit_7, VENUE_INFO, WEEKDAY_TW, web_url
from db import get_sessions, get_bookings, update_session
from notify import enqueue_msg
from shared_logic import get_session_open_date, is_casual_open_for_signup, is_member_only_session  # noqa: F401  (re-export)


# ─────────────────────────
# 場地 / 公告
# ─────────────────────────
def get_venue(weekday_int):
    """根據星期幾回傳場地資訊 dict，找不到回傳 None"""
    if weekday_int in (0, 4):
        return VENUE_INFO["weekday"]
    elif weekday_int == 6:
        return VENUE_INFO["sunday"]
    return None


def user_label(s):
    base = f"{s.get('date','')} ｜ {s.get('label','')} ｜ {s.get('start_time','')[:5]}-{s.get('end_time','')[:5]}"
    if is_member_only_session(s):
        base += " 👑"
    if s.get("cancelled"):
        base += f" ❌（{s.get('cancel_reason','')}）"
    elif s.get("locked"):
        base += " 🔒"
    return base


def get_announcement():
    if os.path.exists("announcement.txt"):
        with open("announcement.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


# ─────────────────────────
# 自動產生固定場次
# ─────────────────────────
def auto_generate_fixed_sessions(existing_sessions, today_date):
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new = False
    for i in range(14):
        check_date = today_date + timedelta(days=i)
        for rule in FIXED_RULES:
            if check_date.weekday() == rule["weekday"]:
                sid = f"{check_date.isoformat()}_{rule['start_time']}_fixed"
                if sid not in existing_keys:
                    try:
                        supabase.table("sessions").insert({
                            "id": sid, "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立",
                            "total_quota": rule.get("quota", Quota_7),
                            "casual_quota": rule.get("casual_quota", Limit_7),
                            "cancelled": False, "cancel_reason": "", "locked": False,
                        }).execute()
                        has_new = True
                    except Exception as e:
                        print(f"自動新增失敗: {e}")
    if has_new:
        get_sessions.clear()
        new_sessions = get_sessions()
        # 收集所有新場次數量，僅供日誌記錄，不再推播「新場次開放報名」通知
        # （會員習慣當天才報名，零打報名靠指定時間排程推播「報名」按鈕即可）
        new_count = 0
        for s in new_sessions:
            sid = s.get("id", "")
            if not sid.endswith("_fixed"):
                continue
            if sid in existing_keys:
                continue
            new_count += 1
        if new_count:
            print(f"[auto_generate] 新建立 {new_count} 個固定場次（不推播通知）")
        return new_sessions
    return existing_sessions


# ─────────────────────────
# 候補遞補通知
# ─────────────────────────
def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info):
    time.sleep(0.3)
    get_bookings.clear()
    updated = [b for b in get_bookings(sid) if b["status"] == "active"]

    # 先算會員佔用名額（會員不受限，但佔位子）
    member_total = sum(int(b["count"]) for b in updated if b["role"] == "member")
    casual_total = 0  # 零打累計（依序判斷是否遞補成功）

    for ub in updated:
        if ub["role"] == "member":
            continue  # 會員不需要通知
        cnt = int(ub["count"])
        # 判斷這筆零打在更新後的名單裡是否屬於正取
        if ub["id"] in old_waitlist_ids:
            # 計算目前該筆零打的遞補狀況
            current_pos = member_total + casual_total
            if current_pos < quota:
                # 計算遞補上了幾人 = min(報名人數, 剩餘名額)
                confirmed_count = min(cnt, quota - current_pos)

                # 發送 LINE 通知
                u_clean = ub["name"].split("_🔑")[0]

                # 判斷是「完全遞補」還是「部分遞補」
                if confirmed_count == cnt:
                    msg = f"📢【遞補成功】{u_clean} 報名場次 {session_label_info}\n恭喜您已全數遞補為正取 ({cnt} 人)！"
                else:
                    msg = f"📢【部分遞補】{u_clean} 報名場次 {session_label_info}\n您已遞補正取 {confirmed_count} 人 (原報名 {cnt} 人，尚有 {cnt - confirmed_count} 人候補)。"
                enqueue_msg(msg, "waitlist", tag="promotion", session_id=sid)
                # 處理完後，從待通知列表中移除該 ID（避免重複通知）
                old_waitlist_ids.remove(ub["id"])
        casual_total += cnt


# ─────────────────────────
# 自動通知：場次從會員限定變成開放時發通知（目前只補標記，不入列推播）
# ─────────────────────────
def check_and_send_open_notifications(session_map, today_date):
    """
    檢查今天是否有場次剛好進入開放日，若是且尚未通知則發送通知。
    用 Supabase sessions 表的 note 欄位記錄已通知的場次，格式加上 [已通知開放]。
    """
    for sid, s in session_map.items():
        # 跳過取消、鎖定、系統紀錄
        if s.get("cancelled") or s.get("locked"):
            continue
        if sid.startswith("_"):
            continue
        # 會員限定場次永遠不開放零打，跳過
        if is_member_only_session(s):
            continue
        # 已通知過，跳過
        if "[已通知開放]" in (s.get("note") or ""):
            continue

        try:
            s_date_obj = datetime.strptime(s["date"], "%Y-%m-%d").date()
        except Exception:
            continue

        # 跳過已過去的場次
        if s_date_obj < today_date:
            continue

        open_date = get_session_open_date(s_date_obj)

        # 開放時間點為開放日 UTC 00:00
        open_dt_utc = datetime(open_date.year, open_date.month, open_date.day,
                               0, 0, 0, tzinfo=ZoneInfo("UTC"))
        now_utc = datetime.now(ZoneInfo("UTC"))

        if now_utc < open_dt_utc:
            # 還未到開放時間，跳過
            continue

        # 開放日已過但標記遺漏（舊版發送失敗留下的殘留）
        # → 只補標記，不重複入列，避免對已過期場次重發通知
        if open_date < today_date:
            print(f"[check_and_send] sid={sid} 開放日已過 ({open_date})，補標記但不入列")
            current_note = (s.get("note") or "").strip()
            update_session(sid, {"note": f"{current_note} [已通知開放]".strip()})
            get_sessions.clear()
            continue

        # 今天剛好是開放日，但不再入列通知（改由 webhook.py 的每週排程處理）
        # 仍然要標記，避免這個場次被重複判斷成「今天是開放日」

        # 先寫 [已通知開放] 當鎖，防止多個 Streamlit session 重複處理
        current_note = (s.get("note") or "").strip()
        update_session(sid, {"note": f"{current_note} [已通知開放]".strip()})
        get_sessions.clear()

        print(f"[check_and_send] sid={sid} 已達開放日，不再入列通知（改由 webhook.py 排程處理）")


# ─────────────────────────
# 自動釋出零打上限（場次前一天 UTC 00:00）
# ─────────────────────────
def check_and_release_casual_limit(session_map):
    now_utc  = datetime.now(ZoneInfo("UTC"))
    # 每次重新計算今天，避免 app 長時間不重啟時 today_date 過期
    tomorrow = datetime.now(ZoneInfo("UTC")).date() + timedelta(days=1)
    print(f"[release_casual] now_utc={now_utc.strftime('%Y-%m-%d %H:%M')}, tomorrow={tomorrow}")

    for sid, s in session_map.items():
        if s.get("cancelled") or s.get("locked"):
            continue
        if "[已釋出名額]" in (s.get("note") or ""):
            continue
        try:
            s_date_obj = datetime.strptime(s["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if s_date_obj != tomorrow:
            continue

        # 前一天 UTC 00:00 才觸發
        release_dt_utc = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day,
            0, 0, 0, tzinfo=ZoneInfo("UTC")
        ) - timedelta(days=1)
        if now_utc < release_dt_utc:
            continue

        # 🔧 拆分時修正的 bug：原本這裡預設值寫的是 TOTAL_QUOTA_WEEKDAY /
        # CASUAL_QUOTA_WEEKDAY，但整個 app.py 裡從未定義過這兩個名字。
        # dict.get(key, default) 的 default 參數一定會被求值，所以只要有
        # 場次的 total_quota/casual_quota 欄位缺值，這裡就會直接 NameError
        # 導致這個排程直接中斷。這裡改用跟其他地方一致的 Quota_7 / Limit_7。
        total_q  = int(s.get("total_quota", Quota_7))
        casual_q = int(s.get("casual_quota", Limit_7))

        # 計算會員已佔用名額，剩餘開放給零打
        try:
            bks = supabase.table("bookings").select("*") \
                .eq("session_id", sid).eq("status", "active").execute().data or []
        except Exception as e:
            print(f"[release_casual] 讀取報名失敗: {e}")
            continue

        member_used  = sum(int(b["count"]) for b in bks if b["role"] == "member")
        new_casual_q = total_q - member_used  # 會員用掉後剩餘全給零打
        print(f"[release_casual] sid={sid} total={total_q} member_used={member_used} new_casual_q={new_casual_q} old_casual_q={casual_q}")

        current_note = (s.get("note") or "").strip()

        if new_casual_q <= casual_q:
            # 無需擴增，只補標記
            print(f"[release_casual] sid={sid} 無需釋出（new={new_casual_q} <= old={casual_q}）")
            update_session(sid, {"note": f"{current_note} [已釋出名額]".strip()})
            get_sessions.clear()
            continue

        wd_str   = WEEKDAY_TW[s_date_obj.weekday()]
        start    = s.get("start_time", "")[:5]
        end      = s.get("end_time", "")[:5]
        label    = s.get("label", "")
        released = new_casual_q - casual_q
        msg = (
            f"🎉【信義羽球隊】明天場次釋出零打名額！\n"
            f"📅 {s['date']}（週{wd_str}）{label} {start}–{end}\n"
            f"零打名額由 {casual_q} 人擴增至 {new_casual_q} 人（多釋出 {released} 個）\n"
            f"候補球友請把握機會！👉 {web_url}/"
        )
        print(f"[release_casual] sid={sid} casual_quota {casual_q} → {new_casual_q}")

        # 先寫標記+更新名額，再入列通知
        update_session(sid, {
            "casual_quota": new_casual_q,
            "note": f"{current_note} [已釋出名額]".strip()
        })
        get_sessions.clear()
        enqueue_msg(msg, "waitlist", tag="release", session_id=sid)
