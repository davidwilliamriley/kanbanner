from datetime import date

import streamlit as st
import requests

st.set_page_config(page_title="Kanban Board", page_icon="📌", layout="wide")

DEFAULT_BOARD = {"backlog": [], "doing": [], "review": []}

# Column key -> (heading, card tint)
COLUMNS = {
    "backlog": ("Backlog", "28, 131, 225"),
    "doing": ("Doing", "255, 189, 69"),
    "review": ("Review", "33, 195, 84"),
}

# Column key -> (quick-move button label, icon, target column)
QUICK_MOVES = {
    "backlog": ("Start", ":material/play_arrow:", "doing"),
    "doing": ("Finish", ":material/check:", "review"),
}

# Badge colours for tags; each tag always gets the same one
TAG_COLORS = ["blue", "green", "orange", "red", "violet", "gray"]

# Sort option -> (sort key, newest/largest first), None keeps the board order
SORTS = {
    "Board Order": None,
    "Due Date": (lambda t: (t["due"] is None, t["due"] or ""), False),
    "Title": (lambda t: t["title"].casefold(), False),
    "Newest First": (lambda t: t["created"] or "", True),
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


def clean_tags(tags):
    # Trim, drop blanks and case-insensitive duplicates, keep the given order.
    # Square brackets would break the badge markdown, so they're removed.
    cleaned, seen = [], set()
    for tag in tags:
        tag = tag.replace("[", "").replace("]", "").strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            cleaned.append(tag)
    return cleaned


def make_task(title, description="", due=None, created=None, tags=()):
    # Dates are stored as ISO strings so the board stays plain JSON
    return {
        "title": title,
        "description": description,
        "due": due.isoformat() if due else None,
        "created": date.today().isoformat() if created is None else created,
        "tags": clean_tags(tags),
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
        "tags": clean_tags(task.get("tags", [])),
    }


def load_board():
    if not BIN_ID or not API_KEY:
        st.error("Missing JSONBIN_BIN_ID / JSONBIN_API_KEY in Streamlit Secrets.")
        return {k: [] for k in DEFAULT_BOARD}
    try:
        resp = requests.get(f"{BASE_URL}/latest", headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("record", {})
        if isinstance(data, dict) and all(k in data for k in DEFAULT_BOARD):
            return {k: [normalize_task(t) for t in data[k]] for k in DEFAULT_BOARD}
    except (requests.RequestException, ValueError):
        st.warning("Couldn't Reach JSONBin — Starting with an Empty Board.")
    return {k: [] for k in DEFAULT_BOARD}


def save_changes():
    try:
        resp = requests.put(
            BASE_URL, headers=HEADERS, json=st.session_state.board, timeout=10
        )
        resp.raise_for_status()
    except requests.RequestException:
        st.error("Couldn't Save to JSONBin — Your Change May Not Persist.")


def due_label(task, column):
    if not task["due"]:
        return ""
    due = date.fromisoformat(task["due"])
    label = f"📅 Due {due:%Y-%m-%d}"
    if column != "review":
        days = (due - date.today()).days
        if days < 0:
            label += " — **Overdue**"
        elif days == 0:
            label += " — **Today**"
    return label


def board_tags():
    tags = {
        tag
        for tasks in st.session_state.board.values()
        for task in tasks
        for tag in task["tags"]
    }
    return sorted(tags, key=str.casefold)


def tag_badge(tag):
    color = TAG_COLORS[sum(map(ord, tag.casefold())) % len(TAG_COLORS)]
    return f":{color}-badge[{tag}]"


def visible_tasks(tasks, show_tags, hide_tags, sort_by):
    # Keep each task's board index so buttons still act on the right task
    shown = [
        (i, t)
        for i, t in enumerate(tasks)
        if (not show_tags or set(t["tags"]) & set(show_tags))
        and not set(t["tags"]) & set(hide_tags)
    ]
    if SORTS[sort_by]:
        key, reverse = SORTS[sort_by]
        shown.sort(key=lambda item: key(item[1]), reverse=reverse)
    return shown


def group_by_tag(shown, show_tags):
    # A task sits under its first tag, or its first shown tag when filtering
    groups = {}
    for i, t in shown:
        tags = [tag for tag in t["tags"] if tag in show_tags] or t["tags"]
        groups.setdefault(tags[0] if tags else None, []).append((i, t))
    order = sorted((g for g in groups if g), key=str.casefold)
    return [(g, groups[g]) for g in order + ([None] if None in groups else [])]


def toggle_edit(column, i):
    # Only one card is open for editing at a time
    if st.session_state.editing == (column, i):
        st.session_state.editing = None
    else:
        st.session_state.editing = (column, i)


def move_task(column, i, target):
    board = st.session_state.board
    board[target].append(board[column].pop(i))
    st.session_state.editing = None
    save_changes()


def render_task(task, column, i):
    lines = [f"**{task['title']}**"]
    if task["description"]:
        lines.append(task["description"])
    if task["tags"]:
        lines.append(" ".join(tag_badge(tag) for tag in task["tags"]))
    meta = [due_label(task, column)]
    if task["created"]:
        meta.append(f"Created {date.fromisoformat(task['created']):%Y-%m-%d}")
    meta = " · ".join(m for m in meta if m)
    if meta:
        lines.append(f":small[{meta}]")
    st.markdown("\n\n".join(lines))

    # Quick move and edit sit in the card's bottom-right corner
    editing = st.session_state.editing == (column, i)
    with st.container(
        horizontal=True, horizontal_alignment="right", gap="small"
    ):
        if column in QUICK_MOVES:
            label, icon, target = QUICK_MOVES[column]
            st.button(
                label,
                key=f"move_{column}_{i}",
                icon=icon,
                type="tertiary",
                on_click=move_task,
                args=(column, i, target),
            )
        st.button(
            "",
            key=f"toggle_{column}_{i}",
            icon=":material/close:" if editing else ":material/edit:",
            help="Close" if editing else "Edit",
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
            "Due Date",
            value=date.fromisoformat(task["due"]) if task["due"] else None,
            format="YYYY-MM-DD",
        )
        tags = st.multiselect(
            "Tags",
            board_tags(),
            default=task["tags"],
            accept_new_options=True,
            placeholder="Choose or Type a Tag",
        )
        status = st.selectbox(
            "Status",
            list(COLUMNS),
            index=list(COLUMNS).index(column),
            format_func=lambda c: COLUMNS[c][0],
        )
        with st.container(horizontal=True, gap="small"):
            save = st.form_submit_button("Save", type="primary")
            delete = st.form_submit_button("Delete", icon=":material/delete:")

    board = st.session_state.board
    if delete:
        board[column].pop(i)
        st.session_state.editing = None
        save_changes()
        st.rerun()
    if save:
        if title.strip():
            updated = make_task(
                title.strip(), description.strip(), due, task["created"], tags
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
            st.warning("Title Can't Be Empty.")


@st.dialog("New Task")
def new_task_dialog():
    with st.form("new_task_form"):
        title = st.text_input("Title", placeholder="What Needs to Be Done?")
        description = st.text_area(
            "Description (Optional)", placeholder="Add Some Detail…"
        )
        due = st.date_input("Due Date (Optional)", value=None, format="YYYY-MM-DD")
        tags = st.multiselect(
            "Tags (Optional)",
            board_tags(),
            accept_new_options=True,
            placeholder="Choose or Type a Tag",
        )
        submitted = st.form_submit_button("Add Task", type="primary")
    if submitted:
        if title.strip():
            st.session_state.board["backlog"].append(
                make_task(title.strip(), description.strip(), due, tags=tags)
            )
            save_changes()
            st.rerun()  # also closes the dialog
        else:
            st.warning("Title Can't Be Empty.")


if "board" not in st.session_state:
    st.session_state.board = load_board()
if "editing" not in st.session_state:
    st.session_state.editing = None

# Tint each card with its column's colour; containers with a key get a
# matching st-key-<key> CSS class
st.html(
    "<style>"
    + "".join(
        f'[class*="st-key-card_{column}_"] {{'
        f"background: rgba({tint}, 0.1); border-color: rgba({tint}, 0.35);}}"
        for column, (_, tint) in COLUMNS.items()
    )
    + "</style>"
)

st.title("📌 Kanban Board")

# New task button, then filter, sort and group controls
all_tags = board_tags()
with st.container(horizontal=True, vertical_alignment="bottom"):
    if st.button("New Task", icon=":material/add:", type="primary"):
        new_task_dialog()
    show_tags = st.multiselect(
        "Show Only Tags", all_tags, key="show_tags", placeholder="All Tasks"
    )
    hide_tags = st.multiselect(
        "Hide Tags", all_tags, key="hide_tags", placeholder="None Hidden"
    )
    sort_by = st.selectbox("Sort By", list(SORTS), key="sort_by", width=180)
    grouped = st.toggle("Group by Tag", key="group_by_tag")

# Each group sits in an expander so it can be collapsed. The stable key keeps
# the open/closed state when the task count in the label changes.
for col, (column, (heading, _)) in zip(st.columns(3), COLUMNS.items()):
    tasks = st.session_state.board[column]
    shown = visible_tasks(tasks, show_tags, hide_tags, sort_by)
    count = f"{len(shown)} of {len(tasks)}" if len(shown) < len(tasks) else len(tasks)
    with col, st.expander(
        f"{heading} ({count})", expanded=True, key=f"group_{column}"
    ):
        if column == "review" and tasks and st.button("🧹 Clear All Done"):
            st.session_state.board["review"] = []
            st.session_state.editing = None
            save_changes()
            st.rerun()
        groups = group_by_tag(shown, show_tags) if grouped else [(None, shown)]
        for tag, items in groups:
            if grouped:
                header = tag_badge(tag) if tag else "**No Tag**"
                st.markdown(f"{header} :small[{len(items)}]")
            for i, task in items:
                with st.container(
                    border=True, key=f"card_{column}_{i}", gap="small"
                ):
                    render_task(task, column, i)
