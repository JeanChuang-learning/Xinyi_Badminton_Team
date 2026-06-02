import streamlit as st
from supabase_client import supabase, LINE_CHANNEL_ACCESS_TOKEN, LINE_GROUP_ID, ADMIN_PASSWORD
from datetime import datetime, date, timedelta
from calendar import monthrange
import requests
import time
import json
import os

# ─────────────────────────
# 常數設定
# ─────────────────────────
ROLE_MAP         = {"會員": "member", "零打": "casual"}
ROLE_TO_ZH       = {"member": "會員", "casual": "零打"}
WEEKDAY_TW       = ["一", "二", "三", "四", "五", "六", "日"]

FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一晚上", "quota": 32},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五晚上", "quota": 32},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日早上", "quota": 24},
]

#quota_map = {rule["weekday"]: rule["quota"] for rule in FIXED_RULES}


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
        #else:
        #    supabase.table("sessions").insert({
        #        "id": "_admin_line_config", "date": "1970-01-01",
        #        "start_time": "00:00", "end_time": "00:00",
        #        "label": "CONFIG", "note": json_str,
        #        "total_quota": 0, "cancelled": True,
        #    }).execute()
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
                            "total_quota": rule.get("quota", 24),
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
        
def get_session_open_date(session_date_obj):
    """
    計算場次的開放報名日：
    - 週五場 (weekday=4) 與 週日場 (weekday=6)：當週三開放（session_date - 到最近的週三）
    - 週一場 (weekday=0)：前一週五開放（session_date - 到前一個週五）
    - 其他：預設 7 天前開放
    """
    wd = session_date_obj.weekday()
    if wd == 4:  # 週五場 → 當週三開放（週五 - 2天）
        return session_date_obj - timedelta(days=2)
    elif wd == 6:  # 週日場 → 當週三開放（週日 - 4天）
        return session_date_obj - timedelta(days=4)
    elif wd == 0:  # 週一場 → 前週五開放（週一 - 3天）
        return session_date_obj - timedelta(days=3)
    else:
        return session_date_obj - timedelta(days=7)

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
        #else:
        #    supabase.table("sessions").insert({
        #        "id": "_system_settings", "date": "1970-01-01",
        #        "start_time": "00:00", "end_time": "00:00",
        #        "label": "SETTINGS", "note": json_str,
        #        "total_quota": 0, "cancelled": True
        #    }).execute()
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
window_preview = today_date + timedelta(days=14)

