# booking.py

def init_session():
    return {
        "members": [],
        "casuals": [],
        "quota": 12,
        "cancelled": False,
        "cancel_reason": ""
    }


def add_user(data, sid, name, role):
    sdata = data["sessions"][sid]
    members = sdata["members"]

    if any(m["name"] == name for m in members):
        return "already_exists"

    members.append({
        "name": name,
        "role": role,
        "created_at": datetime.now().isoformat()
    })

    return "ok"


def cancel_user(data, sid, name):
    sdata = data["sessions"][sid]
    sdata["members"] = [
        m for m in sdata["members"]
        if m["name"] != name
    ]
    return "ok"


def get_queue_view(session):
    """
    回傳：
        confirmed: 正取（含會員 + 補滿 quota 的零打）
        waitlist: 超過 quota 的零打
    """

    quota = session["quota"]
    members = session["members"]
    casuals = session["casuals"]

    confirmed = members[:]  # 會員永遠優先

    remaining_slots = quota - len(confirmed)

    if remaining_slots > 0:
        confirmed += casuals[:remaining_slots]

    if remaining_slots < 0:
        # 會員已超過 quota（不會擋，但代表零打完全進不來）
        waitlist = []
    else:
        waitlist = casuals[remaining_slots:]

    return confirmed, waitlist


def set_quota(session, quota: int):
    session["quota"] = quota
    return session
