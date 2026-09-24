"""
views/admin_sessions.py —— 管理員後台「🗓️ 場次管理」分頁：
取消場次 / 恢復場次 / 會員限定切換 / 加開臨時場次 / 修改場次資訊。
"""

import re
import time
from datetime import date, datetime, timedelta

import streamlit as st
from supabase_client import supabase

from config import Quota_7, Limit_7
from db import get_sessions, update_session
from logic import user_label
from notify import notify_by_type
from shared_logic import is_member_only_session


# ── note 欄位中的系統標記（機關碼）──
# 這些標記由程式判斷業務狀態（會員限定、排程是否已處理等），
# 管理員的「備註」編輯不可以動到它們。
SYSTEM_FLAGS = ("[會員限定]", "[已通知開放]", "[已釋出名額]", "[已恢復場次]")
_FLAG_RE = re.compile("|".join(re.escape(f) for f in SYSTEM_FLAGS))


def split_note(note):
    """把 note 拆成 (自由文字, [系統標記...])，標記依出現順序、不重複。"""
    note = note or ""
    flags = []
    for f in _FLAG_RE.findall(note):
        if f not in flags:
            flags.append(f)
    text = re.sub(r"[ \t]{2,}", " ", _FLAG_RE.sub("", note)).strip()
    return text, flags


def merge_note(free_text, flags):
    """自由文字（會先濾掉誤打的系統標記）＋ 系統標記 → 完整 note。"""
    text, _ = split_note(free_text)
    return " ".join([t for t in [text, *flags] if t]).strip()


def fetch_fresh_note(session_id):
    """直接查資料庫取得最新 note（不走 st.cache_data），失敗回傳 None。"""
    try:
        rows = supabase.table("sessions").select("note").eq("id", session_id).execute().data or []
    except Exception:
        return None
    if not rows:
        return None
    return rows[0].get("note") or ""


