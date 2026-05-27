import streamlit as st
from supabase import create_client

SUPABASE_URL = "https://plnsnmftdxtbxjgdzkbq.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBsbnNubWZ0ZHh0YnhqZ2R6a2JxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3NjIxMTgsImV4cCI6MjA5NTMzODExOH0.F8_jJbX1pA4jtT-4JewN3bCcyy6rNzY9wrH0llcmamo"

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
