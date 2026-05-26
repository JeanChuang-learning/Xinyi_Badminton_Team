import streamlit as st
import json
import os
from datetime import date, timedelta

from booking_service import add_user, cancel_user

# ── config ─────────────────────────
ADMIN_PASSWORD = "admin1234"
DATA_FILE = "data.json"
DEFAULT_TOTAL_QUOTA = 20

WEEKS_AHEAD = 3

FIXED_SESSIONS = [
    {"weekday": 0, "start": "19:00", "end": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start": "19:00", "end": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start": "07:00", "end": "11:00", "label": "週日早上"},
]

ROLE_MAP = {"會員": "member", "零打": "casual"}

# ── UI ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

# ── flash message（關鍵） ─────────────────────────
if "flash" in st.session_state:
    typ, msg = st.session_state.pop("flash")
    if typ == "success":
        st.success(msg)
    else:
        st.error(msg)

# ── data ─────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sessions": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── session init ─────────────────────────
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

# ── queue logic ─────────────────────────
def build_groups(members, quota):
    members = sorted(members, key=lambda x: x["role"] == "casual")

    used = 0
    member_list, casual_list, waitlist = [], [], []

    for m in members:
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

# ── sessions ─────────────────────────
def generate_sessions():
    today = date.today()
    sessions = []

    for w in range(WEEKS_AHEAD + 1):
        for cfg in FIXED_SESSIONS:
            d = today + timedelta(
                days=(cfg["weekday"] - today.weekday()) % 7 + w * 7
            )
            sid = f"{d.isoformat()}_{cfg['start']}"

            sessions.append({
                "id": sid,
                "date": d,
                "label": cfg["label"],
                "start": cfg["start"],
                "end": cfg["end"]
            })

    return sessions

# ── load ─────────────────────────
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

member_list, casual_list, waitlist, used = build_groups(members, quota)

# ── status ─────────────────────────
st.caption(
    f"使用：{used}/{quota} ｜ "
    f"會員：{sum(m.get("count", 1) for m in member_list)} ｜ "
    f"零打：{sum(m.get("count", 1) for m in casual_list)} ｜ "
    f"候補：{len(waitlist)}"
)

if sdata["cancelled"]:
    st.error(f"❌ 已取消：{sdata['cancel_reason']}")
    st.stop()

# ── signup ─────────────────────────
st.divider()

col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name = st.text_input("名字")

with col2:
    role = ROLE_MAP[st.selectbox("身分", ["會員", "零打"])]

with col3:
    count = st.number_input("人數", min_value=1, max_value=10, value=1)

if st.button("報名", type="primary"):

    name = name.strip()

    if not name:
        st.session_state["flash"] = ("error", "請輸入名字")
        st.rerun()

    member_list, casual_list, waitlist, used = build_groups(members, quota)
    available = quota - used

    if count > available:
        st.session_state["flash"] = ("error", "名額不足，報名失敗")
        st.rerun()

    add_user(data, sid, name, role, int(count))
    save_data(data)

    st.session_state["flash"] = ("success", "報名成功")
    st.rerun()

# ── render lists ─────────────────────────
def render_list(title, lst, key_prefix):
    st.subheader(title)

    for i, m in enumerate(lst, 1):
        col1, col2 = st.columns([4, 1])

        with col1:
            st.write(f"{i}. {m['name']}  ｜  {m.get('count',1)} 人")

        with col2:
            if st.session_state.get("is_admin"):
                if st.button("取消", key=f"{key_prefix}_{i}_{m['name']}"):
                    cancel_user(data, sid, m["name"])
                    save_data(data)
                    st.rerun()

render_list("👤 會員", member_list, "m")
render_list("👥 零打", casual_list, "c")
render_list("⏳ 候補", waitlist, "w")

# ── admin ─────────────────────────
st.divider()

with st.expander("🔒 管理"):

    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.session_state["is_admin"] = True
        st.success("admin mode")

        new_quota = st.number_input("總名額", 1, 200, quota)

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
