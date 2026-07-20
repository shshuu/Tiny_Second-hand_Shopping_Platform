# Independent verification guide

## Purpose

Verify this repository from a clean environment without relying on prior conversations. Compare requirements, code, migrations, settings, and runtime behavior directly. Do not modify implementation code before reporting a discrepancy.

Read [the as-built design deviations record](as-built-design-deviations.md) alongside the original system design. It explains final structural and deployment-scope differences without replacing the original design baseline.

## System and preparation

The Compose runtime consists of Django/Daphne (`web`), PostgreSQL 16 (`db`), and Redis 7 (`redis`). PostgreSQL stores application and ledger data; Redis provides rate-limit counters and the Channels layer.

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check
docker compose exec -T web python manage.py migrate --check
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

For a clean local database, run `docker compose down -v` before starting.

## Full test command

```bash
docker compose exec -T web python manage.py test tests --noinput
```

Expected result: `Ran 73 tests ... OK` on PostgreSQL and Redis. Afterward, confirm the test DB is removed and no `admin-login:*` key remains in Redis.

## Main URLs

| Purpose | URL |
|---|---|
| Product list | `http://localhost:8000/` |
| Signup / login | `/signup/`, `/login/` |
| Wallet | `/wallet/` |
| Operations login | `/operations/login/` |
| Operations dashboard | `/operations/` |
| WebSocket room | `/ws/chat/<chat-room-public-id>/` |

## Suggested verification flows

### General user

1. Create two users and log in.
2. Register a product; verify list/search/detail and allowed sales-state changes.
3. Create a DIRECT room and exchange messages as both participants.
4. Block one participant and confirm chat transmission and transfer refusal.
5. Submit user, product, and message reports; compare stored target type/public ID.
6. Confirm `/wallet/` exposes only the signed-in user's transactions.

### Administrator

1. Create a local user and assign a least-privileged operations role through an approved local development procedure.
2. Confirm MODERATOR can process reports and hide product/message content but cannot grant or reverse points.
3. Confirm ADMIN can manage user status and protected wallet actions only with a reason and current-password reauthentication.
4. Confirm SUPERADMIN-only role management separately.
5. Inspect AuditLog/SecurityEvent without expecting passwords, session IDs, Redis keys, or message bodies.

### WebSocket

Use an authenticated browser session and connect to `ws://localhost:8000/ws/chat/<room-public-id>/`. Send `{"content":"hello"}`. Verify that sender identity is derived from the session and that nonparticipants, blocked users, and RESTRICTED/SUSPENDED users are refused.

## Expected Redis fail-closed log

Some tests deliberately inject a Redis backend failure. An application error log or stack output can appear during that test. This is expected: the request is rejected safely and the HTTP response does not disclose an internal exception, password, session identifier, or Redis key.

## Cleanup

```bash
docker compose down
```

To remove local Docker volume data as well:

```bash
docker compose down -v
```

Report discrepancies first with the exact command, observed output, relevant public ID, and affected path. Do not delete source, migrations, tests, or documentation during independent verification.
