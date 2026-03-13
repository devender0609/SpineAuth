from __future__ import annotations

import json
from pathlib import Path

PAYER_PORTALS = {
    "united_healthcare": {
        "label": "UnitedHealthcare",
        "portal_name": "UnitedHealthcare Provider Portal",
        "portal_url": "https://www.uhcprovider.com/en/prior-auth-advance-notification.html",
        "support_url": "https://www.uhcprovider.com/en/resource-library/provider-portal-resources.html",
        "how_to_submit": [
            "Check whether prior authorization is required in the Prior Authorization and Notification tool.",
            "Submit the request online through the UnitedHealthcare Provider Portal.",
            "Upload clinical records, imaging reports, and any requested supporting documentation.",
            "Track status and upload updates in the same portal.",
        ],
        "documents_required": [
            "Office note with diagnosis and symptom history",
            "Neurologic exam",
            "Imaging report",
            "Conservative treatment documentation",
            "Procedure/CPT and ICD-10 details",
        ],
        "notes": "Use member-specific lookup first because requirements can vary by plan and site of service.",
    },
    "aetna": {
        "label": "Aetna",
        "portal_name": "Aetna precertification / provider workflow",
        "portal_url": "https://www.aetna.com/health-care-professionals/precertification.html",
        "support_url": "https://www.aetna.com/health-care-professionals/precertification/precertification-lists.html",
        "how_to_submit": [
            "Review the current precertification requirements and CPT lookup first.",
            "Submit through the Aetna provider workflow or linked portal for the member plan.",
            "Attach office notes, imaging, and conservative care documentation.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Therapy / medication history",
            "Procedure details and levels",
        ],
        "notes": "Requirements vary by product and whether the request is notification versus coverage determination.",
    },
    "cigna": {
        "label": "Cigna Healthcare",
        "portal_name": "Cigna for Health Care Professionals",
        "portal_url": "https://cignaforhcp.cigna.com/",
        "support_url": "https://cignaforhcp.cigna.com/",
        "how_to_submit": [
            "Confirm whether the requested service requires precertification.",
            "Use the Cigna provider portal or designated utilization management workflow for the service line.",
            "Attach clinical documentation supporting medical necessity and prior treatment failure.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Medication and PT history",
            "Procedure/CPT details",
        ],
        "notes": "Some Cigna services are delegated to ancillary utilization partners; verify the correct pathway in the portal.",
    },
    "anthem_bcbs": {
        "label": "Anthem / BCBS",
        "portal_name": "Availity Essentials / Anthem authorizations",
        "portal_url": "https://www.anthem.com/provider",
        "support_url": "https://www.availity.com/",
        "how_to_submit": [
            "Open the authorizations/referrals workflow for the member's plan.",
            "Upload clinical records and imaging within the authorization request.",
            "Verify the exact local Blue plan and delegated vendor before submission.",
        ],
        "documents_required": [
            "Office note",
            "Imaging",
            "Conservative treatment documentation",
            "Functional assessment when relevant",
        ],
        "notes": "BCBS requirements vary by local plan; always confirm the member's specific Blue plan before submission.",
    },
    "humana": {
        "label": "Humana",
        "portal_name": "Humana / HealthHelp / Availity pathway",
        "portal_url": "https://portal.healthhelp.com/login",
        "support_url": "https://www.healthhelp.com/",
        "how_to_submit": [
            "Confirm whether the member plan routes the request through Humana, Availity, or HealthHelp.",
            "Attach all supporting records at the time of submission whenever possible.",
            "Use the payer or delegated vendor portal indicated by the member plan.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging",
            "Conservative treatment records",
            "Procedure and diagnosis details",
        ],
        "notes": "Humana and Medicare Advantage requests may route through delegated clinical partners such as HealthHelp.",
    },
    "tricare": {
        "label": "TRICARE",
        "portal_name": "TRICARE regional authorization workflow",
        "portal_url": "https://www.tricare.mil/referrals",
        "support_url": "https://www.humanamilitary.com/",
        "how_to_submit": [
            "Confirm region-specific authorization policy first.",
            "Use the regional contractor workflow and include referrals when required.",
            "Attach referral and full supporting clinical records.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Referral if required",
            "Conservative treatment history",
        ],
        "notes": "Requirements vary by TRICARE region and service.",
    },
    "carelon": {
        "label": "AIM / Carelon",
        "portal_name": "Carelon provider portal",
        "portal_url": "https://providerportal.com/",
        "support_url": "https://providers.carelonmedicalbenefitsmanagement.com/providerconnections/",
        "how_to_submit": [
            "Use providerportal.com to submit a new case or check an existing one when the plan routes through Carelon.",
            "If the health plan directs you to a dedicated payer portal, continue to use that payer portal instead of Carelon.",
            "Upload clinical records and imaging with the request.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Procedure and diagnosis details",
            "Any payer-specific criteria worksheet",
        ],
        "notes": "Some submissions still route through the health plan's dedicated portal rather than Carelon.",
    },
    "evicore": {
        "label": "eviCore / MedSolutions",
        "portal_name": "eviCore Provider Hub",
        "portal_url": "https://www.evicore.com/provider",
        "support_url": "https://www.evicore.com/resources",
        "how_to_submit": [
            "Open the Provider Hub and choose the health plan and solution.",
            "Use the instructions shown for that payer and service line to route the case.",
            "Upload supporting clinical records and monitor status online.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Conservative treatment records",
            "Requested CPT and ICD-10 codes",
        ],
        "notes": "Use the payer-specific instructions in Provider Hub because routing can differ by plan and service line.",
    },
    "radmd": {
        "label": "RadMD / Evolent",
        "portal_name": "RadMD",
        "portal_url": "https://www1.radmd.com/sign-in",
        "support_url": "https://www1.radmd.com/authorization-requirements",
        "how_to_submit": [
            "Submit the specialty prior authorization request in RadMD when the plan routes through Evolent.",
            "Use the authorization tools after login to request, track, and verify the case.",
            "Attach the supporting clinical packet with the request.",
        ],
        "documents_required": [
            "Member information",
            "Ordering physician information",
            "Requested examination / procedure and CPT",
            "Clinical justification including symptoms, duration, and imaging",
        ],
        "notes": "RadMD is typically used for specialty / imaging pathways delegated to Evolent.",
    },
    "ambetter": {
        "label": "Ambetter / Superior",
        "portal_name": "Ambetter provider resources",
        "portal_url": "https://provider.superiorhealthplan.com",
        "support_url": "https://www.ambetterhealth.com/providers.html",
        "how_to_submit": [
            "Verify the state-specific Ambetter or Superior plan first.",
            "Use the plan portal or delegated vendor listed for the member plan.",
            "Attach diagnosis, imaging, and prior treatment documentation.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Prior conservative treatment history",
            "Procedure request details",
        ],
        "notes": "State plan differences are common.",
    },
    "medicare": {
        "label": "Medicare",
        "portal_name": "CMS / MAC workflow",
        "portal_url": "https://www.cms.gov/data-research/monitoring-programs/medicare-fee-service-compliance-programs/prior-authorization-and-pre-claim-review-initiatives",
        "support_url": "https://www.cms.gov/",
        "how_to_submit": [
            "Confirm that the requested service is one of the services subject to prior authorization or pre-claim review.",
            "Submit the request with supporting documentation to the appropriate Medicare Administrative Contractor when applicable.",
            "Retain the same clinical documentation required to support payment and submit it earlier in the process.",
        ],
        "documents_required": [
            "Ordering note with medical necessity",
            "Imaging / test reports when applicable",
            "Procedure and diagnosis coding",
            "Any documentation specified by the MAC workflow",
        ],
        "notes": "Traditional Medicare does not require prior authorization for all spine procedures; requirements are service- and setting-specific.",
    },
    "generic": {
        "label": "Other / Unknown Payer",
        "portal_name": "Use payer provider portal",
        "portal_url": "",
        "support_url": "",
        "how_to_submit": [
            "Check the member-specific provider portal or utilization management contact.",
            "Verify whether prior authorization is required before scheduling.",
            "Upload the full packet at first submission to reduce avoidable delays.",
        ],
        "documents_required": [
            "Clinical note",
            "Imaging report",
            "Conservative treatment history",
            "Procedure/CPT and ICD-10 details",
        ],
        "notes": "When the payer is not mapped, confirm the exact submission workflow manually.",
    },
}

