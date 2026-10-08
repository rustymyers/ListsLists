# ListsLists

ListsLists is a self-hosted FastAPI application for creating, organizing, sharing, resolving, and exporting contextual lists. Version 1 uses server-rendered Jinja templates enhanced with HTMX, PostgreSQL in production, and SQLite for local development.

## Version 1 scope

Implemented:

- Stable UUIDs and human-readable list slugs
- Private, shared, unlisted, and public lists
- Owner, editor, and viewer access
- Ordered items with quantities, units, categories, tags, location, context, notes, required/optional state, JSON custom metadata, and simple dependencies
- Reusable nested-list references with write-time and resolution-time cycle detection
- Read-only recursive flattening, optional-item filtering, duplicate merging, quantity combination, sorting, source preservation, conflict strategies, and a safe quantity multiplier/rounding calculation
- JSON and UTF-8 CSV export; reusable export profiles
- Search/filter APIs, pagination, item copy/move/reorder, list duplication/archive/soft-delete, shares and revocation
- Local Argon2 password authentication, signed browser sessions, bearer JWTs, single-use expiring reset tokens, and trusted-proxy identity mode for Authelia
- CSRF protection on HTML form posts and route/service permission checks
- Audit events, bootstrap administration, user management, SMTP tests, and health endpoints
- Alembic migration, Podman Compose, backup/restore instructions, and automated security/resolution tests

Deferred: graphical rule builder, organization multi-tenancy, arbitrary formulas, OAuth providers, PDF export, and real-time co-editing.

## Nested-list permission policy (security decision)

ListsLists uses **strict non-inheritance**:

1. Access to a parent does not grant access to a nested list.
2. During preview or export, the acting user must independently be able to view every referenced list. A public nested list is viewable by anyone; otherwise the user must be its owner, administrator, or explicit viewer/editor.
3. Unlisted-link access applies only to the root browser URL. It is not inherited while traversing references. Therefore, a public or unlisted parent cannot silently expose a private, shared, or merely-unlisted child.
4. If any nested list is inaccessible, resolution fails as a whole with a generic 403. Partial results and the inaccessible list's identity are not returned; item read APIs also suppress inaccessible nested UUIDs.
5. Editors may create or move a reference only when they can independently view the target. Consumers must still have independent read access at resolution time, so later revocation takes effect immediately.

This conservative model prevents accidental disclosure. A future release could add explicit, auditable snapshot or delegated-inclusion modes.

## Export formats chosen for v1

- **JSON:** lossless structured output with list metadata, arrays for tags and source IDs, and custom metadata objects.
- **CSV:** spreadsheet-friendly flattened rows. Multi-value fields are semicolon-delimited; custom metadata is compact JSON.

Exports never mutate source lists. Duplicate identity is `identity_key` when explicitly supplied, otherwise the item's stable UUID. Repeated paths to the same reusable item therefore merge reliably. Quantity merging refuses incompatible units. Conflict handling can keep the first record, keep the last, or fail.

## Quick start with Podman Compose

```bash
cp .env.example .env
# Edit .env and replace all placeholders, including POSTGRES_PASSWORD,
# LISTSLISTS_SECRET_KEY, and LISTSLISTS_BOOTSTRAP_ADMIN_PASSWORD.
podman compose up -d --build
```

Open `http://localhost:8000`. On the very first startup, if no accounts exist:

- Set `LISTSLISTS_BOOTSTRAP_ADMIN_PASSWORD` in `.env`; it is used for the initial administrator account.
- Startup fails with a clear error if no account exists and the password is not configured.
- The configured password is not logged or written to a separate file.

## Local development

Requires Python 3.12+.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
mkdir -p data
export LISTSLISTS_ENVIRONMENT=development
export LISTSLISTS_DATABASE_URL=sqlite:///./data/listslists.db
export LISTSLISTS_SECRET_KEY='development-secret-change-me'
alembic upgrade head
uvicorn app.main:app --reload
```

Run verification:

```bash
pytest
ruff check app tests
```

### Import canonical items from CSV

Use [scripts/import_items_example.csv](./scripts/import_items_example.csv) as a template:

```bash
python scripts/import_items_csv.py scripts/import_items_example.csv --owner admin --dry-run
python scripts/import_items_csv.py scripts/import_items_example.csv --owner admin
```

The importer never updates existing items or lists. For the selected owner, it skips a row when
its `identity_key` already exists. Rows without an `identity_key` are skipped when an item with
the same case-insensitive name and unit already exists.

Set `list_name` to add an item to a list. The importer adds the item to one exact
case-insensitive matching list owned by the selected user, or creates that list when it does not
exist. `list_description` and `list_visibility` (`private`, `shared`, `unlisted`, or `public`)
are used only when creating the list. Use `quantity`, `packing_spot`, and `is_required` for
list-specific placement data. A canonical item is added to a given list only once.

Reset Containers:

```bash
podman compose down --volumes --remove-orphans
```

### Logs

Get logs from the app quickly with:

```bash
podman compose logs app
```

## Authentication

### Local mode

Set `LISTSLISTS_AUTH_MODE=local`. Passwords are Argon2-hashed. Form sessions use a signed, HTTP-only cookie. Set `LISTSLISTS_SESSION_HTTPS_ONLY=true` behind HTTPS. API clients obtain a time-limited bearer token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=admin&password=YOUR_PASSWORD'
```