def is_casual_open_for_signup(session_date_obj):
    """判斷零打今天是否已開放報名（依星期規則）"""
    open_date = get_session_open_date(session_date_obj)
    return today_date >= open_date

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
        quota_k    = s.get("total_quota", 24)
        date_short = s["date"][5:]
        time_short = f"{start_t[:2]}-{end_t[:2]}"

        try:
            end_h, end_m = map(int, end_t.split(":"))
            session_end_dt = datetime.combine(s_date_obj, datetime.min.time()).replace(hour=end_h, minute=end_m)
            is_ended = datetime.now() > session_end_dt
        except Exception:
            is_ended = s_date_obj < today_date

        casual_open = is_casual_open_for_signup(s_date_obj)

        if is_ended:
            status = "⬜ 已結束"
        elif s.get("cancelled") or s.get("locked"):
            status = "❌ 不開放"
        elif "[會員限定]" in note:
            status = "👑 會員限定"
        elif not casual_open:
            status = "🔵 會員先行"
        elif used >= quota_k:
            status = "🟡 滿額"
        else:
            status = "🟢 開放"

        btn_label = f"{date_short}({wd}) {time_short} {status}"

        # 只有「已結束」和「取消/鎖定」才 disabled，其他全部可點
        is_disabled = is_ended or s.get("cancelled") or s.get("locked")

        if is_disabled:
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

        if not st.session_state.get("is_admin"):
            st.markdown("### 🔐 管理員登入")
            pwd = st.text_input("請輸入管理員密碼", type="password", key="admin_pwd_input")
            if st.button("登入", type="primary", key="admin_login_btn"):
                if pwd == ADMIN_PASSWORD:
                    st.session_state["is_admin"] = True
                    st.rerun()
                elif pwd:
                    st.error("密碼錯誤")
        else:
            # 初始化公告草稿
            if "ann_draft" not in st.session_state:
                st.session_state["ann_draft"] = get_announcement()

            # --- 已登入，顯示選單與標籤頁 ---
            col_title, col_logout = st.columns([3, 1])
            with col_logout:
                if st.button("登出", key="admin_logout"):
                    st.session_state["is_admin"] = False
                    st.session_state["show_admin"] = False
                    st.rerun()
            st.markdown("### ⚙️ 管理員控制台")
            # 1. 定義標籤頁（加開/規則合併進場次管理）
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "📢 公告", "📱 聯絡人", "🗓️ 場次管理", "🛠 系統參數", "📋 報名紀錄"
            ])

        # 2. 將功能分類放入對應的 tab
            with tab1:
                # 原本的公告編輯邏輯
                st.subheader("📢 公告管理")
                icon_list = ["📢","🏸","✅","❌","⚠️","🔔","🎉","📅","🟢","🔴"]
                icon_cols = st.columns(10)
                for idx, icon in enumerate(icon_list):
                    if icon_cols[idx].button(icon, key=f"icon_{icon}"):
                        st.session_state["ann_draft"] += icon
                        st.rerun()
                fmt_cols = st.columns(7)
                fmt_btns = [("粗體","**文字**"),("大字","# 標題"),("中字","## 標題"),("小字","### 標題"),("換行","\n"),("分隔線","\n---\n"),("醒目","> ")]
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
            
            with tab2:
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

            with tab3:
                st.subheader("🗓️ 場次管理")

                # ── 1. 取消場次 ──
                with st.expander("❌ 取消場次", expanded=False):
                    with st.form("cancel_session_form", clear_on_submit=True):
                        cancel_target = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="cancel_sel")
                        reason = st.text_input("原因")
                        if st.form_submit_button("確認取消"):
                            note = (session_map[cancel_target].get("note") or "").replace("[已恢復場次]", "").strip()
                            update_session(cancel_target, {"cancelled": True, "cancel_reason": reason, "note": note})
                            send_line(f"⚠️【信義羽球隊】{session_map[cancel_target]['date']} 場次已取消。原因：{reason}")
                            st.success("已取消"); st.rerun()

                # ── 2. 恢復場次 ──
                with st.expander("🔄 恢復場次", expanded=False):
                    cancelled_list = [s for s in sessions_sorted if s.get("cancelled")]
                    restore_map = {s["id"]: s for s in cancelled_list}
                    if restore_map:
                        restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()),
                                                      format_func=lambda x: user_label(restore_map[x]), key="restore_target")
                        if st.button("確認恢復場次"):
                            note = restore_map[restore_target].get("note") or ""
                            if "[已恢復場次]" not in note:
                                note = f"{note} [已恢復場次]".strip()
                            update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": note})
                            send_line(f"🟢【信義羽球隊】{restore_map[restore_target]['date']} 場次已恢復！")
                            st.success("已恢復！"); st.rerun()
                    else:
                        st.caption("目前沒有已取消的場次")

                # ── 3. 會員限定切換 ──
                with st.expander("👑 設定會員限定", expanded=False):
                    future_keys = [k for k in keys if not session_map[k].get("cancelled")]
                    if future_keys:
                        member_target = st.selectbox(
                            "選擇場次", future_keys,
                            format_func=lambda x: user_label(session_map[x]),
                            key="member_only_sel"
                        )
                        target_s   = session_map[member_target]
                        target_note = target_s.get("note") or ""
                        is_currently_member_only = "[會員限定]" in target_note
                        st.info(f"目前狀態：{'👑 會員限定' if is_currently_member_only else '🟢 一般開放（含零打）'}")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("設為 👑 會員限定", disabled=is_currently_member_only, use_container_width=True):
                                new_note = f"{target_note} [會員限定]".strip()
                                update_session(member_target, {"note": new_note})
                                send_line(f"👑【信義羽球隊】{target_s['date']} {target_s['label']} 已改為會員限定場次。")
                                st.success("已設為會員限定！"); st.rerun()
                        with col_b:
                            if st.button("改回 🟢 一般開放", disabled=not is_currently_member_only, use_container_width=True):
                                new_note = target_note.replace("[會員限定]", "").strip()
                                update_session(member_target, {"note": new_note})
                                send_line(f"🟢【信義羽球隊】{target_s['date']} {target_s['label']} 已開放零打報名。")
                                st.success("已改回一般開放！"); st.rerun()
                    else:
                        st.caption("目前沒有可設定的場次")

                # ── 4. 加開臨時場次 ──
                with st.expander("🔥 加開臨時場次", expanded=False):
                    with st.form("add_session_form", clear_on_submit=True):
                        add_date  = st.date_input("日期", value=date.today() + timedelta(days=1), key="add_date")
                        add_start = st.time_input("開始時間", value=datetime.strptime("19:00", "%H:%M").time(), key="add_start")
                        add_end   = st.time_input("結束時間", value=datetime.strptime("22:00", "%H:%M").time(), key="add_end")
                        add_label = st.text_input("場次名稱", value="臨時加開", key="add_label")
                        add_quota = st.number_input("人數上限", min_value=1, max_value=200, value=24, key="add_quota")
                        add_note  = st.text_input("備註（選填）", key="add_note")
                        if st.form_submit_button("確認加開", type="primary"):
                            new_sid = f"{add_date.isoformat()}_{add_start.strftime('%H:%M')}_extra_{int(time.time())}"
                            try:
                                supabase.table("sessions").insert({
                                    "id": new_sid,
                                    "date": str(add_date),
                                    "start_time": add_start.strftime("%H:%M"),
                                    "end_time":   add_end.strftime("%H:%M"),
                                    "label":      add_label,
                                    "note":       add_note,
                                    "total_quota": int(add_quota),
                                    "cancelled": False, "cancel_reason": "", "locked": False,
                                }).execute()
                                get_sessions.clear()
                                send_line(f"📢【信義羽球隊】加開場次：{add_date} {add_label} {add_start.strftime('%H:%M')}-{add_end.strftime('%H:%M')}，名額 {add_quota} 人")
                                st.success("加開成功！"); st.rerun()
                            except Exception as e:
                                st.error(f"加開失敗：{e}")

                # ── 5. 修改場次資訊 ──                
                with st.expander("⚙️ 修改場次資訊", expanded=False):
                    # selectbox 必須在 form 外，才能讓 value 動態跟著選擇更新
                    edit_target = st.selectbox(
                        "選擇場次", keys,
                        format_func=lambda x: user_label(session_map[x]),
                        key="edit_sel"
                    )
                    st.write(f"當前 edit_target: {edit_target}") # 先看看它到底是不是空的
                    edit_s = session_map[edit_target]
                    # 用不含 form 的獨立 widget，直接用按鈕提交
                    edit_label = st.text_input("場次名稱", value=edit_s.get("label", ""), key=f"elabel_{edit_target}")                    
                    edit_quota = st.number_input("人數上限", min_value=1, max_value=200, value=int(edit_s.get("total_quota", 20)), key=f"equota_{edit_target}")
                    edit_note  = st.text_input("備註", value=edit_s.get("note") or "", key=f"enote_{edit_target}")
                    if st.button("確認更新", key="edit_session_btn", type="primary"):
                        update_session(edit_target, {
                            "label":       edit_label,
                            "total_quota": int(edit_quota),
                            "note":        edit_note,
                        })
                        st.success("已更新！"); st.rerun()

            with tab4:
                st.subheader("🛠 系統參數設定")
                with st.expander("📝 修改球種與費用", expanded=st.session_state.get("expand_settings", False)):
                    current_set = get_system_settings()
                    new_shuttle = st.text_input("球種名稱", value=current_set.get("shuttlecock", "YY AS-50"))
                    new_fee = st.number_input("零打費用 (元)", value=int(current_set.get("casual_fee", 300)))
                    if st.button("更新系統參數", type="primary"):
                        save_system_settings({"shuttlecock": new_shuttle, "casual_fee": int(new_fee)})
                        st.success("設定已儲存！")
                        st.session_state["expand_settings"] = False
                        st.rerun()

            # ── Tab 5：過去 7 天報名紀錄（管理員專屬）──
            with tab5:
                st.subheader("📋 過去 7 天報名紀錄")
                cutoff = today_date - timedelta(days=7)
                hist_sessions = [
                    s for s in sessions_sorted
                    if s.get("id") and not s["id"].startswith("_")
                    and cutoff <= datetime.strptime(s["date"], "%Y-%m-%d").date() <= today_date
                ]
                if not hist_sessions:
                    st.info("過去 7 天內無場次紀錄。")
                else:
                    for hs in hist_sessions:
                        hs_date   = hs["date"]
                        hs_label  = hs.get("label","")
                        hs_start  = hs.get("start_time","")[:5]
                        hs_end    = hs.get("end_time","")[:5]
                        hs_quota  = hs.get("total_quota", 24)
                        hs_bks    = get_bookings(hs["id"])
                        hs_active = [b for b in hs_bks if b["status"] == "active"]
                        hs_total  = sum(int(b["count"]) for b in hs_active)
                        with st.expander(f"📅 {hs_date} {hs_label} {hs_start}-{hs_end}　（{hs_total}/{hs_quota} 人）", expanded=False):
                            if not hs_active:
                                st.caption("無報名紀錄")
                            else:
                                for b in hs_active:
                                    raw   = b["name"]
                                    dname = raw.split("_🔑")[0] if "_🔑" in raw else raw
                                    zh_r  = ROLE_TO_ZH.get(b["role"], b["role"])
                                    st.write(f"● {dname} ｜ {b['count']} 人 ｜ {zh_r}")


