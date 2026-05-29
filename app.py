import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
from calendar import monthrange
import requests
import time
import json
import os

# ─────────────────────────
# 常數設定
# ─────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = "ScRBbUMhJUJHOn9abgQc9fw6EfUjEiDGxfmpOjQ5ThvQmOprUBbEYoscQzXsM/5RIVOhCskoUcUnd9fI39SpfPznW90I+sRZ8FQ65vNLk0dPfOX51KUNaAuuaeWeyjqJh/fZvh0L0R+UQotasKBOp/QdB04t89/1O/w1cDnyilFU="
LINE_GROUP_ID    = "Cb7b632bd44eb63105a0fbabc8099cf75"
ADMIN_PASSWORD   = "admin"
ROLE_MAP         = {"會員": "member", "零打": "casual"}
ROLE_TO_ZH       = {"member": "會員", "casual": "零打"}
WEEKDAY_TW       = ["一", "二", "三", "四", "五", "六", "日"]

FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日早上"},
]

# ─────────────────────────
# 頁面設定
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸", layout="centered")

# ─────────────────────────
# 工具函式
# ─────────────────────────
def user_label(s):
    base = f"{s.get('date','')} ｜ {s.get('label','')} ｜ {s.get('start_time','')[:5]}-{s.get('end_time','')[:5]}"
    if "[會員限定]" in (s.get("note") or ""):
        base += " 👑"
    if s.get("cancelled"):
        base += f" ❌（{s.get('cancel_reason','')}）"
    elif s.get("locked"):
        base += " 🔒"
    return base

def get_announcement():
    if os.path.exists("announcement.txt"):
        with open("announcement.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

# ─────────────────────────
# LINE 通知
# ─────────────────────────
def send_line(msg_text):
    if not LINE_GROUP_ID or not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            data=json.dumps({"to": LINE_GROUP_ID,
                             "messages": [{"type": "text", "text": msg_text}]}),
        )
        return r.status_code == 200
    except Exception as e:
        print(f"LINE 發送失敗: {e}")
        return False

# ─────────────────────────
# Supabase 函式
# ─────────────────────────
@st.cache_data(ttl=60)
def get_sessions():
    try:
        return supabase.table("sessions").select("*").execute().data or []
    except Exception as e:
        st.exception(e)
        return []

@st.cache_data(ttl=30)
def get_bookings(session_id):
    try:
        return supabase.table("bookings").select("*").eq("session_id", session_id).execute().data or []
    except Exception as e:
        st.error(f"讀取失敗：{e}")
        return []

def get_db_admin_line_list():
    try:
        res = supabase.table("sessions").select("*").eq("id", "_admin_line_config").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    return {}

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

def add_booking_compatible(session_id, name, role, count, password, line_name):
    composite = f"{name}_🔑{password}_💬{line_name}_🔄0"
    try:
        supabase.table("bookings").insert({
            "session_id": session_id, "name": composite,
            "role": role, "count": count, "status": "active",
        }).execute()
        get_bookings.clear()
    except Exception as e:
        st.error(f"寫入失敗：{e}")
        st.stop()

def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    payload = {"count": new_count, "status": status}
    if new_name:
        payload["name"] = new_name
    supabase.table("bookings").update(payload).eq("id", booking_id).execute()
    get_bookings.clear()

def cancel_booking(booking_id, session_id):
    supabase.table("bookings").delete().eq("id", booking_id).execute()
    get_bookings.clear()
    waitlist = supabase.table("bookings").select("*") \
        .eq("session_id", session_id).eq("status", "waitlist") \
        .order("created_at").execute().data
    if waitlist:
        next_p = waitlist[0]
        supabase.table("bookings").update({"status": "confirmed"}).eq("id", next_p["id"]).execute()
        send_line(f"🏸【遞補通知】恭喜「{next_p['name']}」遞補成功！請準時出席。")

def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()
    get_sessions.clear()

