# As-built design deviations and implementation scope

## 1. Purpose

The original system design remains the baseline document and is not replaced by this file. Its core functional and security requirements are retained. This document explains implementation structure and deployment-scope differences that arose while building the final project, so an independent reviewer does not interpret a structural difference alone as a missing requirement.

This is an as-built record: it describes the final repository and distinguishes verified application behavior from future operating-environment work.

## 2. Django application structure

The original design recommended separate feature applications such as accounts, products, chat, and wallet. For this small assignment repository, those domains are consolidated in one Django app, `market`.

Responsibility is still separated inside that app:

| Module | Responsibility |
|---|---|
| `models.py` | Persistent domain models, constraints, public identifiers |
| `services.py` | Atomic domain operations and authorization rules |
| `views.py` | General-user HTTP flows |
| `admin_views.py` | Role-restricted operations UI |
| `consumers.py` | WebSocket chat entry point |
| `middleware.py` | Administrator session and response-security controls |

The single-app layout does not remove the functional or server-side security requirements.

## 3. Execution architecture and deployment boundary

Local execution is:

```text
Browser → Django + Daphne → PostgreSQL 16 / Redis 7
```

Docker Compose services are `web`, `db`, and `redis`. The development Compose file publishes `web` on port 8000 for local use; PostgreSQL and Redis have no external host-port publication in that file.

Local Compose does not include Nginx or a real TLS certificate. Production requires an external TLS proxy or Nginx in front of Django. The Django, PostgreSQL, and Redis internal ports must not be directly exposed publicly. That proxy must remove client-supplied `X-Forwarded-Proto` and set its own trusted HTTPS value.

## 4. ASGI and WebSocket

The final implementation uses Daphne with Django ASGI. `ProtocolTypeRouter`, `AuthMiddlewareStack`, and `URLRouter` route HTTP and WebSocket traffic. Django Channels uses a Redis Channel Layer.

Chat WebSocket connections use `/ws/chat/<chat-room-public-id>/`. The Consumer persists messages through the same service-layer message policy used by HTTP paths, rather than trusting client-provided sender identity. Authentication, room membership, user state, blocking, size, empty-content, and rate-limit checks therefore apply across both transports.

## 5. Administration structure

The project uses a dedicated `/operations/` operations UI rather than relying on direct Django admin model edits. Roles are `USER`, `MODERATOR`, `ADMIN`, and `SUPERADMIN`.

- Direct Django-admin creation of ordinary users is not the supported creation path.
- Important operations use the service layer, reason capture, object-level authorization, POST/CSRF, and where required current-password reauthentication.
- The operations scope includes AuditLog/SecurityEvent review, report assignment, report transition, protected direct-chat review, administrator grants, and transaction reversal.
- Wallet balance, transactions, ledgers, and audit logs are not directly editable by operations roles.

## 6. User, profile, and wallet creation

`register_user()` is the common atomic creation service. It creates the user, profile, a 0P wallet, and an optional welcome bonus transaction/ledger entry in one transaction. Administrator-driven creation uses `create_user_by_admin()`, which delegates to that common registration flow and then applies allowed role policy.

The implementation intentionally does not use a `post_save` wallet-generation signal. A wallet is never created with a client- or administrator-supplied initial balance.

## 7. Wallet and ledger model

`Wallet.balance` is the current-balance cache. `LedgerEntry` is the evidence for each point movement, and `verify_wallet()` compares the aggregate ledger result with that cache. A mismatch creates a SecurityEvent; it is not automatically corrected.

Wallet transaction and ledger UPDATE/DELETE operations are blocked by PostgreSQL triggers. A reversal does not alter an original transaction: it creates a separate opposite-direction `REVERSAL` transaction and entries.

## 8. Image upload and media serving

JPEG, PNG, and static WebP input is decoded, validated, and safely re-encoded. The processing removes EXIF/other metadata and uses UUID-based server filenames. It verifies format/MIME/extension consistency and rejects invalid file size, count, resolution, pixel count, animation policy violations, and decompression-bomb risks.

When `DEBUG=False`, Django does not register direct media-serving URL patterns. Production media must be served from a non-executable proxy or object-storage boundary with suitable `nosniff` and script-execution controls. Local development media serving is not a production media architecture.

## 9. Reporting and restriction policy

The implementation supports reports for users, products, and messages. It rejects invalid target type/ID pairs, self-reporting as defined by target policy, duplicate reporter-target reports, and rate-limit abuse.

Distinct valid reporter accumulation can apply temporary `HIDDEN` to a product or `RESTRICTED` to a user. It does not perform automatic permanent deletion. Administrators can transition report state, apply/recover relevant moderation actions, and leave audit records. Report assignment uses `assignment_version` optimistic concurrency to resolve simultaneous assignment requests.

## 10. Security settings

- Production startup validates `ALLOWED_HOSTS`, HTTPS-only CSRF trusted origins, non-development secrets and DB credentials, URLs, and trusted-proxy policy.
- HTTPS redirect, HSTS, Secure/HttpOnly/SameSite cookies, CSP, `nosniff`, Referrer-Policy, Permissions-Policy, and frame protection are enabled by settings/middleware.
- Redis errors on sensitive rate-limited functionality use fail-closed behavior; the client receives a generalized response.
- After independent verification identified missing public authentication limits, signup POST now uses a SHA-256 IP Redis counter before user creation; public-login failures use SHA-256 account+IP and IP-only counters, with success reset and fail-closed backend behavior.
- Actual HSTS preload registration and real TLS certificates are deployment tasks, not actions completed solely by application settings.

## 11. Tests and migrations

The initial final PostgreSQL/Redis result was 73/73. Independent verification then identified two High public-authentication rate-limit gaps. The corrective follow-up added four tests and the final result is **77/77 passed**, with no failures, errors, skips, or exclusions. Migrations remain `0001_initial` through `0005_report_assignment`.

After the submission-document cleanup, functional source code, Compose, settings, migrations, and tests were not changed; the full suite was therefore not rerun solely for documentation changes.

## 12. Recommended tools versus completed verification

Only actual automated or recorded verification is described as complete. The repository does not claim completion for tools where no execution evidence is recorded. In particular, Bandit, Ruff, Semgrep, pip-audit, ZAP, Dependabot, hosted secret scanning, and equivalent external scanners remain follow-up/CI/operational verification unless separately run and documented.

## 13. Completed scope

- Application implementation and server-side security controls
- Local Docker Compose PostgreSQL/Redis runtime
- PostgreSQL/Redis automated integration testing
- Production-settings validation and security-response tests
- Repository, operations, and independent-verification documentation

## 14. Deployment-stage work remaining

The following are outside the completed local application scope and must be verified for a real deployment:

- Server or cloud infrastructure, domain configuration, and real TLS certificates
- Nginx or cloud proxy configuration and trusted network boundary
- Firewall, security group, and network ACL policy
- Secret-manager credential injection
- Production database backup, restore, and recovery exercises
- Administrator MFA
- SIEM/external logging, alert delivery, and operational security scanning
