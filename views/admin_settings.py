"""
views/admin_settings.py —— 管理員後台「🛠 系統參數設定」分頁。
"""

import streamlit as st

from db import get_system_settings, save_system_settings


def render():
    st.subheader("🛠 系統參數設定")
    with st.expander("📝 修改球種與費用", expanded=st.session_state.get("expand_settings", False)):
        current_set = get_system_settings()
        new_shuttle = st.text_input("球種名稱", value=current_set.get("shuttlecock", "VOLAR 50"))
        new_fee = st.number_input("零打費用 (元)", value=int(current_set.get("casual_fee", 220)))
        if st.button("更新系統參數", type="primary"):
            save_system_settings({"shuttlecock": new_shuttle, "casual_fee": int(new_fee)})
            st.success("設定已儲存！")
            st.session_state["expand_settings"] = False
            st.rerun()
