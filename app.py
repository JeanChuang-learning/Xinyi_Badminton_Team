import streamlit as st
import requests
import json
import os
import time
from datetime import datetime
from supabase import create_client

# ─────────────────────────
# 1. 初始化 (最上方)
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸")

@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

# ─────────────────────────
# 2. 資料獲取函式 (定義在呼叫之前)
# ─────────────────────────
@st.cache_data(ttl=30)
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()
        return res.data if res.data else []
    except:
        return []

# ─────────────────────────
# 3. 變數與狀態初始化 (全域變數)
# ─────────────────────────
all_sessions = get_sessions()
session_map = {s["id"]: s for s in all_sessions if s.get("id")}
keys = sorted(session_map.keys(), key=lambda k: (session_map[k]["date"], session_map[k]["start_time"]))

if "selected_sid" not in st.session_state:
    st.session_state["selected_sid"] = None
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False

# ─────────────────────────
# 4. UI 渲染 (最後才放)
# ─────────────────────────
st.title("🏸 信義羽球隊")

# 這裡接下來我們要一段一段填入邏輯...
st.write("程式架構已重整完成，現在是乾淨的狀態。")
