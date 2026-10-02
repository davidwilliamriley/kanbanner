import uuid
from datetime import date

import streamlit as st

from auth import LINK_PARAM, log_out, remember_link, require_login
from store import StoreError, get_store, make_task

st.set_page_config(page_title="Kanban Board", page_icon="📌", layout="wide")

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
    "review": ("Archive", ":material/inventory_2:", "archive"),
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

# Where the board is saved is set by STORAGE in Streamlit Secrets; see store.py


def due_label(task, column):
    if not task["due"]:
        return ""
    due = date.fromisoformat(task["due"])
    label = f"📅 Due {due:%Y-%m-%d}"
    if column in ("backlog", "doing"):
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
    shown = [
        t
        for t in tasks
        if (not show_tags or set(t["tags"]) & set(show_tags))
        and not set(t["tags"]) & set(hide_tags)
    ]
    if SORTS[sort_by]:
        key, reverse = SORTS[sort_by]
        shown.sort(key=key, reverse=reverse)
    return shown


def group_by_tag(shown, show_tags):
    # A task sits under its first tag, or its first shown tag when filtering
    groups = {}
    for t in shown:
        tags = [tag for tag in t["tags"] if tag in show_tags] or t["tags"]
        groups.setdefault(tags[0] if tags else None, []).append(t)
    order = sorted((g for g in groups if g), key=str.casefold)
    return [(g, groups[g]) for g in order + ([None] if None in groups else [])]


def report(error):
    # Shown at the top of the next run, so a rerun right after doesn't hide it
    st.session_state.store_error = str(error)


def toggle_edit(task_id):
    # Only one card is open for editing at a time
    if st.session_state.editing == task_id:
        st.session_state.editing = None
    else:
        st.session_state.editing = task_id


def move_task(task_id, target):
    st.session_state.editing = None
    try:
        store.move(st.session_state.board, task_id, target, date.today())
    except StoreError as e:
        report(e)


def archive_all_done():
    st.session_state.editing = None
    try:
        store.archive_all(st.session_state.board, date.today())
    except StoreError as e:
        report(e)


def delete_task(task_id):
    try:
        store.delete(st.session_state.board, task_id)
    except StoreError as e:
        report(e)


def render_archived(task):
    lines = [f"**{task['title']}**"]
    if task["tags"]:
        lines[0] += " " + " ".join(tag_badge(tag) for tag in task["tags"])
    meta = [due_label(task, "archive")]
    if task.get("archived"):
        meta.append(f"Archived {task['archived']}")
    meta = " · ".join(m for m in meta if m)
    if meta:
        lines.append(f":small[{meta}]")
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown("\n\n".join(lines), width="stretch")
        st.button(
            "Restore",
            key=f"restore_{task['id']}",
            icon=":material/undo:",
            help="Move Back to Review",
            type="tertiary",
            on_click=move_task,
            args=(task["id"], "review"),
        )
        with st.popover("", icon=":material/delete:", help="Delete Permanently"):
            st.button(
                "Delete Permanently",
                key=f"delete_archived_{task['id']}",
                type="primary",
                on_click=delete_task,
                args=(task["id"],),
            )


def render_task(task, column):
    lines = [f"**{task['title']}**"]
    if task["description"]:
        # Markdown joins single line breaks into one line; a trailing double
        # space keeps each typed line on its own line
        lines.append("  \n".join(task["description"].splitlines()))
    if task["tags"]:
        lines.append(" ".join(tag_badge(tag) for tag in task["tags"]))
    meta = due_label(task, column)
    st.markdown("\n\n".join(lines))

    # Dates on the left and quick move / edit on the right share the last
    # line, wrapping onto two lines when the card is too narrow
    editing = st.session_state.editing == task["id"]
    with st.container(
        horizontal=True,
        vertical_alignment="center",
        gap="small",
        key=f"foot_{column}_{task['id']}",
    ):
        if meta:
            st.markdown(f":small[{meta}]", width="stretch")
        with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
            if column in QUICK_MOVES:
                label, icon, target = QUICK_MOVES[column]
                st.button(
                    label,
                    key=f"move_{task['id']}",
                    icon=icon,
                    type="tertiary",
                    on_click=move_task,
                    args=(task["id"], target),
                )
            st.button(
                "",
                key=f"toggle_{task['id']}",
                icon=":material/close:" if editing else ":material/edit:",
                help="Close" if editing else "Edit",
                type="tertiary",
                on_click=toggle_edit,
                args=(task["id"],),
            )
    if not editing:
        return

    with st.form(f"edit_{task['id']}"):
        title = st.text_input("Title", value=task["title"])
        description = st.text_area("Description", value=task["description"])
        due = st.date_input(
            "Due Date",
            value=date.fromisoformat(task["due"]) if task["due"] else None,
            format="YYYY-MM-DD",
        )
        # Streamlit's date picker can't be emptied once it starts with a date
        clear_due = task["due"] and st.checkbox("Remove Due Date")
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

    if delete:
        st.session_state.editing = None
        delete_task(task["id"])
        st.rerun()
    if save:
        if title.strip():
            updated = make_task(
                title.strip(),
                description.strip(),
                None if clear_due else due,
                task["created"],
                tags,
                id=task["id"],
            )
            st.session_state.editing = None
            try:
                store.update(st.session_state.board, task["id"], updated, status)
            except StoreError as e:
                report(e)
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
            task = make_task(title.strip(), description.strip(), due, tags=tags)
            try:
                store.add(st.session_state.board, task)
            except StoreError as e:
                report(e)
            st.rerun()  # also closes the dialog
        else:
            st.warning("Title Can't Be Empty.")


