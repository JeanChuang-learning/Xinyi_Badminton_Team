import streamlit as st
import json
import os
from datetime import date, timedelta

from booking_service import add_user, cancel_user

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

DEFAULT_CASUAL_QUOTA = 12

# ── UI ─────────────────────────────
st.set_page_config(
    page_title="羽球報名系統",
    page_icon="🏸",
    layout="centered"
)

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

    # ── session migration ──
    if "members" not in session:
        session["members"] = []

    if "quota" not in session:
        session["quota"] = DEFAULT_CASUAL_QUOTA

    if "cancelled" not in session:
        session["cancelled"] = False

    if "cancel_reason" not in session:
        session["cancel_reason"] = ""

    # ── member migration ──
    for m in session["members"]:

        if "count" not in m:
            m["count"] = 1

        if "role" not in m:
            m["role"] = "casual"

    return session


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

selected = st.selectbox(
    "選擇場次",
    list(session_map.keys())
)

session = session_map[selected]

sid = session["id"]

# ── init session ─────────────────────────────
sdata = get_session(data, sid)

members = sdata["members"]

quota = sdata["quota"]

# ── totals ─────────────────────────────
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

# ── status ─────────────────────────────
st.caption(
    f"👤 會員：{member_total} 人 ｜ "
    f"👥 零打：{casual_total}/{quota} 人"
)

# ── cancel banner ─────────────────────────────
if sdata.get("cancelled"):

    reason = sdata.get("cancel_reason", "")

    st.error(f"❌ 本場次已取消\n{reason}")

    st.stop()

# ── 報名區 ─────────────────────────────
st.divider()

col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name_input = st.text_input(
        "名字",
        placeholder="輸入名字"
    )

with col2:
    role_label = st.selectbox(
        "身分",
        ["會員", "零打"]
    )

with col3:
    count_input = st.number_input(
        "人數",
        min_value=1,
        max_value=10,
        value=1
    )

# ── signup ─────────────────────────────
if st.button("報名", type="primary"):

    name = name_input.strip()

    role = ROLE_MAP[role_label]

    count = int(count_input)

    if not name:

        st.warning("請輸入名字")

    else:

        # ── 零打 quota 控制 ──
        if role == "casual":

            if casual_total + count > quota:

                remain = max(0, quota - casual_total)

                st.error(
                    f"零打名額已滿，目前剩餘 {remain} 人"
                )

                st.stop()

        result = add_user(
            data=data,
            sid=sid,
            name=name,
            role=role,
            count=count
        )

        if result == "already_exists":

            st.info("已經報名過了")

        else:

            save_data(data)

            st.success("報名成功")

            st.rerun()

# ── 名單 ─────────────────────────────
st.divider()

st.subheader("📋 報名名單")

member_list = [
    m for m in members
    if m["role"] == "member"
]

casual_list = [
    m for m in members
    if m["role"] == "casual"
]

# ── 會員 ─────────────────────
member_total = sum(
    m.get("count", 1)
    for m in member_list
)

st.markdown(f"### 👤 會員（{member_total} 人）")

if member_list:

    for i, m in enumerate(member_list, 1):

        count = m.get("count", 1)

        col1, col2 = st.columns([4, 1])

        with col1:
            st.write(
                f"{i}. {m['name']} x{count}"
            )

        with col2:
            if st.button(
                "取消",
                key=f"member_{i}_{m['name']}"
            ):

                cancel_user(data, sid, m["name"])

                save_data(data)

                st.rerun()

else:

    st.caption("目前沒有會員報名")

# ── 零打 ─────────────────────
casual_total = sum(
    m.get("count", 1)
    for m in casual_list
)

st.markdown(
    f"### 👥 零打（{casual_total}/{quota} 人）"
)

if casual_list:

    for i, m in enumerate(casual_list, 1):

        count = m.get("count", 1)

        col1, col2 = st.columns([4, 1])

        with col1:
            st.write(
                f"{i}. {m['name']} x{count}"
            )

        with col2:
            if st.button(
                "取消",
                key=f"casual_{i}_{m['name']}"
            ):

                cancel_user(data, sid, m["name"])

                save_data(data)

                st.rerun()

else:

    st.caption("目前沒有零打報名")

# ── admin ─────────────────────────────
st.divider()

with st.expander("🔒 管理"):

    pwd = st.text_input(
        "密碼",
        type="password"
    )

    if pwd == ADMIN_PASSWORD:

        st.success("admin mode")

        # ── quota ──
        new_quota = st.number_input(
            "零打上限",
            min_value=1,
            max_value=100,
            value=quota
        )

        if st.button("更新零打上限"):

            sdata["quota"] = int(new_quota)

            save_data(data)

            st.success("已更新")

            st.rerun()

        st.divider()

        # ── cancel session ──
        if not sdata["cancelled"]:

            reason = st.text_input(
                "取消原因（選填）"
            )

            if st.button("取消本場次"):

                sdata["cancelled"] = True

                sdata["cancel_reason"] = reason

                save_data(data)

                st.rerun()

        else:

            if st.button("恢復場次"):

                sdata["cancelled"] = False

                sdata["cancel_reason"] = ""

                save_data(data)

                st.rerun()
