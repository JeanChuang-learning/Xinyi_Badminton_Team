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
    return session["members"], []

def set_quota(session, quota: int):
    session["quota"] = quota
    return session
