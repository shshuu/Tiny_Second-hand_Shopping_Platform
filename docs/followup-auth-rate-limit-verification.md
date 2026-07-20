# Follow-up authentication rate-limit verification

## Independent verification finding

The independent clean-clone verification passed PostgreSQL/Redis startup, migrations, Django checks, the previous 73 tests, registration/wallet creation, and authenticated WebSocket behavior. It also found two High issues before this follow-up:

1. Public `POST /signup/` had no request rate limit.
2. Public `SafeLoginView` had no repeated failed-login rate limit.

This document preserves that finding and records the corrective verification; it does not overwrite the earlier independent-verification guide or evidence.

## Corrective design

### Signup

- Only `POST /signup/` is counted; GET does not consume a counter.
- A Redis fixed-window counter is checked before form validation and before `register_user()`.
- Key format is `public-rate:signup-ip:<sha256>`; it contains no raw IP or form input.
- Default policy: `SIGNUP_RATE_LIMIT=5` in `SIGNUP_RATE_LIMIT_WINDOW_SECONDS=600`.
- Counter/backend failure is fail-closed with a generic 429 response. No user, profile, wallet, or welcome transaction is created for the refused request.

### Public login

- Only failed `POST /login/` authentication attempts increment counters; GET is free.
- Keys use SHA-256 digests for account+IP and IP-only buckets. No raw username or IP is included in a Redis key.
- Default policy: account+IP `LOGIN_FAILURE_RATE_LIMIT=5`; IP-only `LOGIN_FAILURE_IP_RATE_LIMIT=20`; shared `LOGIN_FAILURE_RATE_LIMIT_WINDOW_SECONDS=300`.
- Before authentication, an already exhausted bucket receives the same generic 429 response regardless of whether the username exists.
- A successful login deletes both relevant failure counters. Redis read/write/delete failure is fail-closed and returns the same generalized 429 response.
- SecurityEvent details retain only a secondary digest, never password, session ID, raw username, raw IP, or Redis key.

## Verification result

`tests/test_public_auth_rate_limits.py` adds four PostgreSQL/Redis integration tests:

- signup limit, DB non-creation, GET exemption, independent IPs, real Redis TTL, and backend fail-closed
- login repeated failures, unknown-account parity, hash-key privacy, successful-login reset, GET exemption, real Redis TTL, and backend fail-closed

After a cacheless dependency image build, the full suite ran **77/77 passed** in 88.226 seconds. No failures, errors, skips, or exclusions occurred. The expected fail-closed Redis exception log in an existing wallet test did not expose an internal exception to HTTP clients.
