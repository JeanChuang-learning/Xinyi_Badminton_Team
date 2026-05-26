import streamlit as st
import json
import os
from datetime import datetime, date, timedelta
import pytz

from booking_service import add_user, get_queue_view, cancel_user

# ── 設定 ─────────────────────────────
ADMIN_PASSWORD = "admin1234"
DATA_FILE = "data.json"
TZ = pytz.timezone("Asia/Taipei")

FIXED_SESSIONS = [
    {"weekday": 0, "start": "19:00", "end": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start": "19:00", "end": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start": "07:00", "end": "11:00", "label": "週日早上"},
]

WEEKS_AHEAD = 3
WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]

ROLE_DISPLAY = {
    "member": "會員",
    "casual": "零打",
}
# ── 基本 UI ─────────────────────────────
st.set_page_config(page_title="羽球報名", page_icon="🏸")

# ── JSON ─────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sessions": {}, "quota": 12}
    return json.load(open(DATA_FILE, "r", encoding="utf-8"))

def save_data(data):
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ── session 初始化 ─────────────────────────────
def get_session(data, sid):
    if sid not in data["sessions"]:
        data["sessions"][sid] = {
            "members": [],
            "casuals": [],
            "quota": data.get("quota", 12),
            "cancelled": False,
            "cancel_reason": ""
        }
    return data["sessions"][sid]

# ── 場次生成 ─────────────────────────────
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


# ── 主流程 ─────────────────────────────
data = load_data()
sessions = generate_sessions()

st.title("🏸 羽球報名系統")

session_map = {
    f"{s['date']} {s['label']} {s['start']}": s
    for s in sessions
}

selected = st.selectbox("選擇場次", list(session_map.keys()))
session = session_map[selected]
sid = session["id"]

sdata = get_session(data, sid)

# ── queue view（核心）
confirmed, waitlist = get_queue_view(sdata)

st.caption(f"正取：{len(confirmed)} / {sdata['quota']}")

# ── 報名區 ─────────────────────────────
col1, col2 = st.columns([3, 1])

with col1:
    name_input = st.text_input(
        "名字",
        placeholder="輸入名字"
    )

with col2:
    role_label = st.selectbox("身分", ["會員", "零打"])

#role mapping
ROLE_MAP = {
    "會員": "member",
    "零打": "casual",
}

#報名按鈕
if st.button("報名", type="primary"):
    name = name_input.strip()

    if not name:
        st.warning("請輸入名字")
    else:
        role = ROLE_MAP[role_label]

        result = add_user(data, sid, name, role)

        if result == "already_exists":
            st.info("已經報名過了")
        else:
            st.success("報名成功")
            st.rerun()
# ── 名單顯示 ─────────────────────────────
st.subheader("📋 報名名單")

for i, m in enumerate(members, 1):
    role_text = "👤會員" if m["role"] == "member" else "👥零打"

    st.markdown(
        f"{i}. {m['name']} ({role_text})"
    )
def handle_cancel(name):
    cancel_user(data, sid, name)
    st.rerun()
    
st.subheader("候補")
for i, n in enumerate(waitlist, 1):
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"{i}. {n}")
    with col2:
        if st.button("取消", key=f"c2_{n}"):
            cancel_user(sdata, n)
            save_data(data)
            st.rerun()

# ── admin ─────────────────────────────
with st.expander("管理"):
    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.success("admin mode")

        new_quota = st.number_input("quota", min_value=1, max_value=100, value=sdata["quota"])

        if st.button("更新 quota"):
            sdata["quota"] = new_quota
            save_data(data)
            st.rerun()
