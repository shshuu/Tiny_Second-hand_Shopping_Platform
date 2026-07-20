# §28-3 / §28-8 wallet and transfer verification

Wallet creation and every point movement are handled by `market.services` transactions.
`register_user()` creates the user, profile, and a zero-balance wallet before an optional
`WELCOME_BONUS` transaction and ledger entry. There is no `post_save` wallet creation path.

## Limits and rate limiting

The environment variables below are validated at Django startup. They must be positive integers;
amount limits are capped at 1,000,000,000 and per-minute request limits at 10,000. Invalid,
zero, negative, or oversized values stop startup rather than silently weakening controls.

| Variable | Default |
| --- | ---: |
| `TRANSFER_MAX_AMOUNT` | 10,000 |
| `TRANSFER_DAILY_LIMIT` | 50,000 |
| `TRANSFER_RATE_LIMIT_PER_MINUTE` | 5 |
| `ADMIN_GRANT_MAX_AMOUNT` | 100,000 |
| `ADMIN_GRANT_DAILY_LIMIT` | 500,000 |
| `ADMIN_GRANT_RATE_LIMIT_PER_MINUTE` | 5 |

Transfer daily totals are calculated only from `USER_TRANSFER` records whose `created_at` is
on or after midnight in Django's `TIME_ZONE` (`Asia/Seoul`). Administrator daily limits are
per administrator and include only that administrator's `ADMIN_GRANT` records.

Redis limits use the key `rate:{action}:{user_id}:{YYYYMMDDHHMM}`, with a 70-second TTL
(overridable only for integration tests). This is a fixed-window algorithm: requests can cluster
around a minute boundary. A production financial service should evaluate a sliding-window or
token-bucket limiter before relying on this policy.
The counter uses Redis `add` then `incr`, so requests through separate web processes share one
atomic count. Every service entry request, including a request that later fails validation or is
an idempotent replay, consumes a rate-limit slot. Redis errors are fail-closed: the request is
rejected with a generalized retry message and an application error is logged; no fail-open
path is used.

External side effects are scheduled through `transaction.on_commit()`. In-app notifications are
created by that callback, so a rolled-back wallet transaction creates no notification.

Database transaction conflicts are not automatically retried. The wallet view returns a
generalized retry message and logs `OperationalError`; callers can safely reuse their
idempotency key.
