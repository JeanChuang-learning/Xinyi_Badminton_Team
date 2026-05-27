import streamlit as st
from supabase import create_client
from datetime import datetime, date, timedelta
import requests
import time
import json
from calendar import monthrange
import os

# ─────────────────────────
# config
# ─────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = "ScRBbUMhJUJHOn9abgQc9fw6EfUjEiDGxfmpOjQ5ThvQmOprUBbEYoscQzXsM/5RIVOhCskoUcUnd9fI39SpfPznW90I+sRZ8FQ65vNLk0dPfOX51KUNaAuuaeWeyjqJh/fZvh0L0R+UQotasKBOp/QdB04t89/1O/w1cDnyilFU="
LINE_GROUP_ID = "Cb7b632bd44eb63105a0fbabc8099cf75"

ADMIN_PASSWORD = "admin"
ROLE_MAP = {"會員": "member", "零打": "casual"}
ROLE_TO_ZH = {"member": "會員", "casual": "零打"}

# ─────────────────────────
# 頁面設定（只能出現一次）
# ─────────────────────────
st.set_page_config(page_title="信義羽球隊", page_icon="🏸", layout="centered")

# 確保這兩個變數對應到你後台 Secrets 的名稱
#def get_supabase_client():
#        st.stop()

@st.cache_resource
def init_supabase():
    # 這裡確保只有在程式啟動時執行一次
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

# 全域使用這個 supabase 物件
supabase = init_supabase()

# 加上快取，避免每次點擊按鈕都重新查詢場次
@st.cache_data(ttl=60)
def get_sessions():
    try:
        # 增加 debug 資訊，看看是否真的連線到資料庫
        res = supabase.table("sessions").select("*").execute()
        data = res.data
        
        # 除錯：在開發環境中看看抓到了什麼
        #st.write(f"DEBUG: 成功抓取到 {len(data)} 筆資料")
        
        return data if data else []
    except Exception as e:
        st.error(f"資料庫讀取異常: {e}")
        return []

def auto_generate_fixed_sessions(existing_sessions):
    return existing_sessions # 沒有新增就直接回傳原本的
    
# 1. 將資料抓取與處理放在最上方
@st.cache_data(ttl=60)
def get_processed_data():
    # 這裡直接呼叫抓取函數
    raw_sessions = get_sessions() 
    # 在這裡處理資料 (排序、篩選等)，確保回傳的是處理後的列表
    processed = sorted(raw_sessions, key=lambda x: x.get("date", ""))
    return processed
    
# 全域狀態初始化 (僅在第一次執行)
if "selected_sid" not in st.session_state:
    st.session_state["selected_sid"] = None

# 資料準備區 (確保在渲染 UI 前，所有變數都已準備好)
all_sessions = get_processed_data()
session_map = {s["id"]: s for s in all_sessions if s.get("id")}




# ─────────────────────────
# helpers
# ─────────────────────────

WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]                    
def user_label(s):
    date_str  = s.get("date", "未知日期")
    label_str = s.get("label", "")
    start     = s.get("start_time", "")[:5]   # 只取 HH:MM，去掉秒數
    end       = s.get("end_time", "")[:5]
    base      = f"{date_str} ｜ {label_str} ｜ {start}-{end}"
    if s.get("note") and "[會員限定]" in s.get("note", ""):
        base += " 👑"
    if s.get("cancelled"):
        base += f" ❌（{s.get('cancel_reason', '')}）"
    elif s.get("locked"):
        base += " 🔒關閉"
    return base

# ─────────────────────────
# 權限檢查函式 (請移至檔案前方)
# ─────────────────────────
def check_is_admin():
    return st.session_state.get("is_admin", False)

def get_announcement():
    if os.path.exists("announcement.txt"):
        with open("announcement.txt", "r", encoding="utf-8") as f:
            return f.read()
    return "歡迎來到信義羽球隊！"
    
# ─────────────────────────
# LINE 通知
# ─────────────────────────
def send_line(msg_text):
    if not LINE_GROUP_ID or not LINE_CHANNEL_ACCESS_TOKEN:
        return False
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            },
            data=json.dumps({
                "to": LINE_GROUP_ID,
                "messages": [{"type": "text", "text": msg_text}],
            }),
        )
        return response.status_code == 200
    except Exception as e:
        print(f"LINE 發送失敗: {e}")
        return False

