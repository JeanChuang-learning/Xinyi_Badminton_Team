import streamlit as st
from supabase import create_client, Client

try:    
    # 確保在匯入時不會因為找不到 secrets 而直接報錯
    #url = st.secrets["SUPABASE_URL"]
    #key = st.secrets["SUPABASE_KEY"]
    #supabase = create_client(url, key)    
    # ─────────────────────────────────────────────
    # supabase_client.py
    # 集中管理所有帳密與金鑰，請勿上傳至公開版控
    # ─────────────────────────────────────────────
    # ── Supabase 連線設定 ──────────────────────────
    SUPABASE_URL = "https://your-project.supabase.co"   # ← 填入你的 Supabase Project URL
    SUPABASE_KEY = "your-anon-or-service-role-key"       # ← 填入你的 Supabase API Key
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # ── LINE Messaging API ────────────────────────
    LINE_CHANNEL_ACCESS_TOKEN = "ScRBbUMhJUJHOn9abgQc9fw6EfUjEiDGxfmpOjQ5ThvQmOprUBbEYoscQzXsM/5RIVOhCskoUcUnd9fI39SpfPznW90I+sRZ8FQ65vNLk0dPfOX51KUNaAuuaeWeyjqJh/fZvh0L0R+UQotasKBOp/QdB04t89/1O/w1cDnyilFU="
    LINE_GROUP_ID             = "Cb7b632bd44eb63105a0fbabc8099cf75"
    
    # ── 管理員密碼 ────────────────────────────────
    ADMIN_PASSWORD = "admin"   # ← 請自行修改為 4 位英數字
except Exception as e:
    # 這裡如果不設定變數，後續引用會出錯，所以我們先設為 None
    supabase = None
    st.error("supabase_client 初始化失敗，請檢查 Streamlit Secrets 設定。")






