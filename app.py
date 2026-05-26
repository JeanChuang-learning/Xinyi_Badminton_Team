import streamlit as st
import json
import os
from datetime import datetime, date, timedelta
import pytz

# ── 設定 ──────────────────────────────────────────
ADMIN_PASSWORD = "admin1234"   # ← 改成你要的管理員密碼
QUOTA = 12                     # ← 預設正取名額
DATA_FILE = "data.json"
TZ = pytz.timezone("Asia/Taipei")

# 固定場次：weekday(0=週一,4=週五,6=週日)
FIXED_SESSIONS = [
    {"weekday": 0, "start": "19:00", "end": "22:00", "label": "週一晚上"},
    {"weekday": 4, "start": "19:00", "end": "22:00", "label": "週五晚上"},
    {"weekday": 6, "start": "07:00", "end": "11:00", "label": "週日早上"},
]
WEEKS_AHEAD = 3
WEEKDAY_TW = ["一", "二", "三", "四", "五", "六", "日"]
# ─────────────────────────────────────────────────

st.set_page_config(page_title="羽球團報名", page_icon="🏸", layout="centered")
st.markdown("""
<style>
    .main > div { padding-top: 1.5rem; }
    .block-container { max-width: 620px; padding: 1rem 1.5rem; }
    h1 { font-size: 1.6rem !important; }
    .stButton > button { border-radius: 10px; font-weight: 600; height: 2.6rem; }
    .member-row {
        display: flex; align-items: center;
        padding: 6px 12px; border-radius: 8px;
        margin-bottom: 4px; font-size: 15px;
    }
    .confirmed { background: #E1F5EE; color: #0F6E56; }
    .waitlist  { background: #FAEEDA; color: #854F0B; }
    .cancelled-banner {
        background: #FCEBEB; color: #A32D2D;
        border-radius: 10px; padding: 12px 16px;
        font-weight: 600; text-align: center; margin-bottom: 1rem;
    }
    .extra-badge {
        display: inline-block; background: #534AB7; color: white;
        font-size: 11px; font-weight: 600; padding: 2px 8px;
        border-radius: 20px; margin-left: 6px; vertical-align: middle;
    }
</style>
""", unsafe_allow_html=True)

# ── 資料讀寫 ──────────────────────────────────────
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sessions": {}, "quota": QUOTA, "extra_sessions": []}
    d = json.load(open(DATA_FILE, "r", encoding="utf-8"))
    if "extra_sessions" not in d:
        d["extra_sessions"] = []
    return d

def save_data(data):
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ── 場次產生 ──────────────────────────────────────
def fmt_date(d):
    return f"{d.month}/{d.day}（週{WEEKDAY_TW[d.weekday()]}）"

def generate_all_sessions(data):
    today = date.today()
    sessions = []

    # 固定場次
    for week in range(WEEKS_AHEAD + 1):
        for cfg in FIXED_SESSIONS:
            days_ahead = (cfg["weekday"] - today.weekday()) % 7
            d = today + timedelta(days=days_ahead + week * 7)
            if week == 0 and days_ahead == 0:
                now = datetime.now(TZ)
                end_h, end_m = map(int, cfg["end"].split(":"))
                end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
                if now > end_dt:
                    continue
            if d < today:
                continue
            full_key = f"{d.isoformat()}_{cfg['start']}_fixed"
            sessions.append({
                "full_key": full_key,
                "date": d,
                "label": cfg["label"],
                "start": cfg["start"],
                "end": cfg["end"],
                "is_extra": False,
            })

    # 臨時場次
    for ex in data.get("extra_sessions", []):
        d = date.fromisoformat(ex["date"])
        if d < today:
            continue
        full_key = ex["key"]
        sessions.append({
            "full_key": full_key,
            "date": d,
            "label": ex["label"],
            "start": ex["start"],
            "end": ex["end"],
            "is_extra": True,
            "extra_key": ex["key"],
        })

    # 去重 + 排序
    seen, result = set(), []
    for s in sorted(sessions, key=lambda x: (x["date"], x["start"])):
        if s["full_key"] not in seen:
            seen.add(s["full_key"])
            result.append(s)
    return result

# ── 載入 ──────────────────────────────────────────
data = load_data()
upcoming = generate_all_sessions(data)

# ── 標題 ──────────────────────────────────────────
st.title("🏸 羽球團報名")

if not upcoming:
    st.info("目前沒有即將到來的場次")
    st.stop()

