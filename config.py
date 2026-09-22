"""
config.py —— 常數、Secrets、頁面設定。

⚠️ 注意：這個檔案只會在 Streamlit process 第一次啟動時被 import 執行一次
（Python 的 import cache），之後每次使用者互動觸發的 rerun 都不會重新執行這裡的程式碼。
所以這裡只放「不隨時間變動」的東西：secrets、常數、st.set_page_config()。

像 today_date 這種「每次 rerun 都要重新計算」的值，
不要放在這裡，維持在 app.py 最上層計算（見 app.py 開頭）。
"""

import streamlit as st

# ─────────────────────────
# 頁面設定（整個 App 生命週期只需要設定一次）
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸", layout="centered")

# ─────────────────────────
# Secrets
# ─────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = st.secrets["LINE_CHANNEL_ACCESS_TOKEN"]

LINE_GROUP_ID_CASUAL = st.secrets["LINE_GROUP_ID_CASUAL"]
LINE_GROUP_ID_MEMBER = st.secrets["LINE_GROUP_ID_MEMBER"]
LINE_GROUP_ID_ADMIN  = st.secrets["LINE_GROUP_ID_ADMIN"]
ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]

web_url = "https://am24logbujoqctvut7bqmk.streamlit.app"

# ─────────────────────────
# 名額常數
# 週一/週五：總額 28 人，零打上限 10 人
# 週日：總額 21 人，零打上限 15 人
# ─────────────────────────
Quota_15 = 28;  Limit_15 = 10
Quota_7  = 21;  Limit_7  = 15

# ─────────────────────────
# 常數設定
# ─────────────────────────
ROLE_MAP   = {"會員": "member", "零打": "casual"}
ROLE_TO_ZH = {"member": "會員", "casual": "零打"}
WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]

FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一", "quota": Quota_15, "casual_quota": Limit_15},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五", "quota": Quota_15, "casual_quota": Limit_15},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日", "quota": Quota_7,  "casual_quota": Limit_7},
]

# ─────────────────────────
# 場地資訊
# ─────────────────────────
VENUE_INFO = {
    "weekday": {  # 週一(0)、週五(4)
        "name": "興中國中",
        "address": "宜蘭縣五結鄉上四村中正東路50號",
        "map_url": "https://maps.app.goo.gl/KXWUpBzNgpFyyBxA7",
    },
    "sunday": {   # 週日(6)
        "name": "中興國小",
        "address": "宜蘭縣五結鄉四結村中興路三段67號",
        "map_url": "https://maps.app.goo.gl/SfSsb3PH7L8jYZo4A",
    },
}

MSG_QUEUE_TABLE = "msg_queue"
SYSTEM_ROW_IDS  = ("_admin_line_config", "_system_settings")
