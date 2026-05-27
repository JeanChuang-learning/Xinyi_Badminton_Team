import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import time

# ─────────────────────────
# config
# ─────────────────────────
ADMIN_PASSWORD = "admin"

ROLE_MAP = {"會員": "member", "零打": "casual"}

# 你要求的固定場次規則
# weekday: 0=週一, 4=週五, 6=週日
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
        # 暫時把真實錯誤印在畫面上
        st.error(f"Supabase 報錯了！真實原因：{e}")
        return []


def add_booking(session_id, name, role, count):
    supabase.table("bookings").insert({
        "session_id": session_id,
        "name": name,
        "role": role,
        "count": count,
        "status": "active",
    }).execute()


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

# 💡 自動建立固定場次的邏輯
def auto_generate_fixed_sessions(existing_sessions):
    """
    檢查從今天開始算起，未來 14 天內的所有固定場次。
    如果資料庫裡沒有，就自動幫忙新增進去。
    """
    today = date.today()
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new_inserted = False

    # 檢查未來 14 天內的場次（確保下週與本週都有被涵蓋到）
    for i in range(15):
        check_date = today + timedelta(days=i)
        w = check_date.weekday()

        for rule in FIXED_RULES:
            if w == rule["weekday"]:
                # 建立這場固定場次在資料庫的唯一 ID，格式如：2026-06-01_19:00_fixed
                session_id = f"{check_date.isoformat()}_{rule['start_time']}_fixed"

                # 如果這個場次不在現有的資料庫內，就自動塞入
                if session_id not in existing_keys:
                    try:
                        supabase.table("sessions").insert({
                            "id": session_id,
                            "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立的固定場次",
                            "total_quota": 20, # 預設正取人數
                            "cancelled": False,
                            "cancel_reason": "",
                            "locked": False,
                        }).execute()
                        has_new_inserted = True
                    except Exception as e:
                        print(f"自動新增場次失敗: {e}")

    # 如果剛才有偷偷在背景塞新場次，就重新撈取一次最新場次列表
    if has_new_inserted:
        return get_sessions()
    return existing_sessions

# ─────────────────────────
# UI
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# load & auto check sessions
# ─────────────────────────
raw_sessions = get_sessions()
# 🚀 在這裡執行自動檢查與建立
sessions = auto_generate_fixed_sessions(raw_sessions)

# 計算篩選範圍（過去 3 天 ~ 未來 7 天）
today = date.today()
start_bound = today - timedelta(days=3)
end_bound = today + timedelta(days=7)

filtered_sessions = []
for s in sessions:
    if not s.get("date"):
        continue
    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if start_bound <= session_date <= end_bound:
            filtered_sessions.append(s)
    except ValueError:
        continue

sessions_sorted = sorted(
    filtered_sessions,
    key=lambda s: (s["date"], s["start_time"])
)

session_map = {
    s["id"]: s
    for s in sessions_sorted
    if s.get("id")
}

# ─────────────────────────
# bookings & signup & list
# ─────────────────────────
if session_map:
    selected_id = st.selectbox(
        "選擇場次",
        list(session_map.keys()),
        format_func=lambda x: user_label(session_map[x])
    )

    session = session_map[selected_id]
    sid = selected_id

    bookings = get_bookings(sid)
    active = [b for b in bookings if b["status"] == "active"]

    used = sum(b["count"] for b in active)
    quota = session.get("total_quota", 20)

    st.caption(f"使用：{used}/{quota}")

    if session.get("cancelled"):
        st.warning("⚠ 此場次已取消")
    elif session.get("locked"):
        st.error("❌ 此場次已關閉")
    else:
        # ─────────────────────────
        # signup 
        # ─────────────────────────
        st.divider()
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            name = st.text_input("名字")
        with col2:
            role = ROLE_MAP[st.selectbox("身分", ["會員", "零打"])]
        with col3:
            count = st.number_input("人數", 1, 10, 1)

        if st.button("報名", type="primary"):
            if not name.strip():
                st.error("請輸入名字")
            else:
                add_booking(sid, name.strip(), role, int(count))
                st.success("報名成功")
                st.rerun()

    # ─────────────────────────
    # list
    # ─────────────────────────
    st.subheader("👥 名單")
    for b in active:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.write(f"{b['name']} ｜ {b['count']} 人 ｜ {b['role']}")
        with col2:
            if st.session_state.get("is_admin"):
                if st.button("取消", key=f"cancel_{b['id']}"):
                    cancel_booking(b["id"])
                    st.rerun()
else:
    st.info("💡 目前暫無本週內場次，請管理員登入下方「🔒 管理」建立新場次。")
    active = []

# ─────────────────────────
# admin
# ─────────────────────────
st.divider()

with st.expander("🔒 管理"):
    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.session_state["is_admin"] = True

        # ── 取消場次 ──
        st.subheader("❌ 取消場次")
        if session_map:
            cancel_target = st.selectbox(
                "場次",
                list(session_map.keys()),
                format_func=lambda x: user_label(session_map[x]),
                key="cancel_target"
            )
            reason = st.text_input("原因", key="cancel_reason")

            if st.button("取消場次"):
                update_session(cancel_target, {
                    "cancelled": True,
                    "cancel_reason": reason,
                })
                st.success("已取消")
                st.rerun()
        else:
            st.caption("沒有可取消的場次")

        # ── 恢復場次 ──
        st.subheader("🔄 恢復場次")
        cancelled_sessions = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map = {s["id"]: s for s in cancelled_sessions}

        if restore_map:
            restore_target = st.selectbox(
                "選擇要恢復的場次",
                list(restore_map.keys()),
                format_func=lambda x: user_label(restore_map[x]),
                key="restore_target"
            )
            if st.button("恢復場次"):
                update_session(restore_target, {
                    "cancelled": False,
                    "cancel_reason": "",
                })
                st.success("已恢復")
                st.rerun()
        else:
            st.caption("目前範圍內沒有已取消的場次")

        # ── 新增額外場次 ──
        st.subheader("➕ 新增額外臨時場次")

        new_date = st.date_input("日期", key="new_date")
        new_start = st.text_input("開始時間", "19:00", key="new_start").strip()
        new_end = st.text_input("結束時間", "22:00", key="new_end").strip()
        new_label = st.text_input("名稱", "加開場次", key="new_label").strip()
        new_quota = st.number_input("名額", min_value=1, max_value=200, value=20, key="new_quota")
        new_note = st.text_area("備註", key="new_note")

        if st.button("新增場次"):
            if not new_label:
                st.error("請填寫場次名稱")
            else:
                new_id = f"{new_date}_{new_start}_{int(time.time())}"
                supabase.table("sessions").insert({
                    "id": new_id,
                    "date": str(new_date),
                    "start_time": new_start,
                    "end_time": new_end,
                    "label": new_label,
                    "note": new_note,
                    "total_quota": new_quota,
                    "cancelled": False,
                    "cancel_reason": "",
                    "locked": False,
                }).execute()
                st.success("新增成功")
                st.rerun()

    elif pwd:
        st.error("密碼錯誤")
