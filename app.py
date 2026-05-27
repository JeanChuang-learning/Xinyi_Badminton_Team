import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import requests  
import time

# ─────────────────────────
# config & Line 設定
# ─────────────────────────
ADMIN_PASSWORD = "admin"
ROLE_MAP = {"會員": "member", "零打": "casual"}

# 💡 如果您之後申請了 Line Notify Token，填在這邊就能連動群組發通知！
LINE_NOTIFY_TOKEN = "" 

# 固定場次規則：0=週一, 4=週五, 6=週日
FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日早上"},
]

# ─────────────────────────
# helpers
# ─────────────────────────
def user_label(s):
    base = f"{s['date']}｜{s['label']}｜{s['start_time']}-{s['end_time']}"
    
    if s.get("cancelled"):
        if s.get("id") and not s["id"].endswith("_fixed"):
            return f"{base} ❌已取消（{s.get('cancel_reason', '')}）"
        else:
            return f"{base} ❌不開放（{s.get('cancel_reason', '')}）"
        
    if s.get("locked"):
        return f"{base} 🔒關閉報名"
        
    if s.get("note") and "[會員限定]" in s.get("note"):
        base = f"{base} 👑 會員限定"
        
    if s.get("note") and "[已恢復場次]" in s.get("note"):
        base = f"{base} ✨ 恢復開放"

    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        open_date = session_date - timedelta(days=7)
        if date.today() < open_date:
            return f"{base} ⏳ 尚未開放（{open_date.strftime('%m/%d')} 開放）"
    except ValueError:
        pass

    return base


def send_line_message(message):
    if not LINE_NOTIFY_TOKEN:
        return
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"}
    data = {"message": message}
    try:
        requests.post(url, headers=headers, data=data)
    except Exception as e:
        print(f"Line 通知發送失敗: {e}")

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


