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
from shared_logic import get_session_open_date, is_casual_open_for_signup, is_member_only_session, compute_allocation  # noqa: F401  (re-export)


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
def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info,
                              session=None, old_confirmed=None):
    """
    名單異動後（修改人數 / 取消 / 管理員調整），對「原本在候補」的零打補發遞補通知。

    判斷正取/候補一律走 shared_logic.compute_allocation（同時受 total_quota 與
    casual_quota 限制）。舊版只用 total_quota（`quota` 參數）判斷，零打名額（casual_quota）
    還是滿的、但總名額有空位時（例如會員取消），會誤發「遞補成功」，跟網站實際算出的候補
    狀態兜不起來。

    old_waitlist_ids：異動前有候補的報名 id。
    old_confirmed：{報名 id: 異動前已正取人數}（全數候補為 0，部分正取為已正取那幾人）。
                   只有「正取人數比異動前變多」才發通知，避免部分候補的報名在別人
                   異動時被重複通知。沒傳的 id 視為 0。
    session：該場次資料；沒傳就從 get_sessions() 找最新的。`quota` 參數保留是為了相容
             舊的呼叫方式，只有找不到場次資料時才當備援。
    """
    # 遞補通知是附帶功能：呼叫它時，取消／修改報名本身已經成功了，這裡出任何錯都只記 log，
    # 不能讓使用者看到 traceback、也不能讓後面的 st.success / st.rerun 跑不到。
    try:
        time.sleep(0.3)
        get_bookings.clear()
        updated = [b for b in get_bookings(sid) if b["status"] == "active"]

        if session is None:
            session = next((s for s in get_sessions() if s.get("id") == sid), None) or {"total_quota": quota}

        allocated, _ = compute_allocation(session, updated)
        old_confirmed = old_confirmed or {}

        for ub in allocated:
            if ub["role"] == "member":
                continue  # 會員不需要通知
            if ub["id"] not in old_waitlist_ids:
                continue
            cnt = int(ub["count"])
            confirmed_count = int(ub["confirmed_count"])
            if confirmed_count <= int(old_confirmed.get(ub["id"], 0)):
                continue  # 正取人數沒有增加（仍在候補），不通知

            u_clean = ub["name"].split("_🔑")[0]
            if confirmed_count >= cnt:
                msg = f"📢【遞補成功】{u_clean} 報名場次 {session_label_info}\n恭喜您已全數遞補為正取 ({cnt} 人)！"
            else:
                msg = f"📢【部分遞補】{u_clean} 報名場次 {session_label_info}\n您已遞補正取 {confirmed_count} 人 (原報名 {cnt} 人，尚有 {cnt - confirmed_count} 人候補)。"
            enqueue_msg(msg, "waitlist", tag="promotion", session_id=sid)
            # 處理完後，從待通知列表中移除該 ID（避免重複通知）
            old_waitlist_ids.discard(ub["id"])
    except Exception as e:
        print(f"[check_and_notify_waitlist] sid={sid} 遞補通知處理失敗（不影響取消／修改結果）: {e}")


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
        # 會員限定場次零打完全不開放，沒有「釋出零打名額」這件事；而且這則通知是發零打群，
        # 會洩漏會員限定場次的存在與時間，違反「會員限定場次完全不通知零打群」的規則。
        if is_member_only_session(s):
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
        # 欄位存在但值是 NULL 時，dict.get(key, default) 不會用 default（回傳 None），
        # int(None) 會讓整個排程中斷；casual_quota = 0 是合法值，不能用 `or` 補預設。
        _tq = s.get("total_quota")
        _cq = s.get("casual_quota")
        total_q  = int(Quota_7 if _tq is None else _tq)
        casual_q = int(Limit_7 if _cq is None else _cq)

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
