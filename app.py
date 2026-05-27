import streamlit as st
from supabase_client import supabase

# ─────────────────────────
# config
# ─────────────────────────
ADMIN_PASSWORD = "admin"

ROLE_MAP = {"會員": "member", "零打": "casual"}

# ─────────────────────────
# Supabase layer
# ─────────────────────────
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()

        st.write(res)

        return res.data or []

    except Exception as e:
        st.exception(e)
        return []


def get_bookings(session_id):
    res = supabase.table("bookings") \
        .select("*") \
        .eq("session_id", session_id) \
        .execute()
    return res.data or []


def add_booking(session_id, name, role, count):
    supabase.table("bookings").insert({
        "session_id": session_id,
        "name": name,
        "role": role,
        "count": count,
        "status": "active"
    }).execute()


def cancel_booking(session_id, name):
    supabase.table("bookings") \
        .update({"status": "cancelled"}) \
        .eq("session_id", session_id) \
        .eq("name", name) \
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
# load sessions (PURE SOURCE)
# ─────────────────────────
sessions = get_sessions()

sessions_sorted = sorted(
    sessions,
    key=lambda s: (s["date"], s["start_time"])
)

session_map = {s["id"]: s for s in sessions_sorted}

# label
def user_label(s):
    base = f"{s['date']}｜{s['label']}｜{s['start_time']}-{s['end_time']}"

    if s.get("cancelled"):
        return f"{base} ❌不開放（{s.get('cancel_reason','')}）"

    if s.get("locked"):
        return f"{base} 🔒關閉報名"

    return base


options = {sid: user_label(s) for sid, s in session_map.items()}

selected_id = st.selectbox(
    "選擇場次",
    list(options.keys()),
    format_func=lambda x: options[x]
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
        st.write(f"{b['name']} ｜ {b['count']} ｜ {b['role']}")

    with col2:
        if st.session_state.get("is_admin"):
            if st.button("取消", key=f"{sid}_{b['name']}"):
                cancel_booking(sid, b["name"])
                st.rerun()

# ─────────────────────────
# admin
# ─────────────────────────
st.divider()

with st.expander("🔒 管理"):

    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.session_state["is_admin"] = True

        st.subheader("❌ 取消場次")

        cancel_target = st.selectbox(
            "場次",
            list(session_map.keys()),
            format_func=lambda x: user_label(session_map[x])
        )

        reason = st.text_input("原因")

        if st.button("取消"):
            update_session(cancel_target, {
                "cancelled": True,
                "cancel_reason": reason
            })
            st.rerun()

        st.subheader("🔄 恢復場次")

        cancelled = [s for s in sessions_sorted if s.get("cancelled")]

        restore_map = {s["id"]: s for s in cancelled}

        if restore_map:
            restore_target = st.selectbox(
                "選擇",
                list(restore_map.keys()),
                format_func=lambda x: user_label(restore_map[x])
            )

            if st.button("恢復"):
                update_session(restore_target, {
                    "cancelled": False,
                    "cancel_reason": ""
                })
                st.rerun()

        st.subheader("➕ 新增場次")

        new_date = st.date_input("日期")
        new_start = st.text_input("開始時間", "19:00").strip()
        new_end = st.text_input("結束時間", "22:00").strip()
        new_label = st.text_input("名稱", "自訂場次").strip()
        new_note = st.text_area("備註")

        if st.button("新增"):
            new_id = f"{new_date}_{new_start}"

            supabase.table("sessions").insert({
                "id": new_id,
                "date": str(new_date),
                "start_time": new_start,
                "end_time": new_end,
                "label": new_label,
                "note": new_note,
                "total_quota": 20,
                "cancelled": False,
                "cancel_reason": "",
                "locked": False
            }).execute()

            st.success("新增成功")
            st.rerun()
