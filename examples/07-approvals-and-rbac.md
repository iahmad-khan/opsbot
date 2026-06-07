# Approvals & RBAC

OpsBot enforces role-based access control and requires human approval for dangerous operations.

---

## Role Hierarchy

| Role | Can execute | Can approve DESTRUCTIVE |
|---|---|---|
| `admin` | All operations | Yes |
| `sre` | READ + WRITE + DESTRUCTIVE (with approval) | Yes |
| `developer` | READ + WRITE | No |
| `readonly` | READ only | No |

> **Default role for new users is `developer`** (configurable via `DEFAULT_USER_ROLE`). New Slack users are auto-created with this role on first interaction.

---

## Managing Roles

### Via Slack

```
/opsbot rbac add @jane sre
/opsbot rbac add @bob admin
/opsbot rbac list
```

> **Caveat:** Full RBAC management is available via the web dashboard. The slash command currently redirects to the dashboard for role changes.

### Via the web dashboard

Navigate to the Users section of the dashboard and change the role dropdown.

### Via SQL (bootstrap)

When setting up for the first time, promote your Slack user ID to admin directly:

```sql
INSERT INTO users (slack_user_id, slack_username, role)
VALUES ('U012AB3CD', 'your-username', 'admin')
ON CONFLICT (slack_user_id) DO UPDATE SET role = 'admin';
```

---

## Approval Flow

When a user triggers a DESTRUCTIVE operation:

1. OpsBot posts a Slack message with **Approve / Deny** buttons to the thread.
2. Any `admin` or `sre` can click a button.
3. **The requester cannot approve their own request** (self-approval is blocked).
4. On approval, a Celery task executes the tool and posts the result.
5. On denial, the task is cancelled and a reason (if provided) is posted.
6. Approvals expire after `APPROVAL_TIMEOUT_MINUTES` (default 30 minutes).

---

## Approval Timeout

```env
APPROVAL_TIMEOUT_MINUTES=30
```

Expired approvals are cleaned up every 5 minutes by the Celery beat scheduler. The task status changes to `TIMED_OUT`.

---

## Dual Approval

Some operations require **two distinct approvers** before execution. Configured via:

```env
REQUIRE_DUAL_APPROVAL_FOR=delete_namespace,drop_database
```

Add any tool name (e.g., `terraform_destroy`, `k8s_drain_node`) to extend the list. The first approver sees "1 more approver needed" — the approval request stays open until the second approver clicks the button.

---

## Deployment Freeze Windows

Block DESTRUCTIVE operations on specific days/times (e.g., weekends, after business hours):

```env
# Block deployments on Saturdays and Sundays (all day)
FREEZE_DEPLOYMENT_DAYS=5,6
FREEZE_DEPLOYMENT_START_UTC=-1      # -1 = all day
FREEZE_DEPLOYMENT_MESSAGE=Weekend freeze in effect. Contact on-call for emergencies.

# Block deployments weeknights after 10pm UTC until 6am UTC
FREEZE_DEPLOYMENT_DAYS=0,1,2,3,4   # Mon–Fri
FREEZE_DEPLOYMENT_START_UTC=22
FREEZE_DEPLOYMENT_END_UTC=6
```

When a freeze is active, OpsBot refuses DESTRUCTIVE tool requests immediately (no approval button is shown) and tells the user why. Approvals already pending when a freeze starts are also blocked from being executed until the freeze ends.

---

## Approving from the Web Dashboard

The `/approvals` page lists all pending approval requests. Click **Approve** or **Deny** there. The `approver_slack_id` field defaults to empty — enter your Slack user ID (format: `U012AB3CD`) to record who approved it.

---

## Audit Trail

Every tool execution and approval decision is recorded in the `audit_logs` PostgreSQL table and visible in the `/audit` dashboard page. Columns include: actor, action, tool, args, risk level, success flag, timestamp.

Audit logs are purged after `AUDIT_LOG_RETENTION_DAYS` (default 90 days) by a nightly Celery beat task.

---

## Caveats

- **Approval messages in Slack show tool args.** The Block Kit card includes the full `tool_args` dict for the approver to review. Avoid embedding secrets or raw credentials in tool inputs — reference env vars or Vault paths instead.
- **Slack approval ≠ web dashboard approval.** Both work, but they update the same `Approval` record. A SELECT FOR UPDATE prevents double-execution if both buttons are clicked simultaneously.
- **Role changes take effect on next request.** The role is checked at task execution time, not at message receipt time.
- **No role inheritance.** Roles are flat — `sre` does not inherit `developer`; all permissions must match the role table above.
