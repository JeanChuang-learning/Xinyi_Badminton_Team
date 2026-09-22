"""
notify.py —— LINE 推播 + msg_queue 佇列處理。

所有 LINE 通知需求先寫入 Supabase msg_queue 表（enqueue_msg），
再由管理員後台「一鍵發送」或排程（process_queue）送出，
避免每次頁面刷新重複發送。
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from supabase_client import supabase

from config import (
    LINE_CHANNEL_ACCESS_TOKEN,
    LINE_GROUP_ID_CASUAL,
    LINE_GROUP_ID_MEMBER,
    LINE_GROUP_ID_ADMIN,
    MSG_QUEUE_TABLE,
)


def _get_target_ids(notify_type):
    """根據 notify_type 回傳目標群組 ID 清單"""
    if notify_type == "waitlist":
        return [LINE_GROUP_ID_CASUAL]
    elif notify_type == "schedule_change":
        return [LINE_GROUP_ID_CASUAL, LINE_GROUP_ID_MEMBER]
    elif notify_type == "admin_only":
        return [LINE_GROUP_ID_ADMIN] if LINE_GROUP_ID_ADMIN else []
    elif notify_type == "all":
        ids = [LINE_GROUP_ID_CASUAL, LINE_GROUP_ID_MEMBER]
        if LINE_GROUP_ID_ADMIN:
            ids.append(LINE_GROUP_ID_ADMIN)
        return ids
    return []


def enqueue_msg(msg_text, notify_type, tag="", session_id=""):
    """
    把通知需求寫入 msg_queue 表（不直接發 LINE）。
    tag: 標籤字串，如 'open_notice', 'waitlist_remind', 'promotion', 'release'
    回傳寫入成功與否（bool）。
    """
    target_ids = _get_target_ids(notify_type)
    if not target_ids:
        print(f"[enqueue_msg] notify_type={notify_type} 無目標群組，跳過")
        return True  # 視為成功，不阻塞流程
    try:
        now_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        supabase.table(MSG_QUEUE_TABLE).insert({
            "msg_text":    msg_text,
            "notify_type": notify_type,
            "target_ids":  json.dumps(target_ids, ensure_ascii=False),
            "tag":         tag,
            "session_id":  session_id,
            "status":      "pending",
            "created_at":  now_str,
            "sent_at":     None,
            "error":       None,
        }).execute()
        print(f"[enqueue_msg] 已入列: tag={tag}, notify_type={notify_type}")
        return True
    except Exception as e:
        print(f"[enqueue_msg] 寫入 Queue 失敗: {e}")
        return False


def notify_by_type(msg_text, notify_type, tag="", session_id=""):
    """
    舊介面保留：所有呼叫點不需改動，
    內部改成 enqueue_msg 入列，不直接打 LINE。
    回傳 True = 入列成功，False = 入列失敗。
    """
    return enqueue_msg(msg_text, notify_type, tag=tag, session_id=session_id)


def send_line_direct(msg_text, target_ids):
    """
    直接發送（只有「處理 Queue」排程呼叫）。
    回傳 (result, detail)：result 為 'ok' / 'quota' / 'error'，
    detail 是 LINE 實際回應內容（存進 msg_queue.error，方便日後診斷是真額度用完還是別的錯誤）。
    """
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return "error", "缺少 LINE_CHANNEL_ACCESS_TOKEN"
    try:
        got_quota = False
        got_error = False
        details = []
        for gid in target_ids:
            r = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
                data=json.dumps({"to": gid, "messages": [{"type": "text", "text": msg_text}]}),
            )
            print(f"[send_line] {gid} → {r.status_code} | {r.text}")
            details.append(f"{gid}: HTTP {r.status_code} {r.text[:200]}")
            if r.status_code == 429:
                got_quota = True
            elif r.status_code != 200:
                got_error = True
        detail_str = " ｜ ".join(details)
        if got_quota:
            return "quota", detail_str
        if got_error:
            return "error", detail_str
        return "ok", detail_str
    except Exception as e:
        return "error", f"例外: {e}"


@st.cache_data(ttl=15)
def get_pending_queue():
    """讀取 pending 中的 Queue 項目"""
    try:
        return supabase.table(MSG_QUEUE_TABLE).select("*") \
            .eq("status", "pending").order("created_at").execute().data or []
    except Exception as e:
        print(f"[get_pending_queue] 讀取失敗: {e}")
        return []


def process_queue():
    """
    逐筆處理 pending Queue：
    - 成功 → status='sent'
    - 429   → status='quota'（保留，等下月）
    - 錯誤  → status='error'（保留重試）
    回傳 (sent, quota, error) 筆數。
    """
    pending = get_pending_queue()
    sent = quota = error = 0
    now_str = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    for item in pending:
        try:
            target_ids = json.loads(item.get("target_ids") or "[]")
        except Exception:
            target_ids = []
        if not target_ids:
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "error", "error": "target_ids 為空", "sent_at": now_str}
            ).eq("id", item["id"]).execute()
            error += 1
            continue
        result, detail = send_line_direct(item["msg_text"], target_ids)
        if result == "ok":
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "sent", "sent_at": now_str, "error": None}
            ).eq("id", item["id"]).execute()
            sent += 1
        elif result == "quota":
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "quota", "error": detail, "sent_at": now_str}
            ).eq("id", item["id"]).execute()
            quota += 1
            break  # 配額用盡後停止，避免打爆剩餘配額
        else:
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "error", "error": detail, "sent_at": now_str}
            ).eq("id", item["id"]).execute()
            error += 1
    get_pending_queue.clear()
    return sent, quota, error
