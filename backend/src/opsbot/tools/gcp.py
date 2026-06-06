from __future__ import annotations

import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


class GCPTools:
    def list_clusters(self, project: str | None = None) -> dict:
        from google.cloud import container_v1
        s = get_settings()
        target_project = project or s.gcp_project
        client = container_v1.ClusterManagerClient()
        parent = f"projects/{target_project}/locations/-"
        response = client.list_clusters(parent=parent)
        clusters = [
            {
                "name": c.name,
                "location": c.location,
                "status": container_v1.Cluster.Status(c.status).name,
                "version": c.current_master_version,
                "node_count": c.current_node_count,
                "endpoint": c.endpoint,
            }
            for c in response.clusters
        ]
        return {"project": target_project, "clusters": clusters, "count": len(clusters)}

    def list_artifact_images(self, project: str | None = None, location: str = "us-central1", repository: str | None = None) -> dict:
        from google.cloud import artifactregistry_v1
        s = get_settings()
        target_project = project or s.gcp_project
        client = artifactregistry_v1.ArtifactRegistryClient()
        if repository:
            parent = f"projects/{target_project}/locations/{location}/repositories/{repository}"
        else:
            parent = f"projects/{target_project}/locations/{location}/repositories/-"
        images = []
        for img in client.list_docker_images(parent=parent):
            images.append({
                "name": img.name.split("/")[-1],
                "tags": list(img.tags),
                "digest": img.image_size_bytes,
                "upload_time": str(img.upload_time),
            })
        return {"images": images[:20], "count": len(images)}

    def get_cluster_credentials(self, cluster_name: str, location: str, project: str | None = None) -> dict:
        from google.cloud import container_v1
        s = get_settings()
        target_project = project or s.gcp_project
        client = container_v1.ClusterManagerClient()
        cluster = client.get_cluster(
            name=f"projects/{target_project}/locations/{location}/clusters/{cluster_name}"
        )
        return {
            "cluster": cluster_name,
            "endpoint": cluster.endpoint,
            "version": cluster.current_master_version,
            "status": container_v1.Cluster.Status(cluster.status).name,
        }
