from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

API_DIR = Path(__file__).resolve().parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None

try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    import docx
except Exception:  # pragma: no cover
    docx = None

try:
    import openpyxl
except Exception:  # pragma: no cover
    openpyxl = None

from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

from criteria_engine import evaluate_case, normalize_diagnosis_and_icd
from procedures import PROCEDURES, canonical_procedure_key, get_procedure
from submission_portals import PAYER_PORTALS, get_payer_portal, load_extra_directory

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
CONFIG_FILE = ROOT_DIR / "config.json"

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
CORS(app)

DIAGNOSIS_LIBRARY = {
    "lumbar": [
        {"label": "Lumbar radiculopathy", "code": "M54.16"},
        {"label": "Lumbar disc herniation", "code": "M51.26"},
        {"label": "Lumbar spinal stenosis", "code": "M48.061"},
        {"label": "Degenerative disc disease, lumbar", "code": "M51.36"},
        {"label": "Spondylolisthesis, lumbar region", "code": "M43.16"},
        {"label": "Low back pain", "code": "M54.50"},
    ],
    "cervical": [
        {"label": "Cervical radiculopathy", "code": "M54.12"},
        {"label": "Cervical myelopathy", "code": "M47.12"},
        {"label": "Cervical disc disorder with radiculopathy", "code": "M50.10"},
        {"label": "Cervical spinal stenosis", "code": "M48.02"},
        {"label": "Cervical spondylosis", "code": "M47.812"},
        {"label": "Cervicalgia", "code": "M54.2"},
    ],
    "thoracic": [
        {"label": "Thoracic radiculopathy", "code": "M54.14"},
        {"label": "Thoracic disc disorder", "code": "M51.24"},
        {"label": "Thoracic spondylosis with myelopathy", "code": "M47.14"},
        {"label": "Thoracic spinal stenosis", "code": "M48.04"},
        {"label": "Thoracic pain", "code": "M54.6"},
    ],
    "deformity": [
        {"label": "Scoliosis, unspecified", "code": "M41.9"},
        {"label": "Other secondary scoliosis", "code": "M41.50"},
        {"label": "Kyphosis, thoracic region", "code": "M40.204"},
        {"label": "Postural kyphosis", "code": "M40.00"},
        {"label": "Spinal deformity / imbalance", "code": "M43.8X9"},
    ],
    "fracture": [
        {"label": "Compression fracture of vertebra", "code": "M48.50XA"},
        {"label": "Collapsed vertebra, not elsewhere classified", "code": "M48.50XA"},
        {"label": "Age-related osteoporosis with current pathological fracture", "code": "M80.08XA"},
    ],
    "pelvis": [
        {"label": "Sacroiliitis", "code": "M46.1"},
        {"label": "Sacrococcygeal disorders, not elsewhere classified", "code": "M53.3"},
        {"label": "SI joint dysfunction", "code": "M53.3"},
    ],
    "pain": [
        {"label": "Chronic pain syndrome", "code": "G89.4"},
        {"label": "Postlaminectomy syndrome", "code": "M96.1"},
        {"label": "Other chronic postprocedural pain", "code": "G89.28"},
        {"label": "Neuralgia and neuritis, unspecified", "code": "M79.2"},
    ],
    "generic": [
        {"label": "Other intervertebral disc degeneration", "code": "M51.30"},
        {"label": "Back pain, unspecified", "code": "M54.9"},
    ],
}


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (value or "")).strip("_").upper()


def title_from_suffix(suffix: str) -> str:
    parts = re.split(r"[_\-\s]+", suffix.strip())
    return " ".join(p.title() for p in parts if p)


def load_providers() -> list[dict]:
    providers: list[dict] = []
    for key, value in os.environ.items():
        if key.startswith("PROVIDER_NPI_") and value:
            suffix = key.replace("PROVIDER_NPI_", "", 1)
            providers.append({"key": slug(suffix), "name": title_from_suffix(suffix), "npi": str(value).strip()})
    providers.sort(key=lambda x: x["name"].lower())
    return providers


