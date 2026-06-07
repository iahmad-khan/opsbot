# Terraform Operations

OpsBot integrates with Terraform via the official Terraform MCP server to run plans, apply changes, and inspect state.

---

## Configuration

```env
# Terraform Cloud / Enterprise (optional)
TFE_TOKEN=<terraform-cloud-token>

# Local working directory for Terraform configs
TERRAFORM_WORKING_DIR=/app/workdir/terraform

# MCP server command (default uses Docker)
MCP_TERRAFORM_COMMAND=docker run --rm -i hashicorp/terraform-mcp-server:0.4.0
```

For local Terraform:
```env
MCP_TERRAFORM_COMMAND=npx -y @hashicorp/terraform-mcp-server
```

---

## READ Operations (auto-execute)

```
@opsbot run terraform plan in payments-infra workspace
@opsbot show current terraform state for production infrastructure
@opsbot what resources are managed by the payments-infra terraform workspace
```

> **Note:** Despite being named READ, `terraform_plan` actually *executes* (calls the Terraform API). It is classified READ because it makes no changes and its output is safe to show.

---

## DESTRUCTIVE Operations (require approval)

```
@opsbot apply terraform changes in payments-infra
@opsbot terraform apply the pending plan in staging
@opsbot destroy the staging terraform environment
```

`terraform apply` and `terraform destroy` are DESTRUCTIVE — they require approval from an `admin` or `sre`.

---

## Workspace-based operations

When using Terraform Cloud / Enterprise, reference workspaces by name:

```
@opsbot run terraform plan in the production workspace
@opsbot apply terraform in staging workspace
@opsbot show state for payments-infrastructure workspace
```

---

## Caveats

- **State locking.** If another process holds the Terraform state lock (e.g., a CI pipeline is running apply), OpsBot's plan or apply will fail with a lock error. The error message will include the lock holder.
- **Drift detection.** Terraform plan always runs against current state. If the state file is stale or corrupted, the plan may be inaccurate. OpsBot surfaces the raw plan output — verify it before approving apply.
- **`terraform destroy` requires dual approval** if `delete_namespace` / `drop_database` protection is enabled. Add `terraform_destroy` to `REQUIRE_DUAL_APPROVAL_FOR` for additional safety:
  ```env
  REQUIRE_DUAL_APPROVAL_FOR=delete_namespace,drop_database,terraform_destroy
  ```
- **Working directory.** The Terraform working directory (`TERRAFORM_WORKING_DIR`) must be mounted into the worker container. In docker-compose, add a volume mount if your configs are outside the repo.
- **Docker-in-Docker.** The default `MCP_TERRAFORM_COMMAND` uses Docker. In Kubernetes, this requires either Docker-in-Docker (dind) or switching to the `npx` command variant.
- **Variable files.** The MCP server reads `.tfvars` files from the working directory. Ensure sensitive variable files are not committed to Git — use Terraform Cloud variables or mounted secrets instead.
