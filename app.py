import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import requests
import time
import json

# ─────────────────────────
# 頁面設定（只能出現一次）
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸", layout="centered")

# ─────────────────────────
# config
# ─────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = "ScRBbUMhJUJHOn9abgQc9fw6EfUjEiDGxfmpOjQ5ThvQmOprUBbEYoscQzXsM/5RIVOhCskoUcUnd9fI39SpfPznW90I+sRZ8FQ65vNLk0dPfOX51KUNaAuuaeWeyjqJh/fZvh0L0R+UQotasKBOp/QdB04t89/1O/w1cDnyilFU="
LINE_GROUP_ID = "Cb7b632bd44eb63105a0fbabc8099cf75"

ADMIN_PASSWORD = "admin"
ROLE_MAP = {"會員": "member", "零打": "casual"}
ROLE_TO_ZH = {"member": "會員", "casual": "零打"}

FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日早上"},
]

# ─────────────────────────
# helpers
# ─────────────────────────
def user_label(s):
    date_str  = s.get("date", "未知日期")
    label_str = s.get("label", "")
    start     = s.get("start_time", "")[:5]   # 只取 HH:MM，去掉秒數
    end       = s.get("end_time", "")[:5]
    base      = f"{date_str} ｜ {label_str} ｜ {start}-{end}"
    if s.get("note") and "[會員限定]" in s.get("note", ""):
        base += " 👑"
    if s.get("cancelled"):
        base += f" ❌（{s.get('cancel_reason', '')}）"
    elif s.get("locked"):
        base += " 🔒關閉"
    return base

# ─────────────────────────
# LINE 通知
# ─────────────────────────
def send_line(msg_text):
    if not LINE_GROUP_ID or not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            },
            data=json.dumps({
                "to": LINE_GROUP_ID,
                "messages": [{"type": "text", "text": msg_text}],
            }),
        )
        return response.status_code == 200
    except Exception as e:
        print(f"LINE 發送失敗: {e}")
        return False

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

def get_db_admin_line_list():
    try:
        res = supabase.table("sessions").select("*").eq("id", "_admin_line_config").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    return {"隊長": "小明", "副隊長": "小華"}

def save_db_admin_line_list(config_dict):
    try:
        json_str = json.dumps(config_dict, ensure_ascii=False)
        res = supabase.table("sessions").select("id").eq("id", "_admin_line_config").execute()
        if res.data:
            supabase.table("sessions").update({"note": json_str}).eq("id", "_admin_line_config").execute()
        else:
            supabase.table("sessions").insert({
                "id": "_admin_line_config", "date": "1970-01-01",
                "start_time": "00:00", "end_time": "00:00",
                "label": "CONFIG", "note": json_str,
                "total_quota": 0, "cancelled": True,
            }).execute()
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

def get_bookings(session_id):
    try:
        res = supabase.table("bookings").select("*").eq("session_id", session_id).execute()
        return res.data or []
    except Exception as e:
        st.error(f"讀取失敗：{e}")
        return []

def add_booking_compatible(session_id, name, role, count, password, line_name):
    composite_name = f"{name}_🔑{password}_💬{line_name}_🔄0"
    try:
        supabase.table("bookings").insert({
            "session_id": session_id,
            "name": composite_name,
            "role": role,
            "count": count,
            "status": "active",
        }).execute()
    except Exception as e:
        st.error(f"寫入失敗：{e}")
        st.stop()

def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    payload = {"count": new_count, "status": status}
    if new_name:
        payload["name"] = new_name
    supabase.table("bookings").update(payload).eq("id", booking_id).execute()

def cancel_booking(booking_id, session_id):
    """刪除報名，並自動通知候補第一位"""
    supabase.table("bookings").delete().eq("id", booking_id).execute()
    # 檢查候補
    waitlist = supabase.table("bookings") \
        .select("*").eq("session_id", session_id).eq("status", "waitlist") \
        .order("created_at").execute().data
    if waitlist:
        next_p = waitlist[0]
        supabase.table("bookings").update({"status": "confirmed"}).eq("id", next_p["id"]).execute()
        send_line(f"🏸【遞補通知】恭喜「{next_p['name']}」遞補成功！請準時出席。")

def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()

