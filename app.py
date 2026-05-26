# ── 報名 ─────────────────────────────
msg = st.empty()

if st.button("報名", type="primary"):

    name = name_input.strip()
    role = ROLE_MAP[role_label]
    count = int(count_input)

    if not name:
        msg.error("❌ 請輸入名字")
        st.stop()

    member_list, casual_list, waitlist, used = build_groups(members, quota)
    available = quota - used

    # ❗通知（強化 UX）
    if count > available:
        st.toast("❌ 報名失敗")
        msg.error("❌ 人數已超過上限，報名失敗")
        st.stop()

    add_user(data, sid, name, role, count)
    save_data(data)

    # ✔ 成功通知（雙層 UX）
    st.toast("✅ 報名成功")
    msg.success("✅ 報名成功")

    st.rerun()
