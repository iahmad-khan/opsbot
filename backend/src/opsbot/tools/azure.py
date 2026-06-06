from __future__ import annotations

import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _credential():
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    s = get_settings()
    if s.azure_client_id and s.azure_client_secret:
        return ClientSecretCredential(
            tenant_id=s.azure_tenant_id,
            client_id=s.azure_client_id,
            client_secret=s.azure_client_secret,
        )
    return DefaultAzureCredential()


class AzureTools:
    def list_clusters(self, resource_group: str | None = None) -> dict:
        from azure.mgmt.containerservice import ContainerServiceClient
        s = get_settings()
        client = ContainerServiceClient(_credential(), s.azure_subscription_id)
        if resource_group:
            clusters = list(client.managed_clusters.list_by_resource_group(resource_group))
        else:
            clusters = list(client.managed_clusters.list())
        return {
            "clusters": [
                {
                    "name": c.name,
                    "resource_group": c.id.split("/")[4] if c.id else None,
                    "location": c.location,
                    "kubernetes_version": c.kubernetes_version,
                    "provisioning_state": c.provisioning_state,
                    "fqdn": c.fqdn,
                }
                for c in clusters
            ],
            "count": len(clusters),
        }

    def list_acr_repositories(self, registry_name: str) -> dict:
        from azure.mgmt.containerregistry import ContainerRegistryManagementClient
        s = get_settings()
        client = ContainerRegistryManagementClient(_credential(), s.azure_subscription_id)
        registries = list(client.registries.list())
        target = next((r for r in registries if r.name == registry_name), None)
        if not target:
            return {"error": f"Registry {registry_name} not found"}
        return {
            "registry": registry_name,
            "login_server": target.login_server,
            "sku": target.sku.name if target.sku else None,
            "status": target.provisioning_state,
        }