def auto_generate_fixed_sessions(existing_sessions):
    """產生未來 36 天的固定場次，已存在的不重複建立"""
    today = date.today()
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new = False
    for i in range(36):
        check_date = today + timedelta(days=i)
        for rule in FIXED_RULES:
            if check_date.weekday() == rule["weekday"]:
                sid = f"{check_date.isoformat()}_{rule['start_time']}_fixed"
                if sid not in existing_keys:
                    try:
                        supabase.table("sessions").insert({
                            "id": sid,
                            "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立",
                            "total_quota": 20,
                            "cancelled": False,
                            "cancel_reason": "",
                            "locked": False,
                        }).execute()
                        has_new = True
                    except Exception as e:
                        print(f"自動新增失敗: {e}")
    return get_sessions() if has_new else existing_sessions

def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info):
    time.sleep(0.3)
    updated = [b for b in get_bookings(sid) if b["status"] == "active"]
    total = 0
    for ub in updated:
        cnt = int(ub["count"])
        if ub["id"] in old_waitlist_ids and total + cnt <= quota:
            if "_💬" in ub["name"]:
                try:
                    u_line = ub["name"].split("_💬")[1].split("_🔄")[0]
                    u_clean = ub["name"].split("_🔑")[0]
                    if u_line.strip():
                        send_line(f"📢【遞補成功】@{u_line}（{u_clean}）已遞補為正取！{session_label_info}")
                except Exception:
                    pass
        total += cnt

# ─────────────────────────
# 載入資料（只做一次）
# ─────────────────────────
raw_sessions = get_sessions()
all_sessions = auto_generate_fixed_sessions(raw_sessions)
admin_line_config = get_db_admin_line_list()

# 去重 + 過濾 config 紀錄 + 排序
unique_map = {}
for s in all_sessions:
    sid = s.get("id")
    if sid and sid != "_admin_line_config":
        unique_map[sid] = s

sessions_sorted = sorted(unique_map.values(), key=lambda s: (s["date"], s["start_time"]))
session_map = {s["id"]: s for s in sessions_sorted}
keys = list(session_map.keys())

# ─────────────────────────
# 頁面標題
# ─────────────────────────
st.title("🏸 信義羽球隊")
st.markdown("#### 🔥 **會員熱烈招生中！歡迎加入我們的行列！**")
st.divider()

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# 場次選單（只出現一次）
# ─────────────────────────
if not keys:
    st.info("💡 目前暫無場次。")
    st.stop()

if "selected_sid" not in st.session_state or st.session_state["selected_sid"] not in session_map:
    st.session_state["selected_sid"] = keys[0]

def on_session_change():
    st.session_state["selected_sid"] = st.session_state["main_session_select"]
    for k in ["name_input", "password_input", "line_name_input"]:
        st.session_state.pop(k, None)

st.markdown("### 📅 請選擇場次")
st.radio(
    "選擇場次",
    keys,
    format_func=lambda x: user_label(session_map[x]),
    key="main_session_select",
    index=keys.index(st.session_state["selected_sid"]),
    on_change=on_session_change,
    label_visibility="collapsed",
)

sid     = st.session_state["selected_sid"]
session = session_map[sid]

# ─────────────────────────
# 場次內容
# ─────────────────────────
bookings = get_bookings(sid)
active   = [b for b in bookings if b["status"] == "active"]

today      = date.today()
s_date     = datetime.strptime(session["date"], "%Y-%m-%d").date()
open_date  = s_date - timedelta(days=7)
is_opened  = today >= open_date
is_member_only = "[會員限定]" in (session.get("note") or "")

quota = session.get("total_quota", 20)
total_member_count = 0
total_casual_count = 0
current_total      = 0
waitlist_count     = 0
list_to_show       = []
old_waitlist_ids   = set()

for b in active:
    b_count    = int(b["count"])
    raw_name   = b["name"]
    display_name = raw_name
    pwd_hidden = line_name_hidden = ""
    modify_count = 0

    if "_🔑" in raw_name:
        parts = raw_name.split("_🔑")
        display_name = parts[0]
        if "_💬" in parts[1]:
            sub = parts[1].split("_💬")
            pwd_hidden = sub[0]
            tail = sub[1].split("_🔄")
            line_name_hidden = tail[0]
            modify_count = int(tail[1]) if len(tail) > 1 and tail[1].isdigit() else 0

    if b["role"] == "member":
        total_member_count += b_count
        is_waitlist = False
        current_total += b_count
    else:
        if current_total >= quota:
            is_waitlist = True
            waitlist_count += b_count
            old_waitlist_ids.add(b["id"])
        elif current_total + b_count > quota:
            is_waitlist = "partial"
            total_casual_count += quota - current_total
            waitlist_count     += current_total + b_count - quota
            current_total       = quota
            old_waitlist_ids.add(b["id"])
        else:
            is_waitlist = False
            current_total      += b_count
            total_casual_count += b_count

    list_to_show.append({
        "data": b, "is_waitlist": is_waitlist,
        "clean_name": display_name, "pwd": pwd_hidden,
        "line_name": line_name_hidden, "modify_count": modify_count,
    })

