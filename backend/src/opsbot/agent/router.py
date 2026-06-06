from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    SLO_ANALYSIS = "slo_analysis"
    RCA = "rca"
    GENERAL_OPS = "general_ops"


@dataclass
class ParsedIntent:
    intent: Intent
    service_name: str | None = None
    namespace: str | None = None
    extra: dict | None = None


_SLO_PATTERNS = [
    r"(?:propose|generate|create|analyze|suggest)\s+slo",
    r"slo\s+(?:for|analysis|recommendations?)",
    r"service level (?:objectives?|indicators?)",
    r"error budget",
]

_RCA_PATTERNS = [
    r"root cause",
    r"\brca\b",
    r"investigate\s+(?:the|this)?\s+(?:issue|incident|error|spike|problem|outage)",
    r"why (?:is|are|did)\s+\w+\s+(?:failing|down|slow|broken)",
    r"what\s+(?:caused|went wrong)",
    r"analyze\s+(?:the\s+)?(?:errors?|failures?|incidents?|spikes?|issues?)",
    r"debug\s+\w+",
]


def detect_intent(message: str) -> ParsedIntent:
    msg = message.lower()

    # Check SLO intent first (more specific)
    for pattern in _SLO_PATTERNS:
        if re.search(pattern, msg, re.IGNORECASE):
            service = _extract_service(message)
            return ParsedIntent(
                intent=Intent.SLO_ANALYSIS,
                service_name=service,
                namespace=_extract_namespace(message),
            )

    # Check RCA intent
    for pattern in _RCA_PATTERNS:
        if re.search(pattern, msg, re.IGNORECASE):
            service = _extract_service(message)
            return ParsedIntent(
                intent=Intent.RCA,
                service_name=service,
                namespace=_extract_namespace(message),
            )

    # Default to general ops (handled by the main agent)
    return ParsedIntent(intent=Intent.GENERAL_OPS)


def _extract_service(message: str) -> str | None:
    # Patterns like "checkout-service", "payment-api", "user-svc"
    patterns = [
        r"\b([\w-]+(?:-service|-api|-svc|-app|-backend|-frontend))\b",
        r"(?:service|deployment|app)\s+[`\"]?([\w-]+)[`\"]?",
        r"for\s+[`\"]?([\w-]+)[`\"]?",
    ]
    for pattern in patterns:
        m = re.search(pattern, message, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    return None


def _extract_namespace(message: str) -> str | None:
    m = re.search(r"(?:namespace|ns)\s+[`\"]?([\w-]+)[`\"]?", message, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    for env in ["production", "prod", "staging", "stage", "uat", "dev", "development"]:
        if env in message.lower():
            return env
    return None