@st.dialog("Remember This Device")
def remember_device_dialog():
    token, link, days = remember_link(user)
    st.markdown(
        "Open the board with this link to skip logging in, even in browsers "
        "that don't keep the login. Tap **Put Link in Address Bar**, then "
        "bookmark the page or add it to your home screen."
    )
    st.warning(
        f"Anyone with this link can open your board, so keep it private. "
        f"It works for {days} days; changing your password cancels it."
    )
    st.code(link, language=None, wrap_lines=True)
    if st.button("Put Link in Address Bar", type="primary"):
        st.query_params[LINK_PARAM] = token
        st.rerun()  # also closes the dialog


user = require_login()


@st.cache_resource
def cached_store(secrets_items):
    return get_store(dict(secrets_items))


try:
    store = cached_store(tuple(sorted(
        (k, v) for k, v in st.secrets.items() if isinstance(v, str)
    )))
    if store.reload_each_run or "board" not in st.session_state:
        st.session_state.board = store.load()
except StoreError as e:
    # Never show (and later save) an empty board in place of the real one
    st.error(f"{e} Reload the Page to Try Again.")
    st.stop()
# A board opened before the archive or task ids existed may lack them
st.session_state.board.setdefault("archive", [])
for tasks in st.session_state.board.values():
    for t in tasks:
        t.setdefault("id", str(uuid.uuid4()))
if "editing" not in st.session_state:
    st.session_state.editing = None
if "store_error" in st.session_state:
    st.error(st.session_state.pop("store_error"))

# Tint each card with its column's colour; containers with a key get a
# matching st-key-<key> CSS class
st.html(
    "<style>"
    + "".join(
        f'[class*="st-key-card_{column}_"] {{'
        f"background: rgba({tint}, 0.1); border-color: rgba({tint}, 0.35);}}"
        for column, (_, tint) in COLUMNS.items()
    )
    # The toolbar lines controls up by their bottom edge; give the shorter
    # toggle a button-height box so it sits on the same centreline
    + ".st-key-group_by_tag {min-height: 2.5rem; display: flex;"
    " align-items: center;}"
    # Card footers: the dates may shrink (wrapping their text) so the buttons
    # stay on the same line, and the row only wraps below ~9rem of date room.
    # The buttons keep their width and hug the right edge either way.
    + '[class*="st-key-foot_"] > .stElementContainer'
    " {flex: 1 1 9rem; min-width: 9rem;}"
    + '[class*="st-key-foot_"] > [data-testid="stLayoutWrapper"],'
    ' [class*="st-key-foot_"] > [data-testid="stLayoutWrapper"] > div'
    " {flex: 0 0 auto; width: auto; margin-left: auto;}"
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
    if st.button("Remember Device", icon=":material/devices:"):
        remember_device_dialog()
    st.button(
        "Log Out",
        icon=":material/logout:",
        help=f"Logged in as {user}",
        on_click=log_out,
    )

# Each group sits in an expander so it can be collapsed. The stable key keeps
# the open/closed state when the task count in the label changes.
for col, (column, (heading, _)) in zip(st.columns(3), COLUMNS.items()):
    tasks = st.session_state.board[column]
    shown = visible_tasks(tasks, show_tags, hide_tags, sort_by)
    count = f"{len(shown)} of {len(tasks)}" if len(shown) < len(tasks) else len(tasks)
    with col, st.expander(
        f"{heading} ({count})", expanded=True, key=f"group_{column}"
    ):
        if column == "review" and tasks:
            st.button(
                "Archive All Done",
                icon=":material/inventory_2:",
                on_click=archive_all_done,
            )
        groups = group_by_tag(shown, show_tags) if grouped else [(None, shown)]
        for tag, items in groups:
            if grouped:
                header = tag_badge(tag) if tag else "**No Tag**"
                st.markdown(f"{header} :small[{len(items)}]")
            for task in items:
                with st.container(
                    border=True, key=f"card_{column}_{task['id']}", gap="small"
                ):
                    render_task(task, column)

# Archived tasks, newest first unless another sort is chosen
archived = st.session_state.board["archive"]
shown = visible_tasks(archived, show_tags, hide_tags, sort_by)
if not SORTS[sort_by]:
    shown.reverse()
count = f"{len(shown)} of {len(archived)}" if len(shown) < len(archived) else len(archived)
with st.expander(f"Archive ({count})", key="group_archive"):
    if not archived:
        st.caption("Archived Tasks Appear Here.")
    for task in shown:
        with st.container(border=True, key=f"archived_{task['id']}"):
            render_archived(task)
