from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from opsbot.models.schemas import RCARequest, RCAResult, SLOAnalysisRequest, SLOProposal

router = APIRouter(prefix="/sre", tags=["sre"])


@router.post("/slo-analysis")
async def trigger_slo_analysis(req: SLOAnalysisRequest, background_tasks: BackgroundTasks) -> dict:
    from opsbot.tasks.celery_app import run_slo_analysis_task

    task = run_slo_analysis_task.delay(
        service_name=req.service_name,
        namespace=req.namespace,
        lookback_days=req.lookback_days,
        requester_slack_id=req.requester_slack_id,
        channel_id=req.requester_slack_id,  # DM back by default
        create_pr=req.create_pr,
        target_repo=req.target_repo,
    )
    return {"task_id": task.id, "status": "queued", "service": req.service_name}


@router.post("/rca")
async def trigger_rca(req: RCARequest) -> dict:
    from opsbot.sre.rca_engine import RCAEngine
    from opsbot.sre.fix_generator import FixGenerator

    engine = RCAEngine()
    result = await engine.analyze(
        incident_description=req.incident_description,
        service_name=req.service_name,
        namespace=req.namespace,
        start_time=req.start_time,
        end_time=req.end_time,
    )

    if req.create_fix_pr and req.target_repo and result.get("remediation_steps"):
        generator = FixGenerator()
        pr_result = await generator.generate_fix(
            issue_description=req.incident_description,
            root_cause=result.get("root_cause", ""),
            affected_files=[],
            repo=req.target_repo,
            auto_create_pr=True,
            requester_slack_id=req.requester_slack_id,
        )
        result["github_pr_url"] = pr_result.get("pr_url")

    return result


@router.get("/slo-reports")
async def list_slo_reports(service_name: str | None = None) -> dict:
    from opsbot.models.db import make_session_factory, SLOReport
    from sqlalchemy import select
    session_factory = make_session_factory()
    async with session_factory() as db:
        q = select(SLOReport).order_by(SLOReport.created_at.desc()).limit(50)
        if service_name:
            q = q.where(SLOReport.service_name == service_name)
        result = await db.execute(q)
        reports = result.scalars().all()
        return {
            "reports": [
                {
                    "id": str(r.id),
                    "service_name": r.service_name,
                    "created_at": r.created_at.isoformat(),
                    "github_pr_url": r.github_pr_url,
                }
                for r in reports
            ]
        }


@router.get("/rca-reports")
async def list_rca_reports(service_name: str | None = None) -> dict:
    from opsbot.models.db import make_session_factory, RCAReport
    from sqlalchemy import select
    session_factory = make_session_factory()
    async with session_factory() as db:
        q = select(RCAReport).order_by(RCAReport.created_at.desc()).limit(50)
        if service_name:
            q = q.where(RCAReport.service_name == service_name)
        result = await db.execute(q)
        reports = result.scalars().all()
        return {
            "reports": [
                {
                    "id": str(r.id),
                    "service_name": r.service_name,
                    "root_cause": r.root_cause,
                    "created_at": r.created_at.isoformat(),
                }
                for r in reports
            ]
        }