def get_bookings(session_id):
    try:
        res = (
            supabase.table("bookings")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
        return res.data or []
    except Exception as e:
        st.error(f"💥 讀取報名資料失敗：{e}")
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
        st.error(f"💥 寫入資料庫失敗：{e}")
        st.stop()


def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    payload = {"count": new_count, "status": status}
    if new_name:
        payload["name"] = new_name
    supabase.table("bookings").update(payload).eq("id", booking_id).execute()


def cancel_booking(booking_id):
    supabase.table("bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()


def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()


def auto_generate_fixed_sessions(existing_sessions):
    today = date.today()
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new_inserted = False

    for i in range(36):
        check_date = today + timedelta(days=i)
        w = check_date.weekday()
        for rule in FIXED_RULES:
            if w == rule["weekday"]:
                session_id = f"{check_date.isoformat()}_{rule['start_time']}_fixed"
                if session_id not in existing_keys:
                    try:
                        supabase.table("sessions").insert({
                            "id": session_id,
                            "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立的固定場次",
                            "total_quota": 20,
                            "cancelled": False,
                            "cancel_reason": "",
                            "locked": False,
                        }).execute()
                        has_new_inserted = True
                    except Exception as e:
                        print(f"自動新增場次失敗: {e}")
    if has_new_inserted:
        return get_sessions()
    return existing_sessions


def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info):
    time.sleep(0.3)
    updated_bookings = get_bookings(sid)
    updated_active = [ub for ub in updated_bookings if ub["status"] == "active"]
    
    chk_total = 0
    for ub in updated_active:
        ub_count = int(ub["count"])
        if ub["id"] in old_waitlist_ids and (chk_total + ub_count <= quota):
            if "_💬" in ub["name"]:
                try:
                    parts = ub["name"].split("_🔑")
                    u_clean = parts[0]
                    sub_parts = parts[1].split("_💬")
                    sub_sub = sub_parts[1].split("_🔄")
                    u_line = sub_sub[0]
                    if u_line.strip():
                        send_line_message(f"\n📢【場次候補成功通知】\n@{u_line} ({u_clean})\n您申請的 {session_label_info} 已成功遞補為【正取】，期待您的出席！🏸")
                except Exception:
                    pass
        chk_total += ub_count

# ─────────────────────────
# UI 初始化
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

raw_sessions = get_sessions()
sessions = auto_generate_fixed_sessions(raw_sessions)
today = date.today()

start_bound = today - timedelta(days=3)
end_bound = today + timedelta(days=35)

filtered_sessions = []
for s in sessions:
    if not s.get("date"): continue
    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if start_bound <= session_date <= end_bound:
            filtered_sessions.append(s)
    except ValueError: continue

sessions_sorted = sorted(filtered_sessions, key=lambda s: (s["date"], s["start_time"]))
session_map = {s["id"]: s for s in sessions_sorted if s.get("id")}

# ─────────────────────────
# 前端主功能區塊
# ─────────────────────────
if session_map:
    selected_id = st.selectbox("選擇場次", list(session_map.keys()), format_func=lambda x: user_label(session_map[x]))
    session = session_map[selected_id]
    sid = selected_id

    bookings = get_bookings(sid)
    active = [b for b in bookings if b["status"] == "active"]

    is_member_only = session.get("note") and "[會員限定]" in session.get("note")
    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    open_date = s_date - timedelta(days=7) 
    is_opened = today >= open_date

    quota = session.get("total_quota", 20)
    total_member_count = 0
    total_casual_count = 0
    current_total = 0
    waitlist_count = 0
    list_to_show = []
    
    old_waitlist_ids = set()
    
    for b in active:
        b_count = int(b["count"])
        
        raw_name = b["name"]
        display_name = raw_name
        pwd_hidden = ""
        line_name_hidden = ""
        modify_count = 0
        
        if "_🔑" in raw_name:
            parts = raw_name.split("_🔑")
            display_name = parts[0]
            if "_💬" in parts[1]:
                sub_parts = parts[1].split("_💬")
                pwd_hidden = sub_parts[0]
                if "_🔄" in sub_parts[1]:
                    sub_sub = sub_parts[1].split("_🔄")
                    line_name_hidden = sub_sub[0]
                    modify_count = int(sub_sub[1]) if sub_sub[1].isdigit() else 0
                else:
                    line_name_hidden = sub_parts[1]

        if b["role"] == "member": total_member_count += b_count
        elif b["role"] == "casual": total_casual_count += b_count
            
        # 💡 計算與標註：區分正取、部分候補、完全候補
        if current_total >= quota:
            is_waitlist = True
            waitlist_count += b_count
            old_waitlist_ids.add(b["id"])
        elif current_total + b_count > quota:
            is_waitlist = "partial"
            waitlist_count += (current_total + b_count - quota)
            current_total = quota
            old_waitlist_ids.add(b["id"])
        else:
            is_waitlist = False
            current_total += b_count
            
        list_to_show.append({
            "data": b, 
            "is_waitlist": is_waitlist, 
            "clean_name": display_name, 
            "pwd": pwd_hidden, 
            "line_name": line_name_hidden,
            "modify_count": modify_count
        })

    # 儀表板
    st.markdown("### 📊 本日場次人數摘要")
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("正取總人數", f"{current_total} / {quota} 人")
    with m2: st.metric("會員人數", f"{total_member_count} 人")
    with m3: st.metric("零打人數", f"{total_casual_count} 人")
    with m4: st.metric("候補人數", f"🔴 {waitlist_count} 人" if waitlist_count > 0 else "0 人")

    # 管理員調整上限
    if st.session_state.get("is_admin"):
        with st.container(border=True):
            st.markdown("🔧 **管理員專區：動態調整本場名額**")
            new_quota = st.number_input("調整本場人數上限", min_value=1, max_value=200, value=int(quota), key=f"adjust_quota_{sid}")
            if st.button("確認修改上限"):
                update_session(sid, {"total_quota": int(new_quota)})
                st.success(f"已成功將人數上限調整為 {new_quota} 人！")
                st.rerun()

    # 狀態檢查
    if session.get("cancelled"):
        st.warning(f"⚠ 此場次已取消/不開放。原因：{session.get('cancel_reason', '無')}")
    elif session.get("locked"):
        st.error("❌ 此場次已關閉")
    elif not is_opened and not st.session_state.get("is_admin"):
        st.warning(f"⏳ 尚未開放報名（本場次將於 {open_date.strftime('%Y-%m-%d')} 開放報名）")
    else:
        if current_total >= quota:
            st.error("🚨 提示：目前正取名額已滿！系統已自動開啟【會員候補保護機制】，此時段僅限「會員」可登記候補，零打暫停登記。")
        elif is_member_only: 
            st.warning("👑 提示：本場次為【會員限定場次】")
        
        st.divider()
        st.markdown("### ✍️ 我要報名")
        
        st.info("💡 **候補備註**：名額已滿時會進入候補。如果您希望收到遞補成功通知，請留下您的 Line 名字，遞補成功時系統會於群組標記您！")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1: name_input = st.text_input("球友名字")
        with col2: role = ROLE_MAP[st.selectbox("身分", ["會員", "零打"])]
        with col3: count = st.number_input("人數", 1, 10, 1)
            
        col4, col5 = st.columns([2, 2])
        with col4: password_input = st.text_input("自訂取消/修改暗號 (4位數數字)", type="password", max_chars=4)
        with col5: line_name_input = st.text_input("Line 名字 (想收候補通知必填)", placeholder="請填寫Line群組內的名稱")

        if st.button("確認報名", type="primary"):
            if not name_input.strip(): 
                st.error("請輸入名字")
            elif not password_input.strip() or not password_input.isdigit(): 
                st.error("請設定4位數字的取消/修改暗號")
            elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
                st.error("⚠️ 本場次為會員限定場，零打暫不開放報名。")
            elif current_total >= quota and role == "casual" and not st.session_state.get("is_admin"):
                st.error("⚠️ 報名失敗：目前本場次正取名額已滿，進入候補階段。依球隊規則，此時僅開放固定會員登記候補，零打球友請改選其他場次！")
            else:
                add_booking_compatible(sid, name_input.strip(), role, int(count), password_input.strip(), line_name_input.strip())
                st.success("報名成功！")
                st.rerun()

    # 顯示名單與修改區塊
    st.subheader("👥 現有報名名單")
    ROLE_TO_ZH = {"member": "會員", "casual": "零打"}

    if not list_to_show:
        st.caption("目前尚無人報名")
        
    for item in list_to_show:
        b = item["data"]
        wl = item["is_waitlist"]
        zh_role = ROLE_TO_ZH.get(b['role'], b['role'])
        c_name = item["clean_name"]
        
        # 💡 依據候補狀態，決定要貼上什麼標籤
        if wl == True:
            status_tag = "🔴 [⏳ 候補]"
        elif wl == "partial":
            status_tag = "🟡 [⚠️ 部分候補]"
        else:
            status_tag = "🟢 [🟢 正取]"
            
        col1, col2 = st.columns([4, 2])
        with col1:
            modify_tag = f" (已改)" if b['role'] == 'casual' and item['modify_count'] > 0 else ""
            st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role} ｜ {status_tag}{modify_tag}")
            
        with col2:
            with st.popover("⚙️ 修改/取消", use_container_width=True):
                if st.session_state.get("is_admin"):
                    st.warning("⚡ 管理員模式：擁有最高修改權限")
                    adm_new_count = st.number_input("調整報名人數 (填 0 等於刪除)", 0, 20, int(b["count"]), key=f"adm_cnt_{b['id']}")
                    if st.button("管理員確認修改", key=f"adm_btn_{b['id']}"):
                        if adm_new_count == 0:
                            cancel_booking(b["id"])
                            st.success("已成功刪除該筆報名")
                        else:
                            update_booking_data(b["id"], int(adm_new_count))
                            st.success(f"已將人數調整為 {adm_new_count} 人")
                        
                        check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                        st.rerun()
                else:
                    input_pwd = st.text_input("請輸入密碼", type="password", key=f"pwd_verify_{b['id']}")
                    
                    if b['role'] == 'casual':
                        st.caption(f"💡 零打限制修改 1 次 (您目前已修改: {item['modify_count']} 次)")
                    else:
                        st.caption("💡 固定會員可無限次自由微調人數。")
                        
                    user_new_count = st.number_input("請選擇新的人數 (填 0 等於取消報名)", 0, 10, int(b["count"]), key=f"user_cnt_{b['id']}")
                    
                    if st.button("確認提交修改", key=f"user_btn_{b['id']}"):
                        if input_pwd != item["pwd"]:
                            st.error("❌ 密碼錯誤，無法修改！")
                        elif b['role'] == 'casual' and item['modify_count'] >= 1 and user_new_count != 0:
                            st.error("❌ 修改失敗：零打身分限制僅能修改 1 次報名人數！(如需特殊協助請洽管理員)")
                        else:
                            if user_new_count == 0:
                                cancel_booking(b["id"])
                                st.success("已成功取消您的報名！")
                            else:
                                new_mod_count = item['modify_count'] + 1 if b['role'] == 'casual' else item['modify_count']
                                new_composite_name = f"{c_name}_🔑{item['pwd']}_💬{item['line_name']}_🔄{new_mod_count}"
                                
                                update_booking_data(b["id"], int(user_new_count), new_name=new_composite_name)
                                st.success(f"修改成功！人數已更新為 {user_new_count} 人")
                            
                            check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                            st.rerun()
