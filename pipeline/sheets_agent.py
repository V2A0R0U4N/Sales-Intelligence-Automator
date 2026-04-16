"""
Google Sheets CRM Sync Agent
=============================
Auto-syncs qualified leads (ICP score > 70 or is_good_fit) to a shared
Google Sheet — the team's free, zero-cost CRM.

Setup (one-time, ~10 minutes):
  1. Go to console.cloud.google.com → Create project → Enable "Google Sheets API"
  2. Create a Service Account → Download JSON key → save as google_credentials.json
  3. Share your Google Sheet with the service account email
  4. Add to .env:
       GOOGLE_SHEETS_CREDENTIALS=google_credentials.json
       GOOGLE_SHEETS_SPREADSHEET_ID=<your_sheet_id_from_url>

All free — Google Cloud charges nothing at this usage level.
"""

import os
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# Lazy imports — only loaded when sheets sync is actually called
_gspread_available = None
_client_cache = None


SHEET_COLUMNS = [
    "Date Processed",
    "Company Name",
    "Website",
    "B2B Qualified",
    "ICP Fit Score",
    "Best Fit Vertical",
    "ICP Fit Verdict",
    "Pitch Angle",
    "Recommended Services",
    "Company Overview",
    "Core Product / Service",
    "Target Customer",
    "Employee Estimate",
    "Revenue Estimate",
    "Tech Stack",
    "Key Contact Name",
    "Key Contact Title",
    "Key Contact Email Guess",
    "Trigger Events",
    "Email Subject",
    "Email Body (Preview)",
    "Gmail Compose Link",
    "Cold Call Opener",
    "Top Objection",
    "Research Confidence",
    "Job ID",
    "Lead ID",
]


def _check_gspread():
    """Lazy-check if gspread is installed."""
    global _gspread_available
    if _gspread_available is not None:
        return _gspread_available
    try:
        import gspread  # noqa: F401
        from google.oauth2.service_account import Credentials  # noqa: F401
        _gspread_available = True
    except ImportError:
        _gspread_available = False
        log.warning(
            "[SheetsAgent] gspread not installed. "
            "Run: pip install gspread google-auth"
        )
    return _gspread_available


def _get_client():
    """
    Authenticate with Google Sheets API via Service Account.
    Caches the client for reuse across multiple lead syncs.
    """
    global _client_cache
    if _client_cache is not None:
        return _client_cache

    import gspread
    from google.oauth2.service_account import Credentials

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "google_credentials.json")

    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Google credentials not found at '{creds_path}'. "
            "Please set up a Google Service Account (free) — see README."
        )

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    _client_cache = gspread.authorize(creds)
    log.info("[SheetsAgent] Authenticated with Google Sheets API")
    return _client_cache


def _get_best_icp_score(lead_doc: dict) -> int:
    """Extract the highest ICP vertical score from a lead document."""
    icp = lead_doc.get("icp_match", {})

    # Phase 1 dynamic format: {"vertical_scores": {"IT Services": 85, ...}}
    vertical_scores = icp.get("vertical_scores", {})
    if vertical_scores:
        return max(vertical_scores.values(), default=0)

    # Legacy hardcoded Moksh format
    legacy_keys = [
        "mokshtech_score", "mokshcad_score",
        "mokshdigital_score", "mokshsigns_score",
    ]
    scores = [icp.get(k, 0) for k in legacy_keys if icp.get(k, 0)]
    return max(scores) if scores else 0


def sync_lead_to_sheet(lead_doc: dict) -> bool:
    """
    Append a completed lead to the Google Sheet CRM.

    Only syncs leads where ICP score > 70 or is_good_fit == True.

    Args:
        lead_doc: Full lead document from the database.

    Returns:
        True if sync succeeded, False otherwise (non-blocking).
    """
    # Guard: check if sheets sync is configured
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        return False

    if not _check_gspread():
        return False

    try:
        icp = lead_doc.get("icp_match", {})
        brief = lead_doc.get("brief", {})
        enriched = lead_doc.get("enriched_data", {})
        email = lead_doc.get("outreach_email", {})
        obj_prep = lead_doc.get("objection_prep", {})
        objections = obj_prep.get("objections", [])
        call_script = lead_doc.get("call_script", {})

        best_score = _get_best_icp_score(lead_doc)

        # Only sync qualified leads
        if best_score < 70 and not icp.get("is_good_fit"):
            log.debug(
                f"[SheetsAgent] Skipping {lead_doc.get('company_name')} "
                f"(score={best_score}, is_good_fit={icp.get('is_good_fit')})"
            )
            return False

        # Get primary decision maker contact
        contacts = enriched.get("decision_makers", [])
        primary_contact = contacts[0] if contacts else {}

        # Trigger events summary (top 2)
        triggers = enriched.get("trigger_events", [])
        trigger_str = "; ".join(
            [t.get("headline", "") for t in triggers[:2]]
        ) if triggers else ""

        # Tech stack names (top 5)
        tech_items = enriched.get("tech_stack", [])
        tech_str = "; ".join(
            [t.get("name", "") for t in tech_items[:5]]
        ) if tech_items else ""

        # Primary contact email guess
        email_guesses = primary_contact.get("email_guesses", [])
        primary_email = email_guesses[0] if email_guesses else ""

        # Recommended services
        rec_services = icp.get("recommended_services", [])
        services_str = "; ".join(rec_services) if rec_services else ""

        # Build the row — matches SHEET_COLUMNS order exactly
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            lead_doc.get("company_name", ""),
            lead_doc.get("website", ""),
            "Yes" if brief.get("b2b_qualified") else "No",
            str(best_score),
            icp.get("best_fit_vertical", ""),
            icp.get("fit_verdict", ""),
            (icp.get("pitch_angle", "") or "")[:200],
            services_str,
            (brief.get("company_overview", "") or "")[:300],
            brief.get("core_product_service", ""),
            brief.get("target_customer", ""),
            enriched.get("employee_estimate", "Unknown"),
            enriched.get("revenue_estimate", "Unknown"),
            tech_str,
            primary_contact.get("name", "Not found"),
            primary_contact.get("title", ""),
            primary_email,
            trigger_str,
            email.get("subject", ""),
            (email.get("body", "") or "")[:500],
            lead_doc.get("gmail_compose_url", ""),
            call_script.get("opener_line", ""),
            objections[0].get("objection", "") if objections else "",
            brief.get("research_confidence", ""),
            lead_doc.get("job_id", ""),
            lead_doc.get("lead_id", ""),
        ]

        # Connect to Google Sheets
        client = _get_client()
        sheet = client.open_by_key(spreadsheet_id).sheet1

        # Add header if sheet is empty
        existing = sheet.get_all_values()
        if not existing or not existing[0]:
            sheet.append_row(SHEET_COLUMNS, value_input_option="RAW")

        # Append the lead row
        sheet.append_row(row, value_input_option="USER_ENTERED")

        log.info(
            f"[SheetsAgent] ✓ Synced '{lead_doc.get('company_name')}' "
            f"(score={best_score}) to Google Sheet"
        )
        return True

    except Exception as e:
        log.error(f"[SheetsAgent] Failed to sync lead: {e}")
        return False  # Non-blocking — never crash the pipeline
