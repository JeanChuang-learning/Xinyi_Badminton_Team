import streamlit as st
import json
import os
from datetime import date, timedelta

from booking_service import add_user, cancel_user

# ── 設定 ─────────────────────────────
ADMIN_PASSWORD = "admin1234"
DATA_FILE = "data.json"

WEEKS_AHEAD = 3

DEFAULT_TOTAL_QUOTA = 20

FIXED_SESSIONS = [
    {"weekday": 0, "start": "19:00", "end": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start": "19:00", "end": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start": "07:00", "end": "11:00", "label": "週日早上"},
]

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
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── session init + migration ─────────────────────────────
def get_session(data, sid):

    if "sessions" not in data:
        data["sessions"] = {}

    if sid not in data["sessions"]:
        data["sessions"][sid] = {}

    session = data["sessions"][sid]

    if "members" not in session:
        session["members"] = []

    if "queue" not in session:
        session["queue"] = []

    if "total_quota" not in session:
        session["total_quota"] = DEFAULT_TOTAL_QUOTA

    if "cancelled" not in session:
        session["cancelled"] = False

    if "cancel_reason" not in session:
        session["cancel_reason"] = ""

    for m in session["members"]:
        if "count" not in m:
            m["count"] = 1
        if "role" not in m:
            m["role"] = "casual"

    return session


# ── sessions ─────────────────────────────
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
    f"{s['date']}｜{s['label']}｜{s['start']}-{s['end']}": s
    for s in sessions
}

selected = st.selectbox("選擇場次", list(session_map.keys()))
session = session_map[selected]
sid = session["id"]

# ── session ─────────────────────────────
sdata = get_session(data, sid)
members = sdata["members"]
total_quota = sdata["total_quota"]

# ── stats ─────────────────────────────
member_total = sum(
    m.get("count", 1)
    for m in members
    if m["role"] == "member"
)

casual_total = sum(
    m.get("count", 1)
    for m in members
    if m["role"] == "casual"
)

total_people = member_total + casual_total

# ── UI status ─────────────────────────────
st.caption(
    f"👥 總人數：{total_people}/{total_quota} ｜ "
    f"👤 會員：{member_total} ｜ "
    f"👥 零打：{casual_total}"
)

# ── cancel ─────────────────────────────
if sdata.get("cancelled"):
    st.error(f"❌ 本場次已取消\n{sdata.get('cancel_reason','')}")
    st.stop()

# ── signup UI ─────────────────────────────
st.divider()

col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name_input = st.text_input("名字", placeholder="輸入名字")

with col2:
    role_label = st.selectbox("身分", ["會員", "零打"])

with col3:
    count_input = st.number_input("人數", min_value=1, max_value=10, value=1)


# ── signup ─────────────────────────────
if st.button("報名", type="primary"):

    name = name_input.strip()
    role = ROLE_MAP[role_label]
    count = int(count_input)

    if not name:
        st.warning("請輸入名字")
        st.stop()

    available = total_quota - total_people

    # ── 不阻擋：直接分流 ──
    if count <= available:
        status = "confirmed"
        members.append({
            "name": name,
            "role": role,
            "count": count,
            "status": status
        })
    else:
        status = "waitlist"
        members.append({
            "name": name,
            "role": role,
            "count": count,
            "status": status
        })

    save_data(data)
    st.success(f"報名成功（{status}）")
    st.rerun()


# ── list ─────────────────────────────
st.divider()
st.subheader("📋 名單")

confirmed = [m for m in members if m.get("status") == "confirmed"]
waitlist = [m for m in members if m.get("status") == "waitlist"]

# ── 正式名單 ─────────────────────────────
st.markdown(f"### ✅ 正式名單（{len(confirmed)}）")

for i, m in enumerate(confirmed, 1):
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")
    with col2:
        if st.button("取消", key=f"c_f_{i}_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()


# ── 候補名單 ─────────────────────────────
st.markdown(f"### ⏳ 候補名單（{len(waitlist)}）")

for i, m in enumerate(waitlist, 1):
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")
    with col2:
        if st.button("取消", key=f"c_w_{i}_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()


# ── admin ─────────────────────────────
st.divider()

with st.expander("🔒 管理"):

    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:

        st.success("admin mode")

        new_quota = st.number_input(
            "總人數上限",
            min_value=1,
            max_value=200,
            value=total_quota
        )

        if st.button("更新上限"):
            sdata["total_quota"] = int(new_quota)
            save_data(data)
            st.rerun()

        st.divider()

        reason = st.text_input("取消原因")

        if st.button("取消本場次"):
            sdata["cancelled"] = True
            sdata["cancel_reason"] = reason
            save_data(data)
            st.rerun()

        if st.button("恢復場次"):
            sdata["cancelled"] = False
            sdata["cancel_reason"] = ""
            save_data(data)
            st.rerun()
