from __future__ import annotations

import asyncio
import json
import os
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


async def _run(cmd: list[str], cwd: str, env: dict | None = None) -> tuple[str, str, int]:
    proc_env = {**os.environ, **(env or {})}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=proc_env,
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode(), stderr.decode(), proc.returncode


class TerraformTools:
    def _work_dir(self, workspace: str | None = None) -> str:
        s = get_settings()
        base = s.terraform_working_dir
        if workspace:
            return os.path.join(base, workspace)
        return base

    def _env(self) -> dict:
        s = get_settings()
        env = {}
        if s.tfe_token:
            env["TF_TOKEN_app_terraform_io"] = s.tfe_token
        return env

    async def init(self, workspace: str | None = None) -> dict:
        cwd = self._work_dir(workspace)
        stdout, stderr, rc = await _run(["terraform", "init", "-no-color"], cwd=cwd, env=self._env())
        return {"workspace": workspace, "stdout": stdout, "stderr": stderr, "success": rc == 0}

    async def plan(self, workspace: str | None = None, var_file: str | None = None, out_file: str = "tfplan") -> dict:
        cwd = self._work_dir(workspace)
        cmd = ["terraform", "plan", "-no-color", f"-out={out_file}"]
        if var_file:
            cmd.extend([f"-var-file={var_file}"])
        stdout, stderr, rc = await _run(cmd, cwd=cwd, env=self._env())
        return {
            "workspace": workspace,
            "plan_file": out_file,
            "stdout": stdout[-4000:] if len(stdout) > 4000 else stdout,
            "stderr": stderr,
            "success": rc == 0,
        }

    async def apply(self, workspace: str | None = None, plan_file: str = "tfplan", auto_approve: bool = True) -> dict:
        cwd = self._work_dir(workspace)
        cmd = ["terraform", "apply", "-no-color"]
        if auto_approve:
            cmd.append("-auto-approve")
        if plan_file:
            cmd.append(plan_file)
        stdout, stderr, rc = await _run(cmd, cwd=cwd, env=self._env())
        log.info("terraform.apply", workspace=workspace, success=rc == 0)
        return {
            "workspace": workspace,
            "stdout": stdout[-4000:] if len(stdout) > 4000 else stdout,
            "stderr": stderr,
            "success": rc == 0,
        }

    async def destroy(self, workspace: str | None = None, auto_approve: bool = False) -> dict:
        cwd = self._work_dir(workspace)
        cmd = ["terraform", "destroy", "-no-color"]
        if auto_approve:
            cmd.append("-auto-approve")
        stdout, stderr, rc = await _run(cmd, cwd=cwd, env=self._env())
        log.warning("terraform.destroy", workspace=workspace, success=rc == 0)
        return {"workspace": workspace, "stdout": stdout, "stderr": stderr, "success": rc == 0}

    async def show_state(self, workspace: str | None = None) -> dict:
        cwd = self._work_dir(workspace)
        stdout, stderr, rc = await _run(["terraform", "show", "-json"], cwd=cwd, env=self._env())
        if rc == 0:
            try:
                state = json.loads(stdout)
                resources = state.get("values", {}).get("root_module", {}).get("resources", [])
                return {
                    "workspace": workspace,
                    "resource_count": len(resources),
                    "resources": [{"type": r["type"], "name": r["name"]} for r in resources[:50]],
                }
            except json.JSONDecodeError:
                pass
        return {"workspace": workspace, "stdout": stdout, "stderr": stderr, "success": rc == 0}

    async def workspace_list(self) -> dict:
        cwd = self._work_dir()
        stdout, _, rc = await _run(["terraform", "workspace", "list"], cwd=cwd, env=self._env())
        workspaces = [w.strip().lstrip("* ") for w in stdout.strip().splitlines() if w.strip()]
        current = next((w.lstrip("* ") for w in stdout.strip().splitlines() if w.startswith("*")), None)
        return {"workspaces": workspaces, "current": current}
