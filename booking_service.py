from supabase_client import supabase
from datetime import datetime

def add_user(session_id, name, role, count=1):

    res = supabase.rpc("add_booking", {
        "p_session_id": session_id,
        "p_name": name,
        "p_role": role,
        "p_count": count
    }).execute()

    return res.data


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
