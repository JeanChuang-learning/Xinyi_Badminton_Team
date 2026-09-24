"""
db.py —— 純資料庫存取層：sessions、bookings、checkins、admin_line_config、system_settings。

原則：這裡的函式只負責讀寫 Supabase，不包含業務規則判斷
（正取/候補演算法、開放時間規則等放在 logic.py）。
"""

import json

import streamlit as st
from supabase_client import supabase

from config import SYSTEM_ROW_IDS


# ─────────────────────────
# sessions
# ─────────────────────────
@st.cache_data(ttl=60)
def get_sessions():
    try:
        rows = supabase.table("sessions").select("*").execute().data or []
        return [r for r in rows if r.get("id") not in SYSTEM_ROW_IDS and not (r.get("id") or "").startswith("_")]
    except Exception as e:
        st.exception(e)
        return []


def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()
    get_sessions.clear()


# ─────────────────────────
# bookings
# ─────────────────────────
@st.cache_data(ttl=30)
def get_bookings(session_id):
    try:
        return supabase.table("bookings").select("*").eq("session_id", session_id).order("created_at", desc=False).execute().data or []
    except Exception as e:
        st.error(f"讀取失敗：{e}")
        return []


def add_booking_compatible(session_id, name, role, count, password, payment_method=None):
    composite = f"{name}_🔑{password}_🔄0"
    try:
        supabase.table("bookings").insert({
            "session_id": session_id, "name": composite,
            "role": role, "count": count, "status": "active",
            "payment_method": payment_method,
        }).execute()
        get_bookings.clear()
    except Exception as e:
        st.error(f"寫入失敗：{e}")
        st.stop()


def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    """
    修改一筆報名的人數／姓名／狀態。
    回傳 True＝更新成功；False＝失敗（已用 st.error 顯示友善訊息，資料未被更動）。
    呼叫端請檢查回傳值，失敗時不要顯示「已更新」、也不要 st.rerun()（會把錯誤訊息洗掉）。
    """
    payload = {"count": new_count, "status": status}
    if new_name:
        payload["name"] = new_name
    try:
        supabase.table("bookings").update(payload).eq("id", booking_id).execute()
    except Exception as e:
        print(f"[update_booking_data] 更新失敗 booking_id={booking_id}: {e}")
        st.error("修改失敗，請稍後再試。如果一直失敗，請聯絡管理員。")
        return False
    get_bookings.clear()
    return True


def promote_waitlist(booking_id):
    """將候補者標記為正取（在 bookings.name 加上 [遞補] 標記）"""
    try:
        row = supabase.table("bookings").select("name").eq("id", booking_id).execute().data
        if row:
            old_name = row[0]["name"]
            if "[遞補]" not in old_name:
                supabase.table("bookings").update({"name": old_name + "[遞補]"}) \
                    .eq("id", booking_id).execute()
                get_bookings.clear()
    except Exception as e:
        st.error(f"遞補失敗：{e}")


def cancel_booking(booking_id, session_id=None):
    """
    取消（刪除）一筆報名。
    回傳 True＝取消成功；False＝取消失敗（已用 st.error 顯示友善訊息，報名資料未被刪除）。
    呼叫端請檢查回傳值，失敗時不要顯示「已取消」、也不要 st.rerun()（會把錯誤訊息洗掉）。

    ⚠️ 這個函式只負責刪除，**不發遞補通知**。遞補通知統一由呼叫端在取消成功後呼叫
    logic.check_and_notify_waitlist()（走 shared_logic.compute_allocation，同時看
    total_quota 與 casual_quota）。2026-09 以前這裡自己用 total_quota 算一次遞補並入列通知，
    有兩個問題：① 沒看 casual_quota，零打上限仍滿時會誤發；② 管理員刪除報名時，呼叫端又
    呼叫 check_and_notify_waitlist()，同一位候補會收到兩則通知。

    session_id 參數已不再使用，保留只是為了相容舊的呼叫方式。
    """
    try:
        supabase.table("bookings").delete().eq("id", booking_id).execute()
    except Exception as e:
        print(f"[cancel_booking] 刪除失敗 booking_id={booking_id}: {e}")
        st.error("取消失敗，請稍後再試。如果一直失敗，請聯絡管理員。")
        return False
    get_bookings.clear()
    return True


# ─────────────────────────
# checkins
# ─────────────────────────
def get_checkins(session_id):
    """讀取本場所有簽到紀錄，回傳 {booking_id: True} dict"""
    try:
        rows = supabase.table("checkins").select("*").eq("session_id", session_id).execute().data or []
        return {r["booking_id"]: True for r in rows}
    except Exception:
        return {}


def set_checkin(session_id, booking_id, checked: bool):
    """新增或刪除簽到紀錄"""
    try:
        if checked:
            # upsert 避免重複：checkins 的主鍵是 id（uuid），不是 (session_id, booking_id)，
            # 所以一定要明確指定 on_conflict，PostgREST 才知道要拿哪個欄位組合判斷衝突。
            # 前提是 Supabase 那邊要對 (session_id, booking_id) 建 UNIQUE 索引，
            # 否則這裡指定 on_conflict 會直接報錯（無法比對到不存在的 constraint）。
            supabase.table("checkins").upsert({
                "session_id": session_id,
                "booking_id": booking_id,
            }, on_conflict="session_id,booking_id").execute()
        else:
            supabase.table("checkins").delete() \
                .eq("session_id", session_id) \
                .eq("booking_id", booking_id).execute()
    except Exception as e:
        st.error(f"簽到寫入失敗：{e}")


# ─────────────────────────
# 聯絡人名單（借用 sessions 表的 _admin_line_config 特殊列）
# ─────────────────────────
def get_db_admin_line_list():
    try:
        res = supabase.table("sessions").select("*").eq("id", "_admin_line_config").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    return {}


def save_db_admin_line_list(config_dict):
    try:
        json_str = json.dumps(config_dict, ensure_ascii=False)
        res = supabase.table("sessions").select("id").eq("id", "_admin_line_config").execute()
        if res.data:
            supabase.table("sessions").update({"note": json_str}).eq("id", "_admin_line_config").execute()
        else:
            supabase.table("sessions").insert({
                "id": "_admin_line_config", "date": "1970-01-01",
                "start_time": "00:00", "end_time": "00:00",
                "label": "CONFIG", "note": json_str,
                "total_quota": 0, "cancelled": True,
            }).execute()
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False


# ─────────────────────────
# 系統全域設定（借用 sessions 表的 _system_settings 特殊列）
# ─────────────────────────
def get_system_settings():
    """讀取系統全域設定"""
    try:
        res = supabase.table("sessions").select("*").eq("id", "_system_settings").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    return {"shuttlecock": "VOLAR 50", "casual_fee": 220}


def save_system_settings(settings_dict):
    """儲存系統全域設定"""
    try:
        json_str = json.dumps(settings_dict, ensure_ascii=False)
        res = supabase.table("sessions").select("id").eq("id", "_system_settings").execute()
        if res.data:
            supabase.table("sessions").update({"note": json_str}).eq("id", "_system_settings").execute()
        else:
            supabase.table("sessions").insert({
                "id": "_system_settings", "date": "1970-01-01",
                "start_time": "00:00", "end_time": "00:00",
                "label": "SETTINGS", "note": json_str,
                "total_quota": 0, "cancelled": True
            }).execute()
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False