PAYER_ALIASES = {
    "uhc": "united_healthcare",
    "united healthcare": "united_healthcare",
    "unitedhealthcare": "united_healthcare",
    "united_healthcare": "united_healthcare",
    "umr": "united_healthcare",
    "aetna": "aetna",
    "cigna": "cigna",
    "bcbs": "anthem_bcbs",
    "blue cross": "anthem_bcbs",
    "blue cross blue shield": "anthem_bcbs",
    "anthem": "anthem_bcbs",
    "anthem bcbs": "anthem_bcbs",
    "humana": "humana",
    "healthhelp": "humana",
    "cohere": "humana",
    "tricare": "tricare",
    "humana tricare": "tricare",
    "triwest": "tricare",
    "medicare": "medicare",
    "aim": "carelon",
    "carelon": "carelon",
    "aim / carelon": "carelon",
    "medsolutions": "evicore",
    "medsolutions/evicore": "evicore",
    "evicore": "evicore",
    "radmd": "radmd",
    "nia": "radmd",
    "radmd / nia / evolent": "radmd",
    "radmd/nia": "radmd",
    "superior": "ambetter",
    "ambetter": "ambetter",
    "superior/ambetter": "ambetter",
}


def canonical_payer_key(value: str) -> str:
    key = (value or "").strip().lower().replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    return PAYER_ALIASES.get(key, "generic")


