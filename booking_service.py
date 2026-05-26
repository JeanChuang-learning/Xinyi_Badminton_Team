# booking.py

def init_session():
    return {
        "members": [],
        "casuals": [],
        "quota": 12,
        "cancelled": False,
        "cancel_reason": ""
    }


def add_user(session, name: str, role: str):
    """
    role:
        - member: 優先加入，不受 quota 限制
        - casual: 受 quota 限制（但仍允許加入 waitlist）
    """

    name = name.strip()

    if not name:
        return {"ok": False, "reason": "EMPTY_NAME"}

    if name in session["members"] or name in session["casuals"]:
        return {"ok": False, "reason": "ALREADY_REGISTERED"}

    if role == "member":
        session["members"].append(name)
        return {"ok": True, "type": "member"}

    if role == "casual":
        session["casuals"].append(name)
        return {"ok": True, "type": "casual"}

    return {"ok": False, "reason": "INVALID_ROLE"}


def cancel_user(session, name: str):
    if name in session["members"]:
        session["members"].remove(name)
        return {"ok": True, "type": "member"}

    if name in session["casuals"]:
        session["casuals"].remove(name)
        return {"ok": True, "type": "casual"}

    return {"ok": False, "reason": "NOT_FOUND"}


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