def resolve_npi(provider_name: str, providers: list[dict]) -> str:
    if os.environ.get("PROVIDER_NPI"):
        return os.environ["PROVIDER_NPI"].strip()
    wanted = slug(provider_name)
    for provider in providers:
        if provider["key"] == wanted:
            return provider["npi"]
    return ""


def load_config() -> dict:
    config: dict = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        config["api_key"] = os.environ["ANTHROPIC_API_KEY"].strip()
    if os.environ.get("PRACTICE_NAME"):
        config["practice_name"] = os.environ["PRACTICE_NAME"].strip()
    if os.environ.get("PROVIDER_NAME"):
        config["provider_name"] = os.environ["PROVIDER_NAME"].strip()
    if os.environ.get("ANTHROPIC_MODEL"):
        config["anthropic_model"] = os.environ["ANTHROPIC_MODEL"].strip()
    config["providers"] = load_providers()
    config["npi"] = resolve_npi(config.get("provider_name", ""), config["providers"])
    return config


def procedure_diagnosis_options(proc_type: str) -> list[dict]:
    procedure = get_procedure(proc_type)
    region = (procedure.get("region") or "").lower()
    category = (procedure.get("category") or "").lower()
    if category == "deformity":
        return DIAGNOSIS_LIBRARY["deformity"]
    if category == "fracture":
        return DIAGNOSIS_LIBRARY["fracture"]
    if region in DIAGNOSIS_LIBRARY:
        return DIAGNOSIS_LIBRARY[region]
    if region == "thoracolumbar":
        return DIAGNOSIS_LIBRARY["thoracic"] + DIAGNOSIS_LIBRARY["lumbar"]
    return DIAGNOSIS_LIBRARY["generic"]


def infer_cpt(proc_type: str) -> str:
    procedure = get_procedure(proc_type)
    codes = procedure.get("cpt") or []
    return ", ".join(codes) if codes else ""


def proc_label(proc_type: str) -> str:
    procedure = get_procedure(proc_type)
    return procedure.get("description") or proc_type or "Requested Procedure"


def try_ai_json(prompt: str, api_key: str, model_name: str) -> dict | None:
    if anthropic is None:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        if fenced:
            text = fenced.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        return json.loads(text)
    except Exception:
        return None


def safe_text(data: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except Exception:
            pass
    return ""


def extract_text_from_pdf(data: bytes) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:20]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()
    except Exception:
        return ""


def extract_text_from_docx(data: bytes) -> str:
    if docx is not None:
        try:
            document = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in document.paragraphs if p.text.strip())
        except Exception:
            pass
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
        tree = ET.fromstring(xml)
        texts = [node.text for node in tree.iter() if node.text]
        return " ".join(texts).strip()
    except Exception:
        return ""


