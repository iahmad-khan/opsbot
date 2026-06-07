# Additional Integrations

Configuration and example commands for Jira, Confluence, OpenSearch, Bitbucket, GitLab, PagerDuty, OpsGenie, and Datadog.

---

## Jira

```env
JIRA_URL=https://your-org.atlassian.net       # Cloud; or self-hosted URL
JIRA_USERNAME=you@your-org.com                # Cloud: email; Server: username
JIRA_API_TOKEN=ATATT3x...                     # Cloud: API token; Server: password or PAT
JIRA_DEFAULT_PROJECT=OPS
```

**Example commands:**

```
@opsbot search Jira for open bugs in OPS project
@opsbot get Jira issue OPS-1234
@opsbot create a Jira bug in OPS: "checkout-api OOM in prod" label incident
@opsbot transition OPS-1234 to In Progress
@opsbot assign OPS-1234 to @jane
@opsbot add comment to OPS-1234: "Root cause identified - rollback complete"
```

> **Caveat:** Jira Cloud uses API tokens; Jira Data Center/Server uses passwords or PATs. Ensure `JIRA_USERNAME` is the email address (Cloud) or username (Server), not the display name.

---

## Confluence

```env
CONFLUENCE_URL=https://your-org.atlassian.net    # Cloud; or self-hosted URL
CONFLUENCE_USERNAME=you@your-org.com
CONFLUENCE_API_TOKEN=ATATT3x...
CONFLUENCE_DEFAULT_SPACE=ENG
```

**Example commands:**

```
@opsbot search Confluence for "deployment runbook"
@opsbot get the Confluence page about on-call procedures
@opsbot create a Confluence page in ENG space: "Incident Report 2026-06-07" with content "..."
@opsbot update the runbook page OPS-123 to add rollback instructions
@opsbot append to the incident log page: "14:44 UTC - checkout-api rolled back to v2.3.0"
```

---

## OpenSearch / Elasticsearch

```env
OPENSEARCH_URL=http://opensearch.logging.svc:9200
OPENSEARCH_USERNAME=admin
OPENSEARCH_PASSWORD=admin
OPENSEARCH_DEFAULT_INDEX=logs-*
OPENSEARCH_VERIFY_SSL=true
# Or use API key auth:
OPENSEARCH_API_KEY=base64encodedkey==
```

**Example commands:**

```
@opsbot search logs for checkout-service errors in the last 30 minutes
@opsbot show error summary for payments-api
@opsbot count 5xx events for checkout-api in the last hour
@opsbot find slow queries taking more than 2 seconds in the last 15 minutes
@opsbot list log indices
```

> **Caveat:** The OpenSearch MCP server defaults to `logs-*` index pattern. If your indices use a different naming scheme, set `OPENSEARCH_DEFAULT_INDEX` to match (e.g., `filebeat-*`, `k8s-logs-*`).

> **Caveat:** `OPENSEARCH_VERIFY_SSL=false` is required for self-signed certificates. Do not disable SSL verification in production if your OpenSearch is internet-exposed.

---

## Bitbucket

```env
# Bitbucket Cloud
BITBUCKET_URL=https://api.bitbucket.org/2.0
BITBUCKET_USERNAME=your-username
BITBUCKET_APP_PASSWORD=your-app-password
BITBUCKET_WORKSPACE=my-workspace

# Bitbucket Server / Data Center
BITBUCKET_URL=https://bitbucket.your-company.com
BITBUCKET_TOKEN=your-personal-access-token
BITBUCKET_WORKSPACE=
```

**Example commands:**

```
@opsbot list repos in Bitbucket
@opsbot show open PRs in checkout-service on Bitbucket
@opsbot get pipeline status for checkout-service branch main
@opsbot trigger the deploy pipeline on checkout-service for branch release/v2
@opsbot create PR in checkout-service: "fix: connection pool leak" from hotfix/conn-pool to main
@opsbot merge PR #47 in checkout-service
```

> **Caveat:** Bitbucket Cloud uses app passwords, not personal access tokens. Generate one at: Bitbucket profile → App passwords → Create app password.

> **Caveat:** `bitbucket_merge_pr` is DESTRUCTIVE — it requires approval.

---

## GitLab

```env
GITLAB_URL=https://gitlab.com                # Or self-hosted
GITLAB_TOKEN=glpat-...
GITLAB_DEFAULT_GROUP=my-group
```

**Example commands:**

```
@opsbot list GitLab projects in my-group
@opsbot show open MRs in checkout-service
@opsbot get pipeline status for checkout-service branch main
@opsbot trigger the deploy pipeline on checkout-service for ref release/v2
@opsbot create MR in checkout-service: "fix: connection pool" from hotfix/conn-pool to main
@opsbot merge MR !42 in checkout-service
```

> **Caveat:** `gitlab_merge_mr` is DESTRUCTIVE.

> **Caveat:** For self-hosted GitLab, ensure your `GITLAB_TOKEN` has `api` scope and that the GitLab instance is reachable from the OpsBot worker pods.

---

## PagerDuty

```env
PAGERDUTY_API_KEY=u+...
PAGERDUTY_FROM_EMAIL=opsbot@your-org.com
```

**Example commands:**

```
@opsbot list active PagerDuty incidents
@opsbot who is on-call for the checkout-service schedule?
@opsbot acknowledge the checkout-api alert in PagerDuty
@opsbot create a PagerDuty incident: "checkout-api OOM - P1" in checkout-service service
@opsbot resolve incident P123456
```

> **Caveat:** `pagerduty_resolve` is DESTRUCTIVE — resolving an incident is hard to undo.

> **Caveat:** `PAGERDUTY_FROM_EMAIL` is required for creating incidents via the PagerDuty Events API.

---

## OpsGenie

```env
OPSGENIE_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**Example commands:**

```
@opsbot list active OpsGenie alerts
@opsbot who is on-call in OpsGenie right now?
@opsbot acknowledge the checkout-api alert in OpsGenie
```

---

## Datadog

```env
DATADOG_API_KEY=...
DATADOG_APP_KEY=...
DATADOG_SITE=datadoghq.com    # or datadoghq.eu for EU region
```

**Example commands:**

```
@opsbot query Datadog metrics for checkout-api error rate over the last hour
@opsbot search Datadog logs for checkout-api ERROR in the last 30 minutes
@opsbot list Datadog monitors that are alerting
@opsbot get Datadog trace summary for checkout-api
```

> **Caveat:** Datadog's metrics API can be slow for wide time ranges. Queries over 24 hours may hit the MCP server's 30-second timeout. Use specific, narrow time ranges for large metric queries.
