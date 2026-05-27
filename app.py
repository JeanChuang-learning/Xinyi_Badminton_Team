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
    if s.get("cancelled"):
        return f"{base} ❌不開放（{s.get('cancel_reason', '')}）"
    if s.get("locked"):
        return f"{base} 🔒關閉報名"
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
    """檢查未來 14 天內固定場次，若無則自動新增"""
    today = date.today()
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new_inserted = False

    for i in range(15):
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
# 載入並篩選場次
# ─────────────────────────
raw_sessions = get_sessions()
sessions = auto_generate_fixed_sessions(raw_sessions)

today = date.today()
start_bound = today - timedelta(days=3)
end_bound = today + timedelta(days=7)

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

sessions_sorted = sorted(
    filtered_sessions,
    key=lambda s: (s["date"], s["start_time"])
)

session_map = {
    s["id"]: s
    for s in sessions_sorted
    if s.get("id")
}

# 用來同步前端名單渲染的安全變數
sessions_sorted_for_admin = sessions_sorted

# ─────────────────────────
# 前端主功能區塊
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

    # 場次狀態檢查與報名
    if session.get("cancelled"):
        st.warning("⚠ 此場次已取消")
    elif session.get("locked"):
        st.error("❌ 此場次已關閉")
    else:
        st.divider()
        st.markdown("### ✍️ 我要報名")
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            name = st.text_input("名字")
        with col2:
            role = ROLE_MAP[st.selectbox("身分", ["會員", "零打"])]
        with col3:
            count = st.number_input("人數", 1, 10, 1)

        if st.button("報名", type="primary"):
            if not name.strip():
                st.error("請輸入名字")
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
        
        col1, col2 = st.columns([4, 1])
        with col1:
            zh_role = ROLE_TO_ZH.get(b['role'], b['role'])
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
    st.info("💡 目前暫無本週內場次，請管理員登入下方「🔒 管理」建立新場次。")
    # 即使沒場次，也讓管理員有現成列表可以使用
    session_map = {} 

# ─────────────────────────
# 管理員功能區塊（獨立最外層，絕不報錯）
# ─────────────────────────
st.divider()

with st.expander("🔒 管理"):
    pwd = st.text_input("密碼", type="password")

    if pwd == ADMIN_PASSWORD:
        st.session_state["is_admin"] = True

        # ── 取消場次 ──
        st.subheader("❌ 取消場次")
        if session_map:
            cancel_target = st.selectbox(
                "選擇要取消的場次",
                list(session_map.keys()),
                format_func=lambda x: user_label(session_map[x]),
                key="cancel_target"
            )
            reason = st.text_input("原因", key="cancel_reason")

            if st.button("確認取消場次"):
                update_session(cancel_target, {
                    "cancelled": True,
                    "cancel_reason": reason,
                })
                st.success("已成功取消該場次")
                st.rerun()
        else:
            st.caption("目前範圍內沒有可供取消的場次")

        # ── 恢復場次 ──
        st.subheader("🔄 恢復場次")
        cancelled_sessions = [s for s in sessions_sorted_for_admin if s.get("cancelled")]
        restore_map = {s["id"]: s for s in cancelled_sessions}

        if restore_map:
            restore_target = st.selectbox(
                "選擇要恢復的場次",
                list(restore_map.keys()),
                format_func=lambda x: user_label(restore_map[x]),
                key="restore_target"
            )
            if st.button("確認恢復場次"):
                update_session(restore_target, {
                    "cancelled": False,
                    "cancel_reason": "",
                })
                st.success("已成功恢復該場次")
                st.rerun()
        else:
            st.caption("目前範圍內沒有已取消的場次")

        # ── 新增臨時場次 ──
        st.subheader("➕ 新增臨時加開場次")

        new_date = st.date_input("日期", key="new_date")
        new_start = st.text_input("開始時間", "19:00", key="new_start").strip()
        new_end = st.text_input("結束時間", "22:00", key="new_end").strip()
        new_label = st.text_input("名稱", "加開場次", key="new_label").strip()
        new_quota = st.number_input("名額", min_value=1, max_value=200, value=20, key="new_quota")
        new_note = st.text_area("備註", key="new_note")

        if st.button("新增臨時場次"):
            if not new_label:
                st.error("請填寫場次名稱")
            else:
                new_id = f"{new_date}_{new_start}_{int(time.time())}"
                supabase.table("sessions").insert({
                    "id": new_id,
                    "date": str(new_date),
                    "start_time": new_start,
                    "end_time": new_end,
                    "label": new_label,
                    "note": new_note,
                    "total_quota": new_quota,
                    "cancelled": False,
                    "cancel_reason": "",
                    "locked": False,
                }).execute()
                st.success("臨時場次新增成功")
                st.rerun()

    elif pwd:
        st.error("密碼錯誤")
