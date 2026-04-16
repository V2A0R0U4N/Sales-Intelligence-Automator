"""
Sales Intelligence Automator — Main FastAPI Application
Routes, background job processing, and API endpoints.
"""

import asyncio
import csv
import io
import json
import os
import re
from typing import Optional, List, Dict
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models.database import (
    connect_db, close_db, create_job, get_job, update_job,
    increment_job_completed, create_lead, update_lead, get_leads_by_job,
    get_lead,
)
from pipeline.input_parser import parse_leads
from models.schemas import ParsedLead
from pipeline.scraper_v2 import scrape_lead
from pipeline.llm_analyzer import analyze_lead
from pipeline.region_discovery import discover_companies, CATEGORIES
from pipeline.email_agent import build_gmail_compose_url, build_mailto_link
from pipeline.objection_whisperer import get_objection_counter
from pipeline.sheets_agent import sync_lead_to_sheet
from pipeline.icp_discovery import discover_leads_by_icp
from pipeline.call_agent import get_call_response
from pipeline.enrichment import enrich_lead
from pipeline.agents.orchestrator import AgentOrchestrator
from pipeline.rag.chat_engine import rag_chat, get_initial_suggestions
from pipeline.messaging_agent import (
    handle_telegram_update, handle_whatsapp_message,
    verify_whatsapp_webhook, setup_telegram_webhook,
)
from models.database import (
    save_icp_profile, get_icp_profile, list_icp_profiles, delete_icp_profile,
    save_chat_message, get_chat_history, search_leads,
)


# --- Concurrency control ---
MAX_CONCURRENT_LEADS = 2  # Process 2 leads at a time
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LEADS)


# --- Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    await connect_db()
    yield
    await close_db()


