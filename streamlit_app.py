import streamlit as st
import requests

DEFAULT_BOARD = {"backlog": [], "doing": [], "review": []}

# --- JSONBin config (set these in Streamlit "Secrets" when you deploy) ---
# .streamlit/secrets.toml (local) or the Secrets panel on Streamlit Cloud:
#
# JSONBIN_BIN_ID = "your-bin-id"
# JSONBIN_API_KEY = "your-x-master-key"
#
BIN_ID = st.secrets.get("JSONBIN_BIN_ID", "")
API_KEY = st.secrets.get("JSONBIN_API_KEY", "")

BASE_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
HEADERS = {
    "X-Master-Key": API_KEY,
    "Content-Type": "application/json",
}


def load_board():
    if not BIN_ID or not API_KEY:
        st.error("Missing JSONBIN_BIN_ID / JSONBIN_API_KEY in Streamlit secrets.")
        return {k: [] for k in DEFAULT_BOARD}
    try:
        resp = requests.get(f"{BASE_URL}/latest", headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("record", {})
        if isinstance(data, dict) and all(k in data for k in DEFAULT_BOARD):
            return data
    except (requests.RequestException, ValueError):
        st.warning("Couldn't reach JSONBin — starting with an empty board.")
    return {k: [] for k in DEFAULT_BOARD}


def save_changes():
    try:
        resp = requests.put(
            BASE_URL, headers=HEADERS, json=st.session_state.board, timeout=10
        )
        resp.raise_for_status()
    except requests.RequestException:
        st.error("Couldn't save to JSONBin — your change may not persist.")


if "board" not in st.session_state:
    st.session_state.board = load_board()

st.title("📌 Kanban Board")

# Task input form — clears itself on submit
with st.form("new_task_form", clear_on_submit=True):
    new_task = st.text_input("Create New Task", placeholder="What needs to be done?")
    submitted = st.form_submit_button("Add Task")
    if submitted:
        if new_task.strip():
            st.session_state.board["todo"].append(new_task.strip())
            save_changes()
            st.rerun()
        else:
            st.warning("Task can't be empty.")

col1, col2, col3 = st.columns(3)

with col1:
    st.header(f"To Do ({len(st.session_state.board['todo'])})")
    for i, task in enumerate(st.session_state.board["todo"]):
        st.info(task)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("👉 Start", key=f"start_{i}"):
                st.session_state.board["doing"].append(st.session_state.board["todo"].pop(i))
                save_changes()
                st.rerun()
        with b2:
            if st.button("🗑️ Delete", key=f"del_todo_{i}"):
                st.session_state.board["todo"].pop(i)
                save_changes()
                st.rerun()

with col2:
    st.header(f"Doing ({len(st.session_state.board['doing'])})")
    for i, task in enumerate(st.session_state.board["doing"]):
        st.warning(task)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("✅ Finish", key=f"done_{i}"):
                st.session_state.board["done"].append(st.session_state.board["doing"].pop(i))
                save_changes()
                st.rerun()
        with b2:
            if st.button("🗑️ Delete", key=f"del_doing_{i}"):
                st.session_state.board["doing"].pop(i)
                save_changes()
                st.rerun()

with col3:
    st.header(f"Done ({len(st.session_state.board['done'])})")
    if st.session_state.board["done"] and st.button("🧹 Clear All Done"):
        st.session_state.board["done"] = []
        save_changes()
        st.rerun()
    for i, task in enumerate(st.session_state.board["done"]):
        st.success(task)
        if st.button("🗑️ Remove", key=f"clear_{i}"):
            st.session_state.board["done"].pop(i)
            save_changes()
            st.rerun()