def auto_generate_fixed_sessions(existing_sessions):
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
                            "id": sid, "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立",
                            "total_quota": 20,
                            "cancelled": False, "cancel_reason": "", "locked": False,
                        }).execute()
                        has_new = True
                    except Exception as e:
                        print(f"自動新增失敗: {e}")
    if has_new:
        get_sessions.clear()
        return get_sessions()
    return existing_sessions

def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info):
    time.sleep(0.3)
    get_bookings.clear()
    updated = [b for b in get_bookings(sid) if b["status"] == "active"]
    total = 0
    for ub in updated:
        cnt = int(ub["count"])
        if ub["id"] in old_waitlist_ids and total + cnt <= quota:
            if "_💬" in ub["name"]:
                try:
                    u_line  = ub["name"].split("_💬")[1].split("_🔄")[0]
                    u_clean = ub["name"].split("_🔑")[0]
                    if u_line.strip():
                        send_line(f"📢【遞補成功】@{u_line}（{u_clean}）已遞補為正取！{session_label_info}")
                except Exception:
                    pass
        total += cnt
        
def get_system_settings():
    """讀取系統全域設定"""
    try:
        res = supabase.table("sessions").select("*").eq("id", "_system_settings").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    return {"shuttlecock": "YY AS-50", "casual_fee": 300}

def save_system_settings(settings_dict):
    """儲存系統全域設定"""
    try:
        json_str = json.dumps(settings_dict, ensure_ascii=False)
        res = supabase.table("sessions").select("id").eq("id", "_system_settings").execute()
        if res.data:
            supabase.table("sessions").update({"note": json_str}).eq("id", "_system_settings").execute()
        else:
            supabase.table("sessions").insert({
                "id": "_system_settings", "date": "1970-01-01",
                "start_time": "00:00", "end_time": "00:00",
                "label": "SETTINGS", "note": json_str,
                "total_quota": 0, "cancelled": True
            }).execute()
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False
# ─────────────────────────
# 資料載入
# ─────────────────────────
raw_sessions      = get_sessions()
all_sessions      = auto_generate_fixed_sessions(raw_sessions)
admin_line_config = get_db_admin_line_list()

unique_map = {}
for s in all_sessions:
    sid = s.get("id")
    if sid and sid != "_admin_line_config":
        unique_map[sid] = s

sessions_sorted = sorted(unique_map.values(), key=lambda s: (s["date"], s["start_time"]))
session_map     = {s["id"]: s for s in sessions_sorted}
keys            = list(session_map.keys())

if "selected_sid" not in st.session_state:
    st.session_state["selected_sid"] = None

today_date = date.today()

# ─────────────────────────
# 標題
# ─────────────────────────
st.title("🏸 信義羽球隊")

ann = get_announcement()
if ann:
    ann_html = ann.replace("\n", "<br>")
    st.markdown(
        f"""<div style='border:2px solid #3b82f6;border-radius:12px;padding:14px 18px;
        background:linear-gradient(135deg,#1e2a3a,#1a1f2e);
        font-size:14px;line-height:1.8;color:#e2e8f0;margin-bottom:8px'>
        {ann_html}</div>""",
        unsafe_allow_html=True
    )

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# 場次選單
# ─────────────────────────
if not keys:
    st.info("目前暫無場次。")
    st.stop()

window_start   = today_date - timedelta(days=7)
window_open    = today_date + timedelta(days=7)
window_preview = today_date + timedelta(days=14)

visible_keys = [
    k for k in keys
    if window_start <= datetime.strptime(session_map[k]["date"], "%Y-%m-%d").date() <= window_preview
]

if not visible_keys:
    st.info("近兩週內暫無場次。")
    st.stop()

if st.session_state["selected_sid"] not in visible_keys:
    st.session_state["selected_sid"] = None

st.markdown("### 📅 請選擇場次")

