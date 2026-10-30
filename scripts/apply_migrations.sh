#!/usr/bin/env bash
# Applies the supabase/migration-*.sql files that have not been applied yet, in file-name (= date) order.
# Each file runs in ONE transaction (all or nothing) and is then noted in public.applied_migrations, so it
# is never run twice. Needs SUPABASE_DB_URL (the Supabase "Session pooler" connection string).
# Without it, nothing happens (exit 0): the automatic migrations stay off until the secret is added.
# Usage: scripts/apply_migrations.sh [--dry-run]   (dry run: only lists what would be applied)
set -euo pipefail

cd "$(dirname "$0")/.."
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

if [ -z "${SUPABASE_DB_URL:-}" ]; then
  echo "SUPABASE_DB_URL is not set: automatic migrations are off. Nothing done."
  exit 0
fi

export PGOPTIONS="-c client_min_messages=warning"
psql_q() { psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -X -q -t -A "$@"; }

# The log table. Row level security without any policy: the site's public API cannot read or write it.
psql_q -c "create table if not exists public.applied_migrations (
             file text primary key, applied_at timestamptz not null default now());
           alter table public.applied_migrations enable row level security;"

done_list=$(psql_q -c "select file from public.applied_migrations")
todo=()
for f in $(ls supabase/migration-*.sql | sort); do
  name=$(basename "$f")
  if ! grep -qxF "$name" <<<"$done_list"; then todo+=("$f"); fi
done

if [ ${#todo[@]} -eq 0 ]; then echo "Nothing to apply: every migration file is already noted."; exit 0; fi

for f in "${todo[@]}"; do
  name=$(basename "$f")
  if [ "$DRY" = 1 ]; then echo "Would apply: $name"; continue; fi
  echo "Applying $name ..."
  # without the byte order mark some Windows editors put first: psql reads it as a syntax error
  { echo "begin;"; sed '1s/^\xEF\xBB\xBF//' "$f"; echo; echo "insert into public.applied_migrations(file) values ('$name');"; echo "commit;"; } \
    | psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -X -q
  echo "  done: $name"
done
