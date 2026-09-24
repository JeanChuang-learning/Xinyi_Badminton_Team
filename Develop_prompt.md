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
   這個判斷跟「這個角色能不能報名這一場」是兩件不同的事，見下面第 5 點。
2. **正取/候補演算法**：會員優先無條件佔額（不受名額限制），零打依報名時間（`created_at`）
   排序，依剩餘名額（`min(總名額剩餘, 零打名額上限剩餘)`）逐筆判斷正取/候補，
   同一筆報名可能「部分正取、部分候補」。
   ⚠️ 這段邏輯目前在 `views/booking_detail.py`、`webhook.py`（`compute_confirmed_ids` /
   `compute_status_text` / `compute_max_new_count`）、`views/dev_tools.py` 至少重複實作了
   4 份，還沒抽成共用函式，改一處記得檢查其他幾處是否也要同步改。
3. **零打開放時間**：依場次是星期幾提前 2～7 天開放，會員不受此限制（規則見
   `shared_logic.py` 的 `get_session_open_date`）。
4. **通知規則**：開放/剩餘名額只發零打群；名單、報名按鈕發零打＋會員兩群。
   **例外：會員限定場次完全不通知零打群**（連名單都不發），見下面第 5 點。
5. **會員限定場次**：`sessions.note` 裡有 `[會員限定]` 標記的場次，零打完全不能報名、
   也不會收到任何跟這場有關的通知或報名按鈕（開放通知、剩餘名額通知、名單、Flex 報名
   按鈕全部排除）。唯一的判斷來源是 `shared_logic.is_member_only_session(session)`，
   **不要在任何地方重寫 `"[會員限定]" in note` 這種判斷式**——2026-09 曾經發生
   `webhook.py`（LINE Bot / LIFF）完全沒有做這個檢查，導致會員限定場次零打還是能透過
   LINE 報名成功繞過網站的限制，修復後統一成這個共用函式，`views/admin_sessions.py`
   是唯一允許「寫入」`[會員限定]` 標記的地方。
6. **付款方式**：`bookings.payment_method` 是唯一的正式儲存欄位（值為英文代碼
   `"card"`/`"cash"`/`"transfer"`），網站與 LINE/LIFF 兩邊報名都要寫這個欄位。
   讀取一律呼叫 `shared_logic.get_payment_method(booking)`（內建舊資料 fallback，
   2026-09 修復前網站報名是把付款方式塞進 `bookings.name` 字串裡的 `[簽卡]`/`[付現]`/
   `[轉帳]`，這個函式讀不到 `payment_method` 欄位時會自動 fallback 解析 `name`，
   所以修復前的舊資料統計還是準的，不用跑遷移）。**不要再自己寫
   `"[付現]" in booking["name"]` 這種判斷。**

## 檔案結構（2026-09 已拆分成模組，不要再把邏輯塞回單一大檔案）

```
app.py                 # 主入口，只做資料載入 + 依序呼叫各畫面，改動要謹慎
config.py               # 常數 / secrets / 頁面設定
db.py                   # Supabase 讀寫（sessions/bookings/checkins/系統設定）
notify.py               # LINE 推播 + msg_queue 佇列
logic.py                # 業務規則（正取候補輔助函式、自動場次產生…）
shared_logic.py          # app.py 和 webhook.py 共用（開放時間規則、會員限定判斷、
                         # 付款方式代碼），改這裡兩邊都要重新部署
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
- **改完程式碼一定要確認有重新部署（Streamlit Cloud 有時候要手動 Reboot app 才會真的套用
  新版本）**：2026-09 曾經改完 `booking_detail.py` 後看起來沒生效，結果是 Streamlit Cloud
  還在跑舊的 process，手動 Reboot 之後才正常。改完程式碼、確認行為跟預期不符時，先檢查
  是否真的部署到最新版，不要急著改程式碼。

## 資料庫（Supabase）注意事項

- **`checkins` 表的主鍵是 `id`（uuid），不是自然鍵 `(session_id, booking_id)`**。
  `db.py` 的 `set_checkin()` 和 `webhook.py` 的 `/liff/checkin-toggle` 都用
  `upsert(..., on_conflict="session_id,booking_id")` 避免同一筆報名重複點名產生多筆
  `checkins` 資料，**這個 `on_conflict` 要能生效，資料庫端必須先有
  `UNIQUE (session_id, booking_id)` 的 constraint**，不是光改程式碼就夠。
  如果之後要在別的地方對 `checkins` 做 upsert，記得比照辦理，不要漏掉 `on_conflict`。
- 如果之後要在其他表新增 upsert 邏輯，先確認那張表的主鍵是不是你實際想拿來判斷「這是
  不是同一筆」的欄位（`line_pending_action` 的主鍵剛好就是自然鍵 `line_user_id`，可以
  直接 upsert 不用特別指定 `on_conflict`；`checkins`／`bookings` 這種主鍵是自增 id 或
  uuid 的表，只要沒指定 `on_conflict`，upsert 幾乎等於每次都 insert 一筆新的）。

## 目前還沒完整驗證過的部分（2026-09 拆分後）

- **候補遞補的完整路徑**：連續灌超過零打名額上限的報名，確認超過的部分正確標記候補，
  拿掉一筆正取後候補是否正確遞補、訊息中心是否正確入列遞補通知。
- **正取/候補演算法的多處重複實作**：目前 `booking_detail.py`、`webhook.py`、
  `dev_tools.py` 各自有一份幾乎一樣的邏輯，還沒抽成 `shared_logic.py` 共用函式，
  是目前風險最高的技術債（見上面業務規則第 2 點）。
- **`payment_method` 舊資料**：2026-09 修復前網站報名的付款方式是存在 `bookings.name`
  字串裡（例如 `王小明[付現]`），修復後這些舊資料的 `payment_method` 欄位仍是
  `NULL`，統計靠 `get_payment_method()` 的 fallback 邏輯撐著。如果之後想讓
  `payment_method` 欄位本身乾淨（例如要直接下 SQL 查這個欄位），需要另外跑一次
  一次性的資料回填，目前還沒做。
- **`app_develop.py`**：repo 根目錄還有一支跟修復前的 `app.py` 幾乎一模一樣的檔案
  （只差換行符號），不在這份文件列出的檔案結構裡，目前不確定是還在被某個部署環境用、
  還是單純的舊備份殘留。改 `app.py` 時記得這支檔案不會自動同步，如果確認沒在用，
  建議直接刪掉避免以後誤改。
