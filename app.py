import streamlit as st
import json
import os
from datetime import date, timedelta
import pytz

from booking_service import add_user, get_queue_view, cancel_user

# ── 設定 ─────────────────────────────
ADMIN_PASSWORD = "admin1234"
DATA_FILE = "data.json"

WEEKS_AHEAD = 3

FIXED_SESSIONS = [
    {"weekday": 0, "start": "19:00", "end": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start": "19:00", "end": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start": "07:00", "end": "11:00", "label": "週日早上"},
]

ROLE_DISPLAY = {
    "member": "會員",
    "casual": "零打",
}

ROLE_MAP = {
    "會員": "member",
    "零打": "casual",
}

# ── UI ─────────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

# ── data ─────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sessions": {}}
    return json.load(open(DATA_FILE, "r", encoding="utf-8"))

def save_data(data):
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ── session init（關鍵穩定點） ─────────────────────────────
def get_session(data, sid):
    if "sessions" not in data:
        data["sessions"] = {}

    if sid not in data["sessions"]:
        data["sessions"][sid] = {
            "members": [],
            "cancelled": False,
            "cancel_reason": ""
        }

    return data["sessions"][sid]

# ── sessions generator ─────────────────────────────
def generate_sessions():
    today = date.today()
    sessions = []

    for week in range(WEEKS_AHEAD + 1):
        for cfg in FIXED_SESSIONS:
            days_ahead = (cfg["weekday"] - today.weekday()) % 7
            d = today + timedelta(days=days_ahead + week * 7)

            sid = f"{d.isoformat()}_{cfg['start']}"

            sessions.append({
                "id": sid,
                "date": d,
                "label": cfg["label"],
                "start": cfg["start"],
                "end": cfg["end"]
            })

    return sessions


# ── load ─────────────────────────────
data = load_data()
sessions = generate_sessions()

session_map = {
    f"{s['date']} {s['label']} {s['start']}": s
    for s in sessions
}

selected = st.selectbox("選擇場次", list(session_map.keys()))
session = session_map[selected]
sid = session["id"]

# ✔ 一定要在 UI 前初始化
sdata = get_session(data, sid)
members = sdata["members"]

# ── queue（如果 booking_service 有實作） ─────────────────────────────
confirmed, waitlist = get_queue_view(sdata)

st.caption(f"報名人數：{len(members)}")

# ── cancel banner ─────────────────────────────
if sdata.get("cancelled"):
    st.error(f"❌ 本場次已取消\n{sdata.get('cancel_reason','')}")
    st.stop()

# ── 報名區 ─────────────────────────────
col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name_input = st.text_input("名字", placeholder="輸入名字")

with col2:
    role_label = st.selectbox("身分", ["會員", "零打"])

with col3:
    count = st.number_input(
        "人數",
        min_value=1,
        max_value=10,
        value=1
    )
    
#報名按鈕
if st.button("報名", type="primary"):
    name = name_input.strip()

    if not name:
        st.warning("請輸入名字")
    else:
        role = ROLE_MAP[role_label]

        result = add_user(
            data,
            sid,
            name,
            role,
            count   # ✔ 加這個
        )

        if result == "already_exists":
            st.info("已經報名過了")
        else:
            save_data(data)
            st.success("報名成功")
            st.rerun()

# ── 名單 ─────────────────────────────
st.subheader("📋 報名名單")

members = sdata["members"]

for i, m in enumerate(members, 1):
    role_text = ROLE_DISPLAY.get(m["role"], "未知")
    count = m.get("count", 1)

    col1, col2 = st.columns([4, 1])

    with col1:
        st.write(f"{i}. {m['name']} x{count} ({role_text})")

    with col2:
        if st.button("取消", key=f"cancel_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()

# ── 候補（如果有 queue） ─────────────────────────────
st.subheader("候補")

for i, m in enumerate(waitlist, 1):
    col1, col2 = st.columns([4, 1])

    with col1:
        st.write(f"{i}. {m['name']}")

    with col2:
        if st.button("取消", key=f"wait_cancel_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()

# ── admin ─────────────────────────────
with st.expander("管理"):
    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.success("admin mode")

        if st.button("取消本場次"):
            sdata["cancelled"] = True
            sdata["cancel_reason"] = "admin cancel"
            save_data(data)
            st.rerun()

        if st.button("恢復場次"):
            sdata["cancelled"] = False
            sdata["cancel_reason"] = ""
            save_data(data)
            st.rerun()
