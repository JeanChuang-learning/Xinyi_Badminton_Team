"""
排程腳本：讀取 message_queue 中 pending 的訊息，逐筆發送到 LINE，
成功標記 sent，失敗標記 failed。
由 GitHub Actions 每 10 分鐘執行一次。
"""
import os
import json
import requests
from datetime import datetime, timezone
from supabase import create_client

SUPABASE_URL              = os.environ["SUPABASE_URL"]
SUPABASE_KEY              = os.environ["SUPABASE_KEY"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_line_message(target_id: str, message: str) -> bool:
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        data=json.dumps({"to": target_id, "messages": [{"type": "text", "text": message}]}),
    )
    print(f"  發送給 {target_id}：{r.status_code} | {r.text}")
    return r.status_code == 200

def process_queue():
    # 讀取所有 pending 訊息，依建立時間排序
    rows = (
        supabase.table("message_queue")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
    )

    if not rows:
        print("message_queue 無待發訊息")
        return

    print(f"共 {len(rows)} 筆待發訊息")
    sent_at = datetime.now(timezone.utc).isoformat()

    for row in rows:
        rid     = row["id"]
        target  = row["target_id"]
        message = row["message"]

        try:
            success = send_line_message(target, message)
            new_status = "sent" if success else "failed"
        except Exception as e:
            print(f"  發送例外：{e}")
            new_status = "failed"

        supabase.table("message_queue").update(
            {"status": new_status, "sent_at": sent_at if new_status == "sent" else None}
        ).eq("id", rid).execute()

if __name__ == "__main__":
    process_queue()
