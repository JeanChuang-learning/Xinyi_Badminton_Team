import streamlit as st
from supabase_client import supabase
from datetime import datetime, date, timedelta
import requests  
import time
import json

# ─── 1. 在這裡定義你剛剛在英文網頁複製的超長 Token ───
LINE_CHANNEL_ACCESS_TOKEN = "ScRBbUMhJUJHOn9abgQc9fw6EfUjEiDGxfmpOjQ5ThvQmOprUBbEYoscQzXsM/5RIVOhCskoUcUnd9fI39SpfPznW90I+sRZ8FQ65vNLk0dPfOX51KUNaAuuaeWyjqJh/fZvh0L0R+UQotasKBOp/QdB04t89/1O/w1cDnyilFU="

# ─── 2. 在這裡定義你們群組的 ID (等一下抓到再貼過來，現在先留空) ───
LINE_GROUP_ID = "Cxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" 

def send_line_message_v2(msg_text):
    """
    這是自動發送 LINE 訊息到群組的專用功能
    """
    # 防呆：如果還沒貼上 Token 或群組 ID，就不執行發送
    if LINE_CHANNEL_ACCESS_TOKEN == "把你在LINE_Developers複製的超長Token貼進這裡" or not LINE_GROUP_ID:
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": LINE_GROUP_ID,
        "messages": [{"type": "text", "text": msg_text}]
    }
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        return response.status_code == 200
    except Exception as e:
        print(f"LINE 發送異常: {e}")
        return False
# ─────────────────────────
# config & Line 設定
# ─────────────────────────
ADMIN_PASSWORD = "admin"
ROLE_MAP = {"會員": "member", "零打": "casual"}

LINE_NOTIFY_TOKEN = "" 

FIXED_RULES = [
    {"weekday": 0, "start_time": "19:00", "end_time": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start_time": "19:00", "end_time": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start_time": "07:00", "end_time": "11:00", "label": "週日早上"},
]

# ─────────────────────────
# helpers
# ─────────────────────────
def user_label(s):
    # 基礎格式
    base = f"{s['date']}｜{s['label']}｜{s['start_time']}-{s['end_time']}"
    
    # 1. 處理「會員限定」標籤 (優先級最高，直接顯示)
    # 這樣即便它是未來的場次或是被鎖定的場次，也會優先標記為會員限定
    if s.get("note") and "[會員限定]" in s.get("note"):
        base = f"{base} 👑 會員限定"
    
    # 2. 處理「取消」狀況 (僅當不是會員限定時才顯示取消)
    elif s.get("cancelled"):
        if s.get("id") and not s["id"].endswith("_fixed"):
            base = f"{base} ❌已取消"
        else:
            base = f"{base} ❌不開放"
            
    # 3. 處理「尚未開放」的時間判斷
    else:
        try:
            session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
            open_date = session_date - timedelta(days=7)
            if date.today() < open_date:
                base = f"{base} ⏳ 尚未開放"
        except ValueError:
            pass

    # 4. 處理鎖定狀態 (若已有上述標籤，則在後面補上)
    if s.get("locked"):
        base = f"{base} 🔒關閉"
        
    return base


def send__message(message):
    if not _NOTIFY_TOKEN:
        return
    url = "https://notify-api..me/api/notify"
    headers = {"Authorization": f"Bearer {_NOTIFY_TOKEN}"}
    data = {"message": message}
    try:
        requests.post(url, headers=headers, data=data)
    except Exception as e:
        print(f" 通知發送失敗: {e}")

# ─────────────────────────
# Supabase layer (含動態聯絡人名單讀寫)
# ─────────────────────────
def get_sessions():
    try:
        res = supabase.table("sessions").select("*").execute()
        return res.data or []
    except Exception as e:
        st.exception(e)
        return []


# 💡 從資料庫讀取聯絡人 LINE 名單
def get_db_admin_line_list():
    try:
        res = supabase.table("sessions").select("*").eq("id", "_admin_line_config").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    # 預設初始值
    return {"隊長": "小明", "副隊長": "小華"}


