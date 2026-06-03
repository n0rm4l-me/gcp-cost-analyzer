"""Gemini-powered cost analysis and recommendations."""

from __future__ import annotations

import os
from typing import Optional

from src.billing import BillingReport
from src.resources import ResourceReport


def _build_context(billing: BillingReport, resources: Optional[ResourceReport]) -> str:
    lines = [
        f"GCP Cost Analysis Report for billing account: {billing.billing_account_id}",
        f"Period: {billing.period_start} to {billing.period_end}",
        f"Total spend: ${billing.total_cost:,.2f} {billing.currency} ({billing.total_delta} vs previous period)",
        "",
        "Top services by cost:",
    ]

    for svc in billing.services[:10]:
        lines.append(f"  - {svc.service}: ${svc.cost:,.2f} ({svc.delta_str})")

    if resources and resources.has_findings:
        lines.append("")
        lines.append("Idle/underutilized resources detected:")

        if resources.idle_disks:
            lines.append(f"  Unattached disks ({len(resources.idle_disks)}):")
            for d in resources.idle_disks[:5]:
                lines.append(f"    - {d.description}")

        if resources.idle_snapshots:
            lines.append(f"  Old snapshots ({len(resources.idle_snapshots)}):")
            for s in resources.idle_snapshots[:5]:
                lines.append(f"    - {s.description}")

        if resources.underutilized_node_pools:
            lines.append(f"  Underutilized GKE node pools ({len(resources.underutilized_node_pools)}):")
            for n in resources.underutilized_node_pools[:5]:
                lines.append(f"    - {n.description}")

        lines.append(f"  Estimated monthly waste: ${resources.total_waste_estimate:,.0f}")

    return "\n".join(lines)


def get_recommendations(
    billing: BillingReport,
    resources: Optional[ResourceReport] = None,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Call Gemini API to generate cost optimization recommendations.
    Returns None if API key is not available.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        context = _build_context(billing, resources)
        prompt = f"""You are a GCP cost optimization expert. Analyze the following cost report and provide:
1. A brief summary of the cost situation (2-3 sentences)
2. Top 3 specific, actionable recommendations to reduce costs
3. Estimated potential savings for each recommendation

Be concise and specific. Focus on the highest-impact items.

{context}"""

        response = model.generate_content(prompt)
        return response.text

    except ImportError:
        return "_Gemini not available — install `google-generativeai` to enable AI recommendations._"
    except Exception as e:
        return f"_AI recommendations unavailable: {e}_"
