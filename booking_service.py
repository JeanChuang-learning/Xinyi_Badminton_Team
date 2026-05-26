from supabase_client import supabase
from datetime import datetime

def add_user(data, sid, name, role, count):
    session = data["sessions"].setdefault(sid, {
        "members": [],
        "total_quota": 20,
        "cancelled": False,
        "cancel_reason": ""
    })

    session["members"].append({
        "name": name,
        "role": role,
        "count": count
    })

    return True

def cancel_user(session_id, name):
    supabase.rpc("cancel_booking", {
        "p_session_id": session_id,
        "p_name": name
    }).execute()


def get_queue_view(session_id):

    res = supabase.rpc("get_queue_view", {
        "p_session_id": session_id
    }).execute()

    return res.data
