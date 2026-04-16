"""
Unified Messaging Agent — WhatsApp & Telegram Integration
==========================================================
Routes incoming messages from WhatsApp Business Cloud API and
Telegram Bot API to the Sales Intelligence pipeline (whisperer + RAG chat).

Users text a lead name or objection → the agent looks up the lead,
routes to the correct engine, and replies back via the same platform.

Configuration (env vars):
  TELEGRAM_BOT_TOKEN        — from @BotFather
  WHATSAPP_VERIFY_TOKEN     — your chosen webhook verification string
  WHATSAPP_ACCESS_TOKEN     — Meta Graph API permanent token
  WHATSAPP_PHONE_NUMBER_ID  — your WhatsApp Business phone number ID
"""

from __future__ import annotations

import os
import re
import json
import logging
import httpx
from typing import Optional

log = logging.getLogger(__name__)

# ── Env Config ────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WHATSAPP_VERIFY = os.getenv("WHATSAPP_VERIFY_TOKEN", "salesintel_verify_2024")
WHATSAPP_ACCESS = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# ── Session State (in-memory; production would use Redis) ─────────────
# Maps platform_user_id → { "lead_id": str, "company_name": str, "mode": "chat"|"whisperer" }
_sessions: dict[str, dict] = {}


# =====================================================================
#  TELEGRAM BOT
# =====================================================================

async def handle_telegram_update(update: dict, db_helpers: dict) -> Optional[dict]:
    """
    Process a single Telegram update (message).
    
    Args:
        update: Raw Telegram update JSON
        db_helpers: Dict with keys 'get_leads_by_job', 'get_lead', 'search_leads'
                    — async callables from the database module.
    
    Returns:
        Response dict for logging, or None.
    """
    message = update.get("message")
    if not message:
        return None

    chat_id = str(message["chat"]["id"])
    text = (message.get("text") or "").strip()
    
    if not text:
        return None

    log.info(f"[Telegram] From {chat_id}: {text[:80]}")

    # ── Command handlers ──────────────────────────────────────────
    if text.startswith("/start"):
        reply = (
            "👋 Welcome to Sales Intelligence Bot!\n\n"
            "I can help you during live sales calls.\n\n"
            "Commands:\n"
            "/search <company> — Find a lead by name\n"
            "/whisperer — Switch to objection whisperer mode\n"
            "/chat — Switch to lead Q&A chat mode\n"
            "/status — Show your current active lead\n"
            "/help — Show this help message\n\n"
            "Start by searching for a lead: /search Acme Corp"
        )
        await _send_telegram(chat_id, reply)
        return {"status": "welcome_sent"}

    if text.startswith("/help"):
        reply = (
            "📖 *Commands:*\n"
            "/search `<company>` — Find & select a lead\n"
            "/whisperer — Objection counter mode (type what they said)\n"
            "/chat — Ask AI about the lead\n"
            "/status — Current lead info\n\n"
            "_In whisperer mode, just type the objection you heard._\n"
            "_In chat mode, ask any question about the lead._"
        )
        await _send_telegram(chat_id, reply, parse_mode="Markdown")
        return {"status": "help_sent"}

    if text.startswith("/search"):
        query = text[7:].strip()
        if not query:
            await _send_telegram(chat_id, "Usage: /search <company name>")
            return {"status": "search_empty"}

        search_fn = db_helpers.get("search_leads")
        if not search_fn:
            await _send_telegram(chat_id, "⚠️ Search not available in this deployment.")
            return {"status": "search_unavailable"}

        leads = await search_fn(query)
        if not leads:
            await _send_telegram(chat_id, f"❌ No leads found matching \"{query}\".\nMake sure the lead has been analyzed on the web dashboard first.")
            return {"status": "no_results"}

        # Auto-select first match
        lead = leads[0]
        _sessions[chat_id] = {
            "lead_id": lead.get("lead_id", ""),
            "company_name": lead.get("company_name", "Unknown"),
            "mode": "whisperer",
            "history": [],
        }

        icp = lead.get("icp_match", {})
        brief = lead.get("brief", {})
        reply = (
            f"✅ *Lead Selected:* {lead.get('company_name', 'Unknown')}\n"
            f"🌐 {lead.get('website', 'N/A')}\n"
            f"🎯 Best Fit: {icp.get('best_fit_vertical', 'N/A')}\n"
            f"📊 Verdict: {icp.get('fit_verdict', 'N/A')}\n\n"
            f"Mode: 🎤 *Whisperer* (type an objection to get a counter)\n"
            f"Switch modes: /chat or /whisperer"
        )
        await _send_telegram(chat_id, reply, parse_mode="Markdown")
        return {"status": "lead_selected", "lead": lead.get("company_name")}

    if text.startswith("/whisperer"):
        session = _sessions.get(chat_id)
        if not session:
            await _send_telegram(chat_id, "No lead selected. Use /search first.")
            return {"status": "no_session"}
        session["mode"] = "whisperer"
        await _send_telegram(chat_id, f"🎤 Whisperer mode for *{session['company_name']}*\nType the objection you just heard on the call.", parse_mode="Markdown")
        return {"status": "mode_whisperer"}

    if text.startswith("/chat"):
        session = _sessions.get(chat_id)
        if not session:
            await _send_telegram(chat_id, "No lead selected. Use /search first.")
            return {"status": "no_session"}
        session["mode"] = "chat"
        session["history"] = []
        await _send_telegram(chat_id, f"💬 Chat mode for *{session['company_name']}*\nAsk anything about this lead.", parse_mode="Markdown")
        return {"status": "mode_chat"}

    if text.startswith("/status"):
        session = _sessions.get(chat_id)
        if not session:
            await _send_telegram(chat_id, "No lead selected. Use /search <company> to start.")
            return {"status": "no_session"}
        mode_emoji = "🎤" if session["mode"] == "whisperer" else "💬"
        await _send_telegram(
            chat_id,
            f"📋 *Active Lead:* {session['company_name']}\n"
            f"{mode_emoji} Mode: {session['mode'].title()}\n"
            f"Lead ID: `{session['lead_id']}`",
            parse_mode="Markdown",
        )
        return {"status": "status_sent"}

    # ── Free-text: route to whisperer or chat ─────────────────────
    if text.startswith("/"):
        await _send_telegram(chat_id, "Unknown command. Type /help for available commands.")
        return {"status": "unknown_command"}

    session = _sessions.get(chat_id)
    if not session:
        await _send_telegram(chat_id, "👋 Welcome! Use /search <company name> to get started.")
        return {"status": "no_session"}

    get_lead = db_helpers.get("get_lead")
    if not get_lead:
        await _send_telegram(chat_id, "⚠️ Database not available.")
        return {"status": "db_unavailable"}

    lead_doc = await get_lead(session["lead_id"])
    if not lead_doc:
        await _send_telegram(chat_id, "⚠️ Lead not found. Try /search again.")
        _sessions.pop(chat_id, None)
        return {"status": "lead_missing"}

    if session["mode"] == "whisperer":
        # Route to objection whisperer
        from pipeline.objection_whisperer import get_objection_counter
        result = await get_objection_counter(text, lead_doc)

        reply = f"💬 *SAY THIS:*\n{result.get('counter', '')}"
        if result.get("probe"):
            reply += f"\n\n❓ *THEN ASK:*\n{result['probe']}"
        reply += f"\n\n⚡ {result.get('response_time_ms', 0)}ms"

        await _send_telegram(chat_id, reply, parse_mode="Markdown")
        return {"status": "whisperer_response", "time_ms": result.get("response_time_ms")}

    else:
        # Route to RAG chat
        from pipeline.rag.chat_engine import rag_chat
        history = session.get("history", [])
        result = await rag_chat(text, lead_doc, history)

        # Update session history
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": result.get("response", "")})
        session["history"] = history[-10:]  # Keep last 10 messages

        reply = result.get("response", "Sorry, I couldn't process that.")
        await _send_telegram(chat_id, reply)
        return {"status": "chat_response", "time_ms": result.get("response_time_ms")}