# ─────────────────────────
# Supabase layer
# ─────────────────────────
# 將原來的匯入移除，直接在函式內部建立

# 加上快取，避免每次點擊按鈕都重新查詢報名清單
@st.cache_data(ttl=30)
def get_bookings(session_id):
    try:
        res = supabase.table("bookings").select("*").eq("session_id", session_id).execute()
        return res.data or []
    except Exception as e:
        st.error(f"讀取失敗：{e}")
        return []

def get_db_admin_line_list():
    try:
        res = supabase.table("sessions").select("*").eq("id", "_admin_line_config").execute()
        if res.data:
            return json.loads(res.data[0].get("note", "{}"))
    except Exception:
        pass
    return {"隊長": "小明", "副隊長": "小華"}

def save_db_admin_line_list(config_dict):
    try:
        json_str = json.dumps(config_dict, ensure_ascii=False)
        res = supabase.table("sessions").select("id").eq("id", "_admin_line_config").execute()
        if res.data:
            supabase.table("sessions").update({"note": json_str}).eq("id", "_admin_line_config").execute()
        else:
            supabase.table("sessions").insert({
                "id": "_admin_line_config", "date": "1970-01-01",
                "start_time": "00:00", "end_time": "00:00",
                "label": "CONFIG", "note": json_str,
                "total_quota": 0, "cancelled": True,
            }).execute()
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

def get_bookings(session_id):
    try:
        res = supabase.table("bookings").select("*").eq("session_id", session_id).execute()
        return res.data or []
    except Exception as e:
        st.error(f"讀取失敗：{e}")
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
        st.error(f"寫入失敗：{e}")
        st.stop()

def update_booking_data(booking_id, new_count, new_name=None, status="active"):
    payload = {"count": new_count, "status": status}
    if new_name:
        payload["name"] = new_name
    supabase.table("bookings").update(payload).eq("id", booking_id).execute()

def cancel_booking(booking_id, session_id):
    """刪除報名，並自動通知候補第一位"""
    supabase.table("bookings").delete().eq("id", booking_id).execute()
    # 檢查候補
    waitlist = supabase.table("bookings") \
        .select("*").eq("session_id", session_id).eq("status", "waitlist") \
        .order("created_at").execute().data
    if waitlist:
        next_p = waitlist[0]
        supabase.table("bookings").update({"status": "confirmed"}).eq("id", next_p["id"]).execute()
        send_line(f"🏸【遞補通知】恭喜「{next_p['name']}」遞補成功！請準時出席。")

def update_session(session_id, payload):
    supabase.table("sessions").update(payload).eq("id", session_id).execute()



def check_and_notify_waitlist(sid, quota, old_waitlist_ids, session_label_info):
    time.sleep(0.3)
    updated = [b for b in get_bookings(sid) if b["status"] == "active"]
    total = 0
    for ub in updated:
        cnt = int(ub["count"])
        if ub["id"] in old_waitlist_ids and total + cnt <= quota:
            if "_💬" in ub["name"]:
                try:
                    u_line = ub["name"].split("_💬")[1].split("_🔄")[0]
                    u_clean = ub["name"].split("_🔑")[0]
                    if u_line.strip():
                        send_line(f"📢【遞補成功】@{u_line}（{u_clean}）已遞補為正取！{session_label_info}")
                except Exception:
                    pass
        total += cnt
        
# ─────────────────────────
# 檢查與發送通知函式 (定義必須放在最上方)
# ─────────────────────────
def check_and_notify(new_sessions):
    current_week = date.today().strftime("%Y-%W") 
    last_notified_file = "last_notify.txt"
    
    if not os.path.exists(last_notified_file):
        with open(last_notified_file, "w") as f: f.write("0")
    
    with open(last_notified_file, "r") as f:
        last_week = f.read()
    
    if last_week != current_week:
        # 準備要發送的訊息
        msg = "🏸【信義羽球隊】本週更新場次通知：\n" + "\n".join([f"{s['date']} {s['label']}" for s in new_sessions])
        send_line(msg)
        # 更新記錄
        with open(last_notified_file, "w") as f: f.write(current_week)

# ─────────────────────────
# 載入資料（只做一次）
# ─────────────────────────
raw_sessions = get_sessions()
all_sessions = auto_generate_fixed_sessions(raw_sessions)
admin_line_config = get_db_admin_line_list()

