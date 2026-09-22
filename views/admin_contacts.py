"""
views/admin_contacts.py —— 管理員後台「📱 聯絡人」分頁。
"""

import time

import streamlit as st

from db import save_db_admin_line_list


def render(admin_line_config):
    st.subheader("📱 聯絡人名單")

    # 向下相容：舊格式 {key: "name"} 自動轉成 {key: {name, personal_line_url}}
    for k_id, val in list(admin_line_config.items()):
        if isinstance(val, str):
            admin_line_config[k_id] = {"name": val, "personal_line_url": ""}

    with st.container(border=True):
        if admin_line_config:
            for k_id, info in list(admin_line_config.items()):
                lname    = info.get("name", "")
                line_url = info.get("personal_line_url", "").strip()
                edit_key = f"edit_mode_{k_id}"

                if st.session_state.get(edit_key):
                    # ── 編輯模式 ──
                    with st.container(border=True):
                        e1, e2 = st.columns(2)
                        new_name = e1.text_input("名稱", value=lname, key=f"edit_name_{k_id}")
                        new_url  = e2.text_input("加好友連結", value=line_url, key=f"edit_url_{k_id}", placeholder="https://line.me/ti/p/xxx")
                        s1, s2 = st.columns(2)
                        if s1.button("💾 儲存", key=f"save_admin_{k_id}", use_container_width=True):
                            admin_line_config[k_id] = {"name": new_name.strip(), "personal_line_url": new_url.strip()}
                            if save_db_admin_line_list(admin_line_config):
                                st.session_state[edit_key] = False
                                st.success("已儲存"); st.rerun()
                        if s2.button("取消", key=f"cancel_edit_{k_id}", use_container_width=True):
                            st.session_state[edit_key] = False
                            st.rerun()
                else:
                    # ── 顯示模式 ──
                    if line_url:
                        name_html = (
                            f'<a href="{line_url}" target="_blank" '
                            f'style="color:#06c755;text-decoration:none;font-weight:600;">'
                            f'💬 {lname} <span style="font-size:11px;opacity:0.7">（點擊加好友）</span></a>'
                        )
                    else:
                        name_html = f'<span style="font-weight:600;">💬 {lname}</span>'

                    c1, c2, c3 = st.columns([4, 1, 1])
                    with c1:
                        st.markdown(name_html, unsafe_allow_html=True)
                    with c2:
                        if st.button("✏️", key=f"edit_btn_{k_id}", use_container_width=True, help="編輯"):
                            st.session_state[edit_key] = True
                            st.rerun()
                    with c3:
                        if st.button("刪除", key=f"del_admin_{k_id}", use_container_width=True):
                            del admin_line_config[k_id]
                            if save_db_admin_line_list(admin_line_config):
                                st.success("已刪除"); st.rerun()
        else:
            st.info("名單為空。")

        st.divider()
        st.caption("新增聯絡人")
        new_line_name = st.text_input("LINE 顯示名稱", key="new_line_name")
        new_line_url  = st.text_input(
            "個人加好友連結（選填）",
            key="new_line_url",
            placeholder="https://line.me/ti/p/xxxxxxxx"
        )
        st.caption("📌 加好友連結在 LINE App → 個人頁面 → 分享 → 複製連結")
        if st.button("確認新增聯絡人"):
            if not new_line_name.strip():
                st.error("請輸入 LINE 顯示名稱")
            else:
                admin_line_config[f"admin_{int(time.time()*1000)}"] = {
                    "name": new_line_name.strip(),
                    "personal_line_url": new_line_url.strip(),
                }
                result = save_db_admin_line_list(admin_line_config)
                if result:
                    st.success("新增成功！")
                    st.rerun()
                else:
                    st.error("儲存失敗，請重試")
