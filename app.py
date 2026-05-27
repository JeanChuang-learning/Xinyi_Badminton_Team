import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import time

# ─────────────────────────
# config
# ─────────────────────────
ADMIN_PASSWORD = "admin"

ROLE_MAP = {"會員": "member", "零打": "casual"}

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
    res = (
        supabase.table("bookings")
        .select("*")
        .eq("session_id", session_id)
        .execute()
    )
    return res.data or []


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

# ─────────────────────────
# UI
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# load sessions & 自動時間範圍篩選
# ─────────────────────────
sessions = get_sessions()

# 1. 計算篩選邊界值
today = date.today()
start_bound = today - timedelta(days=3)  # 過去 3 天
end_bound = today + timedelta(days=7)    # 未來 1 週

# 2. 進行時間區間篩選與排序
filtered_sessions = []
for s in sessions:
    if not s.get("date"):
        continue
    try:
        # 將資料庫中的日期字串轉換為 date 物件進行比較
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if start_bound <= session_date <= end_bound:
            filtered_sessions.append(s)
    except ValueError:
        # 預防資料庫日期格式不符 (%Y-%m-%d) 導致報錯
        continue

# 3. 排序篩選後的場次
sessions_sorted = sorted(
    filtered_sessions,
    key=lambda s: (s["date"], s["start_time"])
)

session_map = {
    s["id"]: s
    for s in sessions_sorted
    if s.get("id")
}

if not session_map:
    st.warning(f"目前沒有該時間區間內（{start_bound} ~ {end_bound}）的場次")
    st.stop()

selected_id = st.selectbox(
    "選擇場次",
    list(session_map.keys()),
    format_func=lambda x: user_label(session_map[x])
)

session = session_map[selected_id]
sid = selected_id

# ─────────────────────────
# bookings
# ─────────────────────────
bookings = get_bookings(sid)
active = [b for b in bookings if b["status"] == "active"]

used = sum(b["count"] for b in active)
quota = session.get("total_quota", 20)

st.caption(f"使用：{used}/{quota}")

if session.get("cancelled"):
    st.warning("⚠ 此場次已取消")
    st.stop()

if session.get("locked"):
    st.error("❌ 此場次已關閉")
    st.stop()

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

        # ── 恢復場次 ──
        st.subheader("🔄 恢復場次")

        # 這裡同步修正為只顯示篩選範圍內已取消的場次，避免選單過長
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

        # ── 新增場次 ──
        st.subheader("➕ 新增場次")

        new_date = st.date_input("日期", key="new_date")
        new_start = st.text_input("開始時間", "19:00", key="new_start").strip()
        new_end = st.text_input("結束時間", "22:00", key="new_end").strip()
        new_label = st.text_input("名稱", "自訂場次", key="new_label").strip()
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