### Authelia / trusted reverse-proxy mode

Set `LISTSLISTS_AUTH_MODE=proxy` or `both`, configure `LISTSLISTS_TRUSTED_PROXY_CIDRS`, and have the proxy set `Remote-User` and optionally `Remote-Email`. Headers are ignored unless the immediate peer address is in a configured network. Never put the app directly on an untrusted network in proxy mode.

Identity mapping is deterministic: `Remote-User` case-insensitively matches the local `username`. If enabled, first contact creates a non-admin local record with `auth_source=proxy`; `Remote-Email` is used when present. Renaming an upstream identity does not automatically merge accounts.

Example Authelia proxy headers:

```nginx
proxy_set_header Remote-User $upstream_http_remote_user;
proxy_set_header Remote-Email $upstream_http_remote_email;
proxy_pass http://listslists:8000;
```

Only trust proxy CIDRs you control. Also set Uvicorn's forwarded-IP allow list through `LISTSLISTS_FORWARDED_ALLOW_IPS` where appropriate.

## API and browser URLs

- OpenAPI UI: `/docs`
- OpenAPI JSON: `/openapi.json`
- Browser list URL: `/l/{slug}`
- API list URL: `/api/v1/lists/{uuid}`
- API item URL: `/api/v1/items/{uuid}` (mutation routes)
- Health: `/healthz`

Collection endpoints accept bounded `limit` and `offset`; list/item searches support `q`, categories, tags, and archive state. Full request models and examples are visible in OpenAPI.

## SMTP and secrets

Configure SMTP only through environment values or an external container secret injector. SMTP credentials are never stored in the database. Password-reset links are random, SHA-256-hashed at rest, single-use, and expire after `LISTSLISTS_PASSWORD_RESET_MINUTES` (30 by default).

Production secret recommendations:

- Inject `LISTSLISTS_SECRET_KEY`, database password, and SMTP password using your orchestrator's secret facility. Configure `LISTSLISTS_BOOTSTRAP_ADMIN_PASSWORD` in `.env` before the first startup.
- Do not commit `.env`.
- Rotate the application secret deliberately: existing sessions and API tokens will be invalidated.

## Backup and restore

### Admin JSON export and import

The **Administration** page provides an application-data JSON export and a replacement import.
The export includes users, lists, canonical items, list placements, shares, dependencies, and
export profiles. It deliberately excludes password hashes, password-reset tokens, audit history,
and application settings.

Importing requires typing `REPLACE`, retains the active administrator account, and replaces the
exported data categories. Local users must reset their passwords after import. Protect exports as
sensitive data because they contain user email addresses and private list content.

### PostgreSQL

```bash
./scripts/backup.sh ./backups
podman compose down
./scripts/restore.sh ./backups/listslists-YYYYMMDD-HHMMSS.sql.gz
# Restore the app_data archive produced with the same timestamp.
podman compose up -d
```

Backups contain sensitive data. Encrypt them, restrict access, copy them off-host, and test restores. See script comments for exact behavior. Back up the database and `/data` as one recovery set.

### SQLite development

Stop the app and copy `data/listslists.db` and `data/`. Do not copy a live SQLite file without using SQLite's online backup mechanism.

## Operational notes

- Run migrations before every release (`alembic upgrade head`); the container entrypoint does this automatically.
- `/healthz` verifies database connectivity and returns 503 when degraded.
- Audit data is append-only through the application but should also be protected at the database and backup layers.
- Soft-deleted lists are hidden. A future retention job may purge them after policy review.
- Rate limiting, malware scanning for future uploads, and centralized observability should be added at the reverse proxy/platform layer before Internet exposure.

## License

No license has been selected. Add one before public distribution.
