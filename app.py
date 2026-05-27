import streamlit as st
import requests
import json
import os
import time
from datetime import datetime, date, timedelta
from supabase import create_client

# ─────────────────────────
# 1. 頁面與初始化
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸", layout="centered")

@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

# ─────────────────────────
# 2. 資料處理函式 (與 UI 分離)
# ─────────────────────────
@st.cache_data(ttl=30)
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()
        return res.data if res.data else []
    except:
        return []

@st.cache_data(ttl=30)
def get_bookings(session_id):
    try:
        res = supabase.table("bookings").select("*").eq("session_id", session_id).execute()
        return res.data or []
    except:
        return []

# ─────────────────────────
# 3. 全域狀態與資料準備
# ─────────────────────────
if "is_admin" not in st.session_state: st.session_state["is_admin"] = False
if "selected_sid" not in st.session_state: st.session_state["selected_sid"] = None

all_sessions = get_sessions()
session_map = {s["id"]: s for s in all_sessions if s.get("id") and s.get("id") != "_admin_line_config"}
# 排序後的 Keys
keys = sorted(session_map.keys(), key=lambda k: (session_map[k]["date"], session_map[k]["start_time"]))

# ─────────────────────────
# 4. UI 渲染邏輯
# ─────────────────────────
st.title("🏸 信義羽球隊")

# 公告區
def get_announcement():
    return open("announcement.txt", "r", encoding="utf-8").read() if os.path.exists("announcement.txt") else "歡迎來到信義羽球隊！"

st.info(f"📢 **最新公告：**\n\n{get_announcement()}")

# 場次選擇區
st.markdown("### 📅 請選擇場次")
# (在此處放入你的 expander 迴圈渲染程式碼)
# ... (建議在此處將你原本的 expander 迴圈放入) ...

# 詳情區與報名區
if st.session_state["selected_sid"] is not None:
    sid = st.session_state["selected_sid"]
    session = session_map[sid]
    st.success(f"✔ 已選：{session['date']} {session.get('label', '')} {session['start_time']}")
    
    # 在這裡放入報名清單與表單邏輯
    # ...
else:
    st.info("請從上方選擇一個場次以查看詳情。")

# 管理員區塊
if st.session_state.get("is_admin"):
    with st.expander("⚙️ 管理員後台"):
        # ... (放入所有管理功能) ...
