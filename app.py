import streamlit as st
import json
import os
from datetime import date, timedelta

from booking_service import add_user, cancel_user

# ─────────────────────────────
# 設定
# ─────────────────────────────
ADMIN_PASSWORD = "admin1234"
DATA_FILE = "data.json"
WEEKS_AHEAD = 3
DEFAULT_QUOTA = 20

FIXED_SESSIONS = [
    {"weekday": 0, "start": "19:00", "end": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start": "19:00", "end": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start": "07:00", "end": "11:00", "label": "週日早上"},
]

ROLE_MAP = {
    "會員": "member",
    "零打": "casual",
}

# ─────────────────────────────
# UI 基礎
# ─────────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 社團羽球報名系統")

# ─────────────────────────────
# session state（訊息控制）
# ─────────────────────────────
if "flash" not in st.session_state:
    st.session_state.flash = None
    st.session_state.flash_type = None


def show_flash():
    if st.session_state.flash:
        if st.session_state.flash_type == "success":
            st.success(st.session_state.flash)
        else:
            st.error(st.session_state.flash)

        st.session_state.flash = None
        st.session_state.flash_type = None


# ─────────────────────────────
# data IO
# ─────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sessions": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────
# session init
# ─────────────────────────────
def get_session(data, sid):
    data.setdefault("sessions", {})
    s = data["sessions"].setdefault(sid, {})

    s.setdefault("members", [])
    s.setdefault("total_quota", DEFAULT_QUOTA)
    s.setdefault("cancelled", False)
    s.setdefault("cancel_reason", "")

    return s


# ─────────────────────────────
# queue rule（核心）
# ─────────────────────────────
def build_queue(members, quota):
    members = sorted(members, key=lambda x: x["role"] != "member")

    used = 0
    confirmed = []
    waitlist = []

    for m in members:
        cnt = m.get("count", 1)

        if used + cnt <= quota:
            confirmed.append(m)
            used += cnt
        else:
            waitlist.append(m)

    return confirmed, waitlist, used


# ─────────────────────────────
# sessions
# ─────────────────────────────
def generate_sessions():
    today = date.today()
    sessions = []

    for w in range(WEEKS_AHEAD + 1):
        for cfg in FIXED_SESSIONS:
            days = (cfg["weekday"] - today.weekday()) % 7
            d = today + timedelta(days=days + w * 7)

            sid = f"{d.isoformat()}_{cfg['start']}"

            sessions.append({
                "id": sid,
                "label": cfg["label"],
                "date": d,
                "start": cfg["start"],
                "end": cfg["end"]
            })

    return sessions


# ─────────────────────────────
# load
# ─────────────────────────────
data = load_data()
sessions = generate_sessions()

session_map = {
    f"{s['date']}｜{s['label']}｜{s['start']}-{s['end']}": s
    for s in sessions
}

selected = st.selectbox("選擇場次", list(session_map.keys()))
session = session_map[selected]
sid = session["id"]

sdata = get_session(data, sid)
members = sdata["members"]
quota = sdata["total_quota"]

confirmed, waitlist, used = build_queue(members, quota)

member_count = sum(m.get("count", 1) for m in confirmed if m["role"] == "member")
casual_count = sum(m.get("count", 1) for m in confirmed if m["role"] == "casual")


# ─────────────────────────────
# cancel check
# ─────────────────────────────
if sdata.get("cancelled"):
    st.error(f"❌ 已取消\n{sdata.get('cancel_reason','')}")
    st.stop()


# ─────────────────────────────
# status bar
# ─────────────────────────────
st.caption(
    f"👥 使用 {used}/{quota} ｜ "
    f"👤 會員 {member_count} ｜ "
    f"👥 零打 {casual_count}"
)

show_flash()

st.divider()


# ─────────────────────────────
# signup
# ─────────────────────────────
col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name = st.text_input("名字")

with col2:
    role_label = st.selectbox("身分", ["會員", "零打"])

with col3:
    count = st.number_input("人數", 1, 10, 1)

role = ROLE_MAP[role_label]


def signup():
    global members

    if not name.strip():
        st.session_state.flash = "請輸入名字"
        st.session_state.flash_type = "error"
        return

    confirmed, waitlist, used = build_queue(members, quota)
    available = quota - used

    if count > available:
        st.session_state.flash = "人數超過上限，進入候補"
        st.session_state.flash_type = "error"
        members.append({
            "name": name,
            "role": role,
            "count": count,
            "status": "waitlist"
        })
    else:
        st.session_state.flash = "報名成功"
        st.session_state.flash_type = "success"
        members.append({
            "name": name,
            "role": role,
            "count": count,
            "status": "confirmed"
        })

    save_data(data)
    st.rerun()


if st.button("報名", type="primary"):
    signup()


# ─────────────────────────────
# render lists
# ─────────────────────────────
st.subheader("👤 會員")
for i, m in enumerate(confirmed, 1):
    if m["role"] != "member":
        continue
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")
    with col2:
        if st.session_state.get("admin"):
            if st.button("取消", key=f"m{i}"):
                cancel_user(data, sid, m["name"])
                save_data(data)
                st.rerun()

st.subheader("👥 零打")
for i, m in enumerate(confirmed, 1):
    if m["role"] != "casual":
        continue
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")
    with col2:
        if st.session_state.get("admin"):
            if st.button("取消", key=f"c{i}"):
                cancel_user(data, sid, m["name"])
                save_data(data)
                st.rerun()

st.subheader("⏳ 候補")
for i, m in enumerate(waitlist, 1):
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")


# ─────────────────────────────
# admin
# ─────────────────────────────
st.divider()

with st.expander("管理"):
    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.session_state.admin = True

        new_q = st.number_input("總名額", 1, 200, quota)
        if st.button("更新"):
            sdata["total_quota"] = new_q
            save_data(data)
            st.rerun()

        reason = st.text_input("取消原因")
        if st.button("取消場次"):
            sdata["cancelled"] = True
            sdata["cancel_reason"] = reason
            save_data(data)
            st.rerun()

        if st.button("恢復"):
            sdata["cancelled"] = False
            sdata["cancel_reason"] = ""
            save_data(data)
            st.rerun()