# ─────────────────────────
# sessions mapping（修正版：避免重複覆蓋）
# ─────────────────────────
# 建立 mapping
unique_map = {s.get("id"): s for s in all_sessions if s.get("id")}
session_map = {k: v for k, v in sorted(unique_map.items(), key=lambda x: (x[1]["date"], x[1]["start_time"]))}
keys = list(session_map.keys())

# 定義 valid_keys (篩選器)
today = date.today()
start_date = today - timedelta(days=7)
end_date = today + timedelta(days=7)
valid_keys = [k for k in keys if start_date <= datetime.strptime(session_map[k]["date"], "%Y-%m-%d").date() <= end_date]

# 初始化 session_state
if "selected_sid" not in st.session_state or st.session_state["selected_sid"] not in session_map:
    st.session_state["selected_sid"] = valid_keys[0] if valid_keys else None
    
for s in all_sessions:
    sid = s.get("id")
    if sid and sid != "_admin_line_config":
        unique_map[sid] = s

sessions_sorted = sorted(
    unique_map.values(),
    key=lambda s: (s["date"], s["start_time"])
)

session_map = {s["id"]: s for s in sessions_sorted}
keys = list(session_map.keys())

# ─────────────────────────
# 2. 第二段邏輯：檢查與發送通知 (放入這裡)
# ─────────────────────────
# 我們先篩選出範圍內的場次，再透過 check_and_notify 檢查是否已發過
start_date = date.today() - timedelta(days=7)
end_date = date.today() + timedelta(days=7)
new_sessions_for_notify = [s for s in all_sessions if start_date <= datetime.strptime(s["date"], "%Y-%m-%d").date() <= end_date]

# 檢查是否需要發送通知
check_and_notify(new_sessions_for_notify)

# ==========================================
# 1. 資料處理區 (放在最上方，確保變數一定會被定義)
# ==========================================
raw_sessions = get_sessions()
all_sessions = auto_generate_fixed_sessions(raw_sessions)

# 建立 mapping 與排序
session_map = {s["id"]: s for s in all_sessions if s.get("id")}
keys = sorted(session_map.keys(), key=lambda k: (session_map[k]["date"], session_map[k]["start_time"]))

# 篩選有效場次 (valid_keys)
today = date.today()
start_date = today - timedelta(days=7)
end_date = today + timedelta(days=7)
valid_keys = [k for k in keys if start_date <= datetime.strptime(session_map[k]["date"], "%Y-%m-%d").date() <= end_date]

# 建立月份選單結構 (months)
months = {}
for k in valid_keys:
    mk = session_map[k]["date"][:7] # YYYY-MM
    months.setdefault(mk, []).append(k)

# 初始化 session_state
if "selected_sid" not in st.session_state or st.session_state["selected_sid"] not in session_map:
    st.session_state["selected_sid"] = valid_keys[0] if valid_keys else None

# ==========================================
# 2. UI 渲染區 (所有 st.xxx 放在後面)
# ==========================================
st.title("🏸 信義羽球隊")

# 公告功能區塊 (顯示區)、確保每次讀取都是最新的
def get_announcement():
    if os.path.exists("announcement.txt"):
        with open("announcement.txt", "r", encoding="utf-8") as f:
            return f.read()
    return "歡迎來到信義羽球隊！"
    
# 使用 st.info 醒目顯示
st.info(f"📢 **最新公告：**\n\n{get_announcement()}")

# 2. 詳情區 (只有當 session_state 有值時才顯示)
if "selected_sid" in st.session_state and st.session_state["selected_sid"]:
    sid = st.session_state["selected_sid"]
    if sid in session_map:
        selected_session = session_map[sid]
        st.success(f"✔ 已選：{selected_session['date']} {selected_session.get('label', '')} {selected_session['start_time']}")
    else:
        st.session_state["selected_sid"] = None
else:
    # 這裡一定要有縮排內容，不能只有一個 else:
    st.info("請點選上方的日期按鈕以查看該場次詳情。")
    
# 3. 管理員編輯區 (只有管理員會看到)
if check_is_admin(): # 請確保這裡是你判斷管理員的函式
    with st.expander("⚙️ 管理員公告編輯"):
        new_text = st.text_area("編輯公告內容：", value=get_announcement(), height=100)
        if st.button("發布更新"):
            with open("announcement.txt", "w", encoding="utf-8") as f:
                f.write(new_text)
            st.success("公告已更新！")
            st.rerun()

