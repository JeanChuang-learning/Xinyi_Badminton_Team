"""
排程腳本：讀取 msg_queue 中 pending 的訊息，逐筆發送到 LINE（可能有多個目標群組），
成功標記 sent，遇到 429（配額用盡）標記 quota 並停止，其餘錯誤標記 error。
由 GitHub Actions 每 10 分鐘執行一次。

⚠️ 這張表 / 這些欄位名稱必須跟 app.py 裡的 MSG_QUEUE_TABLE / enqueue_msg() 完全一致，
   否則排程腳本讀不到網站寫入的訊息（本檔案先前用的是舊版 message_queue 表，已不相容）。
"""
import os
import json
from datetime import datetime, timezone
import requests
from supabase import create_client

SUPABASE_URL              = os.environ["SUPABASE_URL"]
SUPABASE_KEY              = os.environ["SUPABASE_KEY"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MSG_QUEUE_TABLE = "msg_queue"  # 需與 app.py 的 MSG_QUEUE_TABLE 保持一致


def send_line_direct(msg_text, target_ids):
    """
    對 target_ids 內每個群組各發一次。
    回傳 (result, detail)：result 為 'ok' / 'quota' / 'error'（邏輯對齊 app.py 的 send_line_direct），
    detail 是 LINE 實際回應內容，用來判斷卡住的到底是真的月配額用完還是別的錯誤。
    """
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return "error", "缺少 LINE_CHANNEL_ACCESS_TOKEN"

    got_quota = False
    got_error = False
    details = []

    for gid in target_ids:
        try:
            r = requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                },
                data=json.dumps({"to": gid, "messages": [{"type": "text", "text": msg_text}]}),
            )
            print(f"  發送給 {gid}：{r.status_code} | {r.text}")
            details.append(f"{gid}: HTTP {r.status_code} {r.text[:200]}")
            if r.status_code == 429:
                got_quota = True
            elif r.status_code != 200:
                got_error = True
        except Exception as e:
            print(f"  發送例外（{gid}）：{e}")
            details.append(f"{gid}: 例外 {e}")
            got_error = True

    detail_str = " ｜ ".join(details)
    if got_quota:
        return "quota", detail_str
    if got_error:
        return "error", detail_str
    return "ok", detail_str


def process_queue():
    # 讀取所有 pending 訊息，依建立時間排序
    rows = (
        supabase.table(MSG_QUEUE_TABLE)
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
    )

    if not rows:
        print(f"{MSG_QUEUE_TABLE} 無待發訊息")
        return

    print(f"共 {len(rows)} 筆待發訊息")
    sent = quota = error = 0

    for row in rows:
        rid = row["id"]
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        try:
            target_ids = json.loads(row.get("target_ids") or "[]")
        except Exception:
            target_ids = []

        if not target_ids:
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "error", "error": "target_ids 為空", "sent_at": now_str}
            ).eq("id", rid).execute()
            error += 1
            continue

        result, detail = send_line_direct(row["msg_text"], target_ids)

        if result == "ok":
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "sent", "sent_at": now_str, "error": None}
            ).eq("id", rid).execute()
            sent += 1
        elif result == "quota":
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "quota", "error": detail, "sent_at": now_str}
            ).eq("id", rid).execute()
            quota += 1
            print("配額用盡，停止本次執行")
            break  # 配額用盡後停止，避免打爆剩餘配額
        else:
            supabase.table(MSG_QUEUE_TABLE).update(
                {"status": "error", "error": detail, "sent_at": now_str}
            ).eq("id", rid).execute()
            error += 1

    print(f"完成：成功 {sent}，配額用盡 {quota}，失敗 {error}")


if __name__ == "__main__":
    process_queue()
