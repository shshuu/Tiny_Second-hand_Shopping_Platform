# Fresh-clone usability follow-up

## Scope and evidence boundary

An independent user performed the original Ubuntu 22.04 Desktop/VMware browser acceptance exercise. Codex did **not** access that VM. This document records the resulting findings and the corrective implementation, then distinguishes Codex's own Docker-based automated verification from the user's future browser re-acceptance.

## Findings and corrections

| Finding from the independent browser exercise | Correction |
|---|---|
| Host `./media` bind mount could be root-owned and block `appuser` uploads. | Compose now uses persistent `media_data` named volume. `docker-entrypoint.sh` initializes only media/static ownership, then runs Django as `appuser`. |
| Fresh DB had no categories. | Idempotent `seed_categories` command creates six active baseline categories. |
| Administrator preparation required pasting Python into a shell. | `promote_user` and `list_admin_users` management commands provide a constrained, auditable local setup path. |
| Local signup did not provide testable points by default. | `.env.example` enables the existing transaction-and-ledger based welcome promotion for local demonstrations. |
| Invalid wallet recipient caused a Django 404. | Wallet submission now returns a field error with no transaction, ledger, or balance mutation. |
| Product chat was not discoverable by both users. | Product detail creates/reuses a DIRECT room; `/chats/` lists it for both parties and the page opens WebSocket automatically. |
| Global chat was not a useful final product flow. | Public global-chat UI and public creation paths are removed. Existing historic GLOBAL records are retained as data but have no public consumer path. |

## Final direct-chat policy

- New rooms: buyer presses **판매자에게 채팅하기** on an ACTIVE product.
- Participants: the product seller and the initiating buyer only.
- Reuse: same product/seller/buyer returns the existing room.
- Blocked, RESTRICTED, or SUSPENDED accounts cannot create or transmit.
- SOLD, HIDDEN, DELETED, DRAFT, and RESERVED products cannot create a new room.
- Existing rooms remain visible after a product becomes SOLD/HIDDEN/DELETED for transaction follow-up and audit retention; hidden messages are not shown.

## Purchase-only points and persistent unread state

The prior public wallet transfer form is no longer a transaction entry point. Ordinary users can move points only by purchasing an ACTIVE product from its detail page or an existing participant direct-chat room. `purchase_product()` locks the product and wallets, records a `Purchase` and the append-only transaction/ledger entries, then changes the product to SOLD in one database transaction. RESERVED and SOLD products remain viewable but cannot be purchased; SOLD retains existing participant chats and refuses new chats.

`ChatReadState` stores one `(room, user)` read marker. The `/ws/unread/` authenticated WebSocket group sends only the recipient's total unread count; a reconnect receives the count recomputed from the database.

## Codex verification performed in this workspace

After rebuilding the Docker image, Codex ran the PostgreSQL/Redis suite in this local Docker environment:

```text
Found 105 test(s).
Ran 105 tests with both `WELCOME_BONUS_ENABLED=true` and `WELCOME_BONUS_ENABLED=false`
OK
```

It also confirmed that `appuser` could write to `/app/media` and that a marker survived a web-container restart through the named volume. This is not evidence of a VMware Ubuntu browser run.

The expected `Rate-limit backend unavailable for transfer` traceback in the suite is an intentional mocked Redis fail-closed test. It confirms a refused sensitive operation; it is not a live Redis outage and does not expose a traceback in an HTTP response.

## Required independent re-acceptance

Use the fresh-clone command and browser checklist in [README](../README.md). The independent verifier should run it without changing code, and report any mismatch before making a corrective change.

### Ubuntu 22.04 / Docker fresh-clone command sequence

The following is an **instruction for the independent verifier**. It was not run by Codex in a VMware guest.

```bash
git clone <your-repository-url> tiny-secondhand-platform
cd tiny-secondhand-platform
cp .env.example .env
docker compose down -v --remove-orphans
docker compose up -d --build
docker compose ps
docker compose logs -f web
# After migration completion and "Listening on TCP address", press Ctrl+C.
docker compose exec -T web python manage.py seed_categories
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check
docker compose exec -T web python manage.py migrate --check
```

The initial local role can be prepared only after that user has signed up:

```bash
docker compose exec -T web python manage.py promote_user <username> --role SUPERADMIN
docker compose exec -T web python manage.py list_admin_users
```

### Browser acceptance checklist

1. Create a seller; verify wallet shows the configured welcome transaction and point balance.
2. As seller, register a Korean-language product with one image and confirm the list thumbnail; make it ACTIVE.
3. Create a buyer in a second browser profile; verify the same welcome policy.
4. On product detail, select **판매자에게 채팅하기**; confirm both users find the same room under **채팅**.
5. Exchange real-time messages in both browsers and refresh each page to confirm persistence.
6. Transfer points to the seller; submit a nonexistent username and confirm an inline error with no balance change.
7. Change product to RESERVED and SOLD. Confirm SOLD cannot create a new chat, but the existing room remains listed and readable.
8. Confirm **내 스토어** shows only the seller's products and their statuses.
9. Select six images and confirm the immediate five-image client notice; then confirm the server still refuses more than five images.
10. Check `/admin/`, `/operations/`, logout, and an unknown URL: ordinary users must not reach Django admin/operations data, logout returns to `/login/`, and the unknown URL must be a safe user-facing 404 when using the localhost DEBUG=false demonstration setting.
11. Restart only web with `docker compose restart web` and confirm the image persists.
12. Run `docker compose exec -T web python manage.py test tests --noinput`; expected result is `Ran 105 tests ... OK`.

## Latest corrective follow-up

The browser-facing chat and unread scripts are external static files (`market/static/market/js/`) so the enforced CSP can retain `script-src 'self'` without `unsafe-inline`. `ChatReadState` rows with no timestamp, and historic rooms with no row, both mean unread received messages. The user reported VMware acceptance observations separately; Codex did not access that VM. Codex ran the corresponding Docker PostgreSQL/Redis suite with both welcome-bonus environment values.
