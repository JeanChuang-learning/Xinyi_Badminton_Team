"""
views/admin_history.py —— 管理員後台「📋 報名紀錄查詢」分頁（含補點名）。
"""

from datetime import datetime, timedelta

import streamlit as st

from config import Quota_7, ROLE_TO_ZH
from db import get_bookings, get_checkins, set_checkin


def render(sessions_sorted, today_date):
    st.subheader("📋 報名紀錄查詢")

    q_input = st.text_input(
        "查詢日期（YYYYMMDD）",
        placeholder="例：20260601",
        max_chars=8,
        key="hist_query_input"
    )

    # 驗證輸入
    q_date = None
    if q_input:
        if len(q_input) == 8 and q_input.isdigit():
            try:
                q_date = datetime.strptime(q_input, "%Y%m%d").date()
                cutoff_min = today_date - timedelta(days=90)
                if q_date > today_date:
                    st.warning("日期不能是未來日期")
                    q_date = None
                elif q_date < cutoff_min:
                    st.warning(f"僅支援查詢過去三個月（{cutoff_min} 之後）的紀錄")
                    q_date = None
            except ValueError:
                st.error("日期格式錯誤，請輸入有效的 YYYYMMDD")
        else:
            st.caption("請輸入完整八位數數字")

    if not q_date:
        st.caption("輸入日期後顯示當天報名紀錄")
        return

    hist_sessions = [
        s for s in sessions_sorted
        if s.get("id") and not s["id"].startswith("_")
        and datetime.strptime(s["date"], "%Y-%m-%d").date() == q_date
    ]
    if not hist_sessions:
        st.info(f"{q_date} 無場次紀錄")
        return

    for hs in hist_sessions:
        hs_date   = hs["date"]
        hs_label  = hs.get("label", "")
        hs_start  = hs.get("start_time", "")[:5]
        hs_end    = hs.get("end_time", "")[:5]
        hs_quota  = hs.get("total_quota", Quota_7)
        hs_bks    = get_bookings(hs["id"])
        hs_active = [b for b in hs_bks if b["status"] == "active"]
        hs_total  = sum(int(b["count"]) for b in hs_active)
        with st.expander(f"📅 {hs_date} {hs_label} {hs_start}-{hs_end}　（{hs_total}/{hs_quota} 人）", expanded=True):
            if not hs_active:
                st.caption("無報名紀錄")
                continue

            # ── 載入點名快取 ──
            hs_checkins = get_checkins(hs["id"])
            hs_sid      = hs["id"]
            cache_key_h = f"checkin_cache_{hs_sid}"
            if cache_key_h not in st.session_state:
                st.session_state[cache_key_h] = dict(hs_checkins)
            hs_local = st.session_state[cache_key_h]

            # ── 出席統計（只計算實到）──
            hs_arrived     = 0
            hs_member      = 0
            hs_casual_card = 0
            hs_casual_cash = 0
            for b in hs_active:
                if not hs_local.get(b["id"]):
                    continue  # 未到，跳過
                cnt = int(b["count"])
                hs_arrived += cnt
                if b["role"] == "member":
                    hs_member += cnt
                elif "[付現]" in b.get("name", ""):
                    hs_casual_cash += cnt
                else:
                    hs_casual_card += cnt
            hs_absent = hs_total - hs_arrived

            st.markdown(
                f"應到 **{hs_total}** 人，實到 **{hs_arrived}** 人，未到 **{hs_absent}** 人　"
                f"｜　實到：會員 **{hs_member}** 人、零打簽卡 **{hs_casual_card}** 人、零打付現 **{hs_casual_cash}** 人"
            )
            st.divider()

            # ── 名單明細（補點名）──
            for b in hs_active:
                raw   = b["name"]
                dname = raw.split("_🔑")[0] if "_🔑" in raw else raw
                zh_r  = ROLE_TO_ZH.get(b["role"], b["role"])
                bid   = b["id"]
                is_here = hs_local.get(bid, False)
                col_chk, col_lbl = st.columns([1, 7])
                with col_chk:
                    new_val = st.checkbox(
                        "到", value=is_here,
                        key=f"hist_chk_{hs_sid}_{bid}",
                        label_visibility="collapsed"
                    )
                    if new_val != is_here:
                        st.session_state[cache_key_h][bid] = new_val
                with col_lbl:
                    icon = "✅" if hs_local.get(bid) else "⭕"
                    st.write(f"{icon} {dname} ｜ {b['count']} 人 ｜ {zh_r}")

            if st.button("💾 儲存補點名", key=f"hist_save_{hs_sid}", use_container_width=True):
                saved = get_checkins(hs_sid)
                changed = False
                for booking_id, is_checked in st.session_state[cache_key_h].items():
                    if is_checked != saved.get(booking_id, False):
                        set_checkin(hs_sid, booking_id, is_checked)
                        changed = True
                if changed:
                    del st.session_state[cache_key_h]  # 清快取，重新載入
                    st.success("✅ 補點名已儲存")
                    st.rerun()
                else:
                    st.info("點名狀態未變動")
