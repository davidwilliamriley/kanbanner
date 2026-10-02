-- The board's table in Neon. The app and migrate_to_neon.py create it
-- automatically if it doesn't exist, so running this by hand is optional.
create table if not exists tasks (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    description text not null default '',
    due date,
    created date default current_date,
    tags text[] not null default '{}',
    status text not null
        check (status in ('backlog', 'doing', 'review', 'archive')),
    position bigint not null default 0,  -- order within its column
    archived date,                       -- when it was archived
    updated_at timestamptz not null default now()
);
create index if not exists tasks_status_position on tasks (status, position);
