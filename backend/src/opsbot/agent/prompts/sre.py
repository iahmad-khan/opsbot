SRE_REPORT_PROMPT = """\
Generate a professional SRE incident report based on the following RCA.

## Root Cause Analysis
{rca_json}

## Service: {service_name}
## Incident Time: {incident_time}
## Resolved At: {resolved_at}

Format as a Slack-friendly incident report using this template:

🚨 *Incident Report: {service_name}*

*Summary*: [one sentence]

*Impact*: [who was affected, how long]

*Root Cause*: [clear explanation]

*Timeline*:
[bullet list of events with times]

*Resolution*: [what was done to fix it]

*Action Items*:
[numbered list with priority and owner]

*Error Budget Impact*: [how much error budget was consumed]
"""


FIX_PR_PROMPT = """\
You are generating a GitHub Pull Request to fix a production issue.

## Issue to Fix
{issue_description}

## Root Cause
{root_cause}

## Affected Files / Configs
{affected_files}

## Current Content
{current_content}

## Instructions
Generate:
1. The exact code/config changes needed to fix the issue
2. A clear PR title (under 70 chars)
3. A detailed PR description explaining the problem and solution

Respond in this exact JSON format:
{{
  "pr_title": "fix: clear title under 70 chars",
  "pr_body": "## Problem\\n...\\n## Solution\\n...\\n## Testing\\n...",
  "files": [
    {{
      "path": "path/to/file.yaml",
      "action": "update",
      "content": "full new file content",
      "description": "what changed and why"
    }}
  ]
}}
"""
