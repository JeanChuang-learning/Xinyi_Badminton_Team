import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import requests  
import time
import json

# ─────────────────────────
# config & Line 設定
# ─────────────────────────
ADMIN_PASSWORD = "admin"
ROLE_MAP = {"會員": "member", "零打": "casual"}

LINE_NOTIFY_TOKEN = "" 

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

def send_line_message(message):
    if not LINE_NOTIFY_TOKEN: return
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"}
    requests.post(url, headers=headers, data={"message": message})

# ─────────────────────────
# Supabase layer
# ─────────────────────────
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()
        return res.data or []
    except: return []

# 💡 讀取幹部名單 (改為 list 儲存名稱)
def get_admin_name_list():
    try:
        res = supabase.table("sessions").select("*").eq("id", "_admin_names_config").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "[]"))
    except: pass
    return ["小明", "小華"]

def save_admin_name_list(name_list):
    json_str = json.dumps(name_list, ensure_ascii=False)
    res = supabase.table("sessions").select("id").eq("id", "_admin_names_config").execute()
    if res.data:
        supabase.table("sessions").update({"note": json_str}).eq("id", "_admin_names_config").execute()
    else:
        supabase.table("sessions").insert({
            "id": "_admin_names_config", "date": "1970-01-01", "note": json_str, "label": "NAMES_CONFIG"
        }).execute()

# (其他函數如 get_bookings, add_booking_compatible 等保持原樣)
def get_bookings(session_id):
    res = supabase.table("bookings").select("*").eq("session_id", session_id).execute()
    return res.data or []

def add_booking_compatible(session_id, name, role, count, password, line_name):
    composite_name = f"{name}_🔑{password}_💬{line_name}_🔄0"
    supabase.table("bookings").insert({"session_id": session_id, "name": composite_name, "role": role, "count": count, "status": "active"}).execute()

def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    payload = {"count": new_count, "status": status}
    if new_name: payload["name"] = new_name
    supabase.table("bookings").update(payload).eq("id", booking_id).execute()

def cancel_booking(booking_id):
    supabase.table("bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()

def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()

# ─────────────────────────
# UI 初始化
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸")
st.title("🏸 羽球報名系統")

# 💡 顯示幹部清單 (純名字)
admin_names = get_admin_name_list()
with st.container():
    st.markdown("### 📞 聯絡幹部")
    cols = st.columns(max(len(admin_names), 1))
    for idx, name in enumerate(admin_names):
        cols[idx % len(cols)].info(f"👤 {name}")
st.divider()

# (報名邏輯維持不變，省略中間部分以節省篇幅)
# ... [請保持你原本的報名與顯示名單邏輯] ...

# ─────────────────────────
# 管理員功能區塊
# ─────────────────────────
with st.expander("🔒 管理員後台"):
    if not st.session_state.get("is_admin"):
        if st.text_input("輸入密碼", type="password") == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
    else:
        st.subheader("📱 維護幹部名單 (僅顯示名稱)")
        # 顯示並刪除
        for name in list(admin_names):
            c1, c2 = st.columns([4, 1])
            c1.text(f"👤 {name}")
            if c2.button("刪除", key=f"del_{name}"):
                admin_names.remove(name)
                save_admin_name_list(admin_names)
                st.rerun()
        
        # 新增
        new_name = st.text_input("新增幹部名字")
        if st.button("確認新增"):
            if new_name:
                admin_names.append(new_name)
                save_admin_name_list(admin_names)
                st.rerun()
        
        # (其他取消場次、調整名額等邏輯)
