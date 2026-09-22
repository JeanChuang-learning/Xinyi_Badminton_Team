"""
views/dev_tools.py —— 管理員專屬的開發測試工具：
- 測試 LINE 發送（入列到各群組）
- 模擬零打報名流程
只有 st.session_state["is_admin"] 為真時才會顯示。
"""

import random
import string
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from supabase_client import supabase

from config import LINE_GROUP_ID_Casual, LINE_GROUP_ID_Member, LINE_GROUP_ID_Admin, Quota_7, Limit_7
from db import get_sessions
from notify import enqueue_msg


def render():
    if not st.session_state.get("is_admin"):
        return

    st.divider()

    with st.expander("🧪 測試 LINE 發送"):
        test_msg = st.text_input("測試訊息", value="🧪 這是一則測試訊息")
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            if st.button("入列→零打群", use_container_width=True):
                ok = enqueue_msg(test_msg, "waitlist", tag="test")
                if ok:
                    st.success(f"✅ 已入列，群組: `{LINE_GROUP_ID_Casual}`")
                else:
                    st.error("❌ 入列失敗")
        with tc2:
            if st.button("入列→會員群", use_container_width=True):
                ok = enqueue_msg(test_msg, "schedule_change", tag="test")
                if ok:
                    st.success(f"✅ 已入列，群組: `{LINE_GROUP_ID_Member}`")
                else:
                    st.error("❌ 入列失敗")
        with tc3:
            if st.button("入列→幹部群", use_container_width=True):
                if not LINE_GROUP_ID_Admin:
                    st.warning("尚未設定 LINE_GROUP_ID_Admin（請在 secrets 加入）")
                else:
                    ok = enqueue_msg(test_msg, "admin_only", tag="test")
                    if ok:
                        st.success(f"✅ 已入列，群組: `{LINE_GROUP_ID_Admin}`")
                    else:
                        st.error("❌ 入列失敗")
        st.caption("⚠️ 入列後請到「📨 訊息中心」手動發送或等排程觸發")

    with st.expander("🧪 測試零打報名流程（模擬 LINE 按鈕）"):
        st.caption("這裡送出的測試報名，會比照「B群（零打）」的行為：需要選付款方式，並直接寫入 bookings 表。")
        _test_sessions = get_sessions()
        if not _test_sessions:
            st.caption("目前沒有場次可供測試")
        else:
            _test_options = {
                f"{s['date']} {s.get('label','')}": s
                for s in sorted(_test_sessions, key=lambda x: x.get("date", ""))
            }
            _test_label   = st.selectbox("選擇要測試的場次", list(_test_options.keys()), key="test_booking_session")
            _test_session = _test_options[_test_label]

            tcol1, tcol2 = st.columns(2)
            with tcol1:
                _test_count = st.selectbox("人數", [1, 2, 3, 4], key="test_booking_count")
            with tcol2:
                _test_pay = st.radio("付款方式", ["簽卡", "付現"], horizontal=True, key="test_booking_pay")

            if st.button("🧪 模擬送出報名（視為零打）", use_container_width=True):
                quota        = _test_session.get("total_quota") or Quota_7
                casual_quota = _test_session.get("casual_quota") or Limit_7

                rows = (
                    supabase.table("bookings")
                    .select("*")
                    .eq("session_id", _test_session["id"])
                    .eq("status", "active")
                    .order("created_at")
                    .execute()
                    .data or []
                )
                running_total = running_casual = 0
                for b in rows:
                    b_count = int(b["count"])
                    if b.get("role") == "member":
                        running_total += b_count
                    else:
                        remain = min(quota - running_total, casual_quota - running_casual)
                        take = min(max(remain, 0), b_count)
                        running_total  += take
                        running_casual += take
                remain = quota - running_total
                if remain >= _test_count:
                    status_text = "✅ 正取成功！"
                elif remain > 0:
                    status_text = f"⚠️ 正取 {remain} 人、候補 {_test_count - remain} 人"
                else:
                    status_text = "⏳ 目前候補中，名額釋出會依序遞補"

                test_pwd  = "".join(random.choices(string.digits, k=4))
                test_uid  = f"admin_test_{uuid.uuid4().hex[:8]}"
                full_name = f"管理員測試_🔑{test_pwd}_🔄0"
                pay_code  = "card" if _test_pay == "簽卡" else "cash"

                supabase.table("bookings").insert({
                    "session_id":     _test_session["id"],
                    "name":           full_name,
                    "role":           "casual",
                    "count":          _test_count,
                    "status":         "active",
                    "line_user_id":   test_uid,
                    "payment_method": pay_code,
                    "created_at":     datetime.now(ZoneInfo("UTC")).isoformat(),
                }).execute()

                st.success(
                    f"{status_text}\n\n"
                    f"測試報名已寫入：{_test_session['date']} {_test_session.get('label','')} ｜ "
                    f"{_test_count} 人 ｜ {_test_pay}（密碼 {test_pwd}）"
                )
                st.rerun()