# ── 場次選單 ──────────────────────────────────────
def session_display(s):
    tag = "🔸 " if s["is_extra"] else ""
    return f"{tag}{fmt_date(s['date'])} {s['label']} {s['start']}–{s['end']}"

session_map = {session_display(s): s for s in upcoming}
selected_label = st.selectbox("選擇場次", list(session_map.keys()))
session = session_map[selected_label]
sid = session["full_key"]

# 初始化場次資料
if sid not in data["sessions"]:
    data["sessions"][sid] = {
        "members": [], "quota": data.get("quota", QUOTA),
        "cancelled": False, "cancel_reason": "",
    }
    save_data(data)

sdata     = data["sessions"][sid]
members   = sdata["members"]
quota     = sdata["quota"]
cancelled = sdata.get("cancelled", False)
confirmed = members[:quota]
waitlist  = members[quota:]
spots_left = max(0, quota - len(confirmed))

extra_label = ' <span class="extra-badge">臨時</span>' if session["is_extra"] else ""
st.caption(f"名額：{len(confirmed)}/{quota}　｜　剩餘正取：{spots_left} 位")
st.divider()

# ── 取消公告 ──────────────────────────────────────
if cancelled:
    reason = sdata.get("cancel_reason", "")
    st.markdown(
        f'<div class="cancelled-banner">❌ 本場次已取消'
        f'{"<br><span style=\'font-weight:400;font-size:14px\'>" + reason + "</span>" if reason else ""}'
        f'</div>', unsafe_allow_html=True)
    st.stop()

# ── 報名 ──────────────────────────────────────────
col1, col2 = st.columns([3, 1])
with col1:
    name_input = st.text_input("名字", placeholder="輸入名字來報名", label_visibility="collapsed")
with col2:
    signup_btn = st.button("報名", use_container_width=True, type="primary")

if signup_btn:
    name = name_input.strip()
    if not name:
        st.warning("請輸入名字")
    elif name in members:
        idx = members.index(name)
        if idx < quota:
            st.info(f"「{name}」已在正取（第 {idx+1} 位）")
        else:
            st.info(f"「{name}」已在備取（備取第 {idx - quota + 1} 位）")
    else:
        members.append(name)
        sdata["members"] = members
        save_data(data)
        pos = len(members)
        if pos <= quota:
            st.success(f"✅ 報名成功！{name} 是正取第 {pos} 位")
        else:
            st.warning(f"⏳ 正取已滿，{name} 列為備取第 {pos - quota} 位")
        st.rerun()

with st.expander("取消報名"):
    col3, col4 = st.columns([3, 1])
    with col3:
        cancel_name = st.text_input("取消的名字", placeholder="輸入名字", label_visibility="collapsed", key="cancel")
    with col4:
        cancel_btn = st.button("取消", use_container_width=True)
    if cancel_btn:
        name = cancel_name.strip()
        if not name:
            st.warning("請輸入名字")
        elif name not in members:
            st.error(f"找不到「{name}」")
        else:
            idx = members.index(name)
            was_confirmed = idx < quota
            members.remove(name)
            sdata["members"] = members
            save_data(data)
            if was_confirmed and len(members) >= quota:
                promoted = members[quota - 1]
                st.success(f"已取消「{name}」\n🎉「{promoted}」由備取晉升為正取！")
            else:
                st.success(f"已取消「{name}」的報名")
            st.rerun()

st.divider()

# ── 名單 ──────────────────────────────────────────
st.subheader(f"✅ 正取（{len(confirmed)}/{quota} 人）")
if confirmed:
    for i, name in enumerate(confirmed, 1):
        st.markdown(f'<div class="member-row confirmed"><span style="opacity:.5;margin-right:10px;font-size:13px">{i}</span>{name}</div>', unsafe_allow_html=True)
else:
    st.caption("尚無人報名")

st.markdown("<br>", unsafe_allow_html=True)
st.subheader(f"⏳ 備取（{len(waitlist)} 人）")
if waitlist:
    for i, name in enumerate(waitlist, 1):
        st.markdown(f'<div class="member-row waitlist"><span style="opacity:.5;margin-right:10px;font-size:13px">{i}</span>{name}</div>', unsafe_allow_html=True)
else:
    st.caption("目前無備取")

st.divider()

