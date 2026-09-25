from datetime import date

import streamlit as st
import requests

DEFAULT_BOARD = {"backlog": [], "doing": [], "review": []}

# Column key -> (heading, card style)
COLUMNS = {
    "backlog": ("Backlog", st.info),
    "doing": ("Doing", st.warning),
    "review": ("Review", st.success),
}

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


def make_task(title, description="", due=None, created=None):
    # Dates are stored as ISO strings so the board stays plain JSON
    return {
        "title": title,
        "description": description,
        "due": due.isoformat() if due else None,
        "created": date.today().isoformat() if created is None else created,
    }


def normalize_task(task):
    # Older boards stored each task as a bare string
    if isinstance(task, str):
        return make_task(task, created="")
    return {
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "due": task.get("due"),
        "created": task.get("created", ""),
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
            return {k: [normalize_task(t) for t in data[k]] for k in DEFAULT_BOARD}
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


def due_label(task, column):
    if not task["due"]:
        return ""
    due = date.fromisoformat(task["due"])
    label = f"📅 Due {due:%d %b %Y}"
    if column != "review":
        days = (due - date.today()).days
        if days < 0:
            label += " — **overdue**"
        elif days == 0:
            label += " — **today**"
    return label


def toggle_edit(column, i):
    # Only one card is open for editing at a time
    if st.session_state.editing == (column, i):
        st.session_state.editing = None
    else:
        st.session_state.editing = (column, i)


def render_task(task, column, i, box):
    lines = [f"**{task['title']}**"]
    if task["description"]:
        lines.append(task["description"])
    meta = [due_label(task, column)]
    if task["created"]:
        meta.append(f"Created {date.fromisoformat(task['created']):%d %b}")
    meta = " · ".join(m for m in meta if m)
    if meta:
        lines.append(f":small[{meta}]")
    box("\n\n".join(lines))

    editing = st.session_state.editing == (column, i)
    st.button(
        "Close" if editing else "Edit",
        key=f"toggle_{column}_{i}",
        icon=":material/close:" if editing else ":material/edit:",
        type="tertiary",
        on_click=toggle_edit,
        args=(column, i),
    )
    if not editing:
        return

    with st.form(f"edit_{column}_{i}"):
        title = st.text_input("Title", value=task["title"])
        description = st.text_area("Description", value=task["description"])
        due = st.date_input(
            "Due date",
            value=date.fromisoformat(task["due"]) if task["due"] else None,
            format="DD/MM/YYYY",
        )
        status = st.selectbox(
            "Status",
            list(COLUMNS),
            index=list(COLUMNS).index(column),
            format_func=lambda c: COLUMNS[c][0],
        )
        save_col, delete_col = st.columns(2)
        save = save_col.form_submit_button("Save", type="primary")
        delete = delete_col.form_submit_button("Delete", icon=":material/delete:")

    board = st.session_state.board
    if delete:
        board[column].pop(i)
        st.session_state.editing = None
        save_changes()
        st.rerun()
    if save:
        if title.strip():
            updated = make_task(
                title.strip(), description.strip(), due, task["created"]
            )
            if status == column:
                board[column][i] = updated
            else:
                board[column].pop(i)
                board[status].append(updated)
            st.session_state.editing = None
            save_changes()
            st.rerun()
        else:
            st.warning("Title can't be empty.")


if "board" not in st.session_state:
    st.session_state.board = load_board()
if "editing" not in st.session_state:
    st.session_state.editing = None

st.title("📌 Kanban Board")

# Task input form — clears itself on submit
with st.form("new_task_form", clear_on_submit=True):
    new_task = st.text_input("Create New Task", placeholder="What needs to be done?")
    new_description = st.text_area(
        "Description (optional)", placeholder="Add some detail…"
    )
    new_due = st.date_input("Due date (optional)", value=None, format="DD/MM/YYYY")
    submitted = st.form_submit_button("Add Task")
    if submitted:
        if new_task.strip():
            st.session_state.board["backlog"].append(
                make_task(new_task.strip(), new_description.strip(), new_due)
            )
            save_changes()
            st.rerun()
        else:
            st.warning("Task can't be empty.")

# Each group sits in an expander so it can be collapsed. The stable key keeps
# the open/closed state when the task count in the label changes.
for col, (column, (heading, box)) in zip(st.columns(3), COLUMNS.items()):
    tasks = st.session_state.board[column]
    with col, st.expander(
        f"{heading} ({len(tasks)})", expanded=True, key=f"group_{column}"
    ):
        if column == "review" and tasks and st.button("🧹 Clear All Done"):
            st.session_state.board["review"] = []
            st.session_state.editing = None
            save_changes()
            st.rerun()
        for i, task in enumerate(tasks):
            render_task(task, column, i, box)
