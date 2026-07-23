# Final requirements traceability

| Requirement | URL / implementation | Permission | Automated verification | Manual verification |
|---|---|---|---|---|
| Account, profile | `/signup/`, `/profile/`, `/mypage/` | authenticated owner | auth/profile tests | sign up and edit profile |
| Product and search | `/`, `/products/new/`, `/store/` | public / owner | product and search tests | Korean/category search |
| Community chat | `/community/`, `/ws/community/` | active send; restricted read | community tests | two-browser live exchange |
| Direct chat | `/chats/`, `/ws/chat/<id>/` | room participants | websocket tests | product chat flow |
| Reports | `/reports/...`, `/operations/reports/` | reporter / operations roles | report tests | report and review |
| Automatic moderation | `AutoModerationCase` | active reporters / operators | auto moderation tests | review pending case |
| Purchase settlement | `Purchase`, ledger services | buyer / seller | purchase tests | purchase ACTIVE product |
| Operations | `/operations/` | role guarded | operations tests | category and product detail |

## Policies

- Three distinct active reporters temporarily hide an ACTIVE or RESERVED product. Five distinct active reporters temporarily restrict an ACTIVE user.
- A rejected automatic case restores its recorded prior state only if the target still has the automatic action state. Later manual changes are not overwritten.
- RESTRICTED users can sign in and view public data, but cannot create/edit products, purchase, create/send chat messages, post community messages, or submit reports.
- Community messages are intentionally excluded from direct-chat unread counters.
- AuditLog is append-only. `actor`, `action`, `target`, `reason`, and `created_at` are preserved; the operations UI resolves human-readable target labels when the target still exists and otherwise shows a safe fallback.
- Categories are never physically deleted in operations. Inactive categories remain on existing products but are excluded from new product forms.

## Migration and verification

Apply migrations through `0009_automoderationcase_reviewing` after the normal Compose startup. Use `seed_categories` once for a fresh database. `makemigrations --check` and `migrate --check` must both be clean. An upgrade from 0006 preserves existing user, product, chat, report, purchase, transaction, and ledger rows; 0007 creates the automatic-case table, 0008 adds nullable reviewer-assignment fields, and 0009 adds the explicit REVIEWING state. Reversing to 0006 removes automatic-case records, so it is a maintenance operation rather than a production rollback strategy.

## Operations workflow and audit presentation

- An automatic case starts as **PENDING / unassigned**. Any active MODERATOR, ADMIN, or SUPERADMIN may assign an active operator. Assignment uses an optimistic version to reject stale concurrent updates.
- **Start review** needs no reason and automatically assigns the current operator when no assignee exists. **Accept** and **reject** require a non-blank reason. Completed cases render a read-only result and reject subsequent POSTs.
- ADMIN and SUPERADMIN manage categories. Categories are created/edited/activated/deactivated rather than deleted; inactive categories remain attached to existing products but do not appear in new-product forms.
- Operations product detail is role-guarded and shows product, seller, images, reports, automatic cases, and related transactions for every product status.
- AuditLog is immutable. The UI resolves product, user, report, automatic-case, chat-message, and category targets into Korean labels and operation links when possible. A deleted target is shown as a safe fallback with its retained identifier.

## Public search and point policy

Product search accepts `q` across title, description, and category name, and can combine a category filter. ACTIVE, RESERVED, and SOLD results are public; DRAFT, HIDDEN, and DELETED records are excluded. Template escaping protects displayed queries and content.

Tiny Market points are demonstration-only internal credits: they are not cash, electronic money, deposits, withdrawals, or refunds. Settlement occurs only inside the atomic product-purchase service; the ordinary P2P transfer UI and endpoint are unavailable.

## VMware-focused acceptance checklist

The VMware Ubuntu browser acceptance test is performed by the user, not Codex: create seller/buyer/reporter accounts; seed categories; publish an item; exchange direct and community messages; report a community message and a product; verify three product reporters hide it and five user reporters restrict the account; review the automatic case; verify inactive categories disappear from new-product selection; test product/category search; and confirm purchase settlement and existing direct-chat unread behavior.
