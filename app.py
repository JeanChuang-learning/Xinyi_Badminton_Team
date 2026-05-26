import streamlit as st
import json
import os
from datetime import date, timedelta

from booking_service import add_user, cancel_user

# ── config ─────────────────────────
ADMIN_PASSWORD = "admin"
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

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式已啟用")

flash = st.session_state.pop("flash", None)
if flash:
    typ, msg = flash
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
            "cancel_reason": "",
            "note": "",
            "locked": False,
            "allow_roles": ["member", "casual"]
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
            d = today + timedelta(days=(cfg["weekday"] - today.weekday()) % 7 + w * 7)
            sid = f"{d.isoformat()}_{cfg['start']}"

            sessions.append({
                "id": sid,
                "date": d,
                "label": cfg["label"],
                "start": cfg["start"],
                "end": cfg["end"]
            })

    return sessions


# ─────────────────────────────────────────────
# VIEW LAYER（關鍵修正）
# ─────────────────────────────────────────────

def user_label(s, data):
    sid = s["id"]
    sdata = data["sessions"].get(sid, {})

    base = f"{s['date']}｜{s['label']}｜{s['start']}-{s['end']}"

    if sdata.get("cancelled"):
        reason = sdata.get("cancel_reason", "")
        return f"{base} ❌不開放（{reason}）"

    if sdata.get("locked"):
        return f"{base} 🔒關閉報名"

    return base


def admin_label(s, data):
    sid = s["id"]
    sdata = data["sessions"].get(sid, {})

    base = f"{s['date']}｜{s['label']}｜{s['start']}-{s['end']}"

    if sdata.get("cancelled"):
        return f"{base} ❌已取消"

    if sdata.get("locked"):
        return f"{base} 🔒鎖定"

    return base


# ── load ─────────────────────────
data = load_data()
sessions = generate_sessions()

# ✔ 排序（取消置底 + 日期時間排序）
sessions_sorted = sorted(
    sessions,
    key=lambda s: (s["date"], s["start"])
)

# ─────────────────────────────────────────────
# USER DROPDOWN
# ─────────────────────────────────────────────
session_map = {
    s["id"]: s
    for s in sessions_sorted
}
options = {
    s["id"]: user_label(s, data)
    for s in sessions_sorted
}
selected_id = st.selectbox(
    "選擇場次",
    list(options.keys()),
    format_func=lambda x: options[x]
)

session = session_map[selected_id]
sid = selected_id

sdata = get_session(data, sid)
members = sdata["members"]
quota = sdata.get("total_quota", DEFAULT_TOTAL_QUOTA)

if sdata.get("note"):
    st.info(f"📌 備註：{sdata['note']}")

member_list, casual_list, waitlist, used = build_groups(members, quota)

st.caption(
    f"使用：{used}/{quota} ｜ "
    f"會員：{sum(m.get('count', 1) for m in member_list)} ｜ "
    f"零打：{sum(m.get('count', 1) for m in casual_list)} ｜ "
    f"候補：{len(waitlist)}"
)

if sdata.get("cancelled"):
    st.warning(f"⚠ 已取消")

if sdata.get("locked"):
    st.error("❌ 此場次已關閉報名")
    st.stop()

# ── signup ─────────────────────────
st.divider()

col1, col2, col3 = st.columns([3, 1, 1])

with col1:
    name_input = st.text_input("名字")

with col2:
    role = ROLE_MAP[st.selectbox("身分", ["會員", "零打"])]

with col3:
    count = st.number_input("人數", min_value=1, max_value=10, value=1)

if st.button("報名", type="primary"):

    name = name_input.strip()

    if not name:
        st.session_state["flash"] = ("error", "請輸入名字")
        st.rerun()

    add_user(data, sid, name, role, int(count))
    save_data(data)

    member_list, casual_list, waitlist, used = build_groups(
        members + [{"name": name, "role": role, "count": int(count)}],
        quota
    )

    if any(m["name"] == name for m in waitlist):
        st.session_state["flash"] = ("error", "已進入候補")
    else:
        st.session_state["flash"] = ("success", "報名成功")

    st.rerun()

# ── render list ─────────────────────────
def render_list(title, lst, key_prefix):
    st.subheader(title)

    for i, m in enumerate(lst, 1):
        col1, col2 = st.columns([4, 1])

        with col1:
            st.write(f"{i}. {m['name']} ｜ {m.get('count', 1)} 人")

        with col2:
            if st.session_state.get("is_admin"):
                if st.button("取消", key=f"{key_prefix}_{i}_{m['name']}"):
                    cancel_user(sid, m["name"])
                    sdata["cancelled"] = True
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

        admin_session_map = {
            admin_label(s, data): s
            for s in sessions_sorted
        }

        session_list = list(admin_session_map.keys())

        # ❌ 取消
        st.subheader("❌ 取消場次")

        cancel_target = st.selectbox("選擇場次", session_list, key="cancel")
        cancel_reason = st.text_input("取消原因")

        if st.button("取消場次"):
            sid = admin_session_map[cancel_target]["id"]
            target = get_session(data, sid)

            target["cancelled"] = True
            target["cancel_reason"] = cancel_reason

            save_data(data)
            st.rerun()

        # 🔄 恢復（不顯示原因）
        st.subheader("🔄 恢復場次")

        restore_sessions = [
            s for s in sessions_sorted
            if data["sessions"].get(s["id"], {}).get("cancelled")
        ]

        restore_map = {
            f"{s['date']}｜{s['label']}｜{s['start']}-{s['end']} 🔄可恢復": s
            for s in restore_sessions
        }

        if restore_map:
            restore_target = st.selectbox(
                "選擇場次",
                list(restore_map.keys()),
                key="restore"
            )

            if st.button("恢復場次"):
                sid = restore_map[restore_target]["id"]
                target = get_session(data, sid)

                target["cancelled"] = False
                target["cancel_reason"] = ""

                save_data(data)
                st.rerun()
        else:
            st.info("沒有可恢復場次")

        # ➕ 新增
        with st.form("create_session_form"):
            st.subheader("➕ 新增場次")
        
            new_date = st.date_input("日期")
            new_start = st.text_input("開始時間", "19:00")
            new_end = st.text_input("結束時間", "22:00")
            new_label = st.text_input("場次名稱", "自訂場次")
            new_note = st.text_area("備註")
        
            submitted = st.form_submit_button("新增場次")
            
        #---------------------            
        if submitted:
            sid = f"{new_date.isoformat()}_{new_start}"
        
            if sid not in data["sessions"]:
                data["sessions"][sid] = {
                    "members": [],
                    "total_quota": DEFAULT_TOTAL_QUOTA,
                    "cancelled": False,
                    "cancel_reason": "",
                    "note": new_note,
                    "locked": False,
                    "allow_roles": ["member", "casual"],
                    "date": new_date.isoformat(),
                    "label": new_label,
                    "start": new_start,
                    "end": new_end
                }
        
                save_data(data)
                st.rerun()
            else:
                st.error("場次已存在")
