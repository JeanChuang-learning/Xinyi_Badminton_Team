# 信義羽球隊報名系統

給羽球隊使用的線上報名系統，整合 LINE Bot、LIFF 報名頁與管理員後台。

## 系統架構

| 服務 | 說明 | 部署平台 | 技術 |
|---|---|---|---|
| `app.py` | 管理員後台 + 公開報名網站 | Streamlit Cloud | Python + Streamlit |
| `webhook.py` | LINE Bot webhook + LIFF 報名頁 + 排程任務 | Render | Python + FastAPI |

兩邊共用同一個 **Supabase**（PostgreSQL）資料庫。

## 檔案結構

```
app.py                    # 主入口：載入資料 + 依序呼叫各畫面
config.py                  # 常數 / secrets / 頁面設定
db.py                      # Supabase 讀寫（sessions / bookings / checkins / 系統設定）
notify.py                  # LINE 推播 + msg_queue 佇列
logic.py                   # 業務規則（正取候補、自動場次產生…）
shared_logic.py             # app.py 與 webhook.py 共用的開放時間規則
webhook.py                 # LINE webhook + LIFF + 排程任務
supabase_client.py          # Supabase client 初始化（app.py / db.py 等共用）
views/
  session_picker.py          # 場次選擇格
  dev_tools.py                # 管理員測試工具
  contact_footer.py           # 聯絡窗口 + 管理員登入按鈕
  admin_panel.py               # 管理員登入外殼 + 5 個分頁
  admin_messages.py            # 分頁：📨 訊息中心
  admin_contacts.py            # 分頁：📱 聯絡人
  admin_sessions.py            # 分頁：🗓️ 場次管理
  admin_settings.py            # 分頁：🛠 系統參數
  admin_history.py             # 分頁：📊 歷史紀錄
  booking_detail.py            # 選定場次後的報名/名單/點名畫面
```

## 核心業務規則

- **身分判斷**：只有在會員 LINE 群組裡的人才算會員，其餘一律當零打。
- **正取/候補**：會員優先無條件佔額；零打依報名時間排序，依剩餘名額（總名額與零打上限取
  較小值）逐筆判斷正取/候補，同一筆報名可能部分正取、部分候補。
- **零打開放時間**：依場次星期幾提前 2～7 天開放（規則見 `shared_logic.py`），會員不受限。
- **通知規則**：開放/剩餘名額通知只發零打群；名單、報名按鈕發零打＋會員兩群。

## 環境變數 / Secrets

### Streamlit Cloud（`.streamlit/secrets.toml` 或後台 Secrets 設定）

```toml
LINE_CHANNEL_ACCESS_TOKEN = "..."
LINE_GROUP_ID_CASUAL = "..."
LINE_GROUP_ID_MEMBER = "..."
LINE_GROUP_ID_ADMIN = "..."
ADMIN_PASSWORD = "..."
```

### Render（Environment Variables）

```
LINE_CHANNEL_ACCESS_TOKEN
LINE_CHANNEL_SECRET
SUPABASE_URL
SUPABASE_KEY
LINE_GROUP_ID_CASUAL
LINE_GROUP_ID_MEMBER
LIFF_ID                （選填）
LINE_LOGIN_CHANNEL_ID   （選填）
CRON_SECRET             （排程任務端點用）
```

⚠️ **兩個平台的變數是完全獨立的兩套系統，且 key 名稱都已統一為全大寫**
（`LINE_GROUP_ID_CASUAL` / `LINE_GROUP_ID_MEMBER` / `LINE_GROUP_ID_ADMIN`）。
改一邊不會同步到另一邊，兩邊都要各自維護。

## requirements.txt 與 requirements_webhook.txt

兩份分開維護：`requirements.txt` 給 Streamlit Cloud（`app.py`）用（Streamlit Cloud
固定只認這個檔名）；`requirements_webhook.txt` 給 Render（`webhook.py`）用（Render 的
build command 需指定 `pip install -r requirements_webhook.txt`）。不要合併成一份，
避免兩邊互相拖進用不到的重套件、增加版本衝突風險。

## 本機開發

```bash
# app.py（Streamlit）
pip install -r requirements.txt
streamlit run app.py

# webhook.py（FastAPI）
pip install -r requirements_webhook.txt
uvicorn webhook:app --reload
```

本機測試需要自行建立 `.streamlit/secrets.toml`（`app.py` 用）以及對應的環境變數
（`webhook.py` 用），內容同上方「環境變數 / Secrets」章節，值換成測試用的假資料或
自己的測試 LINE 群組。

## 部署

1. **先部署 `webhook.py`（Render）**：改動範圍通常較小，部署後看 Render 的 log，
   確認沒有 `ModuleNotFoundError` 或其他 import 錯誤。
2. **確認穩定後再部署 `app.py`（Streamlit Cloud）**：部署後到 Manage app 看 log
   確認沒有紅字 Traceback。
3. **手動走一次全流程**：開場次 → 會員報名 → 零打報名到額滿觸發候補 → 修改/取消一筆 →
   確認候補是否正確遞補 → 登入管理員後台，5 個分頁都點開看一次 → 點名並儲存。

`shared_logic.py` 必須跟 `app.py`、`webhook.py` 放在同一個 repo 根目錄，且兩邊部署設定
的 root directory 都要能讀到整個 repo，否則 import 會失敗。

## 已知的框架層級小雷

- 管理員登入瞬間畫面結構變化較大，偶爾會跳出 Streamlit 的「Bad message format」，
  這是 Streamlit 框架本身的已知行為，跳出後重新整理頁面即可，不影響資料正確性。
- `logic.py` 的 `check_and_release_casual_limit()` 有一行無條件的 debug `print`，
  只要有人操作網站就會讓 log 多一行，屬於正常現象。

## Changelog（2026-09）

- 把原本 2000 多行的單一 `app.py` 拆分成 `config.py` / `db.py` / `notify.py` /
  `logic.py` / `views/*.py`，`webhook.py` 保留但抽出跟 `app.py` 重複的開放時間規則
  到 `shared_logic.py`，兩邊改為共用同一份實作。
- 修復 `check_and_release_casual_limit()` 引用未定義常數 `TOTAL_QUOTA_WEEKDAY` /
  `CASUAL_QUOTA_WEEKDAY` 導致的 `NameError`（曾造成全站無法開啟）。
- 統一 `LINE_GROUP_ID_CASUAL` / `LINE_GROUP_ID_MEMBER` / `LINE_GROUP_ID_ADMIN`
  在 Streamlit Cloud 與 Render 兩邊的命名大小寫（原本 Streamlit 端是首字大寫、
  Render 端是全大寫，對不起來導致零打群通知的 `target_ids` 為空）。
- 移除未使用的 `from calendar import monthrange` 死 import。

## 待驗證項目

- 候補遞補演算法的完整路徑（連續超過零打上限報名 → 候補標記 → 取消正取後遞補 →
  訊息中心正確入列遞補通知）尚未完整測試過。