# 💡 將聯絡人 LINE 名單寫回資料庫
def save_db_admin_line_list(config_dict):
    try:
        json_str = json.dumps(config_dict, ensure_ascii=False)
        res = supabase.table("sessions").select("id").eq("id", "_admin_line_config").execute()
        if res.data:
            supabase.table("sessions").update({"note": json_str}).eq("id", "_admin_line_config").execute()
        else:
            supabase.table("sessions").insert({
                "id": "_admin_line_config", "date": "1970-01-01", "start_time": "00:00", "end_time": "00:00",
                "label": "CONFIG", "note": json_str, "total_quota": 0, "cancelled": True
            }).execute()
        return True
    except Exception as e:
        st.error(f"儲存聯絡人名單失敗: {e}")
        return False

def get_bookings(session_id):
    try:
        res = (
            supabase.table("bookings")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
        return res.data or []
    except Exception as e:
        st.error(f"💥 讀取報名資料失敗：{e}")
        return []


def add_booking_compatible(session_id, name, role, count, password, line_name):
    composite_name = f"{name}_🔑{password}_💬{line_name}_🔄0"
    try:
        supabase.table("bookings").insert({
            "session_id": session_id,
            "name": composite_name,
            "role": role,
            "count": count,
            "status": "active",
        }).execute()
    except Exception as e:
        st.error(f"💥 寫入資料庫失敗：{e}")
        st.stop()


def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    payload = {"count": new_count, "status": status}
    if new_name:
        payload["name"] = new_name
    supabase.table("bookings").update(payload).eq("id", booking_id).execute()


def cancel_booking(booking_id, session_id):
    # 1. 執行刪除報名動作 (假設這是您原本的 DB 操作)
    supabase.table("bookings").delete().eq("id", booking_id).execute()
    
    # 2. 檢查該場次是否有候補球友
    # 假設候補名單是透過 "waitlist" 欄位或是特定的狀態排序取得
    waitlist = supabase.table("bookings")\
        .select("*")\
        .eq("session_id", session_id)\
        .eq("status", "waitlist")\
        .order("created_at")\
        .execute().data
    
    if waitlist:
        next_person = waitlist[0] # 取出最資深的第一位候補
        next_name = next_person.get("name")
        
        # 3. 發送 LINE 通知
        msg = f"🏸 【候補通知】\n有球友取消報名，候補名單中的「{next_name}」請確認是否可以參加！\n請至系統完成確認。"
        send_line_message(msg)
        
        # (選填) 如果您有自動遞補機制，可以在這裡順便更新該球友的 status 為 "confirmed"
        # supabase.table("bookings").update({"status": "confirmed"}).eq("id", next_person["id"]).execute()

def notify_next_waitlist_person(sid, session_label_info):
    # 1. 取得該場次的所有報名
    bookings = get_bookings(sid)
    active_bookings = [b for b in bookings if b["status"] == "active"]
    
    # 2. 依照報名時間 (created_at) 排序，確保公平性
    # 如果你的表格沒有 created_at，也可以用 id (Supabase 的 ID 通常是有序的)
    sorted_bookings = sorted(active_bookings, key=lambda x: x.get("created_at", x.get("id")))
    
    # 3. 計算目前正取人數
    quota = session_map[sid].get("total_quota", 20)
    current_count = 0
    
    next_person = None
    for b in sorted_bookings:
        b_count = int(b["count"])
        if current_count + b_count <= quota:
            current_count += b_count
        else:
            # 這筆報名就是候補第一位
            next_person = b
            break
            
    # 4. 如果找到了候補第一位，發送通知
    if next_person:
        # 解析 LINE 名稱 (根據你原本的命名格式)
        raw_name = next_person["name"]
        line_name = "球友" # 預設值
        if "_💬" in raw_name:
            line_name = raw_name.split("_💬")[1].split("_🔄")[0]
            
        msg = f"\n📢【候補通知】\n場次：{session_label_info}\n\n候補名單中的「{line_name}」您已遞補進入正取！請確認並準時出席。🏸"
        send_line_message(msg)

def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()


def auto_generate_fixed_sessions(existing_sessions):
    today = date.today()
    existing_keys = {s["id"] for s in existing_sessions if s.get("id")}
    has_new_inserted = False

    for i in range(36):
        check_date = today + timedelta(days=i)
        w = check_date.weekday()
        for rule in FIXED_RULES:
            if w == rule["weekday"]:
                session_id = f"{check_date.isoformat()}_{rule['start_time']}_fixed"
                if session_id not in existing_keys:
                    try:
                        supabase.table("sessions").insert({
                            "id": session_id,
                            "date": str(check_date),
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "label": rule["label"],
                            "note": "系統自動建立的固定場次",
                            "total_quota": 20,
                            "cancelled": False,
                            "cancel_reason": "",
                            "locked": False,
                        }).execute()
                        has_new_inserted = True
                    except Exception as e:
                        print(f"自動新增場次失敗: {e}")
    if has_new_inserted:
        return get_sessions()
    return existing_sessions


def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info):
    time.sleep(0.3)
    updated_bookings = get_bookings(sid)
    updated_active = [ub for ub in updated_bookings if ub["status"] == "active"]
    
    chk_total = 0
    for ub in updated_active:
        ub_count = int(ub["count"])
        if ub["id"] in old_waitlist_ids and (chk_total + ub_count <= quota):
            if "_💬" in ub["name"]:
                try:
                    parts = ub["name"].split("_🔑")
                    u_clean = parts[0]
                    sub_parts = parts[1].split("_💬")
                    sub_sub = sub_parts[1].split("_🔄")
                    u_line = sub_sub[0]
                    if u_line.strip():
                        send_line_message(f"\n📢【場次候補成功通知】\n@{u_line} ({u_clean})\n您申請的 {session_label_info} 已成功遞補為【正取】，期待您的出席！🏸")
                except Exception:
                    pass
        chk_total += ub_count

