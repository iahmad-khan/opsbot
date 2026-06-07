from __future__ import annotations

import json
from typing import Any

import structlog

from opsbot.agent.llm import LLMClient
from opsbot.agent.prompts.sre import FIX_PR_PROMPT
from opsbot.tools.github import GitHubTools

log = structlog.get_logger(__name__)


class FixGenerator:
    def __init__(self) -> None:
        self._llm = LLMClient()
        self._github = GitHubTools()

    async def generate_fix(
        self,
        issue_description: str,
        root_cause: str,
        affected_files: list[dict],
        repo: str,
        base_branch: str = "main",
        auto_create_pr: bool = False,
        requester_slack_id: str = "",
    ) -> dict[str, Any]:
        log.info("fix.generate.start", repo=repo, issue=issue_description[:80])

        # Fetch current content of affected files
        file_contents = []
        for f in affected_files:
            try:
                from github import Auth, Github

                from opsbot.config.settings import get_settings
                s = get_settings()
                g = Github(auth=Auth.Token(s.github_token))
                r = g.get_repo(repo)
                file_obj = r.get_contents(f["path"])
                file_contents.append({
                    "path": f["path"],
                    "content": file_obj.decoded_content.decode("utf-8") if hasattr(file_obj, "decoded_content") else "",
                    "description": f.get("description", ""),
                })
            except Exception as e:
                file_contents.append({"path": f["path"], "content": f"[Could not fetch: {e}]", "description": ""})

        prompt = FIX_PR_PROMPT.format(
            issue_description=issue_description,
            root_cause=root_cause,
            affected_files=json.dumps([{"path": f["path"], "description": f.get("description", "")} for f in affected_files], indent=2),
            current_content=json.dumps(file_contents, indent=2)[:4000],
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            model="claude-sonnet-4-6",
        )

        try:
            content = response.content or "{}"
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            fix_plan = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            log.warning("fix.parse.failed")
            return {"error": "Failed to parse fix plan", "raw": response.content}

        result: dict[str, Any] = {
            "pr_title": fix_plan.get("pr_title", "fix: automated fix from OpsBot"),
            "pr_body": fix_plan.get("pr_body", ""),
            "files": fix_plan.get("files", []),
            "pr_url": None,
        }

        if auto_create_pr and fix_plan.get("files"):
            try:
                pr_url = await self._create_fix_pr(repo, fix_plan, base_branch)
                result["pr_url"] = pr_url
                log.info("fix.pr.created", repo=repo, url=pr_url)
            except Exception as e:
                result["pr_error"] = str(e)
                log.error("fix.pr.failed", error=str(e))

        return result

    async def _create_fix_pr(self, repo: str, fix_plan: dict, base_branch: str) -> str:
        import time

        from github import Auth, Github

        from opsbot.config.settings import get_settings

        s = get_settings()
        g = Github(auth=Auth.Token(s.github_token))
        r = g.get_repo(repo)

        # Create fix branch
        branch_name = f"opsbot-fix-{int(time.time())}"
        source = r.get_branch(base_branch)
        r.create_git_ref(f"refs/heads/{branch_name}", source.commit.sha)

        # Commit each file
        for file_change in fix_plan.get("files", []):
            path = file_change["path"]
            new_content = file_change["content"]
            description = file_change.get("description", "OpsBot automated fix")
            action = file_change.get("action", "update")

            try:
                if action == "update":
                    existing = r.get_contents(path, ref=branch_name)
                    if isinstance(existing, list):
                        existing = existing[0]
                    r.update_file(
                        path=path,
                        message=f"fix: {description}",
                        content=new_content,
                        sha=existing.sha,
                        branch=branch_name,
                    )
                elif action == "create":
                    r.create_file(
                        path=path,
                        message=f"fix: {description}",
                        content=new_content,
                        branch=branch_name,
                    )
            except Exception as e:
                log.error("fix.file.commit.failed", path=path, error=str(e))

        # Create PR
        pr = r.create_pull(
            title=fix_plan["pr_title"],
            body=fix_plan["pr_body"],
            head=branch_name,
            base=base_branch,
        )
        return pr.html_url