# --- App ---
app = FastAPI(
    title="Sales Intelligence Automator",
    description="Automated lead research and sales brief generation",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ====================================================================
# Page Routes
# ====================================================================

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Lead input page."""
    icp_profiles = await list_icp_profiles()
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"request": request, "categories": CATEGORIES, "icp_profiles": icp_profiles},
    )


@app.get("/processing/{job_id}", response_class=HTMLResponse)
async def processing_page(request: Request, job_id: str):
    """Real-time processing status page."""
    job = await get_job(job_id)
    if not job:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "error": "Job not found. Please submit new leads."},
        )
    return templates.TemplateResponse(
        request=request, name="processing.html", context={"request": request, "job_id": job_id}
    )


@app.get("/results/{job_id}", response_class=HTMLResponse)
async def results_page(request: Request, job_id: str):
    """Results display page."""
    job = await get_job(job_id)
    if not job:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "error": "Job not found. Please submit new leads."},
        )

    leads = await get_leads_by_job(job_id)

    # Sort: completed first, then by company name
    leads.sort(key=lambda x: (0 if x.get("status") == "completed" else 1, x.get("company_name", "")))

    return templates.TemplateResponse(
        request=request, name="results.html", context={
            "request": request,
            "job": job,
            "leads": leads,
            "config": {
                "GOOGLE_SHEETS_SPREADSHEET_ID": os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
            },
        }
    )


# ====================================================================
# Phase 1 — ICP Builder Routes
# ====================================================================

@app.get("/icp-builder", response_class=HTMLResponse)
async def icp_builder_page(request: Request):
    """ICP Builder page."""
    return templates.TemplateResponse(
        request=request, name="icp_builder.html", context={"request": request}
    )


@app.post("/api/icp/save")
async def api_save_icp(request: Request):
    """Save a new ICP profile or update an existing one."""
    data = await request.json()
    profile_id = await save_icp_profile(data)
    return JSONResponse({"status": "ok", "profile_id": profile_id})


@app.get("/api/icp/list")
async def api_list_icps():
    """List all saved ICP profiles."""
    profiles = await list_icp_profiles()
    return JSONResponse(profiles)


@app.get("/api/icp/{profile_id}")
async def api_get_icp(profile_id: str):
    """Get a single ICP profile."""
    profile = await get_icp_profile(profile_id)
    if not profile:
        return JSONResponse({"detail": "Profile not found"}, status_code=404)
    return JSONResponse(profile)


@app.delete("/api/icp/{profile_id}")
async def api_delete_icp(profile_id: str):
    """Delete an ICP profile."""
    deleted = await delete_icp_profile(profile_id)
    if not deleted:
        return JSONResponse({"detail": "Profile not found"}, status_code=404)
    return JSONResponse({"status": "deleted"})


@app.post("/api/icp/discover")
async def api_icp_discover(request: Request):
    """Run ICP-driven discovery — the '30 → 5' flow."""
    data = await request.json()
    profile_id = data.get("profile_id")

    if profile_id:
        icp_profile = await get_icp_profile(profile_id)
        if not icp_profile:
            return JSONResponse({"detail": "ICP profile not found"}, status_code=404)
    else:
        icp_profile = data  # Inline profile from form

    max_candidates = int(data.get("max_candidates", 30))

    # Run discovery (synchronous, runs DuckDuckGo + LLM scoring)
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None, discover_leads_by_icp, icp_profile, max_candidates, 50
    )

    return JSONResponse([r.model_dump() for r in results])


# ====================================================================
# API Routes
# ====================================================================

def validate_region_input(region: str) -> Optional[str]:
    if not region or len(region) < 2:
        return "Region must be at least 2 characters long."
    if len(region) > 50:
        return "Region is too long. Please provide a valid city/country name."
    # Basic math or garbage checks
    if re.search(r"\d+\s*[\+\-\*/=]\s*\d+", region):
        return "Please enter a valid region name, not an equation."
    # Basic conversational / prompt checks
    prmpt_pattern = r"^(tell me|what is|how do|write a|create a|give me|can you|help me|explain|find)"
    if re.search(prmpt_pattern, region.lower()):
        return "Please enter just the region name (e.g., 'London' or 'New York')."
    return None

@app.post("/api/discover")
async def discover_region(request: Request):
    """Discover companies by region + category."""
    body = await request.json()
    region = body.get("region", "").strip()
    category = body.get("category", "technology").strip()

    if not region:
        return JSONResponse({"error": "Region is required"}, status_code=400)
    
    validation_error = validate_region_input(region)
    if validation_error:
        return JSONResponse({"error": validation_error}, status_code=400)

    # Run blocking search in thread pool
    loop = asyncio.get_running_loop()
    companies = await loop.run_in_executor(
        None, discover_companies, region, category, 35
    )

    return JSONResponse({
        "region": region,
        "category": category,
        "category_label": CATEGORIES.get(category, category),
        "count": len(companies),
        "companies": companies,
    })


@app.post("/api/analyze")
async def submit_leads(
    request: Request,
    leads_text: str = Form(None),
    selected_companies: str = Form(None),
    icp_profile_id: str = Form(None),
):
    """
    Accept leads text OR selected discovered companies.
    Creates job and starts background processing.
    Optionally uses a custom ICP profile for scoring.
    """
    parsed = []

    # Load ICP profile if selected
    icp_profile = None
    if icp_profile_id:
        icp_profile = await get_icp_profile(icp_profile_id)

    # Option 1: Selected companies from discovery (JSON list)
    if selected_companies:
        try:
            companies = json.loads(selected_companies)
            for comp in companies:
                parsed.append(ParsedLead(
                    raw_input=comp.get("name", "Unknown"),
                    input_type="url" if comp.get("url") else "name_only",
                    url=comp.get("url"),
                    company_name=comp.get("name", "Unknown"),
                    location=comp.get("region"),
                    category=comp.get("category"),
                ))
        except json.JSONDecodeError:
            pass

    # Option 2: Raw text input (ALSO add, not either/or)
    if leads_text and leads_text.strip():
        extra_parsed = parse_leads(leads_text)
        parsed.extend(extra_parsed)

    if not parsed:
        return templates.TemplateResponse(
            request=request, name="index.html",
            context={
                "request": request,
                "categories": CATEGORIES,
                "error": "No valid leads found. Please enter at least one lead.",
            },
            status_code=400,
        )

    # Handle region queries — discover companies first, then analyze each
    final_parsed = []
    for lead in parsed:
        if lead.input_type == "region_query":
            loop = asyncio.get_running_loop()
            companies = await loop.run_in_executor(
                None, discover_companies,
                lead.location or "", lead.category or "technology", 5
            )
            for comp in companies:
                final_parsed.append(ParsedLead(
                    raw_input=comp["name"],
                    input_type="url",
                    url=comp["url"],
                    company_name=comp["name"],
                    location=lead.location,
                ))
        else:
            final_parsed.append(lead)

    if not final_parsed:
        return templates.TemplateResponse(
            request=request, name="index.html",
            context={
                "request": request,
                "categories": CATEGORIES,
                "error": "Could not find any companies for that region. Try a different search.",
            },
            status_code=400,
        )

    # Create job
    job_id = await create_job(len(final_parsed))

    # Create lead documents in DB
    lead_ids = []
    for lead in final_parsed:
        lead_doc = {
            "job_id": job_id,
            "raw_input": lead.raw_input,
            "input_type": lead.input_type,
            "company_name": lead.company_name or "Unknown",
            "website": lead.url,
            "location": lead.location,
            "service_hint": lead.service_hint,
            "status": "queued",
        }
        lead_id = await create_lead(lead_doc)
        lead_ids.append((lead_id, lead))

    # Start background processing
    asyncio.create_task(_process_job(job_id, lead_ids, icp_profile=icp_profile))

    # Redirect to processing page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/processing/{job_id}", status_code=303)


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Get job status for polling."""
    job = await get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    leads = await get_leads_by_job(job_id)

    return JSONResponse({
        "job_id": job_id,
        "status": job.get("status", "processing"),
        "lead_count": job.get("lead_count", 0),
        "completed_count": job.get("completed_count", 0),
        "leads": [
            {
                "lead_id": lead.get("lead_id"),
                "company_name": lead.get("company_name", "Unknown"),
                "raw_input": lead.get("raw_input", ""),
                "status": lead.get("status", "queued"),
                "error_message": lead.get("error_message"),
            }
            for lead in leads
        ],
    })


@app.get("/api/export/{job_id}/{fmt}")
async def export_results(job_id: str, fmt: str):
    """Export results as CSV or JSON."""
    leads = await get_leads_by_job(job_id)

    if not leads:
        return JSONResponse({"error": "No results found"}, status_code=404)

    if fmt == "json":
        # Clean MongoDB-specific fields
        export_data = []
        for lead in leads:
            clean_lead = {k: v for k, v in lead.items() if not k.startswith("_")}
            export_data.append(clean_lead)

        content = json.dumps(export_data, indent=2, default=str)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=leads_{job_id}.json"},
        )

    elif fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "Company Name", "Website", "Status", "Company Overview",
            "Core Product/Service", "Target Customer", "B2B Qualified",
            "B2B Reason", "Sales Question 1", "Sales Question 2",
            "Sales Question 3", "Research Confidence",
            "Best Fit Vertical", "Vertical Score", "Pitch Angle",
            "Recommended Services",
        ])

        for lead in leads:
            brief = lead.get("brief", {})
            icp = lead.get("icp_match", {})

            writer.writerow([
                lead.get("company_name", ""),
                lead.get("website", ""),
                lead.get("status", ""),
                brief.get("company_overview", ""),
                brief.get("core_product_service", ""),
                brief.get("target_customer", ""),
                brief.get("b2b_qualified", ""),
                brief.get("b2b_reason", ""),
                brief.get("sales_question_1", ""),
                brief.get("sales_question_2", ""),
                brief.get("sales_question_3", ""),
                brief.get("research_confidence", ""),
                icp.get("best_fit_vertical", ""),
                icp.get(f"{icp.get('best_fit_vertical', '').lower()}_score", ""),
                icp.get("pitch_angle", ""),
                "; ".join(icp.get("recommended_services", [])),
            ])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=leads_{job_id}.csv"},
        )

    return JSONResponse({"error": "Format must be 'csv' or 'json'"}, status_code=400)