# ─────────────────────────
# UI 初始化
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸")
# 👑 球隊大標題
st.title("🏸 信義羽球隊")

# 📢 宣傳語（使用醒目的粗體字，搭配熱情點綴的 Emoji）
st.markdown("#### 🔥 **會員熱烈招生中！歡迎加入我們的行列！**")

# 加一條分隔線讓畫面更有層次感
st.divider()

if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# 💡 讀取目前資料庫儲存的聯絡人名單
admin_line_config = get_db_admin_line_list()

raw_sessions = get_sessions()
sessions = auto_generate_fixed_sessions(raw_sessions)
today = date.today()

start_bound = today - timedelta(days=3)
end_bound = today + timedelta(days=35)

filtered_sessions = []
for s in sessions:
    if not s.get("date") or s.get("id") == "_admin_line_config": continue
    try:
        session_date = datetime.strptime(s["date"], "%Y-%m-%d").date()
        if start_bound <= session_date <= end_bound:
            filtered_sessions.append(s)
    except ValueError: continue

sessions_sorted = sorted(filtered_sessions, key=lambda s: (s["date"], s["start_time"]))
session_map = {s["id"]: s for s in sessions_sorted if s.get("id")}

# ─────────────────────────
# 前端主功能區塊
# ─────────────────────────
if session_map:
    selected_id = st.selectbox("選擇場次", list(session_map.keys()), format_func=lambda x: user_label(session_map[x]))
    session = session_map[selected_id]
    sid = selected_id

    bookings = get_bookings(sid)
    active = [b for b in bookings if b["status"] == "active"]

    is_member_only = session.get("note") and "[會員限定]" in session.get("note")
    s_date = datetime.strptime(session["date"], "%Y-%m-%d").date()
    open_date = s_date - timedelta(days=7) 
    is_opened = today >= open_date

    quota = session.get("total_quota", 20)
    total_member_count = 0
    total_casual_count = 0  
    current_total = 0
    waitlist_count = 0
    list_to_show = []
    
    old_waitlist_ids = set()
    
    for b in active:
        b_count = int(b["count"])
        
        raw_name = b["name"]
        display_name = raw_name
        pwd_hidden = ""
        line_name_hidden = ""
        modify_count = 0
        
        if "_🔑" in raw_name:
            parts = raw_name.split("_🔑")
            display_name = parts[0]
            if "_💬" in parts[1]:
                sub_parts = parts[1].split("_💬")
                pwd_hidden = sub_parts[0]
                if "_🔄" in sub_parts[1]:
                    sub_sub = sub_parts[1].split("_🔄")
                    line_name_hidden = sub_sub[0]
                    modify_count = int(sub_sub[1]) if sub_sub[1].isdigit() else 0
                else:
                    line_name_hidden = sub_parts[1]

        if b["role"] == "member": 
            total_member_count += b_count
            
        if b["role"] == "member":
            is_waitlist = False
            current_total += b_count  
        else:
            if current_total >= quota:
                is_waitlist = True
                waitlist_count += b_count
                old_waitlist_ids.add(b["id"])
            elif current_total + b_count > quota:
                is_waitlist = "partial"
                casual_in_quota = quota - current_total
                total_casual_count += casual_in_quota
                
                waitlist_count += (current_total + b_count - quota)
                current_total = quota
                old_waitlist_ids.add(b["id"])
            else:
                is_waitlist = False
                current_total += b_count
                total_casual_count += b_count  
            
        list_to_show.append({
            "data": b, 
            "is_waitlist": is_waitlist, 
            "clean_name": display_name, 
            "pwd": pwd_hidden, 
            "line_name": line_name_hidden,
            "modify_count": modify_count
        })

    # 儀表板
    st.markdown("### 📊 本日場次人數摘要")
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("正取總人數", f"{current_total} / {quota} 人")
    with m2: st.metric("會員人數", f"{total_member_count} 人")
    with m3: st.metric("零打人數（正取）", f"{total_casual_count} 人") 
    with m4: st.metric("候補人數", f"🔴 {waitlist_count} 人" if waitlist_count > 0 else "0 人")

    # 管理員調整上限
    if st.session_state.get("is_admin"):
        with st.container(border=True):
            st.markdown("🔧 **管理員專區：動態調整本場名額**")
            new_quota = st.number_input("調整本場人數上限", min_value=1, max_value=200, value=int(quota), key=f"adjust_quota_{sid}")
            if st.button("確認修改上限"):
                update_session(sid, {"total_quota": int(new_quota)})
                st.success(f"已成功將人數上限調整為 {new_quota} 人！")
                st.rerun()

    # 狀態檢查
    if session.get("cancelled"):
        st.warning(f"⚠ 此場次已取消/不開放。原因：{session.get('cancel_reason', '無')}")
    elif session.get("locked"):
        st.error("❌ 此場次已關閉")
    elif not is_opened and not st.session_state.get("is_admin"):
        st.warning(f"⏳ 尚未開放報名（本場次將於 {open_date.strftime('%Y-%m-%d')} 開放報名）")
    else:
        if current_total >= quota:
            st.error("🚨 提示：目前正取名額已滿！系統已自動開啟【會員候補保護機制】，此時段僅限「會員」可登記，零打暫停登記。")
        elif is_member_only: 
            st.warning("👑 提示：本場次為【會員限定場次】")
        
        st.divider()
        st.markdown("### ✍️ 我要報名")
        
        st.info("💡 **候補備註**：名額已滿時會進入候補。如果您希望收到遞補成功通知，請留下您的 Line 名字，遞補成功時系統會於群組標記您！")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1: name_input = st.text_input("球友名字")
        with col2: role = ROLE_MAP[st.selectbox("身分", ["會員", "零打"])]
        with col3: count = st.number_input("人數", 1, 10, 1)
            
        col4, col5 = st.columns([2, 2])
        with col4: password_input = st.text_input("自訂取消/修改暗號 (4位數數字)", type="password", max_chars=4)
        with col5: line_name_input = st.text_input("Line 名字 (想收候補通知必填)", placeholder="請填寫Line群組內的名稱")

        if st.button("確認報名", type="primary"):
            if not name_input.strip(): 
                st.error("請輸入名字")
            elif not password_input.strip() or not password_input.isdigit(): 
                st.error("請設定4位數字的取消/修改暗號")
            elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
                st.error("⚠️ 本場次為會員限定場，零打暫不開放報名。")
            elif current_total >= quota and role == "casual" and not st.session_state.get("is_admin"):
                st.error("⚠️ 報名失敗：目前本場次正取名額已滿。依球隊規則，此時僅開放固定會員登記，零打球友請改選其他場次！")
            else:
                add_booking_compatible(sid, name_input.strip(), role, int(count), password_input.strip(), line_name_input.strip())
                st.success("報名成功！")
                st.rerun()

    # 顯示名單與修改區塊
    st.subheader("👥 現有報名名單")
    ROLE_TO_ZH = {"member": "會員", "casual": "零打"}

    if not list_to_show:
        st.caption("目前尚無人報名")
        
    for item in list_to_show:
        b = item["data"]
        wl = item["is_waitlist"]
        zh_role = ROLE_TO_ZH.get(b['role'], b['role'])
        c_name = item["clean_name"]
        
        if b['role'] == 'member':
            status_tag = "🟢" 
        else:
            if wl == True:
                status_tag = "⏳ 候補"
            elif wl == "partial":
                status_tag = "⚠️ 部分候補"
            else:
                status_tag = "🟢 正取"
            
        col1, col2 = st.columns([4, 2])
        with col1:
            modify_tag = f" (已改)" if b['role'] == 'casual' and item['modify_count'] > 0 else ""
            st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role} ｜ {status_tag}{modify_tag}")
            
        with col2:
            with st.popover("⚙️ 修改/取消", use_container_width=True):
                if st.session_state.get("is_admin"):
                    st.warning("⚡ 管理員模式：擁有最高修改權限")
                    adm_new_count = st.number_input("調整報名人數 (填 0 等於刪除)", 0, 20, int(b["count"]), key=f"adm_cnt_{b['id']}")
                    if st.button("管理員確認修改", key=f"adm_btn_{b['id']}"):
                        if adm_new_count == 0:
                            cancel_booking(b["id"])
                            st.success("已成功刪除該筆報名")
                        else:
                            update_booking_data(b["id"], int(adm_new_count))
                            st.success(f"已將人數調整為 {adm_new_count} 人")
                        
                        check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                        st.rerun()
                else:
                    if current_total >= quota:
                        st.warning("⚠️ 目前場次已滿額，若需追加人數或修改請直接通知管理員協助處理。")
                        
                    input_pwd = st.text_input("請輸入密碼", type="password", key=f"pwd_verify_{b['id']}")
                    
                    if b['role'] == 'casual':
                        st.caption(f"💡 零打限制修改 1 次 (您目前已修改: {item['modify_count']} 次)")
                    else:
                        st.caption("💡 固定會員可無限次自由微調人數。")
                        
                    user_new_count = st.number_input("請選擇新的人數 (填 0 等於取消報名)", 0, 10, int(b["count"]), key=f"user_cnt_{b['id']}")
                    
                    if st.button("確認提交修改", key=f"user_btn_{b['id']}"):
                        if input_pwd != item["pwd"]:
                            st.error("❌ 密碼錯誤，無法修改！")
                        elif b['role'] == 'casual' and item['modify_count'] >= 1 and user_new_count != 0:
                            st.error("❌ 修改失敗：零打身分限制僅能修改 1 次報名人數！(如需特殊協助請洽管理員)")
                        else:
                            if user_new_count == 0:
                                cancel_booking(b["id"])
                                st.success("已成功取消您的報名！")
                            else:
                                new_mod_count = item['modify_count'] + 1 if b['role'] == 'casual' else item['modify_count']
                                new_composite_name = f"{c_name}_🔑{item['pwd']}_💬{item['line_name']}_🔄{new_mod_count}"
                                update_booking_data(b["id"], int(user_new_count), new_name=new_composite_name)
                                st.success(f"修改成功！人數已更新為 {user_new_count} 人")
                            
                            # 無論是取消還是修改，統一呼叫這一個函式處理遞補通知
                            check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                            st.rerun()