for row_start in range(0, len(visible_keys), 3):
    row_keys = visible_keys[row_start:row_start + 3]
    cols = st.columns(3)
    for i, k in enumerate(row_keys):
        s          = session_map[k]
        is_sel     = st.session_state["selected_sid"] == k
        s_date_obj = datetime.strptime(s["date"], "%Y-%m-%d").date()
        wd         = WEEKDAY_TW[s_date_obj.weekday()]
        start_t    = s.get("start_time", "")[:5]
        end_t      = s.get("end_time", "")[:5]
        note       = s.get("note") or ""
        used       = sum(int(b["count"]) for b in get_bookings(k) if b["status"] == "active")
        quota_k    = s.get("total_quota", 20)
        date_short = s["date"][5:]
        time_short = f"{start_t[:2]}-{end_t[:2]}"

        try:
            end_h, end_m = map(int, end_t.split(":"))
            session_end_dt = datetime.combine(s_date_obj, datetime.min.time()).replace(hour=end_h, minute=end_m)
            is_ended = datetime.now() > session_end_dt
        except Exception:
            is_ended = s_date_obj < today_date

        is_not_open = not is_ended and s_date_obj > window_open

        if is_ended:
            status = "⬜ 已結束"
        elif is_not_open:
            status = "🔒 未開放"
        elif s.get("cancelled") or s.get("locked"):
            status = "❌ 不開放"
        elif "[會員限定]" in note:
            status = "🔵 會員限定"
        elif used >= quota_k:
            status = "🟡 滿額"
        else:
            status = "🟢 開放"

        btn_label = f"{date_short}({wd}) {time_short} {status}"

        if is_ended or is_not_open:
            cols[i].button(btn_label, key=f"sess_{k}", use_container_width=True, disabled=True)
        elif is_sel:
            if cols[i].button(btn_label, key=f"sess_{k}", use_container_width=True, type="primary"):
                st.session_state["selected_sid"] = None
                st.rerun()
        else:
            if cols[i].button(btn_label, key=f"sess_{k}", use_container_width=True):
                st.session_state["selected_sid"] = k
                for ck in ["name_input", "password_input", "line_name_input"]:
                    st.session_state.pop(ck, None)
                st.rerun()

# ─────────────────────────
# 聯絡窗口 + 管理員入口
# ─────────────────────────
st.divider()
_phone_col, _names_col = st.columns([1, 6])
with _phone_col:
    if st.button("📞", help="管理員後台", use_container_width=True):
        st.session_state["show_admin"] = not st.session_state.get("show_admin", False)
        st.rerun()
with _names_col:
    if admin_line_config:
        line_accounts = list(set(admin_line_config.values()))
        names_str = "　".join([f"💬 {lname}" for lname in line_accounts])
        st.markdown(f"**聯絡窗口**　{names_str}")
    else:
        st.markdown("**聯絡窗口**　尚未設定聯絡人")