# ── 管理員 ────────────────────────────────────────
with st.expander("🔒 管理員"):
    pwd = st.text_input("密碼", type="password", key="admin_pwd")
    if pwd == ADMIN_PASSWORD:
        st.success("已進入管理員模式")

        tab1, tab2, tab3 = st.tabs(["📋 本場次", "➕ 新增臨時場次", "🗂️ 管理臨時場次"])

        # ── Tab1：本場次操作 ──
        with tab1:
            st.markdown("**取消／恢復場次**")
            if not cancelled:
                cancel_reason = st.text_input("取消原因（選填）", key="cancel_reason")
                if st.button("❌ 取消本場次", type="secondary"):
                    sdata["cancelled"] = True
                    sdata["cancel_reason"] = cancel_reason
                    save_data(data)
                    st.success("已取消本場次")
                    st.rerun()
            else:
                if st.button("↩️ 恢復本場次"):
                    sdata["cancelled"] = False
                    sdata["cancel_reason"] = ""
                    save_data(data)
                    st.success("已恢復")
                    st.rerun()

            st.divider()
            st.markdown("**名額**")
            new_quota = st.number_input("正取名額", min_value=1, max_value=100, value=quota)
            if st.button("更新名額"):
                sdata["quota"] = new_quota
                save_data(data)
                st.success(f"名額已更新為 {new_quota}")
                st.rerun()

            st.divider()
            st.markdown("**成員**")
            if members:
                remove_name = st.selectbox("移除成員", ["— 選擇 —"] + members)
                if st.button("移除") and remove_name != "— 選擇 —":
                    members.remove(remove_name)
                    sdata["members"] = members
                    save_data(data)
                    st.success(f"已移除「{remove_name}」")
                    st.rerun()
            else:
                st.caption("名單為空")
            if st.button("🗑️ 清空本場次名單"):
                sdata["members"] = []
                save_data(data)
                st.success("已清空")
                st.rerun()

        # ── Tab2：新增臨時場次 ──
        with tab2:
            st.markdown("**新增臨時場次**")
            ex_label = st.text_input("場次名稱", placeholder="例：羽球聯誼賽、補打場次")
            ex_date  = st.date_input("日期", min_value=date.today())
            col_a, col_b = st.columns(2)
            with col_a:
                ex_start = st.time_input("開始時間", value=datetime.strptime("19:00", "%H:%M").time())
            with col_b:
                ex_end   = st.time_input("結束時間", value=datetime.strptime("22:00", "%H:%M").time())
            ex_quota = st.number_input("名額", min_value=1, max_value=100, value=QUOTA)

            if st.button("✅ 建立臨時場次", type="primary"):
                if not ex_label.strip():
                    st.error("請填寫場次名稱")
                elif ex_end <= ex_start:
                    st.error("結束時間必須晚於開始時間")
                else:
                    start_str = ex_start.strftime("%H:%M")
                    end_str   = ex_end.strftime("%H:%M")
                    key = f"{ex_date.isoformat()}_{start_str}_extra_{int(datetime.now().timestamp())}"
                    new_ex = {
                        "key": key,
                        "date": ex_date.isoformat(),
                        "label": ex_label.strip(),
                        "start": start_str,
                        "end": end_str,
                    }
                    data["extra_sessions"].append(new_ex)
                    data["sessions"][key] = {
                        "members": [], "quota": ex_quota,
                        "cancelled": False, "cancel_reason": "",
                    }
                    save_data(data)
                    st.success(f"已新增「{ex_label.strip()}」{fmt_date(ex_date)} {start_str}–{end_str}")
                    st.rerun()

        # ── Tab3：管理臨時場次 ──
        with tab3:
            extra_list = data.get("extra_sessions", [])
            if not extra_list:
                st.caption("目前沒有臨時場次")
            else:
                for ex in sorted(extra_list, key=lambda x: (x["date"], x["start"])):
                    d = date.fromisoformat(ex["date"])
                    col_x, col_y = st.columns([4, 1])
                    with col_x:
                        st.markdown(f"🔸 **{ex['label']}** — {fmt_date(d)} {ex['start']}–{ex['end']}")
                    with col_y:
                        if st.button("刪除", key=f"del_{ex['key']}"):
                            data["extra_sessions"] = [e for e in extra_list if e["key"] != ex["key"]]
                            if ex["key"] in data["sessions"]:
                                del data["sessions"][ex["key"]]
                            save_data(data)
                            st.success("已刪除")
                            st.rerun()

    elif pwd:
        st.error("密碼錯誤")
