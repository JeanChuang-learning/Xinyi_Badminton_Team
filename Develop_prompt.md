# 信義羽球隊報名系統 — 開發 Prompt

> 這份文件是設計來**貼到新的 AI 對話最前面**用的，讓新的對話快速掌握這個專案的背景、
> 架構、容易踩雷的地方，不用每次都重新解釋一輪。如果你要請 AI 幫忙改這個專案的程式碼，
> 先把下面整段貼給它，再接著描述你要做的事。

---

## 專案是什麼

一個給羽球隊用的報名系統，兩個服務組成：

- **`app.py`**（部署在 **Streamlit Cloud**）：管理員後台 + 公開報名網站，Python + Streamlit。
- **`webhook.py`**（部署在 **Render**）：LINE Bot webhook + LIFF 報名頁 + 排程任務，Python + FastAPI。

兩邊共用同一個 **Supabase**（PostgreSQL）資料庫，核心資料表：`sessions`（場次）、
`bookings`（報名）、`msg_queue`（LINE 推播佇列）、`checkins`（點名紀錄）、
`line_pending_action`。

## 核心業務規則（改動前務必先搞懂，很多 bug 都出在這裡）

1. **身分判斷鐵律**：只有明確在「會員」LINE 群組裡的人才算會員，其餘一律當「零打」。
   LIFF 報名頁因為平台限制拿不到 groupId，改用網址帶的 `role` 參數判斷。
2. **正取/候補演算法**：會員優先無條件佔額（不受名額限制），零打依報名時間（`created_at`）
   排序，依剩餘名額（`min(總名額剩餘, 零打名額上限剩餘)`）逐筆判斷正取/候補，
   同一筆報名可能「部分正取、部分候補」。
3. **零打開放時間**：依場次是星期幾提前 2～7 天開放，會員不受此限制（規則見
   `shared_logic.py` 的 `get_session_open_date`）。
4. **通知規則**：開放/剩餘名額只發零打群；名單、報名按鈕發零打＋會員兩群。

## 檔案結構（2026-09 已拆分成模組，不要再把邏輯塞回單一大檔案）

```
app.py                 # 主入口，只做資料載入 + 依序呼叫各畫面，改動要謹慎
config.py               # 常數 / secrets / 頁面設定
db.py                   # Supabase 讀寫（sessions/bookings/checkins/系統設定）
notify.py               # LINE 推播 + msg_queue 佇列
logic.py                # 業務規則（正取候補輔助函式、自動場次產生…）
shared_logic.py          # app.py 和 webhook.py 共用（開放時間規則），改這裡兩邊都要重新部署
views/
  session_picker.py       # 場次選擇格
  dev_tools.py             # 管理員測試工具
  contact_footer.py        # 聯絡窗口 + 管理員登入按鈕
  admin_panel.py           # 管理員登入外殼 + 5 個分頁
  admin_messages.py        # 分頁：📨 訊息中心
  admin_contacts.py        # 分頁：📱 聯絡人
  admin_sessions.py        # 分頁：🗓️ 場次管理
  admin_settings.py        # 分頁：🛠 系統參數
  admin_history.py         # 分頁：📊 歷史紀錄
  booking_detail.py        # 選定場次後的報名/名單/點名主畫面（最大最複雜的一個檔案）
webhook.py               # LINE webhook + LIFF + 排程任務入口
```

**改動原則**：先判斷要改的東西屬於上面哪一個檔案的職責，只改那個檔案。
`db.py` 只放純資料庫存取（不含業務規則判斷）；`logic.py` 放業務規則；
`notify.py` 只管 LINE 推播/佇列；UI 相關全部在 `views/`。

## 兩邊 secrets / 環境變數命名（踩過雷，務必注意）

| 常數 | Streamlit Cloud（`st.secrets`） | Render（`os.environ`） |
|---|---|---|
| LINE token | `LINE_CHANNEL_ACCESS_TOKEN` | `LINE_CHANNEL_ACCESS_TOKEN` |
| 零打群組 ID | `LINE_GROUP_ID_CASUAL`（全大寫） | `LINE_GROUP_ID_CASUAL`（全大寫） |
| 會員群組 ID | `LINE_GROUP_ID_MEMBER`（全大寫） | `LINE_GROUP_ID_MEMBER`（全大寫） |
| 幹部群組 ID | `LINE_GROUP_ID_ADMIN`（全大寫） | webhook.py 目前沒用到 |
| 管理員密碼 | `ADMIN_PASSWORD` | 不適用 |

**2026-09 已經統一成全大寫**（原本 Streamlit 那邊是 `LINE_GROUP_ID_Casual` 首字大寫、
跟 Render 對不起來，改過一次了）。**這兩個平台的 secrets/環境變數是完全獨立的兩套系統**，
改一邊不會自動同步到另一邊，兩邊都要手動維護。

## 已知的框架層級小雷（不是程式邏輯錯誤）

- 管理員登入瞬間，畫面結構變化很大（從一個密碼框瞬間變成 5 個分頁），偶爾會跳出
  Streamlit 的「Bad message format」錯誤，這是 Streamlit 框架本身的已知行為
  （跟這個專案的程式邏輯無關），跳出後**重新整理頁面**就會恢復正常，不影響資料正確性。
- `check_and_release_casual_limit()`（在 `logic.py`）裡有一行沒有條件判斷的 `print`，
  只要有人操作網站（任何點擊/送出表單）就會讓整支 `app.py` 重跑一次、印一次 log，
  屬於正常現象，不代表背景有排程異常。

## 部署注意事項

- `shared_logic.py` 一定要放在 repo 根目錄，讓 `app.py`（透過 `logic.py`）和 `webhook.py`
  兩邊的部署都能 import 到（前提：兩邊部署設定的 root directory 都是整個 repo）。
- 建議部署順序：先部署 `webhook.py`（Render），改動小、風險低，確認 log 沒有
  `ModuleNotFoundError` 後，再部署 `app.py`（Streamlit Cloud）。
- 部署後建議手動走一次：開場次 → 會員報名 → 零打報名到額滿觸發候補 → 修改/取消一筆 →
  確認候補遞補正確 → 管理員後台 5 個分頁都點開看一次 → 點名並儲存。

## 目前還沒完整驗證過的部分（2026-09 拆分後）

- **候補遞補的完整路徑**：連續灌超過零打名額上限的報名，確認超過的部分正確標記候補，
  拿掉一筆正取後候補是否正確遞補、訊息中心是否正確入列遞補通知。
