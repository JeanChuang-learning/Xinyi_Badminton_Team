import streamlit as st
import time
from supabase_client import supabase  # 假設這依然是你原本的設定檔

# ─────────────────────────
# 1. 配置與初始化 (Global Config)
# ─────────────────────────
st.set_page_config(page_title="羽球報名系統", page_icon="🏸", layout="wide")

# 管理員預設值
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "selected_sid" not in st.session_state:
    st.session_state["selected_sid"] = None

# ─────────────────────────
# 2. Supabase 資料層 (使用緩存以提速)
# ─────────────────────────
@st.cache_data(ttl=60)
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()
        return res.data or []
    except Exception:
        return []

@st.cache_data(ttl=30)
def get_bookings(session_id):
    try:
        res = supabase.table("bookings").select("*").eq("session_id", session_id).execute()
        return res.data or []
    except Exception:
        return []

# 資料處理：預先計算好對應表，避免 UI 渲染時重複運算
all_sessions = get_sessions()
sessions_sorted = sorted(all_sessions, key=lambda s: (s["date"], s["start_time"]))
session_map = {s["id"]: s for s in sessions_sorted}

# ─────────────────────────
# 3. 輔助函式 (格式化)
# ─────────────────────────
def user_label(s):
    base = f"{s['date']}｜{s.get('label', '羽球場次')}｜{s['start_time']}"
    if s.get("cancelled"): return f"{base} ❌不開放"
    if s.get("locked"): return f"{base} 🔒關閉"
    return base