# ─────────────────────────
# 未選場次則停止
# ─────────────────────────
if not st.session_state["selected_sid"]:
    st.info("☝️ 請點選上方場次來查看詳情與報名")
    st.stop()

sid     = st.session_state["selected_sid"]
session = session_map[sid]

# ─────────────────────────
# 場次內容
# ─────────────────────────
bookings = get_bookings(sid)
active   = [b for b in bookings if b["status"] == "active"]

s_date         = datetime.strptime(session["date"], "%Y-%m-%d").date()
casual_open    = is_casual_open_for_signup(s_date)   # 零打開放：依星期規則
member_open    = s_date <= today_date + timedelta(days=14)  # 會員：兩週內皆可報名
is_member_only = "[會員限定]" in (session.get("note") or "")
quota          = session.get("total_quota", 24)

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
        new_quota = st.number_input("人數上限", min_value=1, max_value=200, value=int(quota), key=f"adjust_quota_{sid}")
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

# 零打尚未開放時顯示提示（但仍可查看名單；會員不受此限制）
if not casual_open and not st.session_state.get("is_admin"):
    open_dt = get_session_open_date(s_date)
    st.warning(f"⏳ 零打報名尚未開放（開放日：{open_dt}）。會員可直接報名。")

c1, c2, c3 = st.columns([2, 1, 1])
with c1: name_input  = st.text_input("球友名字", key=f"name_{sid}")
with c2: role_sel    = st.selectbox("身分", ["會員","零打"], key=f"role_{sid}")
with c3: count       = st.number_input("人數", min_value=1, max_value=10, value=1, key=f"count_{sid}")
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
with c4: password_input  = st.text_input("取消/修改暗號（4位英數字）", type="password", max_chars=4, key=f"pwd_{sid}")
with c5: line_name_input = st.text_input("LINE 名字（想收候補通知必填）", key=f"line_{sid}")

