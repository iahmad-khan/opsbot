from __future__ import annotations

import textwrap

# Max chars for a single Slack text block
MAX_BLOCK_TEXT = 2900
MAX_MESSAGE_TEXT = 40000


def truncate(text: str, max_len: int = MAX_BLOCK_TEXT) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n_...truncated ({len(text) - max_len} chars)_"


def format_agent_response(text: str) -> list[dict]:
    """Convert agent text response to Slack blocks (handles long responses)."""
    if not text:
        return []
    chunks = textwrap.wrap(text, MAX_BLOCK_TEXT, break_long_words=False, replace_whitespace=False)
    blocks = []
    for chunk in chunks:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    return blocks


def format_tool_result(tool_name: str, result: str, success: bool = True) -> list[dict]:
    emoji = "✅" if success else "❌"
    short_name = tool_name.split("__")[-1] if "__" in tool_name else tool_name
    return [
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"{emoji} `{short_name}`"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{truncate(result, 2800)}```",
            },
        },
    ]


def format_error(error: str, context: str = "") -> list[dict]:
    text = f"❌ *Error*\n{error}"
    if context:
        text += f"\n_Context: {context}_"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def format_pods_table(pods: list[dict]) -> str:
    if not pods:
        return "_No pods found._"
    lines = ["```", f"{'NAME':<40} {'STATUS':<12} {'READY':<6} {'RESTARTS':<10}", "-" * 70]
    for pod in pods[:30]:
        ready = "✓" if pod.get("ready") else "✗"
        lines.append(
            f"{pod['name'][:39]:<40} {pod['status'][:11]:<12} {ready:<6} {pod.get('restarts', 0):<10}"
        )
    lines.append("```")
    return "\n".join(lines)


def format_deployments_table(deployments: list[dict]) -> str:
    if not deployments:
        return "_No deployments found._"
    lines = ["```", f"{'NAME':<35} {'DESIRED':<8} {'READY':<8} {'IMAGE':<30}", "-" * 83]
    for d in deployments[:20]:
        image = (d.get("image") or "")[-29:]
        lines.append(f"{d['name'][:34]:<35} {d.get('desired', 0):<8} {d.get('ready', 0):<8} {image:<30}")
    lines.append("```")
    return "\n".join(lines)


def format_rca_report(rca: dict) -> str:
    lines = [
        "🔬 *Root Cause Analysis*",
        "",
        f"*Root Cause*: {rca.get('root_cause', 'Unknown')}",
        f"*Confidence*: {int(rca.get('confidence', 0) * 100)}%",
        "",
        "*Summary*",
        rca.get('summary', ''),
        "",
    ]

    factors = rca.get("contributing_factors", [])
    if factors:
        lines.append("*Contributing Factors*")
        for f in factors:
            lines.append(f"• {f}")
        lines.append("")

    steps = rca.get("remediation_steps", [])
    if steps:
        lines.append("*Remediation Steps*")
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    actions = rca.get("recommended_actions", [])
    if actions:
        lines.append("*Action Items*")
        for action in actions:
            priority = action.get("priority", "medium").upper()
            lines.append(f"• [{priority}] {action.get('action', '')} — _{action.get('owner', 'TBD')}_")

    return "\n".join(lines)


def format_slo_proposal(slo_data: dict) -> str:
    lines = [
        f"📊 *SLO Proposal for {slo_data.get('service_name', 'Service')}*",
        "",
        slo_data.get("analysis_summary", ""),
        "",
        "*Proposed SLOs*",
    ]
    for slo in slo_data.get("proposed_slos", []):
        target_pct = f"{slo.get('target', 0) * 100:.3f}%"
        current_pct = f"{slo.get('current_performance', 0) * 100:.3f}%"
        lines.extend([
            "",
            f"*{slo.get('name', 'SLO').title()}*",
            f"• Target: `{target_pct}` | Current: `{current_pct}`",
            f"• SLI: `{slo.get('sli_description', '')}`",
            f"• Window: {slo.get('window', '30d')}",
        ])
        if slo.get("error_budget_minutes"):
            lines.append(f"• Error Budget: {slo['error_budget_minutes']:.1f} min/month")

    recommendations = slo_data.get("recommendations", [])
    if recommendations:
        lines.append("")
        lines.append("*Recommendations*")
        for rec in recommendations:
            lines.append(f"• {rec}")

    return "\n".join(lines)
