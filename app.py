import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import time

# ─────────────────────────
# config
# ─────────────────────────
ADMIN_PASSWORD = "admin"

ROLE_MAP = {"會員": "member", "零打": "casual"}

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
    
    # 優先權 1：如果管理員已經取消此場次，一律顯示不開放報名，並附上原因
    if s.get("cancelled"):
        return f"{base} ❌不開放（{s.get('cancel_reason', '')}）"
        
    # 優先權 2：如果被手動鎖定
    if s.get("locked"):
        return f"{base} 🔒關閉報名"
        
    # 優先權 3：檢查是否為會員限定場次
    if s.get("note") and "[會員限定]" in s.get("note"):
        base = f"{base} 👑 會員限定"
        
    # 優先權 4：檢查是否為「重新開放」的場次（透過備註或標記判定）
    if s.get("note") and "[已恢復場次]" in s.get("note"):
        base = f"{base} ✨ 恢復開放"

    # 優先權 5：正常沒被取消的場次，檢查是否到了開放時間（前一週開放）
    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        open_date = session_date - timedelta(days=7)
        if date.today() < open_date:
            return f"{base} ⏳ 尚未開放（{open_date.strftime('%m/%d')} 開放）"
    except ValueError:
        pass

    return base

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


def add_booking(session_id, name, role, count):
    try:
        supabase.table("bookings").insert({
            "session_id": session_id,
            "name": name,
            "role": role,
            "count": count,
            "status": "active",
        }).execute()
    except Exception as e:
        st.error(f"💥 寫入資料庫失敗！真實原因：{e}")
        st.stop()


def cancel_booking(booking_id):
    supabase.table("bookings") \
        .update({"status": "cancelled"}) \
        .eq("id", booking_id) \
        .execute()


def update_session(session_id, payload):
    supabase.table("sessions") \
        .update(payload) \
        .eq("id", session_id) \
        .execute()


def auto_generate_fixed_sessions(existing_sessions):
    """自動檢查並建立未來 35 天（約一個月）內的固定場次"""
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

# ─────────────────────────
# UI 初始化
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# 載入所有場次
# ─────────────────────────
raw_sessions = get_sessions()
sessions = auto_generate_fixed_sessions(raw_sessions)

today = date.today()

# 大家都看得到未來 35 天（約一個月）的場次
start_bound = today - timedelta(days=3)
end_bound = today + timedelta(days=35)

filtered_sessions = []
for s in sessions:
    if not s.get("date"):
        continue
    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if start_bound <= session_date <= end_bound:
            filtered_sessions.append(s)
    except ValueError:
        continue

# 排序
sessions_sorted = sorted(filtered_sessions, key=lambda s: (s["date"], s["start_time"]))

# 建立場次對照字典
session_map = {s["id"]: s for s in sessions_sorted if s.get("id")}