else:
    st.info("💡 目前暫無可顯示之場次。")
st.divider()
# 💡 【聯絡窗口看板】
with st.container():
    st.markdown("### 📞 聯絡窗口")
    
    if admin_line_config:
        # 取得所有的 LINE 帳號（不重複）
        line_accounts = list(set(admin_line_config.values()))
        cols = st.columns(min(len(line_accounts), 3)) 
        
        for idx, line_name in enumerate(line_accounts):
            with cols[idx % len(cols)]:
                # ─── 徹底拿掉「名字」與「職稱」，只保留 LINE 帳號 ───
                st.info(f"💬 **LINE ID**\n\n`{line_name}`")
    else:
        st.caption("目前暫無設定聯絡人資訊。")
        
    # 溫馨備註
    st.markdown(
        """
        > 💡 **溫馨提醒**
        > * 歡迎友誼賽交流 🏸
        > * 若有團體因人數較多導致報名不易者，請直接與聯絡人聯絡。
        """
    )
# ─────────────────────────
# 管理員功能區塊
# ─────────────────────────
st.divider()
with st.expander("🔒 管理與後台登入"):
    if st.session_state.get("is_admin"):
        st.markdown("### ⚙️ 管理員選單")
        if st.button("🔓 登出管理員模式", type="secondary"):
            st.session_state["is_admin"] = False
            st.rerun()
        st.divider()

        # 💡 維護聯絡人名單
        st.subheader("📱 維護聯絡人名單")
        with st.container(border=True):
            st.caption("在這裡修改後，首頁頂部的「聯絡窗口」會即時更新。")
            
            if admin_line_config:
                st.markdown("**現有聯絡人 LINE 清單：**")
                for k_id, lname in list(admin_line_config.items()):
                    c1, c2 = st.columns([4, 1])
                    c1.text(f"💬 LINE ID：{lname}")
                    if c2.button("🗑️ 刪除", key=f"del_admin_{k_id}"):
                        del admin_line_config[k_id]
                        if save_db_admin_line_list(admin_line_config):
                            st.success(f"已刪除該聯絡資訊")
                            st.rerun()
            else:
                st.info("目前名單為空，請從下方新增。")
            
            st.divider()
            st.markdown("**➕ 新增聯絡人：**")
            # 只留下一個輸入框，純粹輸入 LINE 帳號
            new_line_name = st.text_input("請輸入幹部的 LINE 帳號", key="new_line_name")
            
            if st.button("確認儲存聯絡人資訊"):
                if not new_line_name.strip():
                    st.error("請輸入有效的 LINE 帳號")
                else:
                    # 使用時間戳記或隨機碼作為 Key，避免「幹部」名稱重複被覆蓋的問題
                    import time
                    unique_key = f"admin_{int(time.time()*1000)}"
                    admin_line_config[unique_key] = new_line_name.strip()
                    
                    if save_db_admin_line_list(admin_line_config):
                        st.success("成功新增聯絡人 LINE 帳號！")
                        st.rerun()
        st.divider()

        # 取消場次
        st.subheader("❌ 取消場次")
        if session_map:
            with st.form("cancel_session_form", clear_on_submit=True):
                cancel_target = st.selectbox("選擇要取消的場次", list(session_map.keys()), format_func=lambda x: user_label(session_map[x]))
                reason = st.text_input("原因")
                submit_cancel = st.form_submit_button("確認取消場次")
                if submit_cancel:
                    current_note = session_map[cancel_target].get("note") or ""
                    clean_note = current_note.replace("[已恢復場次]", "").strip()
                    update_session(cancel_target, {"cancelled": True, "cancel_reason": reason, "note": clean_note})
                    st.success("已成功取消該場次")
                    time.sleep(0.5)
                    st.rerun()

        # 恢復場次
        st.subheader("🔄 恢復場次")
        cancelled_sessions = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map = {s["id"]: s for s in cancelled_sessions}
        if restore_map:
            restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()), format_func=lambda x: user_label(restore_map[x]), key="restore_target")
            if st.button("確認恢復場次"):
                current_note = restore_map[restore_target].get("note") or ""
                new_note = current_note if "[已恢復場次]" in current_note else f"{current_note} [已恢復場次]".strip()
                update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": new_note})
                st.success("已成功恢復該場次！")
                st.rerun()

        # 新增臨時場次
        st.subheader("➕ 加開場次")

