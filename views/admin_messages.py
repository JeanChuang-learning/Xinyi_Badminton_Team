"""
views/admin_messages.py —— 管理員後台「📨 訊息中心」分頁（Msg Queue 管理）。
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from supabase_client import supabase

from config import MSG_QUEUE_TABLE
from notify import get_pending_queue, process_queue, send_line_direct


def render():
    st.subheader("📨 訊息中心")
    get_pending_queue.clear()  # 強制清快取，確保看到最新資料
    pending_msgs = get_pending_queue()
    quota_msgs   = []
    error_msgs   = []
    try:
        quota_msgs = supabase.table(MSG_QUEUE_TABLE).select("*") \
            .eq("status", "quota").order("created_at").execute().data or []
    except Exception:
        pass
    try:
        error_msgs = supabase.table(MSG_QUEUE_TABLE).select("*") \
            .eq("status", "error").order("created_at").execute().data or []
    except Exception:
        pass
    all_unsent = pending_msgs + quota_msgs + error_msgs

    # Debug 區塊：顯示 msg_queue 所有資料
    with st.expander("🔍 Debug：msg_queue 原始資料", expanded=False):
        try:
            all_rows = supabase.table(MSG_QUEUE_TABLE).select("*").order("created_at", desc=True).limit(20).execute().data or []
            st.caption(f"msg_queue 共 {len(all_rows)} 筆（最新20筆）")
            for r in all_rows:
                st.json(r)
        except Exception as e:
            st.error(f"讀取 msg_queue 失敗：{e}")

    if not all_unsent:
        st.caption("✅ 目前沒有待發送的訊息")
        return

    col_info, col_btn = st.columns([3, 1])
    with col_info:
        st.warning(f"⚠️ 待發送 {len(pending_msgs)} 則 | 配額不足 {len(quota_msgs)} 則 | 發送失敗 {len(error_msgs)} 則")
    with col_btn:
        if st.button("🚀 一鍵發送全部", use_container_width=True, type="primary"):
            sent_n, quota_n, err_n = process_queue()
            if quota_n:
                st.error(f"❌ LINE 配額用盡！已發 {sent_n} 則，{quota_n} 則需手動補發，{err_n} 則失敗")
            elif err_n:
                st.warning(f"⚠️ 已發 {sent_n} 則，{err_n} 則失敗，請查看下方錯誤項目")
            else:
                st.success(f"✅ 全部發送成功！共 {sent_n} 則")
            st.rerun()

    TAG_LABEL = {
        "open_notice":     "🟢 零打開放",
        "waitlist_remind": "📋 候補提醒",
        "promotion":       "📢 遞補通知",
        "release":         "🎉 名額釋出",
        "schedule_change": "📅 場次異動",
        "new_session":     "🆕 新場次",
        "daily_roster":    "🗓️ 賽前名單",
        "":                "📨 通知",
    }
    STATUS_LABEL = {
        "pending": "⏳ 等待發送",
        "quota":   "❌ 配額用盡",
        "error":   "⚠️ 發送失敗",
    }

    # ── 分類篩選按鈕 ──
    status_options = {
        "全部":                            None,
        f"⏳ 待發送（{len(pending_msgs)}）":  "pending",
        f"❌ 配額用盡（{len(quota_msgs)}）":   "quota",
        f"⚠️ 發送失敗（{len(error_msgs)}）":   "error",
    }
    status_choice = st.radio(
        "依狀態篩選", list(status_options.keys()),
        horizontal=True, key="msg_center_status_filter",
        label_visibility="collapsed",
    )
    status_pick = status_options[status_choice]

    tag_present = list(dict.fromkeys(item.get("tag", "") for item in all_unsent))
    tag_options = {"全部類型": None}
    for t in tag_present:
        tag_options[TAG_LABEL.get(t, f"📨 {t}" if t else "📨 通知")] = t
    tag_choice = st.selectbox(
        "依類型篩選", list(tag_options.keys()),
        key="msg_center_tag_filter",
    )
    tag_pick = tag_options[tag_choice]

    filtered_msgs = [
        item for item in all_unsent
        if (status_pick is None or item.get("status") == status_pick)
        and (tag_pick is None or item.get("tag", "") == tag_pick)
    ]

    if not filtered_msgs:
        st.caption("這個分類目前沒有符合的訊息")

    for item in filtered_msgs:
        tag     = item.get("tag", "")
        status  = item.get("status", "pending")
        label   = TAG_LABEL.get(tag, f"📨 {tag}")
        slabel  = STATUS_LABEL.get(status, status)
        created = item.get("created_at", "")[:16]
        with st.container(border=True):
            st.caption(f"{label}　{slabel}　{created}")
            msg_text = item.get("msg_text", "")
            st.code(msg_text, language=None)
            if status in ("quota", "error") and item.get("error"):
                st.caption(f"🔍 LINE 回應：{item['error']}")
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("🚀 單筆發送", key=f"q_send_{item['id']}", use_container_width=True):
                    try:
                        tids = json.loads(item.get("target_ids") or "[]")
                    except Exception:
                        tids = []
                    result, detail = send_line_direct(msg_text, tids)
                    now_s = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
                    if result == "ok":
                        supabase.table(MSG_QUEUE_TABLE).update(
                            {"status": "sent", "sent_at": now_s, "error": None}
                        ).eq("id", item["id"]).execute()
                        get_pending_queue.clear()
                        st.success("✅ 發送成功！"); st.rerun()
                    elif result == "quota":
                        supabase.table(MSG_QUEUE_TABLE).update(
                            {"status": "quota", "error": detail, "sent_at": now_s}
                        ).eq("id", item["id"]).execute()
                        get_pending_queue.clear()
                        st.error(f"❌ 配額用盡，請手動複製上方訊息貼到 LINE 群組\n\n{detail}")
                    else:
                        supabase.table(MSG_QUEUE_TABLE).update(
                            {"status": "error", "error": detail, "sent_at": now_s}
                        ).eq("id", item["id"]).execute()
                        get_pending_queue.clear()
                        st.error(f"❌ 發送失敗：{detail}")
            with b2:
                # ✅ 已手動發送完成 → 標記 sent
                if st.button("✅ 已手動完成", key=f"q_manual_{item['id']}", use_container_width=True):
                    now_s = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
                    supabase.table(MSG_QUEUE_TABLE).update(
                        {"status": "sent", "sent_at": now_s, "error": "手動發送"}
                    ).eq("id", item["id"]).execute()
                    get_pending_queue.clear()
                    st.success("已標記完成"); st.rerun()
            with b3:
                # 🗑️ 捨棄（不發）
                if st.button("🗑️ 捨棄", key=f"q_drop_{item['id']}", use_container_width=True):
                    now_s = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
                    supabase.table(MSG_QUEUE_TABLE).update(
                        {"status": "dropped", "sent_at": now_s}
                    ).eq("id", item["id"]).execute()
                    get_pending_queue.clear()
                    st.rerun()
