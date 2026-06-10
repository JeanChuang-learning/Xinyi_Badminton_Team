# 🏸 羽球團報名系統（Streamlit 版）

純 Python 寫的報名網站，部署到 Streamlit Cloud 免費使用。

---

## 開始前先改這三個設定（app.py 最上方）

```python
ADMIN_PASSWORD   # 管理員密碼
QUOTA                     # 正取名額
RESET_WEEKDAYS = [1, 3]        # 1=週二, 3=週四 自動重置
```

---

## 本機執行

```bash
pip install -r requirements.txt
streamlit run app.py
```

瀏覽器開啟 http://localhost:8501

---

## 部署到 Streamlit Cloud（免費）

1. 把這個資料夾上傳到 GitHub（新建一個 repo）
2. 前往 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 登入
3. 點「New app」→ 選你的 repo → Main file: `app.py`
4. 點 Deploy，完成！

網址格式：`https://am24logbujoqctvut7bqmk.streamlit.app/`

---

## 功能說明

| 功能 | 說明 |
|------|------|
| 輸入名字報名 | 超過名額自動進備取 |
| 取消報名 | 備取自動晉升 |
| 每週自動重置 | 到了週二/四自動清空 |
| 管理員後台 | 改名額、移除成員、手動清空 |

---

## 注意事項

- **資料存在 `supabase`**，Streamlit Cloud 重新部署後會清空
