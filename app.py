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
st.set_page_config(page_title="信義羽球隊 - 報名系統", page_icon="🏸")
st.title("🏸 信義羽球隊 - 報名系統")

# ── message slot（關鍵） ─────────────────────────────
msg = st.empty()
# ── data ─────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sessions": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── session init ─────────────────────────────
def get_session(data, sid):
    if "sessions" not in data:
        data["sessions"] = {}

    if sid not in data["sessions"]:
        data["sessions"][sid] = {
            "members": [],
            "total_quota": DEFAULT_TOTAL_QUOTA,
            "cancelled": False,
            "cancel_reason": ""
        }

    return data["sessions"][sid]


# ── queue core ─────────────────────────────
def build_groups(members, quota):

    members_sorted = sorted(
        members,
        key=lambda x: 0 if x["role"] == "member" else 1
    )

    used = 0
    member_list = []
    casual_list = []
    waitlist = []

    for m in members_sorted:
        cnt = m.get("count", 1)

        if used + cnt <= quota:
            used += cnt
            if m["role"] == "member":
                member_list.append(m)
            else:
                casual_list.append(m)
        else:
            waitlist.append(m)

    return member_list, casual_list, waitlist, used


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
    f"{s['date']}｜{s['label']}｜{s['start']}-{s['end']}": s
    for s in sessions
}

selected = st.selectbox("選擇場次", list(session_map.keys()))
session = session_map[selected]
sid = session["id"]

sdata = get_session(data, sid)
members = sdata["members"]
quota = sdata["total_quota"]


# ── stats ─────────────────────────────
member_list, casual_list, waitlist, used = build_groups(members, quota)

member_total = sum(m.get("count", 1) for m in member_list)
casual_total = sum(m.get("count", 1) for m in casual_list)


# ── status UI ─────────────────────────────
st.caption(
    f"👥 使用：{used}/{quota} ｜ "
    f"👤 會員：{member_total} ｜ "
    f"👥 零打：{casual_total}"
)

if sdata.get("cancelled"):
    st.error(f"❌ 本場次已取消\n{sdata.get('cancel_reason','')}")
    st.stop()


# ── signup UI ─────────────────────────────
st.divider()

col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name_input = st.text_input("名字")

with col2:
    role_label = st.selectbox("身分", ["會員", "零打"])

with col3:
    count_input = st.number_input("人數", min_value=1, max_value=10, value=1)





# ── signup action ─────────────────────────────
if st.button("報名", type="primary"):

    name = name_input.strip()
    role = ROLE_MAP[role_label]
    count = int(count_input)

    if not name:
        msg.error("❌ 請輸入名字")
        st.stop()

    member_list, casual_list, waitlist, used = build_groups(members, quota)
    available = quota - used

    # ❗超額處理
    if count > available:
        st.toast("❌ 報名失敗")
        msg.error("❌ 人數已超過上限，報名失敗")
        st.stop()

    add_user(data, sid, name, role, count)
    save_data(data)

    st.toast("✅ 報名成功")
    msg.success("✅ 報名成功")

    st.rerun()


# ── member list ─────────────────────────────
st.subheader("👤 會員")

for i, m in enumerate(member_list, 1):
    col1, col2 = st.columns([4, 1])

    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")

    with col2:
        if st.button("取消", key=f"mem_{i}_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()


# ── casual list ─────────────────────────────
st.subheader("👥 零打")

for i, m in enumerate(casual_list, 1):
    col1, col2 = st.columns([4, 1])

    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count',1)}")

    with col2:
        if st.button("取消", key=f"cas_{i}_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()


# ── waitlist ─────────────────────────────
st.subheader("⏳ 候補")

for i, m in enumerate(waitlist, 1):
    col1, col2 = st.columns([4, 1])

    with col1:
        st.write(f"{i}. {m['name']} x{m.get('count', 1)}")

    with col2:
        if st.button("取消", key=f"wai_{i}_{m['name']}"):
            cancel_user(data, sid, m["name"])
            save_data(data)
            st.rerun()


# ── admin ─────────────────────────────
st.divider()

with st.expander("🔒 管理"):

    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:

        new_quota = st.number_input(
            "總人數上限",
            min_value=1,
            max_value=200,
            value=quota
        )

        if st.button("更新"):
            sdata["total_quota"] = int(new_quota)
            save_data(data)
            st.rerun()

        reason = st.text_input("取消原因")

        if st.button("取消場次"):
            sdata["cancelled"] = True
            sdata["cancel_reason"] = reason
            save_data(data)
            st.rerun()

        if st.button("恢復場次"):
            sdata["cancelled"] = False
            sdata["cancel_reason"] = ""
            save_data(data)
            st.rerun()
