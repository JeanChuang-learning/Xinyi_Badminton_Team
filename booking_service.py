# booking.py

def init_session():
    return {
        "members": [],
        "casuals": [],
        "quota": 12,
        "cancelled": False,
        "cancel_reason": ""
    }


from datetime import datetime

def add_user(data, sid, name, role, count=1):

    session = data["sessions"][sid]

    if "members" not in session:
        session["members"] = []

    if "queue" not in session:
        session["queue"] = []

    # already exists
    for m in session["members"]:
        if m["name"] == name:
            return "already_exists"

    for m in session["queue"]:
        if m["name"] == name:
            return "already_exists"

    session["members"].append({
        "name": name,
        "role": role,
        "count": count
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
    members = session["members"]

    confirmed = []
    waitlist = []

    for m in members:
        confirmed.append(m)  # 無 quota 就全部 confirmed

    return confirmed, waitlist

def set_quota(session, quota: int):
    session["quota"] = quota
    return session