# ====================================================================
# Background Pipeline Processing
# ====================================================================

async def _process_job(job_id: str, lead_ids: list, icp_profile: dict | None = None):
    """Process all leads in a job concurrently with semaphore control."""
    tasks = []
    for lead_id, parsed_lead in lead_ids:
        task = asyncio.create_task(
            _process_single_lead(job_id, lead_id, parsed_lead, icp_profile=icp_profile)
        )
        tasks.append(task)

    await asyncio.gather(*tasks, return_exceptions=True)

    # Mark job as completed
    await update_job(job_id, {"status": "completed"})
    print(f"[Job {job_id}] All leads processed.")


async def _process_single_lead(job_id: str, lead_id: str, parsed_lead, icp_profile: dict | None = None):
    """Process a single lead through the full pipeline."""
    async with _semaphore:
        try:
            website = parsed_lead.url
            company_name = parsed_lead.company_name or "Unknown"
            
            query = parsed_lead.raw_input
            
            await update_lead(lead_id, {"status": "scraping"})
            print(f"[Pipeline] Scraping: {query}")
            
            # Since scrape is synchronous, we run it in a thread pool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            scrape_result = await loop.run_in_executor(None, scrape_lead, query, company_name, website)
            
            if scrape_result["status"] in ["url_not_found", "fetch_failed", "error", "failed", "parked_domain"]:
                error_msg = scrape_result.get("error") or "Failed to resolve or scrape company."
                error_code = scrape_result.get("error_code", "unknown")
                error_detail = scrape_result.get("error_detail", error_msg)
                await update_lead(lead_id, {
                    "status": "error",
                    "error_message": error_msg,
                    "error_code": error_code,
                    "error_detail": error_detail,
                })
                await increment_job_completed(job_id)
                print(f"[Pipeline] Scraping failed for: {query} (code={error_code})")
                return
            
            website = scrape_result.get("url", website) or website
            company_name = scrape_result.get("company_name") or company_name
            combined_text = scrape_result.get("combined_text", "")
            word_count = scrape_result.get("word_count", 0)
            thin_content = word_count < 150
            
            # --- Step 4: Deep Enrichment (Phase 2) ---
            await update_lead(lead_id, {"status": "enriching"})
            enriched_data = await enrich_lead(
                company_name=company_name,
                website=website,
                content=combined_text,
                html_content=scrape_result.get("raw_html", ""),
            )
            print(f"[Pipeline] Enrichment done: {company_name}")

            # --- Step 5: LLM Analysis ---
            await update_lead(lead_id, {"status": "analyzing"})
            print(f"[Pipeline] Analyzing: {company_name} ({word_count} words)")

            analysis = await analyze_lead(
                company_name=company_name,
                website=website,
                content=combined_text,
                thin_content=thin_content,
                icp_profile=icp_profile,
            )

            # --- Step 6: Multi-Agent Insights (Phase 3) ---
            agent_insights = {}
            try:
                orchestrator = AgentOrchestrator()
                agent_insights = await orchestrator.run(
                    company_name=company_name,
                    content=combined_text,
                    brief=analysis.get("brief", {}),
                    icp_match=analysis.get("icp_match", {}),
                )
                print(f"[Pipeline] Agent crew done: {len(agent_insights.get('agents_run', []))} agents")
            except Exception as agent_err:
                print(f"[Pipeline] Agent crew failed (non-fatal): {agent_err}")

            # --- Step 7: Email Agent — build Gmail compose + mailto URLs ---
            _email_data = analysis.get("outreach_email", {})
            _gmail_url = build_gmail_compose_url(
                subject=_email_data.get("subject", ""),
                body=_email_data.get("body", ""),
            )
            _mailto_link = build_mailto_link(
                subject=_email_data.get("subject", ""),
                body=_email_data.get("body", ""),
            )

            # --- Step 8: Save all results ---
            await update_lead(lead_id, {
                "status": "completed",
                "company_name": analysis["brief"].get("company_name", company_name),
                "website": website,
                "brief": analysis["brief"],
                "icp_match": analysis["icp_match"],
                "market_context": analysis["market_context"],
                "outreach_email": analysis["outreach_email"],
                "objection_prep": analysis["objection_prep"],
                "enriched_data": enriched_data,
                "agent_insights": agent_insights,
                "thin_content": thin_content,
                "word_count": word_count,
                "pages_scraped": len(scrape_result.get("pages_scraped", [])),
                "name_mismatch_warning": scrape_result.get("name_mismatch_warning", False),
                "error_code": scrape_result.get("error_code"),
                "error_detail": scrape_result.get("error_detail"),
                "gmail_compose_url": _gmail_url,
                "mailto_link": _mailto_link,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })

            await increment_job_completed(job_id)
            print(f"[Pipeline] Completed: {company_name}")

            # --- Phase 7: Google Sheets CRM sync (non-blocking) ---
            if os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID"):
                completed_lead = await get_lead(lead_id)
                if completed_lead:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(
                        None, sync_lead_to_sheet, completed_lead
                    )

        except Exception as e:
            print(f"[Pipeline] Error processing lead {lead_id}: {e}")
            await update_lead(lead_id, {
                "status": "error",
                "error_message": str(e),
            })
            await increment_job_completed(job_id)