#st.markdown("#### 🔥 **會員熱烈招生中！歡迎加入我們的行列！**")
#st.markdown("<small>🎫 零打卡買十送一熱銷中，如有需要請洽管理員。</small>", unsafe_allow_html=True)

# 4. 分隔線 (將公告與場次分開)
st.divider()

for k in keys:
    mk = session_map[k]["date"][:7] # 格式為 YYYY-MM
    months.setdefault(mk, []).append(k)
month_list = list(months.items())



if st.session_state.get("is_admin"):
    st.success("🔐 管理員模式")

# ─────────────────────────
# 場次選單（已優化：採用收納式設計，確保唯一性）
# ─────────────────────────
if not keys:
    st.info("💡 目前暫無場次。")
    st.stop()

# 刪除原本的指定邏輯，改成這樣：
if "selected_sid" not in st.session_state or st.session_state["selected_sid"] not in session_map:
    st.info("請從上方選單選擇一個場次以查看詳情。")
    st.stop() # 暫停執行下方的渲染（就不會顯示「已選：...」那一行了）

WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]

# ─────────────────────────
# 場次選單（已優化：採用收納式設計，確保唯一性）
# ─────────────────────────
#st.markdown("### 📅 請選擇場次")

# 2. 重新計算月份 (使用篩選後的 valid_keys)
for k in valid_keys:
    mk = session_map[k]["date"][:7]  # YYYY-MM
    months.setdefault(mk, []).append(k)

# 確保篩選後的 valid_keys 與 months 都已定義 (請放在渲染前)
if not months:
    st.info("💡 目前暫無未來的場次。")
else:
    # --- 1. 選單渲染區 (移到最外面，不受選取狀態影響) ---
    st.subheader("📅 請選擇場次")
    # 這裡放置你原本產生按鈕的迴圈
    for month_str, month_keys in months.items():
        year = month_str.split('-')[0]
        month = month_str.split('-')[1]
        
        is_expanded = (month_keys == list(months.values())[0])
        
        with st.expander(f"📅 {year} 年 {month} 月", expanded=is_expanded):
            cols = st.columns(4) 
            for idx, sid in enumerate(month_keys):
                s = session_map[sid]
                
                # --- 1. 在這裡加入狀態判斷邏輯 ---
                d_obj = datetime.strptime(s['date'], "%Y-%m-%d")
                weekday_str = WEEKDAY_TW[d_obj.weekday()]
                
                # 這裡設定開放日期（例如：距離當天 7 天內才開放）
                is_cancelled = s.get("cancelled")
                is_locked = s.get("locked")
                # 確保這裡的判斷邏輯符合你的需求
                is_opened = date.today() >= (d_obj.date() - timedelta(days=7)) 
                
                # 計算報名人數 (假設你有 get_bookings 函式)
                current_s_bookings = [b for b in get_bookings(sid) if b.get("status") == "active"]
                total_count = sum(int(b.get("count", 0)) for b in current_s_bookings)
                quota = s.get("total_quota", 20)
                
                # 判斷圖示
                if is_cancelled: status_icon = "❌"
                elif is_locked: status_icon = "🔒"
                elif not is_opened: status_icon = "⏳"
                elif total_count >= quota: status_icon = "🔴"
                else: status_icon = "🟢"
                
                # --- 2. 組裝新的 btn_label ---
                btn_label = f"{status_icon} {s['date'].split('-')[2]}日 ({weekday_str}) {s['start_time'][:5]}"
                
                # 點擊後的行為：
                if cols[idx % 4].button(btn_label, key=f"btn_sid_{sid}"):
                    st.session_state["selected_sid"] = sid
                    st.rerun()
            st.divider() # 畫一條線區隔上下

        # 2. 詳情區 (只有當 session_state 有值時才顯示)
        if "selected_sid" in st.session_state and st.session_state["selected_sid"]:
            sid = st.session_state["selected_sid"]
            if sid in session_map:
                selected_session = session_map[sid]
                st.success(f"✔ 已選：{selected_session['date']} {selected_session.get('label', '')} {selected_session['start_time']}")
                # 在這裡顯示報名表單...
            else:
                # 如果儲存的 sid 不見了，重置它
                st.session_state["selected_sid"] = None
        else:
            # 這就是使用者剛進來或重整頁面時，你會看到的提示
            st.info("請點選上方的日期按鈕以查看該場次詳情。")
                