# ─────────────────────────
# 管理員後台（toggle）
# ─────────────────────────
if st.session_state.get("show_admin"):
    with st.container(border=True):
        if st.session_state.get("is_admin"):
            col_title, col_logout = st.columns([3, 1])
            with col_title:
                st.markdown("### ⚙️ 管理員選單")
            with col_logout:
                if st.button("🔓 登出", type="secondary", use_container_width=True):
                    st.session_state["is_admin"] = False
                    st.rerun()
            st.divider()

            # 公告編輯
            if "ann_draft" not in st.session_state:
                st.session_state["ann_draft"] = get_announcement()

            st.subheader("📢 公告管理")
            icon_list = ["📢","🏸","✅","❌","⚠️","🔔","🎉","📅","🟢","🔴"]
            icon_cols = st.columns(10)
            for idx, icon in enumerate(icon_list):
                if icon_cols[idx].button(icon, key=f"icon_{icon}"):
                    st.session_state["ann_draft"] += icon
                    st.rerun()
            fmt_cols = st.columns(7)
            fmt_btns = [("粗體","**文字**"),("大字","# 標題"),("中字","## 標題"),("小字","### 標題"),("換行","\n"),("分隔線","\n---\n"),("🔆 醒目","> ")]
            for idx, (label, tag) in enumerate(fmt_btns):
                if fmt_cols[idx].button(label, key=f"fmt_{idx}"):
                    st.session_state["ann_draft"] += tag
                    st.rerun()
            new_ann = st.text_area("公告內容", value=st.session_state["ann_draft"],
                                   height=100, key="ann_textarea", label_visibility="collapsed")
            st.session_state["ann_draft"] = new_ann
            if new_ann.strip():
                ann_html = new_ann.replace("\n", "<br>")
                st.markdown(
                    f"""<div style='border:2px solid #3b82f6;border-radius:12px;padding:12px 16px;
                    background:linear-gradient(135deg,#1e2a3a,#1a1f2e);
                    font-size:14px;line-height:1.8;color:#e2e8f0;margin-bottom:4px'>
                    {ann_html}</div>""", unsafe_allow_html=True
                )
            pc, cc = st.columns([2, 1])
            with pc:
                if st.button("發布公告", type="primary", use_container_width=True):
                    with open("announcement.txt", "w", encoding="utf-8") as f:
                        f.write(new_ann)
                    st.success("公告已更新！")
                    st.rerun()
            with cc:
                if st.button("清空公告", use_container_width=True):
                    st.session_state["ann_draft"] = ""
                    with open("announcement.txt", "w", encoding="utf-8") as f:
                        f.write("")
                    st.success("已清空")
                    st.rerun()
            st.divider()

            # 聯絡人名單
            st.subheader("📱 聯絡人名單")
            with st.container(border=True):
                if admin_line_config:
                    for k_id, lname in list(admin_line_config.items()):
                        c1, c2 = st.columns([4, 1])
                        c1.text(f"💬 {lname}")
                        if c2.button("刪除", key=f"del_admin_{k_id}"):
                            del admin_line_config[k_id]
                            if save_db_admin_line_list(admin_line_config):
                                st.success("已刪除"); st.rerun()
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
                            st.success("新增成功！"); st.rerun()
            st.divider()

            # 取消場次
            st.subheader("❌ 取消場次")
            with st.form("cancel_session_form", clear_on_submit=True):
                cancel_target = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="cancel_sel")
                reason        = st.text_input("原因")
                if st.form_submit_button("確認取消"):
                    note = (session_map[cancel_target].get("note") or "").replace("[已恢復場次]", "").strip()
                    update_session(cancel_target, {"cancelled": True, "cancel_reason": reason, "note": note})
                    send_line(f"⚠️【信義羽球隊】{session_map[cancel_target]['date']} 場次已取消。原因：{reason}")
                    st.success("已取消"); time.sleep(0.5); st.rerun()

            # 恢復場次
            st.subheader("🔄 恢復場次")
            cancelled_list = [s for s in sessions_sorted if s.get("cancelled")]
            restore_map    = {s["id"]: s for s in cancelled_list}
            if restore_map:
                restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()),
                                              format_func=lambda x: user_label(restore_map[x]), key="restore_target")
                if st.button("確認恢復場次"):
                    note = restore_map[restore_target].get("note") or ""
                    if "[已恢復場次]" not in note:
                        note = f"{note} [已恢復場次]".strip()
                    update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": note})
                    send_line(f"🟢【信義羽球隊】{restore_map[restore_target]['date']} 場次已恢復，開放報名！")
                    st.success("已恢復！"); st.rerun()
            else:
                st.caption("目前沒有已取消的場次")
            st.divider()

            # 新增臨時場次
            st.subheader("➕ 加開場次")
            with st.form("add_session_form"):
                r1c1, r1c2, r1c3 = st.columns([2, 1, 1])
                with r1c1: new_date    = st.date_input("日期", min_value=date.today())
                with r1c2: start_time  = st.selectbox("開始", ["06:00","08:00","10:00","12:00","14:00","16:00","18:00","20:00"], index=6)
                with r1c3: end_time    = st.selectbox("結束", ["08:00","10:00","12:00","14:00","16:00","18:00","20:00","22:00"], index=7)
                r2c1, r2c2, r2c3 = st.columns([2, 1, 1])
                with r2c1: new_label   = st.text_input("場地", value="信義羽球館")
                with r2c2: total_quota = st.number_input("名額上限", 1, 100, 20)
                with r2c3: casual_limit= st.number_input("零打上限", 0, 100, 15)
                r3c1, r3c2 = st.columns(2)
                with r3c1: new_note    = st.text_input("備註")
                with r3c2: access_type = st.radio("開放規則", ["所有球友", "限會員"], horizontal=True)
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
                                "total_quota": int(total_quota), "casual_limit": int(casual_limit),
                                "cancelled": False, "cancel_reason": "", "locked": False,
                            }).execute()
                            get_sessions.clear()
                            send_line(f"📢【信義羽球隊】加開場次！{new_date} {start_time}-{end_time}，快上系統報名！")
                            st.success(f"已加開：{new_date} {start_time}-{end_time}"); st.rerun()
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
                    note = (session_map[target_sid].get("note") or "")
                    note = note.replace("[會員限定]", "").replace("[已恢復場次]", "").strip()
                    tag  = "[會員限定]" if rule_type == "僅限會員" else ""
                    update_session(target_sid, {"note": f"{tag} {reason_note}".strip()})
                    st.success("已更新"); time.sleep(0.5); st.rerun()
            st.divider()

            st.subheader("🛠 系統參數設定")      
            with st.container(border=True):
                current_set = get_system_settings()
                
                col_s, col_f = st.columns(2)
                with col_s:
                    new_shuttle = st.text_input("球種名稱", value=current_set.get("shuttlecock", "YY AS-50"))
                with col_f:
                    new_fee = st.number_input("零打費用 (元)", value=int(current_set.get("casual_fee", 300)))
                    
                if st.button("更新系統參數", type="primary"):
                    save_system_settings({"shuttlecock": new_shuttle, "casual_fee": int(new_fee)})
                    st.success("設定已儲存！")
                    st.rerun()             

        else:
            st.markdown("⚠️ **管理員登入**")
            pwd = st.text_input("密碼", type="password")
            if pwd == ADMIN_PASSWORD:
                st.session_state["is_admin"] = True
                st.rerun()
            elif pwd:
                st.error("密碼錯誤")

