from __future__ import annotations

import asyncio
from typing import Any

import structlog
from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


async def _load_kube_config() -> None:
    s = get_settings()
    try:
        await config.load_kube_config(config_file=s.kubeconfig_path if s.kubeconfig_path != "~/.kube/config" else None)
    except Exception:
        config.load_incluster_config()


class KubernetesTools:
    """Direct Kubernetes tool implementations (used when MCP server is unavailable)."""

    async def list_pods(self, namespace: str = "default", label_selector: str = "") -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            v1 = client.CoreV1Api(api_client)
            kwargs = {"namespace": namespace}
            if label_selector:
                kwargs["label_selector"] = label_selector
            result = await v1.list_namespaced_pod(**kwargs)
            pods = []
            for pod in result.items:
                pods.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "ready": all(c.ready for c in (pod.status.container_statuses or [])),
                    "restarts": sum(c.restart_count for c in (pod.status.container_statuses or [])),
                    "age": str(pod.metadata.creation_timestamp),
                    "node": pod.spec.node_name,
                })
            return {"pods": pods, "count": len(pods)}

    async def get_pod_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        container: str | None = None,
        tail_lines: int = 100,
        previous: bool = False,
    ) -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            v1 = client.CoreV1Api(api_client)
            kwargs: dict[str, Any] = {
                "name": pod_name,
                "namespace": namespace,
                "tail_lines": tail_lines,
                "previous": previous,
            }
            if container:
                kwargs["container"] = container
            logs = await v1.read_namespaced_pod_log(**kwargs)
            return {"pod": pod_name, "namespace": namespace, "logs": logs}

    async def list_deployments(self, namespace: str = "default") -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            apps_v1 = client.AppsV1Api(api_client)
            result = await apps_v1.list_namespaced_deployment(namespace=namespace)
            deployments = []
            for d in result.items:
                deployments.append({
                    "name": d.metadata.name,
                    "namespace": d.metadata.namespace,
                    "desired": d.spec.replicas,
                    "ready": d.status.ready_replicas or 0,
                    "available": d.status.available_replicas or 0,
                    "image": d.spec.template.spec.containers[0].image if d.spec.template.spec.containers else None,
                    "age": str(d.metadata.creation_timestamp),
                })
            return {"deployments": deployments, "count": len(deployments)}

    async def deploy_image(
        self,
        deployment: str,
        image: str,
        namespace: str = "default",
        container: str | None = None,
    ) -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            apps_v1 = client.AppsV1Api(api_client)
            dep = await apps_v1.read_namespaced_deployment(name=deployment, namespace=namespace)
            containers = dep.spec.template.spec.containers
            target = container or containers[0].name
            for c in containers:
                if c.name == target:
                    old_image = c.image
                    c.image = image
                    break
            await apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=dep)
            return {
                "deployment": deployment,
                "namespace": namespace,
                "container": target,
                "old_image": old_image,
                "new_image": image,
                "status": "patched",
            }

    async def rollback_deployment(
        self,
        deployment: str,
        namespace: str = "default",
        revision: int | None = None,
    ) -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            apps_v1 = client.AppsV1Api(api_client)
            if revision:
                body = {
                    "spec": {
                        "rollbackTo": {"revision": revision}
                    }
                }
            else:
                # Undo last rollout by annotating
                body = {
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "kubectl.kubernetes.io/restartedAt": asyncio.get_event_loop().time().__str__()
                                }
                            }
                        }
                    }
                }
            await apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=body)
            return {"deployment": deployment, "namespace": namespace, "status": "rollback_initiated"}

    async def restart_deployment(self, deployment: str, namespace: str = "default") -> dict:
        from datetime import datetime, timezone
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            apps_v1 = client.AppsV1Api(api_client)
            now = datetime.now(timezone.utc).isoformat()
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                        }
                    }
                }
            }
            await apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=body)
            return {"deployment": deployment, "namespace": namespace, "status": "restart_triggered", "time": now}

    async def scale_deployment(
        self,
        deployment: str,
        replicas: int,
        namespace: str = "default",
    ) -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            apps_v1 = client.AppsV1Api(api_client)
            body = {"spec": {"replicas": replicas}}
            await apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=body)
            return {"deployment": deployment, "namespace": namespace, "replicas": replicas, "status": "scaled"}

    async def list_events(self, namespace: str = "default", field_selector: str = "") -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            v1 = client.CoreV1Api(api_client)
            kwargs: dict[str, Any] = {"namespace": namespace}
            if field_selector:
                kwargs["field_selector"] = field_selector
            result = await v1.list_namespaced_event(**kwargs)
            events = []
            for e in sorted(result.items, key=lambda x: x.last_timestamp or x.event_time or "", reverse=True)[:50]:
                events.append({
                    "type": e.type,
                    "reason": e.reason,
                    "message": e.message,
                    "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                    "count": e.count,
                    "last_time": str(e.last_timestamp or e.event_time),
                })
            return {"events": events, "count": len(events)}

    async def delete_pod(self, pod_name: str, namespace: str = "default") -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            v1 = client.CoreV1Api(api_client)
            await v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return {"pod": pod_name, "namespace": namespace, "status": "deleted"}

    async def list_namespaces(self) -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            v1 = client.CoreV1Api(api_client)
            result = await v1.list_namespace()
            return {
                "namespaces": [
                    {"name": ns.metadata.name, "status": ns.status.phase}
                    for ns in result.items
                ]
            }

    async def list_nodes(self) -> dict:
        await _load_kube_config()
        async with client.ApiClient() as api_client:
            v1 = client.CoreV1Api(api_client)
            result = await v1.list_node()
            nodes = []
            for n in result.items:
                conditions = {c.type: c.status for c in (n.status.conditions or [])}
                nodes.append({
                    "name": n.metadata.name,
                    "ready": conditions.get("Ready") == "True",
                    "version": n.status.node_info.kubelet_version if n.status.node_info else None,
                    "cpu": n.status.capacity.get("cpu") if n.status.capacity else None,
                    "memory": n.status.capacity.get("memory") if n.status.capacity else None,
                    "unschedulable": n.spec.unschedulable or False,
                })
            return {"nodes": nodes, "count": len(nodes)}
