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
    # ─────────────────────────
    # 管理員後台區塊
    # ─────────────────────────
    with st.expander("🔒 管理與後台登入"):
        if st.session_state.get("is_admin"):
            st.markdown("### ⚙️ 管理員選單")
            if st.button("🔓 登出管理員模式", type="secondary"):
                st.session_state["is_admin"] = False
                st.rerun()
            
            st.divider()

            # 1. 維護聯絡人
            st.subheader("📱 維護聯絡人名單")
            new_line_name = st.text_input("新增 LINE 帳號")
            if st.button("確認新增聯絡人"):
                if new_line_name.strip():
                    admin_line_config[f"admin_{int(time.time()*1000)}"] = new_line_name.strip()
                    if save_db_admin_line_list(admin_line_config):
                        st.success("新增成功！")
                        st.rerun()

            st.divider()

            # 2. 取消場次 (使用你的 cancel_session_form 邏輯)
            st.subheader("❌ 取消場次")
            with st.form("cancel_session_form", clear_on_submit=True):
                cancel_target = st.selectbox("選擇要取消的場次", keys, format_func=lambda x: user_label(session_map[x]))
                reason = st.text_input("取消原因")
                if st.form_submit_button("確認取消"):
                    update_session(cancel_target, {"cancelled": True, "cancel_reason": reason})
                    send_line(f"⚠️ 場次已取消: {reason}")
                    st.success("已執行取消")
                    st.rerun()
        else:
            # 未登入時顯示密碼輸入框
            admin_pwd = st.text_input("管理員密碼", type="password")
            if st.button("登入管理員"):
                if admin_pwd == ADMIN_PASSWORD:
                    st.session_state["is_admin"] = True
                    st.rerun()
                else:
                    st.error("密碼錯誤")