def get_payer_portal(value: str) -> dict:
    raw = (value or "").strip()
    key = canonical_payer_key(value)
    if key in PAYER_PORTALS:
        return {**PAYER_PORTALS[key]}

    raw_lower = raw.lower()
    for item in load_extra_directory():
        names = [item.get("display_name", "")] + (item.get("aliases") or [])
        if any(raw_lower == str(name).strip().lower() for name in names if name):
            return _extra_directory_portal(item)

    portal = PAYER_PORTALS.get(key, PAYER_PORTALS["generic"])
    return {**portal}



def load_extra_directory() -> list[dict]:
    path = Path(__file__).resolve().parent / "insurance_directory.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, dict):
        insurers = payload.get("insurers") or []
    elif isinstance(payload, list):
        insurers = payload
    else:
        insurers = []
    normalized = []
    for item in insurers:
        if not isinstance(item, dict):
            continue
        display_name = (item.get("display_name") or "").strip()
        if not display_name:
            continue
        normalized.append(item)
    return normalized


def _extra_directory_portal(entry: dict) -> dict:
    return {
        "label": entry.get("display_name") or entry.get("label") or "Other / Unknown Payer",
        "portal_name": entry.get("portal_name") or entry.get("display_name") or "",
        "portal_url": entry.get("portal_url") or "",
        "support_url": entry.get("support_url") or "",
        "how_to_submit": entry.get("how_to_submit") or [
            "Verify the exact plan and delegated vendor from the member ID card or provider portal.",
            "Use the payer or delegated vendor portal whenever available.",
            "Attach the full clinical packet with diagnosis, imaging, and prior treatment history.",
        ],
        "documents_required": entry.get("documents_required") or [
            "Clinical note",
            "Imaging report",
            "Prior conservative treatment documentation",
            "Procedure / CPT details",
        ],
        "notes": entry.get("notes") or "",
        "provider_phone": entry.get("provider_phone") or "",
        "prior_auth_phone": entry.get("prior_auth_phone") or "",
        "fax": entry.get("prior_auth_fax") or entry.get("fax") or "",
        "verification_status": entry.get("verification_status") or "needs_manual_verification",
        "source_urls": entry.get("source_urls") or [],
        "aliases": entry.get("aliases") or [],
    }
