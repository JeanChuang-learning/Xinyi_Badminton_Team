"""
views/admin_panel.py —— 管理員登入表單 + 5 個分頁的外殼。
實際每個分頁的內容都在 views/admin_*.py，這裡只負責登入判斷跟切分頁籤。
"""

import streamlit as st

from config import ADMIN_PASSWORD
from views import admin_history, admin_messages, admin_contacts, admin_sessions, admin_settings


def render(session_map, keys, sessions_sorted, admin_line_config, today_date):
    if not st.session_state.get("show_admin"):
        return

    with st.container(border=True):
        if not st.session_state.get("is_admin"):
            st.markdown("### 🔐 管理員登入")
            pwd = st.text_input("請輸入管理員密碼", type="password", key="admin_pwd_input")
            if st.button("登入", type="primary", key="admin_login_btn"):
                if pwd == ADMIN_PASSWORD:
                    st.session_state["is_admin"] = True
                    st.rerun()
                elif pwd:
                    st.error("密碼錯誤")
            return

        # --- 已登入，顯示選單與標籤頁 ---
        col_title, col_logout = st.columns([3, 1])
        with col_logout:
            if st.button("登出", key="admin_logout"):
                st.session_state["is_admin"] = False
                st.session_state["show_admin"] = False
                st.rerun()
        st.markdown("### ⚙️ 管理員控制台")

        # 定義標籤頁（加開/規則合併進場次管理）
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 歷史紀錄", "📨 訊息中心", "📱 聯絡人", "🗓️ 場次管理", "🛠 系統參數"
        ])

        with tab2:
            admin_messages.render()

        with tab3:
            admin_contacts.render(admin_line_config)

        with tab4:
            admin_sessions.render(keys, session_map, sessions_sorted)

        with tab5:
            admin_settings.render()

        with tab1:
            admin_history.render(sessions_sorted, today_date)
