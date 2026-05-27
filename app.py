import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import time

# ─────────────────────────
# config
# ─────────────────────────
ADMIN_PASSWORD = "admin"

ROLE_MAP = {"會員": "member", "零打": "casual"}

# 固定場次規則：0=週一, 4=週五, 6=週日
FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日早上"},
]

# ─────────────────────────
# helpers
# ─────────────────────────
def user_label(s):
    base = f"{s['date']}｜{s['label']}｜{s['start_time']}-{s['end_time']}"
    if s.get("cancelled"):
        return f"{base} ❌不開放（{s.get('cancel_reason', '')}）"
    if s.get("locked"):
        return f"{base} 🔒關閉報名"
    return base

# ─────────────────────────
# Supabase layer
# ─────────────────────────
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()
        return res.data or []
    except Exception as e:
        st.exception(e)
        return []


def get_bookings(session_id):
    try:
        res = (
            supabase.table("bookings")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
        return res.data or []
    except Exception as e:
        st.error(f"💥 讀取報名資料失敗：{e}")
        return []


def add_booking(session_id, name, role, count):
    try:
        supabase.table("bookings").insert({
            "session_id": session_id,
            "name": name,
            "role": role,
            "count": count,
            "status": "active",
        }).execute()
    except Exception as e:
        st.error(f"💥 寫入資料庫失敗！真實原因：{e}")
        st.stop()


def cancel_booking(booking_id):
    supabase.table("bookings") \
        .update({"status": "cancelled"}) \
        .eq("id", booking_id) \
        .execute()


def update_session(session_id, payload):
    supabase.table("sessions") \
        .update(payload) \
        .eq("id", session_id) \
        .execute()


def auto_generate_fixed_sessions(existing_sessions):
    """💡 升級：自動檢查並建立未來 35 天（約一個月）內的固定場次"""
    today = date.today()
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new_inserted = False

    # 檢查範圍拉長到未來 35 天
    for i in range(36):
        check_date = today + timedelta(days=i)
        w = check_date.weekday()

        for rule in FIXED_RULES:
            if w == rule["weekday"]:
                session_id = f"{check_date.isoformat()}_{rule['start_time']}_fixed"

                if session_id not in existing_keys:
                    try:
                        supabase.table("sessions").insert({
                            "id": session_id,
                            "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立的固定場次",
                            "total_quota": 20,
                            "cancelled": False,
                            "cancel_reason": "",
                            "locked": False,
                        }).execute()
                        has_new_inserted = True
                    except Exception as e:
                        print(f"自動新增場次失敗: {e}")

    if has_new_inserted:
        return get_sessions()
    return existing_sessions

# ─────────────────────────
# UI 初始化
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# 載入所有場次
# ─────────────────────────
raw_sessions = get_sessions()
sessions = auto_generate_fixed_sessions(raw_sessions)

today = date.today()

# ── 篩選 1：一般使用者看得到的場次（過去 3 天 ~ 未來 7 天） ──
user_start_bound = today - timedelta(days=3)
user_end_bound = today + timedelta(days=7)

# ── 篩選 2：💡 管理員看得到且管得到的場次（過去 3 天 ~ 未來 35 天） ──
admin_start_bound = today - timedelta(days=3)
admin_end_bound = today + timedelta(days=35)

user_filtered = []
admin_filtered = []

for s in sessions:
    if not s.get("date"):
        continue
    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        # 分流歸類
        if user_start_bound <= session_date <= user_end_bound:
            user_filtered.append(s)
        if admin_start_bound <= session_date <= admin_end_bound:
            admin_filtered.append(s)
    except ValueError:
        continue

# 排序
user_sorted = sorted(user_filtered, key=lambda s: (s["date"], s["start_time"]))
admin_sorted = sorted(admin_filtered, key=lambda s: (s["date"], s["start_time"]))

# 建立一般使用者的對照字典
session_map = {s["id"]: s for s in user_sorted if s.get("id")}

# 建立管理員專用的對照字典（包含未來