# ─────────────────────────
# 未選場次則停止
# ─────────────────────────
if not st.session_state["selected_sid"]:
    st.info("☝️ 請點選上方場次來查看詳情與報名")
    st.stop()

sid     = st.session_state["selected_sid"]
session = session_map[sid]

# 未開放場次不可進入
_s_date_check = datetime.strptime(session["date"], "%Y-%m-%d").date()
if _s_date_check > window_open:
    st.session_state["selected_sid"] = None
    st.rerun()

# ─────────────────────────
# 場次內容
# ─────────────────────────
bookings = get_bookings(sid)
active   = [b for b in bookings if b["status"] == "active"]

s_date         = datetime.strptime(session["date"], "%Y-%m-%d").date()
is_opened      = today_date >= s_date - timedelta(days=7)
is_member_only = "[會員限定]" in (session.get("note") or "")
quota          = session.get("total_quota", 20)

total_member_count = total_casual_count = current_total = waitlist_count = 0
list_to_show = []
old_waitlist_ids = set()

for b in active:
    b_count      = int(b["count"])
    raw_name     = b["name"]
    display_name = raw_name
    pwd_hidden   = line_name_hidden = ""
    modify_count = 0

    if "_🔑" in raw_name:
        parts        = raw_name.split("_🔑")
        display_name = parts[0]
        if "_💬" in parts[1]:
            sub              = parts[1].split("_💬")
            pwd_hidden       = sub[0]
            tail             = sub[1].split("_🔄")
            line_name_hidden = tail[0]
            modify_count     = int(tail[1]) if len(tail) > 1 and tail[1].isdigit() else 0

    if b["role"] == "member":
        total_member_count += b_count
        is_waitlist   = False
        current_total += b_count
    else:
        if current_total >= quota:
            is_waitlist = True
            waitlist_count += b_count
            old_waitlist_ids.add(b["id"])
        elif current_total + b_count > quota:
            is_waitlist         = "partial"
            total_casual_count += quota - current_total
            waitlist_count     += current_total + b_count - quota
            current_total       = quota
            old_waitlist_ids.add(b["id"])
        else:
            is_waitlist         = False
            current_total      += b_count
            total_casual_count += b_count

    list_to_show.append({
        "data": b, "is_waitlist": is_waitlist,
        "clean_name": display_name, "pwd": pwd_hidden,
        "line_name": line_name_hidden, "modify_count": modify_count,
    })