# ─────────────────────────
# 場次狀態說明列
# ─────────────────────────
st.markdown("""
<div style="display: flex; gap: 10px; font-size: 12px; color: #888; margin-bottom: 5px;">
    <span>🟢 正常開放</span>
    <span>🔴 額滿-零打排候補</span>
    <span>⏳ 未開放</span>
    <span>❌ 已取消</span>
    <span>🔒 會員限定</span>
</div>
""", unsafe_allow_html=True)


st.divider()

# ─────────────────────────
# 修正後的統計邏輯
# ─────────────────────────
# 使用 keys (所有已排序的場次 ID) 來取代原本錯誤的變數
booking_counts_map = {}
for sid in keys:
    bks = get_bookings(sid)
    active = [b for b in bks if b["status"] == "active"]
    booking_counts_map[sid] = sum(int(b["count"]) for b in active)

params = st.query_params
if "sid" in params:
    # 直接更新 session_state，Streamlit 會自動觸發 rerun
    st.session_state["selected_sid"] = params["sid"]   

# 已選場次顯示
selected_s = session_map[st.session_state["selected_sid"]]
sel_date   = selected_s["date"]
sel_wd     = WEEKDAY_TW[datetime.strptime(sel_date, "%Y-%m-%d").weekday()]
sel_label  = selected_s.get("label", "")
sel_start  = selected_s.get("start_time", "")[:5]
sel_end    = selected_s.get("end_time", "")[:5]
cancelled_tag = " ❌ 已取消" if selected_s.get("cancelled") else ""

# 1. 先確認過濾後的清單 (valid_keys) 是否有值
if not valid_keys:
    st.warning("目前沒有可顯示的場次。")
    st.session_state["selected_sid"] = None
else:
    # 2. 如果沒有選擇，或者舊的選擇已經不在這次的過濾清單中，才重新指派
    if "selected_sid" not in st.session_state or st.session_state["selected_sid"] not in valid_keys:
        # 只從 valid_keys (也就是 5/20~6/3 之間) 取第一個
        st.session_state["selected_sid"] = valid_keys[0]

# ─────────────────────────
# 只在使用者有明確選擇時才顯示「已選」區塊
# ─────────────────────────
if st.session_state.get("selected_sid"):
    # 確保選到的 sid 在目前的 session_map 中以防報錯
    if st.session_state["selected_sid"] in session_map:
        selected_session = session_map[st.session_state["selected_sid"]]
        
        # 這裡修正了 'None' 的問題：確保 label 有值，沒有的話顯示空字串
        label_text = selected_session.get("label") or ""
        
        st.success(f"✔ 已選：{selected_session['date']} {label_text} {selected_session['start_time']}")
    
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

sid     = st.session_state["selected_sid"]
session = session_map[sid]

# ─────────────────────────
# 場次內容
# ─────────────────────────
bookings = get_bookings(sid)
active   = [b for b in bookings if b["status"] == "active"]

today      = date.today()
s_date     = datetime.strptime(session["date"], "%Y-%m-%d").date()
open_date  = s_date - timedelta(days=7)
is_opened  = today >= open_date
is_member_only = "[會員限定]" in (session.get("note") or "")

quota = session.get("total_quota", 20)
total_member_count = 0
total_casual_count = 0
current_total      = 0
waitlist_count     = 0
list_to_show       = []
old_waitlist_ids   = set()

for b in active:
    b_count    = int(b["count"])
    raw_name   = b["name"]
    display_name = raw_name
    pwd_hidden = line_name_hidden = ""
    modify_count = 0

    if "_🔑" in raw_name:
        parts = raw_name.split("_🔑")
        display_name = parts[0]
        if "_💬" in parts[1]:
            sub = parts[1].split("_💬")
            pwd_hidden = sub[0]
            tail = sub[1].split("_🔄")
            line_name_hidden = tail[0]
            modify_count = int(tail[1]) if len(tail) > 1 and tail[1].isdigit() else 0

    if b["role"] == "member":
        total_member_count += b_count
        is_waitlist = False
        current_total += b_count
    else:
        if current_total >= quota:
            is_waitlist = True
            waitlist_count += b_count
            old_waitlist_ids.add(b["id"])
        elif current_total + b_count > quota:
            is_waitlist = "partial"
            total_casual_count += quota - current_total
            waitlist_count     += current_total + b_count - quota
            current_total       = quota
            old_waitlist_ids.add(b["id"])
        else:
            is_waitlist = False
            current_total      += b_count
            total_casual_count += b_count

    list_to_show.append({
        "data": b, "is_waitlist": is_waitlist,
        "clean_name": display_name, "pwd": pwd_hidden,
        "line_name": line_name_hidden, "modify_count": modify_count,
    })

