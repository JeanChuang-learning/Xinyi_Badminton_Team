"""
views/session_picker.py —— 頁首標題 + 場次選擇按鈕格（近兩週場次）。
"""

from datetime import datetime, timedelta

import streamlit as st

from config import Quota_7, Limit_7, WEEKDAY_TW
from db import get_bookings
from shared_logic import is_casual_open_for_signup


def render(session_map, keys, today_date):
    """回傳更新後的 (session_map, keys)（因為選單畫面本身不會改動這兩個值，直接回傳原值即可）。"""

    # ─────────────────────────
    # 標題
    # ─────────────────────────
    st.markdown("""<h1 style='margin-bottom: 0px;'>🏸 信義羽球隊</h1>""", unsafe_allow_html=True)
    st.markdown("""
        <h3>年度會員招募中！
            <span style='font-size: 18px; color: #E0E0E0; font-weight: normal;'>
                誠摯邀請熱愛羽球的夥伴加入我們
            </span>
        </h3>
    """, unsafe_allow_html=True)

    if st.session_state.get("is_admin"):
        st.success("🔐 管理員模式")

    # ─────────────────────────
    # 場次選單
    # ─────────────────────────
    if not keys:
        st.info("目前暫無場次。")
        st.stop()

    window_start   = today_date - timedelta(days=7)
    window_preview = today_date + timedelta(days=14)

    visible_keys = [
        k for k in keys
        if window_start <= datetime.strptime(session_map[k]["date"], "%Y-%m-%d").date() <= window_preview
    ]

    if not visible_keys:
        st.info("近兩週內暫無場次。")
        st.stop()

    if st.session_state["selected_sid"] not in visible_keys:
        st.session_state["selected_sid"] = None

    st.markdown("### 📅 請選擇場次")

    for row_start in range(0, len(visible_keys), 3):
        row_keys = visible_keys[row_start:row_start + 3]
        cols = st.columns(3)
        for i, k in enumerate(row_keys):
            s          = session_map[k]
            is_sel     = st.session_state["selected_sid"] == k
            s_date_obj = datetime.strptime(s["date"], "%Y-%m-%d").date()
            wd         = WEEKDAY_TW[s_date_obj.weekday()]
            start_t    = s.get("start_time", "")[:5]
            end_t      = s.get("end_time", "")[:5]
            note       = s.get("note") or ""
            _bks_active  = [b for b in get_bookings(k) if b["status"] == "active"]
            member_used  = sum(int(b["count"]) for b in _bks_active if b["role"] == "member")
            casual_used  = sum(int(b["count"]) for b in _bks_active if b["role"] != "member")
            total_used   = member_used + casual_used
            total_q      = int(s.get("total_quota", Quota_7))
            casual_q     = int(s.get("casual_quota", Limit_7))
            date_short   = s["date"][5:]
            time_short   = f"{start_t[:2]}-{end_t[:2]}"

            try:
                end_h, end_m = map(int, end_t.split(":"))
                session_end_dt = datetime.combine(s_date_obj, datetime.min.time()).replace(hour=end_h, minute=end_m)
                is_ended = datetime.now() > session_end_dt
            except Exception:
                is_ended = s_date_obj < today_date

            casual_open = is_casual_open_for_signup(s_date_obj)

            if is_ended:
                status = "⬜ 已結束"
            elif s.get("cancelled") or s.get("locked"):
                status = "❌ 不開放"
            elif "[會員限定]" in note:
                status = "👑 會員限定"
            elif total_used >= total_q:
                status = "🔴 額滿"
            elif casual_open and casual_used >= casual_q:
                status = "🟡 零打額滿"
            elif not casual_open:
                status = "🔵 會員先行"
            else:
                status = "🟢 開放"

            btn_label = f"{date_short}({wd}) {time_short} {status}"

            # 只有「已結束」和「取消/鎖定」才 disabled，其他全部可點
            is_disabled = is_ended or s.get("cancelled") or s.get("locked")

            if is_disabled:
                cols[i].button(btn_label, key=f"sess_{k}", use_container_width=True, disabled=True)
            elif is_sel:
                if cols[i].button(btn_label, key=f"sess_{k}", use_container_width=True, type="primary"):
                    st.session_state["selected_sid"] = None
                    st.rerun()
            else:
                if cols[i].button(btn_label, key=f"sess_{k}", use_container_width=True):
                    st.session_state["selected_sid"] = k
                    for ck in ["name_input", "password_input"]:
                        st.session_state.pop(ck, None)
                    st.rerun()