# ====================================================================
# Phase 9 — Real-Time Objection Whisperer (WebSocket)
# ====================================================================

@app.websocket("/ws/whisperer/{lead_id}")
async def objection_whisperer_ws(websocket: WebSocket, lead_id: str):
    """
    Real-time objection handler for live sales calls.
    
    Client sends:  {"objection": "They say they already use competitor X"}
    Server returns: {"counter": "...", "probe": "...", "response_time_ms": 820}
    """
    await websocket.accept()
    print(f"[Whisperer] WebSocket connected for lead: {lead_id}")

    # Load lead data once at connection time
    lead_doc = await get_lead(lead_id)

    if not lead_doc:
        await websocket.send_json({"error": f"Lead {lead_id} not found"})
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_json()
            objection = data.get("objection", "").strip()

            if not objection:
                await websocket.send_json({
                    "counter": "I need to hear the objection first — type what they said.",
                    "probe": None,
                    "response_time_ms": 0,
                })
                continue

            result = await get_objection_counter(objection, lead_doc)

            print(f"[Whisperer] Objection: '{objection[:60]}...' → {result.get('response_time_ms')}ms")
            await websocket.send_json(result)

    except WebSocketDisconnect:
        print(f"[Whisperer] WebSocket disconnected for lead: {lead_id}")
    except Exception as e:
        print(f"[Whisperer] Error: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass

# ====================================================================
# Phase 6 — Bilingual Call Practice Agent (WebSocket)
# ====================================================================

@app.websocket("/ws/call-practice/{lead_id}")
async def call_practice_ws(websocket: WebSocket, lead_id: str):
    """
    Bilingual call practice / live coaching agent.
    
    Client sends:  {"message": "Hi, I'm calling about...", "language": "english"}
    Server returns: {"response": "...", "suggestion": "...", "response_time_ms": 820}
    """
    await websocket.accept()
    print(f"[CallAgent] WebSocket connected for lead: {lead_id}")

    lead_doc = await get_lead(lead_id)
    if not lead_doc:
        await websocket.send_json({"error": f"Lead {lead_id} not found"})
        await websocket.close()
        return

    conversation_history = []

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "").strip()
            language = data.get("language", "english").lower()

            if not message:
                await websocket.send_json({
                    "response": "I didn't catch that — what did you say to the prospect?",
                    "suggestion": None,
                    "response_time_ms": 0,
                })
                continue

            result = await get_call_response(
                message=message,
                lead_doc=lead_doc,
                conversation_history=conversation_history,
                language=language,
            )

            # Update history
            conversation_history.append({"role": "user", "content": message})
            conversation_history.append({"role": "assistant", "content": result.get("response", "")})

            print(f"[CallAgent] Turn {len(conversation_history)//2}: lang={language}, {result.get('response_time_ms')}ms")
            await websocket.send_json(result)

    except WebSocketDisconnect:
        print(f"[CallAgent] WebSocket disconnected for lead: {lead_id}")
    except Exception as e:
        print(f"[CallAgent] Error: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass

# ====================================================================
# Phase 4 — RAG Lead Chat (WebSocket)
# ====================================================================

@app.websocket("/ws/chat/{lead_id}")
async def rag_chat_ws(websocket: WebSocket, lead_id: str):
    """
    Per-lead RAG chatbot.
    
    Client sends:  {"message": "What services should I pitch?"}
    Server returns: {"response": "...", "suggested_questions": [...], "response_time_ms": 820}
    """
    await websocket.accept()
    print(f"[RAGChat] WebSocket connected for lead: {lead_id}")

    lead_doc = await get_lead(lead_id)
    if not lead_doc:
        await websocket.send_json({"error": f"Lead {lead_id} not found"})
        await websocket.close()
        return

    # Load any existing chat history
    conversation_history = await get_chat_history(lead_id)

    # Send initial suggestions
    await websocket.send_json({
        "type": "init",
        "suggested_questions": get_initial_suggestions(),
        "history_count": len(conversation_history),
    })

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "").strip()

            if not message:
                await websocket.send_json({
                    "response": "Please ask me a question about this lead.",
                    "suggested_questions": get_initial_suggestions(),
                    "response_time_ms": 0,
                })
                continue

            result = await rag_chat(
                message=message,
                lead_doc=lead_doc,
                conversation_history=conversation_history,
            )

            # Update history
            conversation_history.append({"role": "user", "content": message})
            conversation_history.append({"role": "assistant", "content": result.get("response", "")})

            # Persist to database (non-blocking)
            asyncio.create_task(save_chat_message(lead_id, "user", message))
            asyncio.create_task(save_chat_message(lead_id, "assistant", result.get("response", "")))

            print(f"[RAGChat] Q: '{message[:50]}...' → {result.get('response_time_ms')}ms")
            await websocket.send_json(result)

    except WebSocketDisconnect:
        print(f"[RAGChat] WebSocket disconnected for lead: {lead_id}")
    except Exception as e:
        print(f"[RAGChat] Error: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass


# ====================================================================
# Phase 10 — WhatsApp & Telegram Webhook Routes
# ====================================================================

# Database helper dict for the messaging agent
_msg_db_helpers = {
    "get_lead": get_lead,
    "search_leads": search_leads,
}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram Bot API webhook endpoint.
    Receives updates from Telegram and routes them to the messaging agent.
    """
    try:
        body = await request.json()
        result = await handle_telegram_update(body, _msg_db_helpers)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        print(f"[Telegram Webhook] Error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """
    WhatsApp webhook verification (GET request).
    Meta sends this during webhook setup to verify ownership.
    """
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    result = verify_whatsapp_webhook(mode, token, challenge)
    if result is not None:
        return HTMLResponse(content=result, status_code=200)
    return JSONResponse({"error": "Verification failed"}, status_code=403)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    WhatsApp Business Cloud API webhook endpoint.
    Receives messages and routes them to the messaging agent.
    """
    try:
        body = await request.json()
        result = await handle_whatsapp_message(body, _msg_db_helpers)
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        print(f"[WhatsApp Webhook] Error: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/telegram/setup")
async def api_setup_telegram(request: Request):
    """
    One-time Telegram webhook setup.
    POST body: {"base_url": "https://your-domain.com"}
    """
    data = await request.json()
    base_url = data.get("base_url", "").rstrip("/")
    if not base_url:
        return JSONResponse({"error": "base_url is required"}, status_code=400)

    success = await setup_telegram_webhook(base_url)
    return JSONResponse({"ok": success})


# ====================================================================
# Run with: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# ====================================================================