if st.button("確認報名", type="primary"):
    if not name_input.strip():
        st.error("請輸入名字")
    elif len(password_input.strip()) != 4 or not password_input.strip().isalnum():
        st.error("請設定4位英數字暗號（字母或數字皆可）")
    elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
        st.error("本場為會員限定，零打暫不開放。")
    elif role == "casual" and not casual_open and not st.session_state.get("is_admin"):
        open_dt = get_session_open_date(s_date)
        st.error(f"零打報名尚未開放，開放日為 {open_dt}。")
    else:
        with st.spinner("正在與伺服器同步資料，請稍候..."):
            full_name = f"{name_input.strip()}[{pay_method}]" if pay_method else name_input.strip()
            add_booking_compatible(sid, full_name, role, int(count),
                                   password_input.strip(), line_name_input.strip())
            st.success("報名成功！")
            time.sleep(1)
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
    elif wl == "partial":
        confirmed_part = quota - (current_total - b_count) if (current_total - b_count) < quota else 0
        # 重新計算此筆的正取/候補人數
        _before = current_total - b_count
        _confirmed_in_this = max(0, min(b_count, quota - _before)) if _before < quota else 0
        _waitlist_in_this = b_count - _confirmed_in_this
        status_tag = f"⚠️ 部分候補（正取 {_confirmed_in_this} 人 / 備取 {_waitlist_in_this} 人）"
    else:                      status_tag = "🟢 正取"
    modify_tag = " (已改)" if b["role"] == "casual" and item["modify_count"] > 0 else ""

    col1, col2 = st.columns([4, 2])
    with col1:
        st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role} ｜ {status_tag}{modify_tag}")
    with col2:
        with st.expander("⚙️ 修改/取消"):
            if st.session_state.get("is_admin"):
                st.warning("⚡ 管理員模式")
                adm_new = st.number_input("調整人數（0＝刪除）", min_value=0, max_value=20, value=int(b["count"]), key=f"adm_cnt_{b['id']}")
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
                user_new = st.number_input("新的人數（0＝取消）", min_value=0, max_value=10, value=int(b["count"]), key=f"user_cnt_{b['id']}")
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