# 儀表板
st.markdown(f"### 📊 場次人數摘要 : {session['date']}")
m1, m2, m3, m4 = st.columns(4)
m1.metric("正取總人數",   f"{current_total} / {quota}")
m2.metric("會員",         f"{total_member_count} 人")
m3.metric("零打（正取）", f"{total_casual_count} 人")
m4.metric("候補",         f"🔴 {waitlist_count}" if waitlist_count else "0")

if st.session_state.get("is_admin"):
    with st.container(border=True):
        st.markdown("🔧 **調整本場名額**")
        new_quota = st.number_input("人數上限", 1, 200, int(quota), key=f"adjust_quota_{sid}")
        if st.button("確認修改上限"):
            update_session(sid, {"total_quota": int(new_quota)})
            st.success(f"已調整為 {new_quota} 人")
            st.rerun()

# 狀態攔截
if session.get("cancelled"):
    st.warning(f"⚠ 此場次已取消。原因：{session.get('cancel_reason','無')}")
    st.stop()
if session.get("locked"):
    st.error("❌ 此場次已關閉")
    st.stop()
if not is_opened and not st.session_state.get("is_admin"):
    st.warning(f"⏳ 尚未開放報名（將於 {s_date - timedelta(days=7)} 開放）")
    st.stop()

if current_total >= quota:
    st.warning("⚠️ 正取名額已滿！零打報名將進入候補，有人取消時依序遞補。")
elif is_member_only:
    st.warning("👑 本場次為會員限定場次")

# ─────────────────────────
# 報名表單
# ─────────────────────────
st.divider()
st.markdown("### ✍️ 我要報名")
settings = get_system_settings()
st.info(f"🏸 當前球種：{settings.get('shuttlecock')} | 💰 零打費用：{settings.get('casual_fee')} 元/人\n\n💡 會員報名不受名額限制，名額已滿時，零打報名將進入候補，成功遞補會在 Line 群組通知")

c1, c2, c3 = st.columns([2, 1, 1])
with c1: name_input  = st.text_input("球友名字", key=f"name_{sid}")
with c2: role_sel    = st.selectbox("身分", ["會員","零打"], key=f"role_{sid}")
with c3: count       = st.number_input("人數", 1, 10, 1, key=f"count_{sid}")
role = ROLE_MAP[role_sel]

if role_sel == "零打":
    pay_col1, pay_col2, pay_col3 = st.columns(3)
    with pay_col1:
        if st.button("💳 簽卡", key=f"pay_card_{sid}", use_container_width=True,
                     type="primary" if st.session_state.get(f"pay_{sid}","簽卡") == "簽卡" else "secondary"):
            st.session_state[f"pay_{sid}"] = "簽卡"
    with pay_col2:
        if st.button("💵 付現", key=f"pay_cash_{sid}", use_container_width=True,
                     type="primary" if st.session_state.get(f"pay_{sid}","簽卡") == "付現" else "secondary"):
            st.session_state[f"pay_{sid}"] = "付現"
    with pay_col3:
        if st.button("🏦 轉帳", key=f"pay_transfer_{sid}", use_container_width=True,
                     type="primary" if st.session_state.get(f"pay_{sid}","簽卡") == "轉帳" else "secondary"):
            st.session_state[f"pay_{sid}"] = "轉帳"
    pay_method = st.session_state.get(f"pay_{sid}", "簽卡")
    st.caption(f"付費方式：{pay_method}")