# ─────────────────────────
# 前端主功能區塊（使用者介面）
# ─────────────────────────
if session_map:
    selected_id = st.selectbox(
        "選擇場次",
        list(session_map.keys()),
        format_func=lambda x: user_label(session_map[x])
    )

    session = session_map[selected_id]
    sid = selected_id

    bookings = get_bookings(sid)
    active = [b for b in bookings if b["status"] == "active"]

    # 檢查是否為會員限定場
    is_member_only = session.get("note") and "[會員限定]" in session.get("note")

    # 計算開放時間
    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    open_date = s_date - timedelta(days=7) 
    is_opened = today >= open_date

    # 人數與統計邏輯
    quota = session.get("total_quota", 20)
    total_member_count = 0
    total_casual_count = 0
    current_total = 0
    waitlist_count = 0
    list_to_show = []
    
    for b in active:
        b_count = int(b["count"])
        b_role = b["role"]
        
        if b_role == "member":
            total_member_count += b_count
        elif b_role == "casual":
            total_casual_count += b_count
            
        if current_total >= quota:
            is_waitlist = True
            waitlist_count += b_count
        elif current_total + b_count > quota:
            is_waitlist = "partial"
            waitlist_count += (current_total + b_count - quota)
            current_total = quota
        else:
            is_waitlist = False
            current_total += b_count
            
        list_to_show.append({"data": b, "is_waitlist": is_waitlist})

    # 儀表板
    st.markdown("### 📊 本日場次人數摘要")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("總報名人數", f"{current_total} / {quota} 人")
    with m2:
        st.metric("會員人數", f"{total_member_count} 人")
    with m3:
        st.metric("零打人數", f"{total_casual_count} 人")
    with m4:
        if waitlist_count > 0:
            st.metric("候補人數", f"🔴 {waitlist_count} 人")
        else:
            st.metric("候補人數", "0 人")

    # 管理員動態調整名額
    if st.session_state.get("is_admin"):
        with st.container(border=True):
            st.markdown("🔧 **管理員專區：動態調整本場名額**")
            new_quota = st.number_input(
                "調整本場人數上限", 
                min_value=1, 
                max_value=200, 
                value=int(quota), 
                key=f"adjust_quota_{sid}"
            )
            if st.button("確認修改上限"):
                update_session(sid, {"total_quota": int(new_quota)})
                st.success(f"已成功將人數上限調整為 {new_quota} 人！")
                st.rerun()

    # 場次狀態與報名權限檢查
    if session.get("cancelled"):
        st.warning(f"⚠ 此場次已取消。原因：{session.get('cancel_reason', '無')}")
    elif session.get("locked"):
        st.error("❌ 此場次已關閉")
    elif not is_opened and not st.session_state.get("is_admin"):
        if session.get("note") and "[已恢復場次]" in session.get("note"):
            st.warning(f"⏳ 本場次已恢復開放！但尚未開放報名（將於 {open_date.strftime('%Y-%m-%d')} 開放報名）")
        else:
            st.warning(f"⏳ 尚未開放報名（本場次將於 {open_date.strftime('%Y-%m-%d')} 開放報名）")
    else:
        # 提示區
        if is_member_only:
            st.warning("👑 提示：本場次為【會員限定場次】，僅限固定會員報名。")
            
        if not is_opened and st.session_state.get("is_admin"):
            st.info("💡 提示：本場次一般成員尚未開放，但您目前為管理員，可提早幫團員登記報名。")
        elif session.get("note") and "[已恢復場次]" in session.get("note"):
            st.info("✨ 提示：本場次先前曾取消，目前已重新恢復開放報名！")
            
        st.divider()
        st.markdown("### ✍️ 我要報名")
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            name = st.text_input("名字")
        with col2:
            role_zh = st.selectbox("身分", ["會員", "零打"])
            role = ROLE_MAP[role_zh]
        with col3:
            count = st.number_input("人數", 1, 10, 1)

        if st.button("報名", type="primary"):
            if not name.strip():
                st.error("請輸入名字")
            # 💡 核心判定：如果是會員限定場，非管理員且選擇「零打」身分時阻擋報名
            elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
                st.error("⚠️ 本場次為會員限定場，零打暫不開放報名。請聯繫管理員或選擇會員身分。")
            else:
                add_booking(sid, name.strip(), role, int(count))
                st.success("報名成功")
                st.rerun()

    # 顯示名單
    st.subheader("👥 現有報名名單")
    ROLE_TO_ZH = {"member": "會員", "casual": "零打"}

    if not list_to_show:
        st.caption("目前尚無人報名")
        
    for item in list_to_show:
        b = item["data"]
        wl = item["is_waitlist"]
        zh_role = ROLE_TO_ZH.get(b['role'], b['role'])
        
        col1, col2 = st.columns([4, 1])
        with col1:
            if b['role'] == "member":
                if wl == True:
                    st.write(f"❌ {b['name']} ｜ {b['count']} 人 ｜ {zh_role}  ⏳ [候補]")
                elif wl == "partial":
                    st.write(f"🔸 {b['name']} ｜ {b['count']} 人 ｜ {zh_role}  ⚠️ [部分候補]")
                else:
                    st.write(f"● {b['name']} ｜ {b['count']} 人 ｜ {zh_role}")
            else:
                if wl == True:
                    st.write(f"❌ {b['name']} ｜ {b['count']} 人 ｜ {zh_role}  ⏳ [候補]")
                elif wl == "partial":
                    st.write(f"🔸 {b['name']} ｜ {b['count']} 人 ｜ {zh_role}  ⚠️ [部分候補]")
                else:
                    st.write(f"● {b['name']} ｜ {b['count']} 人 ｜ {zh_role}  ✅ [正取]")
            
        with col2:
            if st.session_state.get("is_admin"):
                if st.button("取消", key=f"cancel_{b['id']}"):
                    cancel_booking(b["id"])
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

        # ── 取消場次 ──
        st.subheader("❌ 取消場次 (可管理未來一個月內)")
        if session_map:
            with st.form("cancel_session_form", clear_on_submit=True):
                cancel_target = st.selectbox(
                    "選擇要取消的場次",
                    list(session_map.keys()),
                    format_func=lambda x: user_label(session_map[x]),
                )
                
                reason = st.text_input("原因")
                submit_cancel = st.form_submit_button("確認取消場次")

                if submit_cancel:
                    current_note = session_map[cancel_target].get("note") or ""
                    clean_note = current_note.replace("[已恢復場次]", "").strip()
                    
                    update_session(cancel_target, {
                        "cancelled": True,
                        "cancel_reason": reason,
                        "note": clean_note
                    })
                    
                    st.success("已成功取消該場次")
                    time.sleep(0.5)
                    st.rerun()
        else:
            st.caption("評估範圍內沒有可供取消的場次")

        # ── 恢復場次 ──
        st.subheader("🔄 恢復場次 (可管理未來一個月內)")
        cancelled_sessions = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map = {s["id"]: s for s in cancelled_sessions}

        if restore_map:
            restore_target = st.selectbox(
                "選擇要恢復的場次",
                list(restore_map.keys()),
                format_func=lambda x: user_label(restore_map[x]),
                key="restore_target"
            )
            if st.button("確認恢復場次"):
                current_note = restore_map[restore_target].get("note") or ""
                if "[已恢復場次]" not in current_note:
                    new_note = f"{current_note} [已恢復場次]".strip()
                else:
                    new_note = current_note

                update_session(restore_target, {
                    "cancelled": False,
                    "cancel_reason": "",
                    "note": new_note
                })
                st.success("已成功恢復該場次，並已動態加上恢復標記！")
                st.rerun()
        else:
            st.caption("目前未來一個月內沒有已取消的場次")

        # ── 新增臨時場次 ──
        st.subheader("➕ 新增臨時加開場次")

        new_date = st.date_input("日期", key="new_date")
        new_start = st.text_input("開始時間", "19:00", key="new_start").strip()
        new_end = st.text_input("結束時間", "22:00", key="new_end").strip()
        new_label = st.text_input("名稱", "加開場次", key="new_label").strip()
        new_quota = st.number_input("名額", min_value=1, max_value=200, value=20, key="new_quota")
        
        # 💡 新增：報名權限單選鈕
        access_type = st.radio("開放對象設定", ["所有人皆可報名", "限會員報名（零打不可）"], horizontal=True)
        
        new_note = st.text_area("備註內容 (選填)", key="new_note")

        if st.button("新增臨時場次"):
            if not new_label:
                st.error("請填寫場次名稱")
            else:
                # 💡 根據選擇，在備註後方默默疊加識別標記
                final_note = new_note.strip()
                if access_type == "限會員報名（零打不可）":
                    final_note = f"{final_note} [會員限定]".strip()

                new_id = f"{new_date}_{new_start}_{int(time.time())}"
                supabase.table("sessions").insert({
                    "id": new_id,
                    "date": str(new_date),
                    "start_time": new_start,
                    "end_time": new_end,
                    "label": new_label,
                    "note": final_note,
                    "total_quota": new_quota,
                    "cancelled": False,
                    "cancel_reason": "",
                    "locked": False,
                }).execute()
                st.success("臨時場次新增成功")
                st.rerun()

    else:
        pwd = st.text_input("密碼", type="password")
        if pwd == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
        elif pwd:
            st.error("密碼錯誤")
