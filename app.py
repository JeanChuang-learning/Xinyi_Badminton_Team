"""
app.py —— Streamlit 管理員後台 + 報名網站的主入口。

這支檔案只負責「orchestration」：
1. 載入場次資料、跑自動化檢查（開放通知、零打名額釋出）
2. 依序呼叫各個 views/*.py 畫面

實際的業務邏輯、資料庫存取、UI 內容都拆到對應模組：
    config.py        常數 / secrets / 頁面設定
    db.py            Supabase 讀寫（sessions / bookings / checkins / 系統設定）
    notify.py        LINE 推播 + msg_queue 佇列
    logic.py         業務規則（正取候補相關的輔助函式、自動場次產生…）
    shared_logic.py  跟 webhook.py 共用的開放時間規則（避免重複實作）
    views/           每個畫面區塊一個檔案
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

import config  # noqa: F401  (import 時就會執行 st.set_page_config 等初始化)
from db import get_sessions, get_db_admin_line_list
from logic import auto_generate_fixed_sessions, check_and_send_open_notifications, check_and_release_casual_limit
from views import session_picker, dev_tools, contact_footer, admin_panel, booking_detail

# ─────────────────────────
# today_date 一定要留在 app.py 這一層計算！
# Streamlit 每次互動都會把 app.py 整支重新執行一次，但 import 進來的模組
# （config.py / logic.py…）只有 process 第一次啟動時會真的執行一次。
# 如果把 today_date 放進某個模組的模組層級變數，就會被 Python 的
# import cache 卡住、永遠停在 process 剛啟動那一刻，隔天也不會更新。
# ─────────────────────────
today_date = datetime.now(ZoneInfo("UTC")).date()

# ─────────────────────────
# 資料載入
# ─────────────────────────
raw_sessions      = get_sessions()
all_sessions      = auto_generate_fixed_sessions(raw_sessions, today_date)
admin_line_config = get_db_admin_line_list()

unique_map = {}
for s in all_sessions:
    sid = s.get("id")
    if sid:
        unique_map[sid] = s

sessions_sorted = sorted(unique_map.values(), key=lambda s: (s["date"], s["start_time"]))

session_map = {s["id"]: s for s in sessions_sorted}
keys        = list(session_map.keys())

if "selected_sid" not in st.session_state:
    st.session_state["selected_sid"] = None

# ─────────────────────────
# 自動化檢查（開放通知標記 / 零打名額自動釋出）
# ─────────────────────────
check_and_send_open_notifications(session_map, today_date)
check_and_release_casual_limit(session_map)

# 若有場次剛被開放，重新載入 session_map 確保畫面正確
_fresh_sessions = get_sessions()
_fresh_map = {s["id"]: s for s in _fresh_sessions}
if any(
    "[會員限定]" in (session_map.get(k, {}).get("note") or "") and
    "[會員限定]" not in (_fresh_map.get(k, {}).get("note") or "")
    for k in session_map
):
    session_map = _fresh_map
    keys = list(session_map.keys())

# ─────────────────────────
# 畫面渲染（依原本頁面順序）
# ─────────────────────────
session_picker.render(session_map, keys, today_date)
dev_tools.render()
contact_footer.render(admin_line_config)
admin_panel.render(session_map, keys, sessions_sorted, admin_line_config, today_date)
booking_detail.render(session_map, today_date)