else:
    pay_method = ""

c4, c5 = st.columns(2)
with c4: password_input  = st.text_input("取消/修改暗號（4位數字）", type="password", max_chars=4, key=f"pwd_{sid}")
with c5: line_name_input = st.text_input("LINE 名字（想收候補通知必填）", key=f"line_{sid}")

if st.button("確認報名", type="primary"):
    if not name_input.strip():
        st.error("請輸入名字")
    elif not password_input.strip() or not password_input.isdigit():
        st.error("請設定4位數字暗號")
    elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
        st.error("本場為會員限定，零打暫不開放。")
    elif current_total >= quota and role == "casual" and not st.session_state.get("is_admin") and is_member_only:
        st.error("本場為會員限定，零打暫不開放。")
    else:
        # 使用 spinner 給予視覺回饋
        with st.spinner("正在與伺服器同步資料，請稍候..."):
            full_name = f"{name_input.strip()}[{pay_method}]" if pay_method else name_input.strip()
            add_booking_compatible(sid, full_name, role, int(count),
                                   password_input.strip(), line_name_input.strip())
            st.success("報名成功！")
            time.sleep(1) # 讓成功訊息停留一秒
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
    if b["role"] == "member":  status_tag = "🟢 正取"
    elif wl == True:           status_tag = "⏳ 候補"
    elif wl == "partial":      status_tag = "⚠️ 部分候補"
    else:                      status_tag = "🟢 正取"
    modify_tag = " (已改)" if b["role"] == "casual" and item["modify_count"] > 0 else ""

    col1, col2 = st.columns([4, 2])
    with col1:
        st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role} ｜ {status_tag}{modify_tag}")
    with col2:
        with st.expander("⚙️ 修改/取消"):
            if st.session_state.get("is_admin"):
                st.warning("⚡ 管理員模式")
                adm_new = st.number_input("調整人數（0＝刪除）", 0, 20, int(b["count"]), key=f"adm_cnt_{b['id']}")
                if st.button("管理員確認修改", key=f"adm_btn_{b['id']}"):
                    if adm_new == 0:
                        cancel_booking(b["id"], b["session_id"]); st.success("已刪除")
                    else:
                        update_booking_data(b["id"], int(adm_new)); st.success(f"已調整為 {adm_new} 人")
                    check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                    st.rerun()
            else:
                if current_total >= quota:
                    st.warning("名額已滿，如需調整請聯絡管理員。")
                input_pwd = st.text_input("請輸入密碼", type="password", key=f"pwd_verify_{b['id']}")
                if b["role"] == "casual":
                    if item["modify_count"] >= 1:
                        st.error("⚠️ 零打修改次數已達上限（1次），如需調整請聯絡管理員。")
                    else:
                        st.caption("零打限改1次（尚未使用修改次數）")
                else:
                    st.caption("會員可無限次調整人數。")
                user_new = st.number_input("新的人數（0＝取消）", 0, 10, int(b["count"]), key=f"user_cnt_{b['id']}")
                if st.button("確認提交修改", key=f"user_btn_{b['id']}"):
                    if input_pwd != item["pwd"]:
                        st.error("密碼錯誤！")
                    elif b["role"] == "casual" and item["modify_count"] >= 1 and user_new != 0:
                        st.error("零打修改次數已達上限，請聯絡管理員。")
                    else:
                        if user_new == 0:
                            cancel_booking(b["id"], b["session_id"]); st.success("已取消報名！")
                        else:
                            new_mod = item["modify_count"] + 1 if b["role"] == "casual" else item["modify_count"]
                            update_booking_data(b["id"], int(user_new),
                                new_name=f"{c_name}_🔑{item['pwd']}_💬{item['line_name']}_🔄{new_mod}")
                            st.success(f"已更新為 {user_new} 人")
                        check_and_notify_waitlist(sid, quota, old_waitlist_ids,
                                                  f"{session['date']} {session['label']}")
                        st.rerun()


def main():
    init_state()
    render_app()

if __name__ == "__main__":
    main()