# 儀表板
st.markdown("### 📊 本日場次人數摘要")
m1, m2, m3, m4 = st.columns(4)
m1.metric("正取總人數",      f"{current_total} / {quota} 人")
m2.metric("會員人數",        f"{total_member_count} 人")
m3.metric("零打人數（正取）", f"{total_casual_count} 人")
m4.metric("候補人數",        f"🔴 {waitlist_count} 人" if waitlist_count else "0 人")

if st.session_state.get("is_admin"):
    with st.container(border=True):
        st.markdown("🔧 **管理員：動態調整本場名額**")
        new_quota = st.number_input("人數上限", 1, 200, int(quota), key=f"adjust_quota_{sid}")
        if st.button("確認修改上限"):
            update_session(sid, {"total_quota": int(new_quota)})
            st.success(f"已調整為 {new_quota} 人")
            st.rerun()

# 狀態攔截
if session.get("cancelled"):
    st.warning(f"⚠ 此場次已取消。原因：{session.get('cancel_reason', '無')}")
    st.stop()
if session.get("locked"):
    st.error("❌ 此場次已關閉")
    st.stop()
if not is_opened and not st.session_state.get("is_admin"):
    st.warning(f"⏳ 尚未開放報名（將於 {open_date} 開放）")
    st.stop()

if current_total >= quota:
    st.error("🚨 正取名額已滿！名額已滿時僅開放會員候補，零打暫停。")
elif is_member_only:
    st.warning("👑 本場次為會員限定場次")

# ─────────────────────────
# 報名表單
# ─────────────────────────
st.divider()
st.markdown("### ✍️ 我要報名")
st.info("💡 名額已滿會進入候補，填寫 LINE 名字可收到遞補通知。")

col1, col2, col3 = st.columns([2, 1, 1])
with col1: name_input     = st.text_input("球友名字", key=f"name_{sid}")
with col2: role           = ROLE_MAP[st.selectbox("身分", ["會員", "零打"], key=f"role_{sid}")]
with col3: count          = st.number_input("人數", 1, 10, 1, key=f"count_{sid}")
col4, col5 = st.columns(2)
with col4: password_input = st.text_input("取消/修改暗號（4位數字）", type="password", max_chars=4, key=f"pwd_{sid}")
with col5: line_name_input= st.text_input("LINE 名字（想收候補通知必填）", key=f"line_{sid}")

if st.button("確認報名", type="primary"):
    if not name_input.strip():
        st.error("請輸入名字")
    elif not password_input.strip() or not password_input.isdigit():
        st.error("請設定4位數字暗號")
    elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
        st.error("本場為會員限定，零打暫不開放。")
    elif current_total >= quota and role == "casual" and not st.session_state.get("is_admin"):
        st.error("名額已滿，零打暫停登記。")
    else:
        add_booking_compatible(sid, name_input.strip(), role, int(count), password_input.strip(), line_name_input.strip())
        st.success("報名成功！")
        st.rerun()

# ─────────────────────────
# 名單
# ─────────────────────────
st.subheader("👥 現有報名名單")
if not list_to_show:
    st.caption("目前尚無人報名")

