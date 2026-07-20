# Security-event monitoring runbook

| Signal | Window / threshold | Severity | First response | False-positive check |
| --- | --- | --- | --- | --- |
| Admin login failure | 5 minutes / 10 | High | Check source IP and account, retain rate limit | Known password-reset window |
| Rate-limit or Redis fail-closed | 5 minutes / 3 | High | Check Redis health and deny-login continuity | Scheduled Redis maintenance |
| Admin session expiry or reauth failure | 15 minutes / 10 | Medium | Check clock, proxy, and account activity | Expected idle expiry pattern |
| Object authorization denial | 5 minutes / 20 | High | Review target public IDs and actor | UI retry or stale browser session |
| Ledger mismatch | Any event | Critical | Freeze affected wallet operations and investigate ledger | Never auto-correct balance |
| Grant or reversal | 1 hour / 10 | High | Review AuditLog reason and actor | Approved incident ticket |
| Automatic report action | 1 hour / 20 | Medium | Check report quality and abuse pattern | Legitimate incident burst |
| Audit mutation attempt | Any event | Critical | Preserve DB evidence and investigate access | No expected normal case |

The project stores source events in `SecurityEvent` and `AuditLog`. External alerting, retention,
and SIEM export are operational integrations, not application-side actions in this project.

## Deployment checks

Run `pip-audit` for Python packages and `docker scout cves <image>` or Trivy for the image in CI.
Inject production secrets through the orchestrator secret store or read-only secret files; do not
place them in Compose, the image, build context, or application logs.
