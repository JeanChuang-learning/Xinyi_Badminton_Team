"""
共用業務邏輯 —— app.py（Streamlit 後台）與 webhook.py（LINE Bot / LIFF）都 import 這個檔案。

⚠️ 這兩個函式原本在 app.py 和 webhook.py 各自維護一份幾乎逐字重複的版本
   （交接文件已提醒「多處重複實作，邏輯要保持一致」）。
   現在統一成單一來源，兩邊都改成 import 這裡的版本，之後只要改一處。

放在 repo 根目錄，讓 Streamlit Cloud（app.py）跟 Render（webhook.py）
兩邊的 deploy 都能直接 import
（前提：兩邊的 root directory 設定都是整個 repo，不是各自的子資料夾）。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def get_session_open_date(session_date_obj):
    """
    計算場次的開放報名日：
    - 週五場 (weekday=4)：提前 2 天開放（週三）
    - 週日場 (weekday=6)：提前 4 天開放（週三）
    - 週一場 (weekday=0)：提前 3 天開放（前一個週五）
    - 其他：預設提前 7 天開放
    """
    wd = session_date_obj.weekday()
    if wd == 4:
        return session_date_obj - timedelta(days=2)
    elif wd == 6:
        return session_date_obj - timedelta(days=4)
    elif wd == 0:
        return session_date_obj - timedelta(days=3)
    else:
        return session_date_obj - timedelta(days=7)


def is_casual_open_for_signup(session_date_obj) -> bool:
    """判斷零打是否已開放報名（依星期規則，開放日 UTC 0 點即開放）"""
    open_date = get_session_open_date(session_date_obj)
    open_dt_utc = datetime(
        open_date.year, open_date.month, open_date.day,
        0, 0, 0, tzinfo=ZoneInfo("UTC")
    )
    return datetime.now(ZoneInfo("UTC")) >= open_dt_utc


def is_member_only_session(session: dict) -> bool:
    """
    判斷這個場次是否為「會員限定」（零打完全不開放報名）。
    目前用 sessions.note 欄位裡有沒有 [會員限定] 字串標記來判斷
    （跟管理員後台「設定會員限定」用的是同一個標記，見 views/admin_sessions.py）。

    ⚠️ 網站（booking_detail.py）跟 LINE/LIFF（webhook.py）都要呼叫這個函式，
    不要各自重寫一份 "[會員限定]" in note 的判斷，否則以後改標記方式
    （例如改成獨立欄位）很容易漏改一邊，造成零打能繞過會員限定場次報名。
    """
    return "[會員限定]" in (session.get("note") or "")
