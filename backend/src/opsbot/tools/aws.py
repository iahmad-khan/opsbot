from __future__ import annotations

import structlog
import boto3

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _session() -> boto3.Session:
    s = get_settings()
    kwargs = {"region_name": s.aws_region}
    if s.aws_access_key_id:
        kwargs["aws_access_key_id"] = s.aws_access_key_id
        kwargs["aws_secret_access_key"] = s.aws_secret_access_key
    return boto3.Session(**kwargs)


class AWSTools:
    def list_eks_clusters(self) -> dict:
        eks = _session().client("eks")
        response = eks.list_clusters()
        clusters = []
        for name in response["clusters"]:
            desc = eks.describe_cluster(name=name)["cluster"]
            clusters.append({
                "name": name,
                "status": desc["status"],
                "version": desc["version"],
                "endpoint": desc.get("endpoint", ""),
            })
        return {"clusters": clusters, "count": len(clusters)}

    def list_ecr_images(self, repository: str, max_results: int = 20) -> dict:
        ecr = _session().client("ecr")
        response = ecr.describe_images(
            repositoryName=repository,
            maxResults=max_results,
            filter={"tagStatus": "TAGGED"},
        )
        images = sorted(
            response.get("imageDetails", []),
            key=lambda x: x.get("imagePushedAt", ""),
            reverse=True,
        )
        return {
            "repository": repository,
            "images": [
                {
                    "digest": img["imageDigest"][:19],
                    "tags": img.get("imageTags", []),
                    "size_mb": round(img.get("imageSizeInBytes", 0) / 1024 / 1024, 2),
                    "pushed_at": str(img.get("imagePushedAt")),
                }
                for img in images
            ],
        }

    def list_iam_users(self) -> dict:
        iam = _session().client("iam")
        paginator = iam.get_paginator("list_users")
        users = []
        for page in paginator.paginate():
            for u in page["Users"]:
                users.append({
                    "username": u["UserName"],
                    "arn": u["Arn"],
                    "created": str(u["CreateDate"]),
                    "password_last_used": str(u.get("PasswordLastUsed", "never")),
                })
        return {"users": users, "count": len(users)}

    def add_iam_user_to_group(self, username: str, group: str) -> dict:
        iam = _session().client("iam")
        iam.add_user_to_group(GroupName=group, UserName=username)
        log.info("aws.iam.add_to_group", user=username, group=group)
        return {"username": username, "group": group, "status": "added"}

    def describe_ec2_instances(self, filters: list | None = None) -> dict:
        ec2 = _session().client("ec2")
        kwargs = {}
        if filters:
            kwargs["Filters"] = filters
        response = ec2.describe_instances(**kwargs)
        instances = []
        for reservation in response["Reservations"]:
            for i in reservation["Instances"]:
                name = next((t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"), "")
                instances.append({
                    "id": i["InstanceId"],
                    "name": name,
                    "type": i["InstanceType"],
                    "state": i["State"]["Name"],
                    "private_ip": i.get("PrivateIpAddress"),
                    "public_ip": i.get("PublicIpAddress"),
                })
        return {"instances": instances, "count": len(instances)}