else:
    st.info("💡 目前暫無可顯示之場次。")

# ─────────────────────────
# 管理員功能區塊
# ─────────────────────────
st.divider()
with st.expander("🔒 管理"):
    if st.session_state.get("is_admin"):
        st.markdown("### ⚙️ 管理員選單")
        if st.button("🔓 登出管理員模式", type="secondary"):
            st.session_state["is_admin"] = False
            st.rerun()
        st.divider()

        # 取消場次
        st.subheader("❌ 取消場次")
        if session_map:
            with st.form("cancel_session_form", clear_on_submit=True):
                cancel_target = st.selectbox("選擇要取消的場次", list(session_map.keys()), format_func=lambda x: user_label(session_map[x]))
                reason = st.text_input("原因")
                submit_cancel = st.form_submit_button("確認取消場次")
                if submit_cancel:
                    current_note = session_map[cancel_target].get("note") or ""
                    clean_note = current_note.replace("[已恢復場次]", "").strip()
                    update_session(cancel_target, {"cancelled": True, "cancel_reason": reason, "note": clean_note})
                    st.success("已成功取消該場次")
                    time.sleep(0.5)
                    st.rerun()

        # 恢復場次
        st.subheader("🔄 恢復場次")
        cancelled_sessions = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map = {s["id"]: s for s in cancelled_sessions}
        if restore_map:
            restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()), format_func=lambda x: user_label(restore_map[x]), key="restore_target")
            if st.button("確認恢復場次"):
                current_note = restore_map[restore_target].get("note") or ""
                new_note = current_note if "[已恢復場次]" in current_note else f"{current_note} [已恢復場次]".strip()
                update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": new_note})
                st.success("已成功恢復該場次！")
                st.rerun()

        # 新增臨時場次
        st.subheader("➕ 新增臨時加開場次")
        new_date = st.date_input("日期", key="new_date")
        new_start = st.text_input("開始時間", "19:00", key="new_start").strip()
        new_end = st.text_input("結束時間", "22:00", key="new_end").strip()
        new_label = st.text_input("名稱", "加開場次", key="new_label").strip()
        new_quota = st.number_input("名額", min_value=1, max_value=200, value=20, key="new_quota")
        access_type = st.radio("開放對象設定", ["所有人皆可報名", "限會員報名（零打不可）"], horizontal=True)
        new_note = st.text_area("備註內容 (選填)", key="new_note")

        if st.button("新增臨時場次"):
            if not new_label: st.error("請填寫場次名稱")
            else:
                final_note = new_note.strip()
                if access_type == "限會員報名（零打不可）": final_note = f"{final_note} [會員限定]".strip()
                new_id = f"{new_date}_{new_start}_{int(time.time())}"
                supabase.table("sessions").insert({
                    "id": new_id, "date": str(new_date), "start_time": new_start, "end_time": new_end,
                    "label": new_label, "note": final_note, "total_quota": new_quota,
                    "cancelled": False, "cancel_reason": "", "locked": False,
                }).execute()
                st.success("臨時場次新增成功")
                st.rerun()
    else:
        pwd = st.text_input("密碼", type="password")
        if pwd == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
        elif pwd: st.error("密碼錯誤")