def render(keys, session_map, sessions_sorted):
    st.subheader("🗓️ 場次管理")

    # ── 1. 取消場次 ──
    with st.expander("❌ 取消場次", expanded=False):
        with st.form("cancel_session_form", clear_on_submit=True):
            cancel_target = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="cancel_sel")
            reason = st.text_input("原因")
            if st.form_submit_button("確認取消"):
                note = (session_map[cancel_target].get("note") or "").replace("[已恢復場次]", "").strip()
                update_session(cancel_target, {"cancelled": True, "cancel_reason": reason, "note": note})
                notify_by_type(f"⚠️【信義羽球隊】{session_map[cancel_target]['date']} 場次已取消。原因：{reason}", 'schedule_change')
                st.success("已取消"); st.rerun()

    # ── 2. 恢復場次 ──
    with st.expander("🔄 恢復場次", expanded=False):
        cancelled_list = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map = {s["id"]: s for s in cancelled_list}
        if restore_map:
            restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()),
                                          format_func=lambda x: user_label(restore_map[x]), key="restore_target")
            if st.button("確認恢復場次"):
                note = restore_map[restore_target].get("note") or ""
                if "[已恢復場次]" not in note:
                    note = f"{note} [已恢復場次]".strip()
                update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": note})
                notify_by_type(f"🟢【信義羽球隊】{restore_map[restore_target]['date']} 場次已恢復！", 'schedule_change')
                st.success("已恢復！"); st.rerun()
        else:
            st.caption("目前沒有已取消的場次")

    # ── 3. 會員限定切換 ──
    with st.expander("👑 設定會員限定", expanded=False):
        future_keys = [k for k in keys if not session_map[k].get("cancelled")]
        if future_keys:
            member_target = st.selectbox(
                "選擇場次", future_keys,
                format_func=lambda x: user_label(session_map[x]),
                key="member_only_sel"
            )
            target_s   = session_map[member_target]
            target_note = target_s.get("note") or ""
            is_currently_member_only = is_member_only_session(target_s)
            st.info(f"目前狀態：{'👑 會員限定' if is_currently_member_only else '🟢 一般開放（含零打）'}")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("設為 👑 會員限定", disabled=is_currently_member_only, use_container_width=True):
                    new_note = f"{target_note} [會員限定]".strip()
                    update_session(member_target, {"note": new_note})
                    notify_by_type(f"👑【信義羽球隊】{target_s['date']} {target_s['label']} 已改為會員限定場次。", 'schedule_change')
                    st.success("已設為會員限定！"); st.rerun()
            with col_b:
                if st.button("改回 🟢 一般開放", disabled=not is_currently_member_only, use_container_width=True):
                    new_note = target_note.replace("[會員限定]", "").strip()
                    update_session(member_target, {"note": new_note})
                    notify_by_type(f"🟢【信義羽球隊】{target_s['date']} {target_s['label']} 已開放零打報名。", 'schedule_change')
                    st.success("已改回一般開放！"); st.rerun()
        else:
            st.caption("目前沒有可設定的場次")

    # ── 4. 加開臨時場次 ──
    with st.expander("🔥 加開臨時場次", expanded=False):
        with st.form("add_session_form", clear_on_submit=True):
            add_date  = st.date_input("日期", value=date.today() + timedelta(days=1), key="add_date")
            add_start = st.time_input("開始時間", value=datetime.strptime("19:00", "%H:%M").time(), key="add_start")
            add_end   = st.time_input("結束時間", value=datetime.strptime("22:00", "%H:%M").time(), key="add_end")
            add_label = st.text_input("場次名稱", value="臨時加開", key="add_label")
            add_quota = st.number_input("人數上限", min_value=1, max_value=200, value=Quota_7, key="add_quota")
            add_casual_quota = st.number_input("零打名額上限", min_value=0, max_value=100, value=Limit_7, key="add_casual_quota")
            add_note  = st.text_input("備註（選填）", key="add_note")
            if st.form_submit_button("確認加開", type="primary"):
                new_sid = f"{add_date.isoformat()}_{add_start.strftime('%H:%M')}_extra_{int(time.time())}"
                try:
                    supabase.table("sessions").insert({
                        "id": new_sid,
                        "date": str(add_date),
                        "start_time": add_start.strftime("%H:%M"),
                        "end_time":   add_end.strftime("%H:%M"),
                        "label":      add_label,
                        "note":       add_note,
                        "total_quota": int(add_quota),
                        "casual_quota": int(add_casual_quota),
                        "cancelled": False, "cancel_reason": "", "locked": False,
                    }).execute()
                    get_sessions.clear()
                    # 不再推播「新場次開放報名」通知（會員習慣當天才報名，
                    # 零打報名靠指定時間排程推播「報名」按鈕即可）
                    st.success("加開成功！"); st.rerun()
                except Exception as e:
                    st.error(f"加開失敗：{e}")

    # ── 5. 修改場次資訊 (絕對安全版) ──
    with st.expander("⚙️ 修改場次資訊", expanded=False):
        # 這裡的 key 確保不會跟下面輸入框的 key 衝突
        edit_target = st.selectbox(
            "選擇場次",
            options=keys,
            format_func=lambda x: user_label(session_map[x]),
            key="admin_selectbox_main_session"
        )

        if edit_target:
            edit_s = session_map[edit_target]

            # 【強制唯一化 Key】使用 session_id 作為變數名稱一部分
            unique_id = str(edit_target)

            edit_label = st.text_input(
                "場次名稱",
                value=edit_s.get("label", ""),
                key=f"field_label_{unique_id}"
            )

            edit_quota = st.number_input(
                "人數上限",
                min_value=1,
                max_value=200,
                value=max(1, int(edit_s.get("total_quota", Quota_7))),
                key=f"field_quota_{unique_id}"
            )

            edit_casual_quota = st.number_input(
                "零打名額上限",
                min_value=0,
                max_value=100,
                value=int(edit_s.get("casual_quota", Limit_7)),
                key=f"field_casual_quota_{unique_id}"
            )

            # 備註只編輯「自由文字」；系統標記另外唯讀顯示，不放進輸入框
            shown_text, shown_flags = split_note(edit_s.get("note"))
            edit_note = st.text_input(
                "備註",
                value=shown_text,
                key=f"field_note_{unique_id}"
            )
            if shown_flags:
                st.caption("🔒 系統標記（自動保留，無法在此編輯）：" + " ".join(shown_flags))

            if st.button("確認更新", key=f"btn_update_{unique_id}", type="primary"):
                # 儲存當下重新讀最新 note，取最新的系統標記，
                # 避免畫面開著期間排程新增的標記被舊內容蓋掉
                fresh_note = fetch_fresh_note(edit_target)
                if fresh_note is None:
                    st.error("讀取最新場次資料失敗，為避免覆蓋系統標記，本次未更新，請稍後再試。")
                else:
                    _, fresh_flags = split_note(fresh_note)
                    update_session(edit_target, {
                        "label": edit_label,
                        "total_quota": int(edit_quota),
                        "casual_quota": int(edit_casual_quota),
                        "note": merge_note(edit_note, fresh_flags),
                    })
                    st.success("已更新！")
                    st.rerun()
        else:
            st.write("請選擇一個場次進行編輯")