for item in list_to_show:
    b       = item["data"]
    wl      = item["is_waitlist"]
    c_name  = item["clean_name"]
    zh_role = ROLE_TO_ZH.get(b["role"], b["role"])

    if b["role"] == "member":
        status_tag = "🟢 正取"
    elif wl == True:
        status_tag = "⏳ 候補"
    elif wl == "partial":
        status_tag = "⚠️ 部分候補"
    else:
        status_tag = "🟢 正取"

    modify_tag = " (已改)" if b["role"] == "casual" and item["modify_count"] > 0 else ""

    col1, col2 = st.columns([4, 2])
    with col1:
        st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role} ｜ {status_tag}{modify_tag}")
    with col2:
        with st.expander("⚙️ 修改/取消"):
            if st.session_state.get("is_admin"):
                st.warning("⚡ 管理員模式")
                adm_new_count = st.number_input("調整人數（0＝刪除）", 0, 20, int(b["count"]), key=f"adm_cnt_{b['id']}")
                if st.button("管理員確認修改", key=f"adm_btn_{b['id']}"):
                    if adm_new_count == 0:
                        cancel_booking(b["id"], b["session_id"])
                        st.success("已刪除")
                    else:
                        update_booking_data(b["id"], int(adm_new_count))
                        st.success(f"已調整為 {adm_new_count} 人")
                    check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                    st.rerun()
            else:
                if current_total >= quota:
                    st.warning("名額已滿，如需調整請聯絡管理員。")
                input_pwd    = st.text_input("請輸入密碼", type="password", key=f"pwd_verify_{b['id']}")
                if b["role"] == "casual":
                    st.caption(f"零打限改1次（已改：{item['modify_count']} 次）")
                else:
                    st.caption("會員可無限次調整人數。")
                user_new_count = st.number_input("新的人數（0＝取消）", 0, 10, int(b["count"]), key=f"user_cnt_{b['id']}")
                if st.button("確認提交修改", key=f"user_btn_{b['id']}"):
                    if input_pwd != item["pwd"]:
                        st.error("密碼錯誤！")
                    elif b["role"] == "casual" and item["modify_count"] >= 1 and user_new_count != 0:
                        st.error("零打限修改1次！")
                    else:
                        if user_new_count == 0:
                            cancel_booking(b["id"], b["session_id"])
                            st.success("已取消報名！")
                        else:
                            new_mod = item["modify_count"] + 1 if b["role"] == "casual" else item["modify_count"]
                            new_composite = f"{c_name}_🔑{item['pwd']}_💬{item['line_name']}_🔄{new_mod}"
                            update_booking_data(b["id"], int(user_new_count), new_name=new_composite)
                            st.success(f"已更新為 {user_new_count} 人")
                        check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                        st.rerun()

# ─────────────────────────
# 聯絡窗口
# ─────────────────────────
st.divider()
with st.container():
    st.markdown("### 📞 聯絡窗口")
    if admin_line_config:
        line_accounts = list(set(admin_line_config.values()))
        cols = st.columns(min(len(line_accounts), 3))
        for idx, line_name in enumerate(line_accounts):
            with cols[idx % len(cols)]:
                st.info(f"💬 **LINE ID**\n\n`{line_name}`")
    else:
        st.caption("目前暫無設定聯絡人。")
    st.markdown("> 💡 歡迎友誼賽交流 🏸，團體報名人數較多請直接聯絡窗口。")