# 儀表板
st.markdown("### 📊 本日場次人數摘要")
m1, m2, m3, m4 = st.columns(4)
m1.metric("正取總人數",      f"{current_total} / {quota} 人")
m2.metric("會員人數",        f"{total_member_count} 人")
m3.metric("零打人數（正取）", f"{total_casual_count} 人")
m4.metric("候補人數",        f"🔴 {waitlist_count} 人" if waitlist_count else "0 人")

if st.session_state.get("is_admin"):
    with st.container(border=True):
        st.markdown("🔧 **管理員：動態調整本場名額**")
        new_quota = st.number_input("人數上限", 1, 200, int(quota), key=f"adjust_quota_{sid}")
        if st.button("確認修改上限"):
            update_session(sid, {"total_quota": int(new_quota)})
            st.success(f"已調整為 {new_quota} 人")
            st.rerun()

# 狀態攔截
if session.get("cancelled"):
    st.warning(f"⚠ 此場次已取消。原因：{session.get('cancel_reason', '無')}")
    st.stop()
if session.get("locked"):
    st.error("❌ 此場次已關閉")
    st.stop()
if not is_opened and not st.session_state.get("is_admin"):
    st.warning(f"⏳ 尚未開放報名（將於 {open_date} 開放）")
    st.stop()

if current_total >= quota:
    st.error("🚨 正取名額已滿！名額已滿時僅開放會員候補，零打暫停。")
elif is_member_only:
    st.warning("👑 本場次為會員限定場次")

# ─────────────────────────
# 報名表單
# ─────────────────────────
st.divider()
st.markdown("### ✍️ 我要報名")
st.info("💡 名額已滿會進入候補，填寫 LINE 名字可收到遞補通知。")

col1, col2, col3 = st.columns([2, 1, 1])
with col1: name_input     = st.text_input("球友名字", key=f"name_{sid}")
with col2: role           = ROLE_MAP[st.selectbox("身分", ["會員", "零打"], key=f"role_{sid}")]
with col3: count          = st.number_input("人數", 1, 10, 1, key=f"count_{sid}")
col4, col5 = st.columns(2)
with col4: password_input = st.text_input("取消/修改暗號（4位數字）", type="password", max_chars=4, key=f"pwd_{sid}")
with col5: line_name_input= st.text_input("LINE 名字（想收候補通知必填）", key=f"line_{sid}")

if st.button("確認報名", type="primary"):
    if not name_input.strip():
        st.error("請輸入名字")
    elif not password_input.strip() or not password_input.isdigit():
        st.error("請設定4位數字暗號")
    elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
        st.error("本場為會員限定，零打暫不開放。")
    elif current_total >= quota and role == "casual" and not st.session_state.get("is_admin"):
        st.error("名額已滿，零打暫停登記。")
    else:
        add_booking_compatible(sid, name_input.strip(), role, int(count), password_input.strip(), line_name_input.strip())
        st.success("報名成功！")
        st.rerun()

# ─────────────────────────
# 名單
# ─────────────────────────
st.subheader("👥 現有報名名單")
if not list_to_show:
    st.caption("目前尚無人報名")

