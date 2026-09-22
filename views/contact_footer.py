"""
views/contact_footer.py —— 聯絡窗口顯示 + 📞 管理員後台切換按鈕。
"""

import streamlit as st


def render(admin_line_config):
    _phone_col, _names_col = st.columns([1, 6])
    with _phone_col:
        if st.button("📞", help="管理員後台", use_container_width=True):
            st.session_state["show_admin"] = not st.session_state.get("show_admin", False)
            st.rerun()
    with _names_col:
        if admin_line_config:
            line_accounts = list(admin_line_config.values())
            parts = []
            for info in line_accounts:
                lname    = info.get("name", info) if isinstance(info, dict) else info
                line_url = info.get("personal_line_url", "").strip() if isinstance(info, dict) else ""
                if line_url:
                    parts.append(f'<a href="{line_url}" target="_blank" style="color:#06c755;text-decoration:none;">💬 {lname}</a>')
                else:
                    parts.append(f"💬 {lname}")
            st.markdown(f"**聯絡窗口**　" + "　".join(parts), unsafe_allow_html=True)
        else:
            st.markdown("**聯絡窗口**　尚未設定聯絡人")