# ─────────────────────────
# 管理員後台
# ─────────────────────────
st.divider()
with st.expander("🔒 管理與後台登入"):
    if st.session_state.get("is_admin"):
        st.markdown("### ⚙️ 管理員選單")
        if st.button("🔓 登出管理員模式", type="secondary"):
            st.session_state["is_admin"] = False
            st.rerun()
        st.divider()

        # 聯絡人名單
        st.subheader("📱 維護聯絡人名單")
        with st.container(border=True):
            if admin_line_config:
                st.markdown("**現有聯絡人：**")
                for k_id, lname in list(admin_line_config.items()):
                    c1, c2 = st.columns([4, 1])
                    c1.text(f"💬 {lname}")
                    if c2.button("刪除", key=f"del_admin_{k_id}"):
                        del admin_line_config[k_id]
                        if save_db_admin_line_list(admin_line_config):
                            st.success("已刪除")
                            st.rerun()
            else:
                st.info("名單為空。")
            st.divider()
            new_line_name = st.text_input("新增 LINE 帳號", key="new_line_name")
            if st.button("確認新增聯絡人"):
                if not new_line_name.strip():
                    st.error("請輸入 LINE 帳號")
                else:
                    admin_line_config[f"admin_{int(time.time()*1000)}"] = new_line_name.strip()
                    if save_db_admin_line_list(admin_line_config):
                        st.success("新增成功！")
                        st.rerun()

        st.divider()

        # 取消場次
        st.subheader("❌ 取消場次")
        with st.form("cancel_session_form", clear_on_submit=True):
            cancel_target = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="cancel_sel")
            reason        = st.text_input("原因")
            if st.form_submit_button("確認取消"):
                current_note = session_map[cancel_target].get("note") or ""
                update_session(cancel_target, {
                    "cancelled": True, "cancel_reason": reason,
                    "note": current_note.replace("[已恢復場次]", "").strip(),
                })
                send_line(f"⚠️【信義羽球隊】{session_map[cancel_target]['date']} 場次已取消。原因：{reason}")
                st.success("已取消")
                time.sleep(0.5)
                st.rerun()

        # 恢復場次
        st.subheader("🔄 恢復場次")
        cancelled_list = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map    = {s["id"]: s for s in cancelled_list}
        if restore_map:
            restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()), format_func=lambda x: user_label(restore_map[x]), key="restore_target")
            if st.button("確認恢復場次"):
                current_note = restore_map[restore_target].get("note") or ""
                new_note = current_note if "[已恢復場次]" in current_note else f"{current_note} [已恢復場次]".strip()
                update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": new_note})
                send_line(f"🟢【信義羽球隊】{restore_map[restore_target]['date']} 場次已恢復，開放報名！")
                st.success("已恢復！")
                st.rerun()
        else:
            st.caption("目前沒有已取消的場次")

        st.divider()

        # 新增臨時場次
        st.subheader("➕ 加開場次")
        with st.form("add_session_form"):
            r1c1, r1c2, r1c3 = st.columns([2, 1, 1])
            with r1c1: new_date  = st.date_input("日期", min_value=date.today())
            with r1c2: start_time = st.selectbox("開始", ["06:00","08:00","10:00","12:00","14:00","16:00","18:00","20:00"], index=6)
            with r1c3: end_time   = st.selectbox("結束", ["08:00","10:00","12:00","14:00","16:00","18:00","20:00","22:00"], index=7)
            r2c1, r2c2, r2c3 = st.columns([2, 1, 1])
            with r2c1: new_label   = st.text_input("場地", value="信義羽球館")
            with r2c2: total_quota = st.number_input("名額上限", 1, 100, 20)
            with r2c3: casual_limit= st.number_input("零打上限", 0, 100, 15)
            r3c1, r3c2 = st.columns(2)
            with r3c1: new_note   = st.text_input("備註")
            with r3c2: access_type= st.radio("開放規則", ["所有球友", "限會員"], horizontal=True)

            if st.form_submit_button("🔥 確認加開", use_container_width=True):
                if not new_label.strip():
                    st.error("請填寫場地名稱")
                else:
                    final_note = ("[會員限定] " if access_type == "限會員" else "") + new_note.strip()
                    new_id = f"{new_date}_{start_time}_{int(time.time())}"
                    try:
                        supabase.table("sessions").insert({
                            "id": new_id, "date": str(new_date),
                            "start_time": start_time, "end_time": end_time,
                            "label": new_label.strip(), "note": final_note,
                            "total_quota": int(total_quota),
                            "casual_limit": int(casual_limit),
                            "cancelled": False, "cancel_reason": "", "locked": False,
                        }).execute()
                        send_line(f"📢【信義羽球隊】加開場次！{new_date} {start_time}-{end_time}，快上系統報名！")
                        st.success(f"已加開：{new_date} {start_time}-{end_time}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"寫入失敗：{e}")

        st.divider()

        # 修改場次規則
        st.subheader("⚙️ 修改場次規則")
        with st.form("rule_session_form"):
            target_sid  = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="rule_sel")
            rule_type   = st.radio("開放規則", ["所有球友", "僅限會員"], horizontal=True)
            reason_note = st.text_input("備註說明")
            if st.form_submit_button("確認更新"):
                current_note = session_map[target_sid].get("note") or ""
                clean_note = current_note.replace("[會員限定]", "").replace("[已恢復場次]", "").strip()
                tag = "[會員限定]" if rule_type == "僅限會員" else ""
                update_session(target_sid, {"note": f"{tag} {reason_note}".strip()})
                st.success("已更新")
                time.sleep(0.5)
                st.rerun()

    else:
        st.markdown("⚠️ **管理員登入**")
        pwd = st.text_input("密碼", type="password")
        if pwd == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
        elif pwd:
            st.error("密碼錯誤")