for item in list_to_show:
    b       = item["data"]
    wl      = item["is_waitlist"]
    c_name  = item["clean_name"]
    zh_role = ROLE_TO_ZH.get(b["role"], b["role"])

    if b["role"] == "member":
        status_tag = "🟢 正取"
    elif wl == True:
        status_tag = "⏳ 候補"
    elif wl == "partial":
        status_tag = "⚠️ 部分候補"
    else:
        status_tag = "🟢 正取"

    modify_tag = " (已改)" if b["role"] == "casual" and item["modify_count"] > 0 else ""

    col1, col2 = st.columns([4, 2])
    with col1:
        st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role} ｜ {status_tag}{modify_tag}")
    with col2:
        with st.expander("⚙️ 修改/取消"):
            if st.session_state.get("is_admin"):
                st.warning("⚡ 管理員模式")
                adm_new_count = st.number_input("調整人數（0＝刪除）", 0, 20, int(b["count"]), key=f"adm_cnt_{b['id']}")
                if st.button("管理員確認修改", key=f"adm_btn_{b['id']}"):
                    if adm_new_count == 0:
                        cancel_booking(b["id"], b["session_id"])
                        st.success("已刪除")
                    else:
                        update_booking_data(b["id"], int(adm_new_count))
                        st.success(f"已調整為 {adm_new_count} 人")
                    check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                    st.rerun()
            else:
                if current_total >= quota:
                    st.warning("名額已滿，如需調整請聯絡管理員。")
                input_pwd    = st.text_input("請輸入密碼", type="password", key=f"pwd_verify_{b['id']}")
                if b["role"] == "casual":
                    st.caption(f"零打限改1次（已改：{item['modify_count']} 次）")
                else:
                    st.caption("會員可無限次調整人數。")
                user_new_count = st.number_input("新的人數（0＝取消）", 0, 10, int(b["count"]), key=f"user_cnt_{b['id']}")
                if st.button("確認提交修改", key=f"user_btn_{b['id']}"):
                    if input_pwd != item["pwd"]:
                        st.error("密碼錯誤！")
                    elif b["role"] == "casual" and item["modify_count"] >= 1 and user_new_count != 0:
                        st.error("零打限修改1次！")
                    else:
                        if user_new_count == 0:
                            cancel_booking(b["id"], b["session_id"])
                            st.success("已取消報名！")
                        else:
                            new_mod = item["modify_count"] + 1 if b["role"] == "casual" else item["modify_count"]
                            new_composite = f"{c_name}_🔑{item['pwd']}_💬{item['line_name']}_🔄{new_mod}"
                            update_booking_data(b["id"], int(user_new_count), new_name=new_composite)
                            st.success(f"已更新為 {user_new_count} 人")
                        check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}")
                        st.rerun()

# ─────────────────────────
# 聯絡窗口
# ─────────────────────────
st.divider()
with st.container():
    st.markdown("### 📞 聯絡窗口")
    if admin_line_config:
        line_accounts = list(set(admin_line_config.values()))
        cols = st.columns(min(len(line_accounts), 3))
        for idx, line_name in enumerate(line_accounts):
            with cols[idx % len(cols)]:
                st.info(f"💬 **LINE ID**\n\n`{line_name}`")
    else:
        st.caption("目前暫無設定聯絡人。")
    st.markdown("> 💡 歡迎友誼賽交流 🏸，團體報名人數較多請直接聯絡窗口。")

# ─────────────────────────
# 管理員後台
# ─────────────────────────
st.divider()
    
