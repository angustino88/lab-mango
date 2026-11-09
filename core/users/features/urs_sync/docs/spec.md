# Feature Specification: URS Directory Synchronization (`core/users/features/urs_sync`)

## 1. Domain Overview & Purpose
Provides background synchronization with the enterprise Bosch URS (User Rights Service) REST API, reconciling directory memberships, user provisioning, and role assignments against local authorization groups.

---

## 2. Invariants & Reconciliation Policies

1. **Token Authentication:**
   - Requires configured `URS_ACCESS_TOKEN` and endpoint `URS_API_URL` (`https://rb-pandora-n1.bosch.com:15000/service/info`). Fails closed if token is missing.
2. **Membership Synchronization:**
   - Users present in external URS group response are added to the corresponding local Django `Group`.
   - Users removed from external URS group are batch-removed from the local group.
   - Local superusers remain members of their mapped groups even when absent from the URS response.
3. **Just-In-Time Provisioning:**
   - Auto-creates stub accounts (`is_urs_managed=True`) for unknown valid corporate usernames discovered in URS responses.
4. **Deactivation Policy:**
   - URS-managed non-superusers who retain zero group memberships after synchronization are automatically deactivated (`is_active=False`) to prevent orphaned access. Superusers are exempt even when they have no groups.

---

## 3. Scheduled Tasks & Ingestion Logic

- Triggered via Celery periodic task (`core.users.tasks.sync_urs_groups_task`).
- Runs over active `URSGroup` querysets, logging sync metrics and connection failures without aborting unrelated transactions.
