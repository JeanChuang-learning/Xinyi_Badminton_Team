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


# ─────────────────────────
# 付款方式（bookings.payment_method）
# ─────────────────────────
# 統一用英文代碼當作資料庫裡的正式值，兩邊（webhook.py / booking_detail.py）都用同一套。
PAY_LABELS = {"card": "💳 簽卡", "cash": "💵 付現", "transfer": "🏦 轉帳"}

# 網站表單上顯示的是中文按鈕文字，這裡對應回資料庫要存的英文代碼。
PAY_CODE_BY_ZH = {"簽卡": "card", "付現": "cash", "轉帳": "transfer"}

# ⚠️ 舊資料相容用：這個修正上線之前，網站報名是把付款方式塞進 bookings.name
# 字串裡（例如 "王小明[付現]"），而不是寫進 payment_method 欄位。
# get_payment_method() 會優先讀 payment_method 欄位，讀不到才 fallback 去
# 解析 name 字串，這樣舊資料的統計還是準的，不用特地跑一次資料庫遷移。
_LEGACY_NAME_TAG_CODE = {"付現": "cash", "轉帳": "transfer", "簽卡": "card"}


def get_payment_method(booking: dict):
    """
    回傳這筆報名的付款方式代碼："card" / "cash" / "transfer"，或 None（會員、或無資料）。
    這是唯一應該用來判斷付款方式的地方——不要再各自去 `"[付現]" in booking["name"]`
    或各自讀 `booking["payment_method"]`，兩邊只要有一邊漏改，統計就會兜不起來
    （這正是本次要修的 bug：網站報名以前只寫 name 字串、沒寫這個欄位）。
    """
    pm = booking.get("payment_method")
    if pm in PAY_LABELS:
        return pm
    raw_name = booking.get("name") or ""
    for tag, code in _LEGACY_NAME_TAG_CODE.items():
        if f"[{tag}]" in raw_name:
            return code
    return None


# ─────────────────────────
# 正取／候補分配演算法
# ─────────────────────────
# 場次沒有明確設定名額時的預設值（正常情況下每個場次都會有自己的
# total_quota / casual_quota，這兩個常數只在資料缺漏時當備援）。
TOTAL_QUOTA_DEFAULT  = 21
CASUAL_QUOTA_DEFAULT = 15


def compute_allocation(session: dict, rows: list):
    """
    對一串「依報名時間排序」的 active bookings，套用正取/候補的分配演算法。
    這是唯一應該用來判斷「誰正取、誰候補、候補了幾人」的地方——原本
    booking_detail.py（網站）、webhook.py 的 compute_confirmed_ids /
    compute_status_text / compute_max_new_count、views/dev_tools.py 的模擬報名，
    各自重寫了一份幾乎一樣但不完全同步的版本，其中 webhook.py 那幾份甚至沒有
    處理「部分正取」（同一筆報名一部分人正取、一部分候補），導致：
      - 零打名額（casual_quota）滿了但總名額（total_quota）還有空間時，
        LINE/LIFF 回覆的「正取成功」文字跟網站後台實際算出來的狀態會兜不起來
      - 候補遞補的推播通知，會把「只遞補了一部分」講成「已經全部正取」

    規則（會員永遠正取、零打依報名時間先後排隊，同時受 total_quota 與
    casual_quota 雙重限制）：
      - member：一律全數正取，不佔用 casual_quota。
      - casual：這筆能拿到的名額 = min(total_quota 剩餘, casual_quota 剩餘)，
        如果比自己要的人數少，就是「部分正取」；等於 0 就是「全數候補」。

    rows 只需要每筆有 "role"／"count"（其他欄位會原封不動保留在回傳結果裡），
    不需要是資料庫裡已經存在的資料——呼叫端可以自己在最後面加一筆「假設要
    新增」的報名，藉此模擬「如果現在送出這筆，結果會是什麼」，不用真的先寫
    進資料庫再回頭查一次。

    回傳 (allocated, summary)：
      allocated：跟 rows 等長、等順序的 list，每筆是原本的 dict 再加上：
        - "confirmed_count"：這筆實際拿到幾個名額（member 一定等於 count）
        - "waitlist_count"： 這筆候補幾人（member 一定是 0）
        - "is_waitlist"：    False（全數正取）／True（全數候補）／
                             "partial"（部分正取，同時看 confirmed_count
                             與 waitlist_count 就知道各是幾人）
      summary：{"running_total": ..., "running_casual": ...}
        代表處理完「所有 rows」之後，目前已佔用的總名額／零打名額，
        呼叫端可以拿這個去算「扣掉這些之後還剩多少空位」。
    """
    quota        = session.get("total_quota") or TOTAL_QUOTA_DEFAULT
    casual_quota = session.get("casual_quota") or CASUAL_QUOTA_DEFAULT

    running_total = running_casual = 0
    allocated = []
    for row in rows:
        count = int(row.get("count") or 0)
        if row.get("role") == "member":
            confirmed_count = count
            waitlist_count  = 0
            is_waitlist     = False
            running_total  += count
        else:
            total_remaining     = quota - running_total
            casual_remaining    = casual_quota - running_casual
            effective_remaining = min(total_remaining, casual_remaining)

            if effective_remaining <= 0:
                confirmed_count = 0
                waitlist_count  = count
                is_waitlist     = True
            elif count > effective_remaining:
                confirmed_count = effective_remaining
                waitlist_count  = count - effective_remaining
                is_waitlist     = "partial"
            else:
                confirmed_count = count
                waitlist_count  = 0
                is_waitlist     = False

            running_total  += confirmed_count
            running_casual += confirmed_count

        allocated.append({
            **row,
            "confirmed_count": confirmed_count,
            "waitlist_count":  waitlist_count,
            "is_waitlist":     is_waitlist,
        })

    return allocated, {"running_total": running_total, "running_casual": running_casual}
