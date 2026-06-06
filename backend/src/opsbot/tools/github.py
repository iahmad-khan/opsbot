from __future__ import annotations

import structlog
from github import Auth, Github, GithubException

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _gh_client() -> Github:
    s = get_settings()
    return Github(auth=Auth.Token(s.github_token))


class GitHubTools:
    def list_repos(self, org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        target_org = org or s.github_org
        if target_org:
            repos = g.get_organization(target_org).get_repos()
        else:
            repos = g.get_user().get_repos()
        result = [{"name": r.name, "full_name": r.full_name, "private": r.private, "url": r.html_url} for r in repos]
        return {"repos": result, "count": len(result)}

    def list_members(self, repo: str, org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        collaborators = [
            {"login": c.login, "permissions": {"admin": c.permissions.admin, "push": c.permissions.push, "pull": c.permissions.pull}}
            for c in r.get_collaborators()
        ]
        return {"repo": full_name, "collaborators": collaborators, "count": len(collaborators)}

    def add_member(self, repo: str, username: str, permission: str = "push", org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        r.add_to_collaborators(username, permission=permission)
        log.info("github.member.added", repo=full_name, user=username, permission=permission)
        return {"repo": full_name, "username": username, "permission": permission, "status": "added"}

    def remove_member(self, repo: str, username: str, org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        r.remove_from_collaborators(username)
        log.info("github.member.removed", repo=full_name, user=username)
        return {"repo": full_name, "username": username, "status": "removed"}

    def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        org: str | None = None,
    ) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        pr = r.create_pull(title=title, body=body, head=head, base=base)
        log.info("github.pr.created", repo=full_name, pr=pr.number, url=pr.html_url)
        return {"repo": full_name, "pr_number": pr.number, "url": pr.html_url, "status": "created"}

    def create_issue(self, repo: str, title: str, body: str, labels: list[str] | None = None, org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        issue = r.create_issue(title=title, body=body, labels=labels or [])
        return {"repo": full_name, "issue_number": issue.number, "url": issue.html_url}

    def list_prs(self, repo: str, state: str = "open", org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        prs = [
            {"number": p.number, "title": p.title, "state": p.state, "url": p.html_url, "author": p.user.login, "created": str(p.created_at)}
            for p in r.get_pulls(state=state)
        ]
        return {"repo": full_name, "prs": prs, "count": len(prs)}

    def get_ci_status(self, repo: str, ref: str = "main", org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        commit = r.get_commit(ref)
        combined = commit.get_combined_status()
        checks = [
            {"name": s.context, "state": s.state, "url": s.target_url}
            for s in combined.statuses
        ]
        return {
            "repo": full_name,
            "ref": ref,
            "overall_state": combined.state,
            "checks": checks,
        }

    def create_file(self, repo: str, path: str, content: str, message: str, branch: str = "main", org: str | None = None) -> dict:
        import base64
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        result = r.create_file(path, message, content, branch=branch)
        return {"repo": full_name, "path": path, "sha": result["commit"].sha, "url": result["content"].html_url}

    def create_branch(self, repo: str, branch: str, from_ref: str = "main", org: str | None = None) -> dict:
        s = get_settings()
        g = _gh_client()
        org_name = org or s.github_org
        full_name = f"{org_name}/{repo}" if org_name and "/" not in repo else repo
        r = g.get_repo(full_name)
        source = r.get_branch(from_ref)
        r.create_git_ref(f"refs/heads/{branch}", source.commit.sha)
        return {"repo": full_name, "branch": branch, "from": from_ref, "status": "created"}