with st.expander("🔒 管理與後台登入"):
    if st.session_state.get("is_admin"):
        st.markdown("### ⚙️ 管理員選單")
        if st.button("🔓 登出管理員模式", type="secondary"):
            st.session_state["is_admin"] = False
            st.rerun()
        st.divider()

        # 聯絡人名單
        st.subheader("📱 維護聯絡人名單")
        with st.container(border=True):
            if admin_line_config:
                st.markdown("**現有聯絡人：**")
                for k_id, lname in list(admin_line_config.items()):
                    c1, c2 = st.columns([4, 1])
                    c1.text(f"💬 {lname}")
                    if c2.button("刪除", key=f"del_admin_{k_id}"):
                        del admin_line_config[k_id]
                        if save_db_admin_line_list(admin_line_config):
                            st.success("已刪除")
                            st.rerun()
            else:
                st.info("名單為空。")
            st.divider()
            new_line_name = st.text_input("新增 LINE 帳號", key="new_line_name")
            if st.button("確認新增聯絡人"):
                if not new_line_name.strip():
                    st.error("請輸入 LINE 帳號")
                else:
                    admin_line_config[f"admin_{int(time.time()*1000)}"] = new_line_name.strip()
                    if save_db_admin_line_list(admin_line_config):
                        st.success("新增成功！")
                        st.rerun()

        st.divider()

        # 取消場次
        st.subheader("❌ 取消場次")
        with st.form("cancel_session_form", clear_on_submit=True):
            cancel_target = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="cancel_sel")
            reason        = st.text_input("原因")
            if st.form_submit_button("確認取消"):
                current_note = session_map[cancel_target].get("note") or ""
                update_session(cancel_target, {
                    "cancelled": True, "cancel_reason": reason,
                    "note": current_note.replace("[已恢復場次]", "").strip(),
                })
                send_line(f"⚠️【信義羽球隊】{session_map[cancel_target]['date']} 場次已取消。原因：{reason}")
                st.success("已取消")
                time.sleep(0.5)
                st.rerun()

        # 恢復場次
        st.subheader("🔄 恢復場次")
        cancelled_list = [s for s in sessions_sorted if s.get("cancelled")]
        restore_map    = {s["id"]: s for s in cancelled_list}
        if restore_map:
            restore_target = st.selectbox("選擇要恢復的場次", list(restore_map.keys()), format_func=lambda x: user_label(restore_map[x]), key="restore_target")
            if st.button("確認恢復場次"):
                current_note = restore_map[restore_target].get("note") or ""
                new_note = current_note if "[已恢復場次]" in current_note else f"{current_note} [已恢復場次]".strip()
                update_session(restore_target, {"cancelled": False, "cancel_reason": "", "note": new_note})
                send_line(f"🟢【信義羽球隊】{restore_map[restore_target]['date']} 場次已恢復，開放報名！")
                st.success("已恢復！")
                st.rerun()
        else:
            st.caption("目前沒有已取消的場次")

        st.divider()

        # 新增臨時場次
        st.subheader("➕ 加開場次")
        with st.form("add_session_form"):
            r1c1, r1c2, r1c3 = st.columns([2, 1, 1])
            with r1c1: new_date  = st.date_input("日期", min_value=date.today())
            with r1c2: start_time = st.selectbox("開始", ["06:00","08:00","10:00","12:00","14:00","16:00","18:00","20:00"], index=6)
            with r1c3: end_time   = st.selectbox("結束", ["08:00","10:00","12:00","14:00","16:00","18:00","20:00","22:00"], index=7)
            r2c1, r2c2, r2c3 = st.columns([2, 1, 1])
            with r2c1: new_label   = st.text_input("場地", value="信義羽球館")
            with r2c2: total_quota = st.number_input("名額上限", 1, 100, 20)
            with r2c3: casual_limit= st.number_input("零打上限", 0, 100, 15)
            r3c1, r3c2 = st.columns(2)
            with r3c1: new_note   = st.text_input("備註")
            with r3c2: access_type= st.radio("開放規則", ["所有球友", "限會員"], horizontal=True)

            if st.form_submit_button("🔥 確認加開", use_container_width=True):
                if not new_label.strip():
                    st.error("請填寫場地名稱")
                else:
                    final_note = ("[會員限定] " if access_type == "限會員" else "") + new_note.strip()
                    new_id = f"{new_date}_{start_time}_{int(time.time())}"
                    try:
                        supabase.table("sessions").insert({
                            "id": new_id, "date": str(new_date),
                            "start_time": start_time, "end_time": end_time,
                            "label": new_label.strip(), "note": final_note,
                            "total_quota": int(total_quota),
                            "casual_limit": int(casual_limit),
                            "cancelled": False, "cancel_reason": "", "locked": False,
                        }).execute()
                        send_line(f"📢【信義羽球隊】加開場次！{new_date} {start_time}-{end_time}，快上系統報名！")
                        st.success(f"已加開：{new_date} {start_time}-{end_time}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"寫入失敗：{e}")

        st.divider()

        # 修改場次規則
        st.subheader("⚙️ 修改場次規則")
        with st.form("rule_session_form"):
            target_sid  = st.selectbox("場次", keys, format_func=lambda x: user_label(session_map[x]), key="rule_sel")
            rule_type   = st.radio("開放規則", ["所有球友", "僅限會員"], horizontal=True)
            reason_note = st.text_input("備註說明")
            if st.form_submit_button("確認更新"):
                current_note = session_map[target_sid].get("note") or ""
                clean_note = current_note.replace("[會員限定]", "").replace("[已恢復場次]", "").strip()
                tag = "[會員限定]" if rule_type == "僅限會員" else ""
                update_session(target_sid, {"note": f"{tag} {reason_note}".strip()})
                st.success("已更新")
                time.sleep(0.5)
                st.rerun()

    else:
        st.markdown("⚠️ **管理員登入**")
        pwd = st.text_input("密碼", type="password")
        if pwd == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.rerun()
        elif pwd:
            st.error("密碼錯誤")
