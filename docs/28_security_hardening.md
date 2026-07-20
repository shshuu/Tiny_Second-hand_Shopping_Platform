# §28-10 Security hardening

## Mandatory application controls

- Administrator login uses a Redis-backed, fail-closed fixed-window counter keyed by a SHA-256 account-and-IP digest. The key and SecurityEvent detail never contain a password, session identifier, or Redis key. Intentional Redis-outage tests may write an application traceback to test logs; the HTTP response is a generalized 403 and never exposes that traceback.
- Production requires `DEBUG=false`, a non-development secret, a non-development PostgreSQL password, non-local `ALLOWED_HOSTS`, `DATABASE_URL`, `REDIS_URL`, and `DJANGO_TRUSTED_PROXY=true`.
- Production cookies are Secure, HttpOnly (session and CSRF), and SameSite=Lax. HTTPS redirects, HSTS, proxy HTTPS recognition, CSP, frame denial, MIME-sniffing protection, and a restrictive referrer policy are enabled.
- Django serves media only in DEBUG mode. Production media must be served by a non-executable object store or reverse proxy with an explicit content-type policy.

## Recommended follow-up

- Add an account-only administrator-login counter, an IP-only counter, and replace the fixed window with sliding-window or token-bucket limits.
- Add MFA for MODERATOR, ADMIN, and SUPERADMIN accounts.
- Export aggregated AuditLog/SecurityEvent metrics and alert on login failures, rate-limit failures, ledger mismatches, reversals, and administrator privilege changes.
- Pin and continuously scan Python dependencies and base-container images; use a secret manager rather than Compose example credentials.

## Operational deployment controls

- Terminate TLS at a trusted proxy, set `X-Forwarded-Proto: https`, and set `DJANGO_TRUSTED_PROXY=true` only for that trusted proxy network.
- Use a production database/Redis with network ACLs, TLS where available, backups, rotation, and non-default credentials.
- Configure the proxy to restrict media uploads to static bytes, set `X-Content-Type-Options: nosniff`, and prevent script execution from the media origin.
- The web container must be reachable only from the trusted proxy network. The proxy must remove any client-supplied `X-Forwarded-Proto` and set its own `https` value before forwarding. Do not publish the Django application port, PostgreSQL, or Redis ports directly in production.
- The checked-in Compose `8000:8000` mapping is a development-only convenience. Production deployment must omit that mapping and expose only the TLS proxy.

Example reverse-proxy media policy (the application does not serve this route in production):

```nginx
location /media/ {
    alias /srv/tiny-market-media/;
    types { image/jpeg jpg jpeg; image/png png; image/webp webp; }
    default_type application/octet-stream;
    add_header X-Content-Type-Options nosniff always;
    add_header Content-Security-Policy "sandbox" always;
    try_files $uri =404;
}
```

## Out of scope for this project

- MFA enrolment/recovery UI, SIEM integration, managed WAF/DDoS controls, production certificate provisioning, and organization-wide vulnerability-management infrastructure.
