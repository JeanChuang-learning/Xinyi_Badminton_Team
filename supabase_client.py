import streamlit as st
from supabase import create_client

# 確保在匯入時不會因為找不到 secrets 而直接報錯
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except Exception as e:
    # 這裡如果不設定變數，後續引用會出錯，所以我們先設為 None
    supabase = None
    st.error("supabase_client 初始化失敗，請檢查 Streamlit Secrets 設定。")
