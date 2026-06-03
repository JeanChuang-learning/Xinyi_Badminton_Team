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
    SUPABASE_URL = "https://plnsnmftdxtbxjgdzkbq.supabase.co"   # ← 填入你的 Supabase Project URL
    SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBsbnNubWZ0ZHh0YnhqZ2R6a2JxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3NjIxMTgsImV4cCI6MjA5NTMzODExOH0.F8_jJbX1pA4jtT-4JewN3bCcyy6rNzY9wrH0llcmamo"       # ← 填入你的 Supabase API Key
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # ── LINE Messaging API ────────────────────────
    LINE_CHANNEL_ACCESS_TOKEN = "ScRBbUMhJUJHOn9abgQc9fw6EfUjEiDGxfmpOjQ5ThvQmOprUBbEYoscQzXsM/5RIVOhCskoUcUnd9fI39SpfPznW90I+sRZ8FQ65vNLk0dPfOX51KUNaAuuaeWeyjqJh/fZvh0L0R+UQotasKBOp/QdB04t89/1O/w1cDnyilFU="
    LINE_GROUP_ID             = "Cb7b632bd44eb63105a0fbabc8099cf75"

    LINE_GROUP_ID_Master      = "Cb7b632bd44eb63105a0fbabc8099cf75" #幹部群
    LINE_GROUP_ID_Member      = "C8cf6ec860980c8ebe413cff3edafc7a1" #會員群
    LINE_GROUP_ID_Casual      = "Cdddbcd7a1179646fada1865a266ec608" #零打群
    LINE_GROUP_ID_Mine        = "C8b804c605ea8c610eadc1b6ff392a844" #我的群  
    
    # ── 管理員密碼 ────────────────────────────────
    ADMIN_PASSWORD = "admin"   # ← 請自行修改為 4 位英數字
except Exception as e:
    # 這裡如果不設定變數，後續引用會出錯，所以我們先設為 None
    supabase = None
    st.error("supabase_client 初始化失敗，請檢查 Streamlit Secrets 設定。")