with st.form("add_session_form"):
    # 第一排：日期與時間並排
    row1_col1, row1_col2, row1_col3 = st.columns([2, 1, 1])
    with row1_col1:
        new_date = st.date_input("活動日期", min_value=date.today())        
    with row1_col2:
        start_time = st.selectbox(
            "開始時間", 
            ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"], 
            index=6  # 預設 18:00
        )
    with row1_col3:
        end_time = st.selectbox(
            "結束時間", 
            ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00", "22:00"], 
            index=7  # 預設 22:00
        )
        
    # 第二排：場地與人數限制並排
    row2_col1, row2_col2, row2_col3 = st.columns([2, 1, 1])
    with row2_col1:
        new_label = st.text_input("場地", placeholder="例如：信義羽球館-A場", value="信義羽球館")        
    with row2_col2:
        total_quota = st.number_input("名額上限", min_value=1, max_value=100, value=20)
    with row2_col3:
        # 新增的零打上限欄位
        casual_limit = st.number_input("零打上限", min_value=0, max_value=100, value=15)
    
    # 第三排：如果你原本有這兩個欄位（備註與權限），我也幫你補進來
    row3_col1, row3_col2 = st.columns([2, 2])
    with row3_col1:
        new_note = st.text_input("備註原因", placeholder="例如：本場零打名額有限")
    with row3_col2:
        access_type = st.radio("開放規則", ["所有球友皆可報名", "限會員報名（零打不可）"], horizontal=True)

    # ─── 統一使用這個表單送出按鈕 ───
    submit_new_session = st.form_submit_button("🔥 確認加開場次", use_container_width=True)
    
    if submit_new_session:
        if not new_label: 
            st.error("❌ 請填寫場次名稱")
        else:
            # 處理會員限定標籤
            final_note = new_note.strip()
            if access_type == "限會員報名（零打不可）": 
                final_note = f"[會員限定] {final_note}".strip()
            
            # 產生唯一的 ID
            import time
            new_id = f"{new_date}_{start_time}_{int(time.time())}"
            
            # 寫入 Supabase 資料庫 (變數名稱全部校正完畢)
            supabase.table("sessions").insert({
                "id": new_id, 
                "date": str(new_date), 
                "start_time": start_time, 
                "end_time": end_time,
                "label": new_label, 
                "note": final_note, 
                "total_quota": int(total_quota),
                "casual_limit": int(casual_limit), # 記得把零打上限也存進資料庫！
                "cancelled": False, 
                "cancel_reason": "", 
                "locked": False
            }).execute()

            # ─── 🎯 就是這裡！把 LINE 通知程式碼貼在下面 ───
            # 注意：因為我們最上面表單定義的變數是 new_date，所以訊息裡的 {date_str} 要改成 {new_date} 喔！
            send_line_message_v2(f"📢【信義羽球隊】{new_date} {start_time}-{end_time} 的場次已開，想打球的快上系統報名喔！")
            
            st.success(f"🎉 成功加開：{new_date} {start_time}-{end_time} 場次！")
            st.cache_data.clear() # 清除快取讓前端即時更新
            st.rerun()
                
        st.subheader("⚙️ 修改場次")
        if session_map:
            with st.form("rule_session_form"):
                target_sid = st.selectbox("選擇要設定的場次", list(session_map.keys()), format_func=lambda x: user_label(session_map[x]))
                rule_type = st.radio("開放規則", ["所有球友皆可報名", "僅限會員報名 ([會員限定])"], horizontal=True)
                reason_note = st.text_input("備註原因 (會顯示在場次資訊中)", placeholder="例如：因人數過多，本場改為會員限定")
                
                submit_rule = st.form_submit_button("確認更新")
                
                if submit_rule:
                    target_session = session_map[target_sid]
                    current_note = target_session.get("note") or ""
                    
                    # 清除舊標籤與舊的規則備註 (假設備註格式為 [規則]: 原因)
                    # 這裡簡單處理：移除 [會員限定] 與 [恢復開放]，並加上新規則
                    clean_note = current_note.replace("[會員限定]", "").replace("[已恢復場次]", "").strip()
                    
                    # 組建新的備註
                    new_rule_tag = "[會員限定]" if rule_type == "僅限會員報名 ([會員限定])" else ""
                    new_note = f"{new_rule_tag} {reason_note}".strip()
                    
                    update_session(target_sid, {"note": new_note})
                    st.success(f"已更新場次規則：{rule_type}")
                    time.sleep(0.5)
                    st.rerun()

        st.divider()
        # (以下保留原有的 取消場次 / 恢復場次 / 新增臨時場次 功能...)
    else:
        st.markdown("⚠️ **管理員功能登入**")
        pwd = st.text_input("請輸入管理員後台密碼", type="password")
        if pwd == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
        elif pwd: st.error("密碼錯誤")