def extract_text_from_xlsx(data: bytes) -> str:
    if openpyxl is None:
        return ""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        parts = []
        for ws in wb.worksheets[:5]:
            parts.append(f"Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                vals = [str(v).strip() for v in row if v not in (None, "")]
                if vals:
                    parts.append(" | ".join(vals))
        return "\n".join(parts).strip()
    except Exception:
        return ""


def extract_attachment_text(item: dict) -> dict:
    filename = Path(item.get("filename") or "attachment.bin").name
    content_type = (item.get("content_type") or "").lower()
    data_b64 = item.get("data_base64") or ""
    if not data_b64:
        return {"filename": filename, "content_type": content_type, "text": ""}
    try:
        raw = base64.b64decode(data_b64)
    except Exception:
        return {"filename": filename, "content_type": content_type, "text": ""}

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    text = ""
    if ext in {"txt", "md", "csv", "json", "xml", "html", "htm"}:
        text = safe_text(raw)
    elif ext == "pdf" or "pdf" in content_type:
        text = extract_text_from_pdf(raw)
    elif ext == "docx":
        text = extract_text_from_docx(raw)
    elif ext in {"xlsx", "xlsm"}:
        text = extract_text_from_xlsx(raw)
    else:
        text = safe_text(raw[:200000])

    text = re.sub(r"\s+", " ", text).strip()
    return {"filename": filename, "content_type": content_type, "text": text[:20000]}


def summarize_extracted_documents(extracted_docs: list[dict]) -> tuple[str, list[dict]]:
    summaries = []
    for doc in extracted_docs:
        text = (doc.get("text") or "").strip()
        if not text:
            continue
        snippet = text[:1400]
        summaries.append({
            "filename": doc.get("filename", "document"),
            "snippet": snippet,
            "char_count": len(text),
        })
    merged = "\n\n".join([f"FILE: {d['filename']}\n{d['snippet']}" for d in summaries])
    return merged[:18000], summaries


def normalize_case_payload(data: dict, config: dict | None = None) -> dict:
    config = config or load_config()
    providers = config.get("providers", [])
    fname = (data.get("fname") or "").strip()
    lname = (data.get("lname") or "").strip()
    patient = (data.get("patient") or f"{fname} {lname}").strip()
    provider = (data.get("provider") or config.get("provider_name") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or data.get("providerNpi") or "").strip() or resolve_npi(provider, providers) or config.get("npi", "")
    uploaded = data.get("uploaded_attachments") or data.get("uploadedAttachments") or []
    extracted_docs = [extract_attachment_text(item) for item in uploaded]
    extracted_summary, extracted_short = summarize_extracted_documents(extracted_docs)
    return {
        "patient": patient,
        "fname": fname,
        "lname": lname,
        "dob": (data.get("dob") or "").strip(),
        "member_id": (data.get("member_id") or data.get("memberId") or "").strip(),
        "payer": (data.get("payer") or "").strip(),
        "diagnosis": (data.get("diagnosis") or "").strip(),
        "proc_type": canonical_procedure_key((data.get("proc_type") or data.get("procType") or "").strip()),
        "provider": provider,
        "provider_npi": provider_npi,
        "referring_provider": (data.get("referring_provider") or data.get("referringProvider") or "").strip(),
        "pain_score": str(data.get("pain_score") or data.get("painScore") or "").strip(),
        "duration": str(data.get("duration") or "").strip(),
        "notes": (data.get("notes") or "").strip(),
        "clinical_note": (data.get("clinical_note") or data.get("clinicalNote") or data.get("notes") or "").strip(),
        "conservative_treatment": (data.get("conservative_treatment") or data.get("conservativeTreatment") or "").strip(),
        "imaging_summary": (data.get("imaging_summary") or data.get("imagingSummary") or "").strip(),
        "uploaded_attachments": uploaded,
        "extracted_documents": extracted_short,
        "extracted_text_summary": extracted_summary,
    }


def conservative_analysis(data: dict) -> dict:
    analysis = evaluate_case(data)
    analysis["portal"] = get_payer_portal(data.get("payer") or "")
    return analysis


def find_insurance_entry(payer_name: str) -> dict:
    raw = (payer_name or "").strip().lower()
    if not raw:
        return {}
    for item in load_extra_directory():
        names = [item.get("display_name", "")] + (item.get("aliases") or [])
        for name in names:
            if raw == str(name).strip().lower():
                return item
    return {}


def insurance_info_for_ui(payer_name: str, portal: dict) -> dict:
    entry = find_insurance_entry(payer_name)
    return {
        "name": (entry.get("display_name") or portal.get("label") or payer_name or "").strip(),
        "provider_phone": (entry.get("provider_phone") or portal.get("provider_phone") or "").strip(),
        "prior_auth_phone": (entry.get("prior_auth_phone") or portal.get("prior_auth_phone") or "").strip(),
        "prior_auth_fax": (entry.get("prior_auth_fax") or entry.get("fax") or portal.get("fax") or "").strip(),
        "portal_name": (entry.get("portal_name") or portal.get("portal_name") or "").strip(),
        "portal_url": (entry.get("portal_url") or portal.get("portal_url") or "").strip(),
        "support_url": (entry.get("support_url") or portal.get("support_url") or "").strip(),
        "documents_required": entry.get("documents_required") or portal.get("documents_required") or [],
        "how_to_submit": entry.get("how_to_submit") or portal.get("how_to_submit") or [],
        "notes": (entry.get("notes") or portal.get("notes") or "").strip(),
        "verification_status": (entry.get("verification_status") or portal.get("verification_status") or "needs_manual_verification").strip(),
        "source_urls": entry.get("source_urls") or portal.get("source_urls") or [],
    }


def build_portal_helper(data: dict, analysis: dict) -> dict:
    raw_missing = analysis.get("missing_elements") if isinstance(analysis, dict) else []
    missing = []
    for item in raw_missing or []:
        if isinstance(item, dict):
            missing.append(item)
        else:
            missing.append({"element": str(item), "detail": ""})
    portal = analysis.get("portal") or get_payer_portal(data.get("payer") or "")
    recommended_documents = analysis.get("recommended_documents") or portal.get("documents_required", [])
    proc_name = proc_label(data.get("proc_type") or data.get("procType") or "")
    status = "Ready for manual submission" if not missing else "Needs review before submission"
    insurance_info = insurance_info_for_ui(data.get("payer") or "", portal)
    return {
        "status": status,
        "missing": missing,
        "attachments": recommended_documents,
        "insurance_info": insurance_info,
        "next_steps": [
            "Verify demographics, procedure, CPT, ICD-10, and requested level(s).",
            "Attach the full clinical packet on first submission whenever possible.",
            f"Use the payer workflow below to submit the {proc_name} request and track status.",
        ],
        "portal": portal,
        "payer_rules": analysis.get("payer_rules") or [],
        "common_rules": analysis.get("common_rules") or [],
        "denial_risk": analysis.get("denial_risk") or {},
        "privacy_mode": "No backend PHI storage. Files are processed in-memory and returned only in the generated packet.",
    }


def build_portal_copy_block(normalized: dict, analysis: dict) -> str:
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(normalized.get("diagnosis") or "")
    extracted_docs = normalized.get("extracted_documents") or []
    imaging_hint = normalized.get("imaging_summary") or next((d.get("snippet", "") for d in extracted_docs if "mri" in d.get("filename", "").lower() or "imaging" in d.get("filename", "").lower()), "")
    clinic_hint = normalized.get("clinical_note") or next((d.get("snippet", "") for d in extracted_docs if "note" in d.get("filename", "").lower()), "")
    return "\n".join([
        "PORTAL COPY BLOCK",
        "=================",
        f"Patient: {normalized.get('patient') or '[Patient not provided]'}",
        f"DOB: {normalized.get('dob') or '[DOB not provided]'}",
        f"Payer: {normalized.get('payer') or '[Payer not provided]'}",
        f"Ordering provider: {normalized.get('provider') or '[Provider not provided]'}",
        f"NPI: {normalized.get('provider_npi') or '[NPI not provided]'}",
        f"Requested procedure: {proc_label(normalized.get('proc_type') or '')}",
        f"CPT: {infer_cpt(normalized.get('proc_type') or '') or '[CPT not mapped]'}",
        f"Diagnosis: {diagnosis_text or normalized.get('diagnosis') or '[Diagnosis not provided]'}",
        f"ICD-10: {icd_code or '[ICD-10 not provided]'}",
        f"Pain score: {normalized.get('pain_score') or '[Not provided]'}",
        f"Duration: {normalized.get('duration') or '[Not provided]'}",
        "Symptoms / clinical summary:",
        clinic_hint or normalized.get("notes") or "[No clinical summary provided]",
        "Conservative treatment:",
        normalized.get("conservative_treatment") or "[No conservative care summary provided]",
        "Imaging summary:",
        imaging_hint or "[No imaging summary provided]",
        f"Support score: {analysis.get('approval_score', 'N/A')} / 100",
        f"Criteria met: {analysis.get('criteria_met', 'N/A')} / {analysis.get('criteria_total', 'N/A')}",
        f"Missing items: {analysis.get('missing_count', 0)}",
    ]).strip()


def build_structured_letter(data: dict, practice_name: str) -> tuple[str, dict]:
    patient = (data.get("patient") or "").strip()
    dob = (data.get("dob") or "").strip()
    member_id = (data.get("member_id") or data.get("memberId") or "").strip()
    payer = (data.get("payer") or "").strip()
    diagnosis_raw = data.get("diagnosis") or ""
    diagnosis_text, icd_code = normalize_diagnosis_and_icd(diagnosis_raw)
    proc_type = (data.get("proc_type") or data.get("procType") or "").strip()
    pain_score = (data.get("pain_score") or data.get("painScore") or "").strip()
    duration = (data.get("duration") or "").strip()
    notes = (data.get("notes") or "").strip()
    conservative_treatment = (data.get("conservative_treatment") or "").strip()
    imaging_summary = (data.get("imaging_summary") or "").strip()
    referring_provider = (data.get("referring_provider") or data.get("referringProvider") or "").strip()
    provider = (data.get("provider") or "Treating Physician").strip()
    provider_npi = (data.get("provider_npi") or data.get("providerNpi") or "").strip()

    procedure = get_procedure(proc_type)
    cpt_code = infer_cpt(proc_type)
    proc_name = proc_label(proc_type)
    analysis = conservative_analysis(data)

    extracted_docs = data.get("extracted_documents") or []
    have_clinic_docs = bool(extracted_docs)

    clinical_lines = []
    if diagnosis_text or diagnosis_raw:
        clinical_lines.append(f"The patient is being submitted for review for {diagnosis_text or diagnosis_raw}.")
    else:
        clinical_lines.append("The patient is being submitted for review based on the attached clinical documentation.")

    if duration and pain_score:
        clinical_lines.append(f"Symptoms have been present for {duration} with reported pain severity of {pain_score}/10.")
    elif duration:
        clinical_lines.append(f"Symptoms have been present for {duration}.")
    elif pain_score:
        clinical_lines.append(f"Reported pain severity is {pain_score}/10.")

    if notes:
        clinical_lines.append(notes)
    elif have_clinic_docs:
        clinical_lines.append("Attached clinic documentation and supporting records describe the patient history, symptom pattern, and examination findings for review.")

    imaging_lines = []
    if imaging_summary:
        imaging_lines.append(imaging_summary)
    elif any((d.get("filename") or "").lower().find("mri") >= 0 or (d.get("filename") or "").lower().find("imaging") >= 0 for d in extracted_docs):
        imaging_lines.append("Imaging reports are attached and support the requested review.")

    conservative_lines = []
    if conservative_treatment:
        conservative_lines.append(conservative_treatment)
    elif any((d.get("filename") or "").lower().find("pt") >= 0 for d in extracted_docs):
        conservative_lines.append("Conservative treatment documentation is attached for review.")

    supporting_documents = []
    seen = set()
    for item in (analysis.get("recommended_documents") or ["Clinical note", "Imaging report", "Prior conservative treatment documentation", "Procedure / CPT details"]):
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            supporting_documents.append(str(item).strip())

    today = date.today().strftime("%B %d, %Y")

    lines = [
        today,
        "",
        f"RE: Prior Authorization Request for {proc_name}",
        "",
        f"Patient Name: {patient or '[Patient Name Not Provided]'}",
        f"Date of Birth: {dob or '[DOB Not Provided]'}",
        f"Member ID: {member_id or '[Member ID Not Provided]'}",
        f"Insurance / Payer: {payer or '[Payer Not Provided]'}",
        f"Requested Procedure: {proc_name}",
        f"CPT Code(s): {cpt_code or '[CPT Not Provided]'}",
        f"Diagnosis: {diagnosis_text or diagnosis_raw or '[Diagnosis Not Provided]'}",
        f"ICD-10 Code: {icd_code or '[ICD-10 Not Provided]'}",
        "",
        "To Whom It May Concern,",
        "",
        f"I am requesting prior authorization for the procedure listed above on behalf of my patient. This request is supported by the attached clinical records and relevant imaging.",
        "",
        "Clinical Summary:",
    ]
    lines += [f"- {item}" for item in clinical_lines if item]

    if conservative_lines:
        lines += ["", "Conservative Treatment History:"]
        lines += [f"- {item}" for item in conservative_lines if item]

    if imaging_lines:
        lines += ["", "Imaging Findings:"]
        lines += [f"- {item}" for item in imaging_lines if item]

    lines += [
        "",
        "Supporting Documentation Included:",
    ]
    lines += [f"- {doc}" for doc in supporting_documents] if supporting_documents else ["- Clinical note", "- Imaging report"]

    lines += [
        "",
        "Please review this request along with the attached documentation. If additional information is required to complete medical review, please contact our office.",
        "",
        "Sincerely,",
        "",
        provider,
        "Ordering Provider",
    ]
    if provider_npi:
        lines.append(f"NPI: {provider_npi}")
    if referring_provider:
        lines.append(f"Referring Provider: {referring_provider}")
    lines.append(practice_name)

    letter = "\n".join(lines).strip() + "\n"

    structured = {
        "patient": patient,
        "dob": dob,
        "member_id": member_id,
        "payer": payer,
        "procedure": proc_name,
        "procedure_key": canonical_procedure_key(proc_type),
        "cpt_code": cpt_code,
        "diagnosis": diagnosis_text or diagnosis_raw,
        "icd_10": icd_code,
        "provider": provider,
        "provider_npi": provider_npi,
        "referring_provider": referring_provider,
    }
    return letter, structured

def build_package_payload(data: dict, config: dict) -> dict:
    normalized = normalize_case_payload(data, config)
    analysis = conservative_analysis(normalized)
    api_key = config.get("api_key")
    if api_key:
        prompt = f"""
You are a medical prior authorization specialist. Using the structured payload and extracted uploaded document text below, return JSON with keys:
summary, medical_necessity, approval_likelihood, approval_score, strengths, missing_elements.
missing_elements must be a list of objects with keys element and detail.
Do not invent patient demographics. Base the response on the provided facts and payer workflow.

PAYLOAD:\n{json.dumps({k:v for k,v in normalized.items() if k not in ['uploaded_attachments']}, indent=2)}
ANALYSIS BASELINE:\n{json.dumps(analysis, indent=2)}
"""
        ai_json = try_ai_json(prompt, api_key, config.get("anthropic_model") or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
        if isinstance(ai_json, dict):
            analysis = {**analysis, **ai_json}
            analysis["portal"] = get_payer_portal(normalized.get("payer") or "")
            analysis.setdefault("criteria_met", analysis.get("criteria_met", 0))
            analysis.setdefault("criteria_total", analysis.get("criteria_total", len(analysis.get("criteria_results") or [])))
            analysis.setdefault("missing_count", len(analysis.get("missing_elements") or []))

    helper = build_portal_helper(normalized, analysis)
    letter, structured = build_structured_letter(normalized, config.get("practice_name", "Spine Clinic"))
    portal_copy = build_portal_copy_block(normalized, analysis)
    return {
        "generated_at": now_iso(),
        "privacy_mode": "zero_retention_transient_processing",
        "practice_name": config.get("practice_name", "Spine Clinic"),
        "patient": {
            "name": normalized["patient"],
            "dob": normalized["dob"],
            "member_id": normalized["member_id"],
            "payer": normalized["payer"],
        },
        "request": {
            "procedure": structured["procedure"],
            "procedure_key": structured["procedure_key"],
            "cpt_code": structured["cpt_code"],
            "diagnosis": structured["diagnosis"],
            "icd_10": structured["icd_10"],
            "pain_score": normalized["pain_score"],
            "duration": normalized["duration"],
        },
        "providers": {
            "ordering_provider": normalized["provider"],
            "provider_npi": normalized["provider_npi"],
            "referring_provider": normalized["referring_provider"],
        },
        "clinical_notes": normalized["notes"],
        "conservative_treatment": normalized.get("conservative_treatment", ""),
        "imaging_summary": normalized.get("imaging_summary", ""),
        "criteria_results": analysis.get("criteria_results") or [],
        "analysis": analysis,
        "portal_helper": helper,
        "insurance_info": helper.get("insurance_info") or {},
        "procedure_details": get_procedure(normalized["proc_type"]),
        "letter": letter,
        "portal_copy_block": portal_copy,
        "submission_checklist": helper.get("attachments", []),
        "submission_steps": (helper.get("portal") or {}).get("how_to_submit", []),
        "portal": helper.get("portal") or {},
        "denial_risk": analysis.get("denial_risk") or {},
        "extracted_documents": normalized.get("extracted_documents") or [],
        "email_draft": {
            "subject": f"PA Packet - {normalized['patient'] or 'Patient'} - {structured['procedure']}",
            "body": "\n".join([
                f"Please find the prior authorization packet for {normalized['patient'] or 'the patient'}.",
                "",
                f"Procedure: {structured['procedure']}",
                f"Payer: {normalized['payer']}",
                f"Support Score: {analysis.get('approval_score', 'N/A')} / 100",
                f"Criteria Met: {analysis.get('criteria_met', 'N/A')} / {analysis.get('criteria_total', 'N/A')}",
                f"Missing Items: {analysis.get('missing_count', 0)}",
                "",
                "Submission steps:",
                *[f"- {step}" for step in (helper.get('portal') or {}).get('how_to_submit', [])],
                "",
                "Please attach the downloaded PA package ZIP or PDF before sending.",
            ]).strip(),
        },
        "uploaded_attachments": normalized.get("uploaded_attachments") or [],
    }


@app.route("/")
def home():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/favicon.ico")
def favicon():
    target = PUBLIC_DIR / "favicon.ico"
    if target.exists():
        return send_from_directory(PUBLIC_DIR, "favicon.ico")
    return ("", 204)


@app.route("/<path:path>")
def static_files(path: str):
    target = PUBLIC_DIR / path
    if target.exists():
        return send_from_directory(PUBLIC_DIR, path)
    return jsonify({"error": "Not found"}), 404


@app.route("/status")
def status():
    config = load_config()
    return jsonify({
        "running": True,
        "has_api_key": bool(config.get("api_key")),
        "practice_name": config.get("practice_name", ""),
        "provider_name": config.get("provider_name", ""),
        "npi": config.get("npi", ""),
        "providers": config.get("providers", []),
        "storage_mode": "zero_retention_no_backend_case_repository",
        "procedures": [{"key": k, **v, "diagnosis_options": procedure_diagnosis_options(k)} for k, v in PROCEDURES.items()],
        "payers": load_extra_directory() or [{"key": k, **v} for k, v in PAYER_PORTALS.items() if k != "generic"],
        "diagnosis_library": DIAGNOSIS_LIBRARY,
        "additional_insurance_directory": load_extra_directory(),
    })


@app.route("/settings")
def settings():
    return status()


@app.route("/knowledge-base")
def knowledge_base():
    return jsonify({
        "procedures": [{"key": k, **v, "diagnosis_options": procedure_diagnosis_options(k)} for k, v in PROCEDURES.items()],
        "payers": load_extra_directory() or [{"key": k, **v} for k, v in PAYER_PORTALS.items()],
        "diagnosis_library": DIAGNOSIS_LIBRARY,
        "additional_insurance_directory": load_extra_directory(),
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    config = load_config()
    package = build_package_payload(request.json or {}, config)
    return jsonify({
        "analysis": package.get("analysis"),
        "portal_helper": package.get("portal_helper"),
        "criteria_results": package.get("criteria_results", []),
        "extracted_documents": package.get("extracted_documents", []),
        "portal_copy_block": package.get("portal_copy_block", ""),
        "echo_input": package.get("patient", {}),
    })


@app.route("/generate-letter", methods=["POST"])
def generate_letter():
    config = load_config()
    package = build_package_payload(request.json or {}, config)
    structured = package.get("request", {})
    return jsonify({
        "letter": package.get("letter", ""),
        "structured": structured,
        "portal_copy_block": package.get("portal_copy_block", ""),
        "extracted_documents": package.get("extracted_documents", []),
        "privacy_mode": package.get("privacy_mode"),
    })


@app.route("/build-package", methods=["POST"])
def build_package():
    config = load_config()
    return jsonify(build_package_payload(request.json or {}, config))


@app.route("/export-package", methods=["POST"])
def export_package():
    config = load_config()
    package = build_package_payload(request.json or {}, config)
    tempdir = Path(tempfile.mkdtemp(prefix="spinepa_export_"))
    case_stub = slug(package["patient"].get("name", "case") or "case")[:40] or "CASE"
    outfile = tempdir / f"{case_stub}_PA_PACKET.zip"

    with zipfile.ZipFile(outfile, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.json", json.dumps(package, indent=2))
        zf.writestr("pa_letter.txt", package.get("letter", ""))
        zf.writestr("portal_copy_block.txt", package.get("portal_copy_block", ""))

        analysis = package.get("analysis") or {}
        analysis_text = "\n".join([
            "PRIOR AUTHORIZATION READINESS REPORT",
            "=================================",
            f"Approval likelihood: {analysis.get('approval_likelihood', 'N/A')}",
            f"Support score: {analysis.get('approval_score', 'N/A')} / 100",
            f"Criteria met: {analysis.get('criteria_met', 'N/A')} / {analysis.get('criteria_total', 'N/A')}",
            f"Missing items: {analysis.get('missing_count', 0)}",
            "",
            "Executive summary:",
            analysis.get('summary', ''),
            "",
            "Medical necessity:",
            analysis.get('medical_necessity', ''),
            "",
            "Top denial risks:",
            *[f"- {item}" for item in (analysis.get('denial_risk') or {}).get('top_reasons', [])],
        ]).strip() + "\n"
        zf.writestr("analysis_report.txt", analysis_text)

        zf.writestr("clinic_submission_instructions.txt", "\n".join([
            "SUBMISSION INSTRUCTIONS",
            "=======================",
            f"Portal: {package.get('portal', {}).get('portal_name', '')}",
            f"Portal URL: {package.get('portal', {}).get('portal_url', '')}",
            f"Support URL: {package.get('portal', {}).get('support_url', '')}",
            "",
            "Steps:",
            *[f"- {x}" for x in package.get('submission_steps', [])],
            "",
            "Checklist:",
            *[f"- {x}" for x in package.get('submission_checklist', [])],
            "",
            "Privacy mode: zero-retention transient processing.",
        ]))

        zf.writestr("email_draft.txt", f"Subject: {package.get('email_draft', {}).get('subject', '')}\n\n{package.get('email_draft', {}).get('body', '')}\n")
        zf.writestr("extracted_documents.json", json.dumps(package.get("extracted_documents", []), indent=2))

        for item in package.get("uploaded_attachments", []) or []:
            filename = Path(item.get("filename") or "attachment.bin").name
            data_b64 = item.get("data_base64") or ""
            if not data_b64:
                continue
            try:
                raw = base64.b64decode(data_b64)
            except Exception:
                continue
            zf.writestr(f"attachments/{filename}", raw)

    return send_file(outfile, as_attachment=True, download_name=outfile.name, mimetype="application/zip")


@app.route("/cases", methods=["GET"])
def list_cases():
    return jsonify({"cases": [], "privacy_mode": "No backend case repository enabled in zero-retention mode."})


@app.route("/cases/<int:case_id>", methods=["GET", "PUT", "DELETE"])
def case_disabled(case_id: int):
    return jsonify({"error": "Backend case storage is disabled in zero-retention privacy mode."}), 410


@app.route("/submit", methods=["POST"])
def submit_disabled():
    return jsonify({"error": "Backend submission storage is disabled in zero-retention privacy mode. Use Download PA Package instead."}), 410


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050)