async def _send_telegram(chat_id: str, text: str, parse_mode: str = None):
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_TOKEN:
        log.warning("[Telegram] No TELEGRAM_BOT_TOKEN set, skipping send.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                log.error(f"[Telegram] Send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        log.error(f"[Telegram] Send error: {e}")


async def setup_telegram_webhook(base_url: str) -> bool:
    """
    Register the webhook URL with Telegram.
    Call this once after deploy with your public URL.
    
    Args:
        base_url: e.g. "https://yourdomain.com"
    
    Returns:
        True if successful
    """
    if not TELEGRAM_TOKEN:
        log.warning("[Telegram] No token set, skipping webhook setup.")
        return False

    webhook_url = f"{base_url}/webhook/telegram"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"url": webhook_url})
            data = resp.json()
            if data.get("ok"):
                log.info(f"[Telegram] Webhook set to {webhook_url}")
                return True
            else:
                log.error(f"[Telegram] Webhook setup failed: {data}")
                return False
    except Exception as e:
        log.error(f"[Telegram] Webhook setup error: {e}")
        return False


# =====================================================================
#  WHATSAPP BUSINESS CLOUD API
# =====================================================================

async def handle_whatsapp_message(body: dict, db_helpers: dict) -> Optional[dict]:
    """
    Process an incoming WhatsApp webhook event.
    
    Args:
        body: Raw webhook JSON from Meta Graph API
        db_helpers: Same as Telegram handler
    
    Returns:
        Response dict for logging.
    """
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return None  # Status update, not a message

        msg = messages[0]
        wa_id = msg.get("from", "")  # Sender's WhatsApp ID
        text = (msg.get("text", {}).get("body", "") or "").strip()

        if not text or not wa_id:
            return None

        log.info(f"[WhatsApp] From {wa_id}: {text[:80]}")

        # Re-use the same session/routing logic as Telegram
        session = _sessions.get(f"wa_{wa_id}")

        if text.lower().startswith("search "):
            query = text[7:].strip()
            search_fn = db_helpers.get("search_leads")
            if search_fn:
                leads = await search_fn(query)
                if leads:
                    lead = leads[0]
                    _sessions[f"wa_{wa_id}"] = {
                        "lead_id": lead.get("lead_id", ""),
                        "company_name": lead.get("company_name", "Unknown"),
                        "mode": "whisperer",
                        "history": [],
                    }
                    reply = (
                        f"✅ Lead: {lead.get('company_name')}\n"
                        f"🎯 {lead.get('icp_match', {}).get('best_fit_vertical', 'N/A')}\n\n"
                        f"Mode: Whisperer 🎤\n"
                        f"Type an objection to get a counter.\n"
                        f"Send 'chat' to switch to Q&A mode."
                    )
                    await _send_whatsapp(wa_id, reply)
                    return {"status": "lead_selected"}
                else:
                    await _send_whatsapp(wa_id, f"No leads found for \"{query}\". Analyze them on the web first.")
                    return {"status": "no_results"}

        elif text.lower() == "chat":
            if session:
                session["mode"] = "chat"
                session["history"] = []
                await _send_whatsapp(wa_id, f"💬 Chat mode for {session['company_name']}. Ask anything!")
                return {"status": "mode_chat"}

        elif text.lower() == "whisperer":
            if session:
                session["mode"] = "whisperer"
                await _send_whatsapp(wa_id, f"🎤 Whisperer mode for {session['company_name']}. Type the objection.")
                return {"status": "mode_whisperer"}

        elif text.lower() == "help":
            await _send_whatsapp(
                wa_id,
                "🤖 Sales Intelligence Bot\n\n"
                "• search <company> — Find a lead\n"
                "• whisperer — Objection counter mode\n"
                "• chat — Lead Q&A mode\n"
                "• help — Show this message\n\n"
                "Start with: search Acme Corp"
            )
            return {"status": "help_sent"}

        # Free-text routing
        if not session:
            await _send_whatsapp(wa_id, "👋 Welcome! Send 'search <company name>' to get started, or 'help' for commands.")
            return {"status": "no_session"}

        get_lead = db_helpers.get("get_lead")
        lead_doc = await get_lead(session["lead_id"]) if get_lead else None
        if not lead_doc:
            await _send_whatsapp(wa_id, "⚠️ Lead not found. Send 'search <company>' again.")
            _sessions.pop(f"wa_{wa_id}", None)
            return {"status": "lead_missing"}

        if session["mode"] == "whisperer":
            from pipeline.objection_whisperer import get_objection_counter
            result = await get_objection_counter(text, lead_doc)
            reply = f"💬 SAY THIS:\n{result.get('counter', '')}"
            if result.get("probe"):
                reply += f"\n\n❓ THEN ASK:\n{result['probe']}"
            reply += f"\n\n⚡ {result.get('response_time_ms', 0)}ms"
            await _send_whatsapp(wa_id, reply)
            return {"status": "whisperer_response"}

        else:
            from pipeline.rag.chat_engine import rag_chat
            history = session.get("history", [])
            result = await rag_chat(text, lead_doc, history)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": result.get("response", "")})
            session["history"] = history[-10:]
            await _send_whatsapp(wa_id, result.get("response", "Sorry, couldn't process that."))
            return {"status": "chat_response"}

    except Exception as e:
        log.error(f"[WhatsApp] Handler error: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


def verify_whatsapp_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    """
    Handle the WhatsApp webhook verification (GET request).
    
    Returns the challenge string if valid, None otherwise.
    """
    if mode == "subscribe" and token == WHATSAPP_VERIFY:
        log.info("[WhatsApp] Webhook verified successfully.")
        return challenge
    log.warning(f"[WhatsApp] Webhook verification failed: mode={mode}, token={token}")
    return None


async def _send_whatsapp(to: str, text: str):
    """Send a text message via WhatsApp Business Cloud API."""
    if not WHATSAPP_ACCESS or not WHATSAPP_PHONE_ID:
        log.warning("[WhatsApp] No access token or phone ID set, skipping send.")
        return

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                log.error(f"[WhatsApp] Send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        log.error(f"[WhatsApp] Send error: {e}")
