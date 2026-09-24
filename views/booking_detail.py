"""
views/booking_detail.py —— 選定某一場次後的畫面：
- 場次人數摘要儀表板
- 報名表單（含正取/候補單輪演算法）
- 報名名單（一般使用者：修改/取消；管理員：另含點名）

這個檔案刻意不再往下拆，因為儀表板 / 報名表單 / 名單三個區塊
都共用同一組「正取/候補」計算結果（list_to_show 等），
硬拆開只會讓三個檔案互丟一堆參數，風險比維持在一起更高。
"""

import time
from datetime import datetime, timedelta

import streamlit as st

from config import Quota_7, Limit_7, ROLE_MAP, ROLE_TO_ZH, WEEKDAY_TW, web_url
from db import (
    get_bookings, get_checkins, set_checkin,
    add_booking_compatible, update_session, update_booking_data,
    cancel_booking, promote_waitlist, get_system_settings,
)
from logic import get_venue, check_and_notify_waitlist
from shared_logic import (
    is_casual_open_for_signup, get_session_open_date, is_member_only_session,
    get_payment_method, PAY_LABELS, PAY_CODE_BY_ZH, compute_allocation,
)


def render(session_map, today_date):
    # ─────────────────────────
    # 未選場次則停止
    # ─────────────────────────
    if not st.session_state["selected_sid"]:
        st.info("☝️ 請點選上方場次來查看詳情與報名")
        st.stop()

    sid     = st.session_state["selected_sid"]
    session = session_map[sid]

    # ─────────────────────────
    # 場次內容
    # ─────────────────────────
    bookings = get_bookings(sid)
    active   = [b for b in bookings if b["status"] == "active"]

    s_date         = datetime.strptime(session["date"], "%Y-%m-%d").date()
    casual_open    = is_casual_open_for_signup(s_date)   # 零打開放：依星期規則
    member_open    = s_date <= today_date + timedelta(days=14)  # 會員：兩週內皆可報名
    is_member_only = is_member_only_session(session)
    quota          = session.get("total_quota", Quota_7)
    casual_quota   = session.get("casual_quota", Limit_7)  # 零打名額上限

    total_member_count = total_casual_count = current_total = waitlist_count = 0
    list_to_show = []
    old_waitlist_ids = set()
    old_confirmed_map = {}   # {報名 id: 異動前已正取人數}，遞補通知只在人數增加時才發

    # 先計算名單資訊（解析姓名等），再依「會員優先」重新判斷正取/候補
    parsed = []
    for b in active:
        b_count      = int(b["count"])
        raw_name     = b["name"]
        display_name = raw_name
        pwd_hidden   = ""
        modify_count = 0

        if "_🔑" in raw_name:
            parts        = raw_name.split("_🔑")
            display_name = parts[0]
            after_key    = parts[1]
            if "_🔄" in after_key:
                tail         = after_key.split("_🔄")
                pwd_hidden   = tail[0]
                modify_count = int(tail[1]) if len(tail) > 1 and tail[1].isdigit() else 0
            else:
                pwd_hidden = after_key

        parsed.append({
            "data": b, "count": b_count,
            "clean_name": display_name, "pwd": pwd_hidden,
            "modify_count": modify_count,
        })

    # 單輪：依報名時間順序逐筆判斷正取/候補（邏輯統一在 shared_logic.compute_allocation，
    # webhook.py／dev_tools.py 也是呼叫同一份，避免各自維護容易失同步）
    # 會員永遠正取（無上限），但零打的名額是即時依序計算
    # 這樣才能保護在會員後報名的零打不會被後來才來的會員擠掉
    allocated, _summary = compute_allocation(session, [p["data"] for p in parsed])
    for p, alloc in zip(parsed, allocated):
        b = p["data"]
        is_waitlist = alloc["is_waitlist"]
        if b["role"] == "member":
            total_member_count += p["count"]
            current_total      += p["count"]
        else:
            if is_waitlist is True:
                waitlist_count += p["count"]
                old_waitlist_ids.add(b["id"])
                old_confirmed_map[b["id"]] = 0
            elif is_waitlist == "partial":
                confirmed_part      = alloc["confirmed_count"]
                waitlist_part       = alloc["waitlist_count"]
                total_casual_count += confirmed_part
                waitlist_count     += waitlist_part
                current_total      += confirmed_part
                old_waitlist_ids.add(b["id"])
                old_confirmed_map[b["id"]] = confirmed_part
                p["partial_confirmed"] = confirmed_part
                p["partial_waitlist"]  = waitlist_part
            else:
                total_casual_count += p["count"]
                current_total      += p["count"]

        list_to_show.append({
            "data": b, "is_waitlist": is_waitlist,
            "clean_name": p["clean_name"], "pwd": p["pwd"],
            "modify_count": p["modify_count"],
            "partial_confirmed": p.get("partial_confirmed", 0),
            "partial_waitlist":  p.get("partial_waitlist", 0),
            "pay_label": PAY_LABELS.get(get_payment_method(b), ""),
        })

    # 儀表板
    st.markdown(f"### 📊 場次人數摘要 : {session['date']}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("正取總人數",   f"{current_total} / {quota}")
    m2.metric("會員",         f"{total_member_count} 人")
    m3.metric("零打（正取）", f"{total_casual_count} / {casual_quota}")
    m4.metric("候補",         f"🔴 {waitlist_count}" if waitlist_count else "0")

    if st.session_state.get("is_admin"):
        with st.container(border=True):
            st.markdown("🔧 **調整本場名額**")
            col_q1, col_q2 = st.columns(2)
            with col_q1:
                new_quota = st.number_input("總人數上限", min_value=1, max_value=200, value=int(quota), key=f"adjust_quota_{sid}")
            with col_q2:
                new_casual_quota = st.number_input("零打名額上限", min_value=0, max_value=100, value=int(casual_quota), key=f"adjust_casual_quota_{sid}")
            if st.button("確認修改上限"):
                update_session(sid, {"total_quota": int(new_quota), "casual_quota": int(new_casual_quota)})
                st.success(f"已調整：總名額 {new_quota} 人 / 零打上限 {new_casual_quota} 人")
                st.rerun()

    # 狀態攔截
    if session.get("cancelled"):
        st.warning(f"⚠ 此場次已取消。原因：{session.get('cancel_reason','無')}")
        st.stop()
    if session.get("locked"):
        st.error("❌ 此場次已關閉")
        st.stop()

    if is_member_only:
        st.warning("👑 本場次為會員限定場次")
    elif total_casual_count >= casual_quota:
        st.warning(f"⚠️ 零打名額已滿（上限 {casual_quota} 人）！零打報名將進入候補，有人取消時依序遞補。")
    elif current_total >= quota:
        st.warning("⚠️ 正取名額已滿！零打報名將進入候補，有人取消時依序遞補。")
    # 零打尚未開放時顯示提示（但仍可查看名單；會員不受此限制）
    elif not casual_open and not st.session_state.get("is_admin"):
        open_dt = get_session_open_date(s_date)
        st.warning(f"⏳ 零打報名尚未開放（開放日：{open_dt}）。會員可直接報名。")

    # ─────────────────────────
    # 報名表單
    # ─────────────────────────
    st.divider()
    st.markdown("### ✍️ 我要報名")
    settings = get_system_settings()

    # 根據場次星期幾取得場地資訊
    _venue = get_venue(datetime.strptime(session['date'], '%Y-%m-%d').weekday())
    _venue_line = (
        f"\n\n📍 **打球地點**：[{_venue['name']}]({_venue['map_url']}) ：{_venue['address']}\n\n"
        if _venue else ""
    )

    st.info(f"""
🏸 **【場地資訊與費用】**
{_venue_line}💰 **零打費用**：{settings.get('casual_fee')} 元/人
🏸 **當前球種**：{settings.get('shuttlecock')}

🪪 **【零打卡優惠】**
* 費用：{settings.get('casual_fee')}0 元/張
* 特色：可打 11 次，認卡不認人，無使用期限，如有需求請洽現場管理員

💡 **【報名規則小提醒】**
* **會員**：優先報名不受名額限制
* **零打**：本場零打名額上限 **{casual_quota} 人**，若名額已滿，系統將自動排入候補；

📌 為了維護大家的打球體驗，會進行每日人數的控管，建議會員把握機會提前報名；若當天場地尚有名額，前一天會增加零打報名，請備取的球友注意遞補情況！
""")

    session_date = datetime.strptime(session['date'], '%Y-%m-%d')
    if session_date.weekday() == 6:  # 6 代表週日
        st.warning("""
### 📢 中興國小特別公告

為了維護優質且乾淨的運動環境，請各位球友共同配合以下事項：

* **鞋履規範**：為維護羽球地墊清潔，請務必於地墊外更換羽球鞋後，再進入場地
* **器材歸位**：為確保球場淨空安全，場內不額外置放座椅。若有借用需求，請於使用後將椅子放回「前方樓梯下」，感謝您的協助
* **報名規定**：為維持場地秩序與公平性，未報名成功（含候補）者請勿自行入場。若經現場確認未報名，將酌收 2 倍（含）以上之臨打費用作為球隊基金

感謝您的配合！
""")

    c1, c3 = st.columns([2, 1])
    with c1: name_input  = st.text_input("球友名字", key=f"name_{sid}")
    with c3: count       = st.number_input("人數", min_value=1, max_value=3, value=1, key=f"count_{sid}")

    role_sel = st.radio("身分", ["會員", "零打"], index=None, horizontal=True, key=f"role_{sid}")
    role = ROLE_MAP.get(role_sel, None)

    if role_sel == "零打":
        pay_col1, pay_col2, pay_col3 = st.columns(3)
        with pay_col1:
            if st.button("💳 簽卡", key=f"pay_card_{sid}", use_container_width=True,
                         type="primary" if st.session_state.get(f"pay_{sid}","簽卡") == "簽卡" else "secondary"):
                st.session_state[f"pay_{sid}"] = "簽卡"
        with pay_col2:
            if st.button("💵 付現", key=f"pay_cash_{sid}", use_container_width=True,
                         type="primary" if st.session_state.get(f"pay_{sid}","簽卡") == "付現" else "secondary"):
                st.session_state[f"pay_{sid}"] = "付現"
        with pay_col3:
            if st.button("🏦 轉帳", key=f"pay_transfer_{sid}", use_container_width=True,
                         type="primary" if st.session_state.get(f"pay_{sid}","簽卡") == "轉帳" else "secondary"):
                st.session_state[f"pay_{sid}"] = "轉帳"
        pay_method = st.session_state.get(f"pay_{sid}", "簽卡")
        st.caption(f"付費方式：{pay_method}")
    else:
        pay_method = ""

    payment_method_code = PAY_CODE_BY_ZH.get(pay_method) if role_sel == "零打" else None

    c4, c5 = st.columns([3, 1])
    with c4: password_input = st.text_input("零打球友請正確選擇身分，自由輸入密碼(4位英數字）以保障報名權益", type="password", max_chars=4, key=f"pwd_{sid}")
    with c5:
        st.write("")  # 對齊 label 的高度
        st.write("")
        submit_btn = st.button("確認報名", type="primary", key=f"btn_submit_{sid}", use_container_width=True)

    # 報名執行邏輯
    if submit_btn:
        if not name_input.strip():
            st.error("請輸入名字")
        elif role_sel is None:
            st.error("請選擇身分（會員或零打）")
        elif role_sel == "零打" and (len(password_input.strip()) != 4 or not password_input.strip().isalnum()):
            st.error("零打報名請設定4位英數字暗號")
        elif is_member_only and role == "casual" and not st.session_state.get("is_admin"):
            st.error("本場為會員限定，零打暫不開放。")
        elif role == "casual" and not casual_open and not st.session_state.get("is_admin"):
            open_dt = get_session_open_date(s_date)
            st.error(f"零打報名尚未開放，開放日為 {open_dt}。")
        elif role == "casual" and int(count) > 3:
            st.error("零打每次報名人數上限為 3 人。")
        elif role == "casual" and total_casual_count >= casual_quota:
            st.warning(f"⏳ 零打名額已滿（上限 {casual_quota} 人），已為您加入候補名單！")
            with st.spinner("正在登記中，請稍候..."):
                save_pwd = str(password_input).strip()
                add_booking_compatible(sid, name_input.strip(), role, int(count), save_pwd,
                                        payment_method=payment_method_code)
                time.sleep(1)
                st.rerun()
        else:
            with st.spinner("正在登記中，請稍候..."):
                # 儲存時，會員的密碼可以是空的或預設值，零打則存入使用者設定的密碼
                save_pwd = str(password_input).strip() if role_sel == "零打" else "none"
                # 檢查零打是否超過正取名額，若超過則標記為候補
                add_booking_compatible(sid, name_input.strip(), role, int(count), save_pwd,
                                        payment_method=payment_method_code)
                if role == "casual" and current_total >= quota:
                    # 直接寫入，後端 list_to_show 邏輯會自動標為候補
                    st.warning(f"⏳ 正取名額已滿，已為您加入候補名單！")
                else:
                    st.success("報名成功！")
                time.sleep(1)
                st.rerun()

    # ─────────────────────────
    # 報名名單（管理員含點名）
    # ─────────────────────────

    # 管理員：初始化點名暫存區（只在進入此 sid 時從 DB 載入一次）
    checkins = {}
    cache_key = f"checkin_cache_{sid}"
    open_slots = 0
    if st.session_state.get("is_admin"):
        if cache_key not in st.session_state:
            st.session_state[cache_key] = get_checkins(sid)
        checkins = st.session_state[cache_key]

        confirmed_items = [it for it in list_to_show if not it["is_waitlist"]]
        waitlist_items  = [it for it in list_to_show if it["is_waitlist"]]

        arrived_count = sum(
            int(it["data"]["count"]) for it in confirmed_items
            if checkins.get(it["data"]["id"])
        )
        absent_count = sum(
            int(it["data"]["count"]) for it in confirmed_items
            if not checkins.get(it["data"]["id"])
        )
        open_slots = absent_count

        # 細分統計：會員 / 零打簽卡 / 零打付現 / 零打轉帳
        member_count    = 0
        casual_card     = 0
        casual_cash     = 0
        casual_transfer = 0
        for it in confirmed_items:
            b   = it["data"]
            cnt = int(b["count"])
            if b["role"] == "member":
                member_count += cnt
            else:
                pm = get_payment_method(b)
                if pm == "cash":
                    casual_cash += cnt
                elif pm == "transfer":
                    casual_transfer += cnt
                else:
                    casual_card += cnt  # 預設簽卡（含 [簽卡] 或未設定）

        # 統計列
        total_confirmed = sum(int(it["data"]["count"]) for it in confirmed_items)
        st.markdown(
            f"應到 **{total_confirmed}** 人，實到 **{arrived_count}** 人，未到 **{absent_count}** 人　"
            f"｜　其中會員 **{member_count}** 人、零打簽卡 **{casual_card}** 人、"
            f"零打付現 **{casual_cash}** 人、零打轉帳 **{casual_transfer}** 人"
        )

    st.subheader("👥 報名名單")

    # ── 一鍵產生名單（管理員）──
    if st.session_state.get("is_admin"):
        if st.button("📋 產生名單文字", use_container_width=True):
            s_wd    = WEEKDAY_TW[s_date.weekday()]
            s_start = session.get("start_time", "")[:5]
            s_end   = session.get("end_time", "")[:5]
            s_label = session.get("label", "")
            lines   = [
                f"🏸【信義羽球隊】{session['date']}（週{s_wd}）{s_label} {s_start}–{s_end}",
                f"名額：{current_total}/{quota} 人",
                "",
            ]
            # 正取
            confirmed = [it for it in list_to_show if not it["is_waitlist"]]
            if confirmed:
                lines.append("✅ 正取名單")
                for i, it in enumerate(confirmed, 1):
                    b    = it["data"]
                    name = it["clean_name"]
                    zh_r = ROLE_TO_ZH.get(b["role"], b["role"])
                    pay  = f"／{it['pay_label']}" if it["pay_label"] else ""
                    lines.append(f"  {i}. {name}（{b['count']}人／{zh_r}{pay}）")
            # 候補
            waitlist = [it for it in list_to_show if it["is_waitlist"]]
            if waitlist:
                lines.append("")
                lines.append("⏳ 候補名單")
                for i, it in enumerate(waitlist, 1):
                    b    = it["data"]
                    name = it["clean_name"]
                    zh_r = ROLE_TO_ZH.get(b["role"], b["role"])
                    pay  = f"／{it['pay_label']}" if it["pay_label"] else ""
                    lines.append(f"  {i}. {name}（{b['count']}人／{zh_r}{pay}）")
            lines += [
                "",
                f"👉 報名連結：{web_url}",
            ]
            st.text_area("複製後貼到 LINE", value="\n".join(lines), height=300, key="roster_text")

    if not list_to_show:
        st.caption("目前尚無人報名")

    for item in list_to_show:
        b       = item["data"]
        wl      = item["is_waitlist"]
        c_name  = item["clean_name"]
        zh_role = ROLE_TO_ZH.get(b["role"], b["role"])
        bid     = b["id"]

        if b["role"] == "member":  status_tag = "🟢 正取"
        elif wl == True:           status_tag = "⏳ 候補"
        elif wl == "partial":
            _confirmed = item.get("partial_confirmed", 0)
            _waitlist  = item.get("partial_waitlist", 0)
            status_tag = f"⚠️ 部分候補（正取 {_confirmed} 人 / 備取 {_waitlist} 人）"
        else:                      status_tag = "🟢 正取"
        modify_tag = " (已改)" if b["role"] == "casual" and item["modify_count"] > 0 else ""
        pay_suffix = f" ｜ {item['pay_label']}" if b["role"] == "casual" and item["pay_label"] else ""

        # 管理員模式：checkbox／按鈕本身就帶完整資訊文字，確保手機上同一行不跑版
        if st.session_state.get("is_admin"):
            is_waitlist_row = wl not in (False,)  # True or "partial" = 候補
            already_promoted = "[遞補]" in b.get("name", "")

            if not is_waitlist_row:
                # 正取 → checkbox 本身就是一整行（勾選框＋文字），不再拆多欄，手機上不會被擠成兩行
                is_here = checkins.get(bid, False)
                icon = "🟢" if is_here else "⭕"
                new_val = st.checkbox(
                    f"{icon} {c_name} ｜ {b['count']} 人 ｜ {zh_role}{pay_suffix} ｜ {status_tag}{modify_tag}",
                    value=is_here,
                    key=f"chk_{bid}",
                )
                # 只寫入 session_state，不立即打 DB
                if new_val != checkins.get(bid, False):
                    st.session_state[cache_key][bid] = new_val
            else:
                # 候補 → 狀態文字整行顯示，遞補按鈕另起一行、滿版寬度，手機上好點按
                promote_tag = "（已遞補）" if already_promoted else ""
                st.write(f"⏳ {c_name} ｜ {b['count']} 人 ｜ {zh_role}{pay_suffix}{promote_tag}")
                if not already_promoted and open_slots > 0:
                    if st.button("➕ 遞補為正取", key=f"promote_{bid}", use_container_width=True):
                        promote_waitlist(bid)
                        st.success(f"已將 {c_name} 標記為遞補正取")
                        st.rerun()

            with st.expander("⚙️ 修改/取消"):
                if st.session_state.get("is_admin"):
                    st.warning("⚡ 管理員模式")
                    adm_new = st.number_input("調整人數（0＝刪除）", min_value=0, max_value=Quota_7, value=int(b["count"]), key=f"adm_cnt_{b['id']}")
                    if st.button("管理員確認修改", key=f"adm_btn_{b['id']}"):
                        if adm_new == 0:
                            _ok = cancel_booking(b["id"], b["session_id"])
                            if _ok:
                                st.success("已刪除")
                        else:
                            try:
                                after_key   = b["name"].split("_🔑")[1]
                                current_pwd = after_key.split("_🔄")[0] if "_🔄" in after_key else after_key
                            except:
                                current_pwd = "none"
                            new_mod       = item["modify_count"]  # 管理員修改不計入次數
                            new_full_name = f"{c_name}_🔑{current_pwd}_🔄{new_mod}"
                            _ok = update_booking_data(b["id"], int(adm_new), new_name=new_full_name)
                            if _ok:
                                st.success(f"已調整為 {adm_new} 人")
                        if _ok:  # 失敗時不跑後續、也不 rerun，讓錯誤訊息留在畫面上
                            check_and_notify_waitlist(sid, quota, old_waitlist_ids, f"{session['date']} {session['label']}",
                                                      session=session, old_confirmed=old_confirmed_map)
                            st.rerun()
                else:
                    if b["role"] == "casual":
                        input_pwd = st.text_input("請輸入密碼", type="password", key=f"pwd_verify_{b['id']}")
                    else:
                        input_pwd = ""
                        st.caption("會員修改資料無需密碼")

                    _current_count = int(b["count"])
                    if b["role"] == "casual":
                        st.caption(f"目前人數：{_current_count} 人，只能減少（不可增加）")
                        user_new = st.number_input("新的人數（0＝取消報名）", min_value=0, max_value=_current_count, value=_current_count, key=f"user_cnt_{b['id']}")
                    else:
                        user_new = st.number_input("新的人數（0＝取消報名）", min_value=0, max_value=10, value=_current_count, key=f"user_cnt_{b['id']}")

                    if st.button("確認提交", key=f"user_btn_{b['id']}", use_container_width=True):
                        try:
                            db_pwd = b["name"].split("_🔑")[1].split("_🔄")[0]
                        except:
                            db_pwd = "none"

                        is_authorized = (b["role"] == "member") or (input_pwd == db_pwd)

                        if b["role"] == "casual" and not input_pwd:
                            st.error("請輸入當初設定的密碼")
                        elif not is_authorized:
                            st.error("密碼錯誤！")
                        elif user_new == 0:
                            if cancel_booking(b["id"], b["session_id"]):
                                st.success("已取消報名！")
                                st.rerun()
                        else:
                            try:
                                after_key   = b["name"].split("_🔑")[1]
                                current_pwd = after_key.split("_🔄")[0] if "_🔄" in after_key else after_key
                            except:
                                current_pwd = "none"
                            new_mod       = item["modify_count"]
                            new_full_name = f"{c_name}_🔑{current_pwd}_🔄{new_mod}"
                            if update_booking_data(b["id"], int(user_new), new_name=new_full_name):
                                check_and_notify_waitlist(sid, quota, old_waitlist_ids,
                                                          f"{session['date']} {session['label']}",
                                                          session=session, old_confirmed=old_confirmed_map)
                                st.success(f"已更新為 {user_new} 人")
                                st.rerun()

        else:
            # 一般使用者：顯示名單 + 修改/取消
            col1, col2 = st.columns([4, 2])
            with col1:
                st.write(f"● {c_name} ｜ {b['count']} 人 ｜ {zh_role}{pay_suffix} ｜ {status_tag}{modify_tag}")
            with col2:
                with st.expander("⚙️ 修改/取消"):
                    if b["role"] == "casual":
                        input_pwd = st.text_input("請輸入密碼", type="password", key=f"pwd_verify2_{b['id']}")
                    else:
                        input_pwd = ""
                        st.caption("會員修改資料無需密碼")
                    _current_count = int(b["count"])
                    if b["role"] == "casual":
                        st.caption(f"目前人數：{_current_count} 人，只能減少（不可增加）")
                        user_new = st.number_input("新的人數（0＝取消報名）", min_value=0, max_value=_current_count, value=_current_count, key=f"user_cnt2_{b['id']}")
                    else:
                        user_new = st.number_input("新的人數（0＝取消報名）", min_value=0, max_value=10, value=_current_count, key=f"user_cnt2_{b['id']}")
                    if st.button("確認提交", key=f"user_btn2_{b['id']}", use_container_width=True):
                        try:
                            db_pwd = b["name"].split("_🔑")[1].split("_🔄")[0]
                        except:
                            db_pwd = "none"
                        is_authorized = (b["role"] == "member") or (input_pwd == db_pwd)
                        if b["role"] == "casual" and not input_pwd:
                            st.error("請輸入當初設定的密碼")
                        elif not is_authorized:
                            st.error("密碼錯誤！")
                        elif user_new == 0:
                            if cancel_booking(b["id"], b["session_id"]):
                                st.success("已取消報名！")
                                st.rerun()
                        else:
                            try:
                                after_key   = b["name"].split("_🔑")[1]
                                current_pwd = after_key.split("_🔄")[0] if "_🔄" in after_key else after_key
                            except:
                                current_pwd = "none"
                            new_mod       = item["modify_count"]
                            new_full_name = f"{c_name}_🔑{current_pwd}_🔄{new_mod}"
                            if update_booking_data(b["id"], int(user_new), new_name=new_full_name):
                                check_and_notify_waitlist(sid, quota, old_waitlist_ids,
                                                          f"{session['date']} {session['label']}",
                                                          session=session, old_confirmed=old_confirmed_map)
                                st.success(f"已更新為 {user_new} 人")
                                st.rerun()

    # 管理員：點名儲存按鈕（一次寫入，避免每次 checkbox 都打 DB）
    if st.session_state.get("is_admin"):
        if cache_key in st.session_state:
            st.divider()
            if st.button("💾 儲存點名紀錄", type="primary", use_container_width=True):
                saved_checkins = get_checkins(sid)          # 目前 DB 狀態
                local_state    = st.session_state[cache_key]
                changed = False
                for booking_id, is_checked in local_state.items():
                    db_val = saved_checkins.get(booking_id, False)
                    if is_checked != db_val:
                        set_checkin(sid, booking_id, is_checked)
                        changed = True
                if changed:
                    st.success("✅ 點名紀錄已儲存")
                else:
                    st.info("點名狀態未變動")
