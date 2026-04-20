# 🧠 Sales Intelligence Automator

An autonomous, multi-agent B2B sales intelligence platform that turns a list of company names or URLs into deep, actionable sales intelligence — fully enriched, ICP-matched, and delivered across your web dashboard, WhatsApp, and Telegram.

---

## ✨ Overview

Sales Intelligence Automator is built for B2B sales teams. Given a target Ideal Customer Profile (ICP) and a region / industry query, the system:

1. **Autonomously discovers** real company websites using multi-source search.
2. **Deeply scrapes** each company's web content (HTTP-first, Playwright fallback for SPAs).
3. **Runs a multi-agent LLM crew** to extract pain points, competitive angles, and personalization hooks.
4. **Generates a full sales brief** per lead — ICP match, outreach email, objection battlecard, and call prep.
5. **Delivers intelligence** via a beautiful web dashboard, a live **RAG Chatbot** per lead, a real-time **Objection Whisperer**, and a **WhatsApp / Telegram bot** for field sales reps.

---

## 🏗️ System Architecture

The system is organized as a layered, asynchronous pipeline:

```
┌─────────────────────────────────────────────────────────────┐
│                        WEB UI (FastAPI + Jinja2)             │
│  Home / ICP Builder / Processing / Results Dashboard         │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                     CORE PIPELINE                            │
│  1. Input Parser   →   2. Region Discovery                   │
│  3. Smart Scraper  →   4. LLM Analyzer (multi-stage)         │
│  5. Agent Crew     →   6. MongoDB Storage                    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                  DELIVERY LAYER                              │
│  RAG Chatbot (WebSocket) │ Objection Whisperer (WebSocket)  │
│  WhatsApp Bot (Meta API) │ Telegram Bot (Bot API)           │
│  Google Sheets Export    │ Email Agent (Gmail compose)      │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔩 Pipeline Stages (Deep Dive)

### Stage 1 — Input Parser (`pipeline/input_parser.py`)
- Accepts mixed input: raw company names, full URLs, partial domains, or any combination.
- Classifies each lead and normalizes it into a structured object.
- Extracts search hints (city, industry vertical) to guide the discovery stage.

### Stage 2 — Region & Company Discovery (`pipeline/region_discovery.py`)
- Queries DuckDuckGo and custom search strategies to find official company websites.
- Applies a comprehensive **ad and spam filter**:
  - Blocks Google Ads, tracking URLs (`gclid=`, `/pagead/`, etc.), Taboola, Outbrain.
  - Rejects country/region pages (`/in/`, `/us/`, country-only titles).
  - Maintains a curated `ALWAYS_BLOCKED` domain blocklist (150+ directory, review, and social sites: LinkedIn, Justdial, Glassdoor, etc.).
  - Filters out 70+ country and city names used as fake company names in ad results.
- Uses smart listing-site detection to recursively extract individual company entries from aggregator pages (e.g., Clutch, GoodFirms).
- Falls back to domain-based company name extraction when page titles are misleading.

### Stage 3 — Smart Scraper (`pipeline/scraper_v2.py`)
- **Primary**: Fast HTTP fetch using `requests` + anti-bot headers.
- **Fallback**: Headless Chromium via Playwright for JS-rendered SPAs.
- **Content Extraction**: Text-density scoring algorithm strips headers, footers, navbars, and cookie banners to isolate core company messaging.
- Deduplicates, cleans, and chunks content for downstream LLM and RAG use.

### Stage 4 — LLM Analyzer (`pipeline/llm_analyzer.py`)
Runs sequential Groq/LLaMA calls to generate a complete sales brief per lead:

| Analysis Module | Output |
|---|---|
| **Sales Brief** | Company overview, core product/service, target customer, team size |
| **ICP Match** | Fit score 1–10, best-fit Moksh vertical, pitch angle, recommended services |
| **Market Context** | Industry trends, recent news, funding signals |
| **Outreach Email** | Personalized cold email with subject line, structured paragraphs & sign-off |
| **Objection Prep** | Pre-built counter-arguments for the 5 most common objections |

All outputs are validated with **Pydantic v2** — the LLM is never trusted to return free-form text.

### Stage 5 — Multi-Agent Crew (`pipeline/agents/`)
An orchestrated crew of three specialized agents runs in **parallel** after the base LLM analysis:

- **`PainPointAgent`** — Identifies deep operational pain points from scraped content.
- **`PersonalizationAgent`** — Generates highly personalized conversation openers referencing specific details from the company's own website.
- **`CompetitiveAgent`** — Maps the prospect's likely current vendors and drafts differentiation talking points.

The `Orchestrator` runs all three concurrently using `asyncio.gather` and merges their outputs into the final lead document.

---

## 🤖 Agentic Features

### 💬 RAG Chatbot (per Lead)
- **File**: `pipeline/rag/chat_engine.py`
- Each lead card has its own **floating AI chat panel** powered by WebSockets.
- Uses **Retrieval-Augmented Generation (RAG)**: the chatbot's context is built from the lead's scraped website content, not generic internet knowledge.
- **Context-aware**: All user messages are automatically prefixed with the active company's name, so questions like *"What are their worst business decisions?"* correctly resolve to the current lead.
- **Scroll persistence**: Conversation histories are stored per lead in a `_chatHistories` map. Scrolling to another lead switches context without losing the previous conversation.
- **Concurrency safe**: A `_chatPending` flag and `_pendingLeadSwitch` queue ensure no answers are lost if the user scrolls while a response is still loading.

### 🎤 Objection Whisperer (Live Call Coach)
- **File**: `pipeline/objection_whisperer.py`
- A real-time WebSocket tool designed for use **during a live sales call**.
- The salesperson types the objection they just heard; the Whisperer instantly returns:
  - **`[SAY THIS:]`** — A declarative, psychologically-tuned statement to say out loud. Questions are strictly forbidden from this block.
  - **`[THEN ASK:]`** — A probing follow-up question to deepen the conversation.
- The response is grounded in the specific lead's ICP match and sales brief.

### 📊 ICP Builder (`pipeline/icp_discovery.py` + `templates/icp_builder.html`)
- Dedicated UI for Moksh Group to define their Ideal Customer Profile.
- Users input their company's verticals, services, and targeting criteria.
- The system uses this ICP as the lens for scoring and pitching every discovered lead.

### 📧 Email Agent (`pipeline/email_agent.py`)
- Generates personalized cold outreach emails using lead intelligence.
- Emails are structured with proper greeting, body paragraphs, and sign-off using `\n` line breaks.
- Rendered with `white-space: pre-wrap` in the UI so formatting is always preserved.
- Each lead card includes a **"Open in Gmail"** button that pre-populates a Gmail compose window with the generated subject and body.

### 📞 Call Practice Agent (`pipeline/call_agent.py`)
- Prepares salespeople **before** getting on a call.
- Generates a structured call guide: opening hook, key conversation themes, and anticipated objections with counters — all grounded in the specific lead's data.

### 📋 Google Sheets Agent (`pipeline/sheets_agent.py`)
- Exports the full enriched lead database to a Google Sheet.
- Formats data into a clean CRM-ready table: company, website, ICP score, vertical, pitch angle, and email subject.

---

## 📱 Messaging Integrations (`pipeline/messaging_agent.py`)

The platform supports **WhatsApp Business Cloud API** and **Telegram Bot API** for field sales reps who need intelligence on the go.

### Commands (WhatsApp & Telegram)
| Command | Action |
|---|---|
| `search <company>` | Find a lead by name and set it as active |
| `whisperer` | Switch to Objection Whisperer mode |
| `chat` | Switch to RAG Chat mode (ask anything about the lead) |
| `status` | Show the currently active lead |
| `help` | Show all available commands |

### How it works
1. The salesperson texts `search Moksh` → bot confirms the lead with ICP score and fit vertical.
2. They type any objection they hear on the call → bot instantly replies with SAY THIS + THEN ASK.
3. They type any question → bot answers from the lead's RAG knowledge base.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Web Framework** | FastAPI + Uvicorn (async) |
| **Frontend** | Jinja2 templates + Vanilla JS + WebSockets |
| **Scraping** | Requests + BeautifulSoup4 + Playwright (Chromium) |
| **LLM Inference** | Groq API (LLaMA 3.3 70B Versatile) |
| **Data Validation** | Pydantic v2 |
| **Database** | MongoDB (Motor async driver) |
| **Messaging** | Meta WhatsApp Business Cloud API + Telegram Bot API |
| **Tunneling (dev)** | ngrok |
| **Containerization** | Docker + OpenShift deployment YAML |

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```env
# Core LLM
GROQ_API_KEY=your_groq_api_key_here

# Database
MONGODB_URI=mongodb://localhost:27017
DB_NAME=sales_intelligence

# WhatsApp Business Cloud API (Meta)
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=salesintel_verify_2024

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Google Sheets (optional)
GOOGLE_SHEETS_CREDENTIALS_JSON=path/to/credentials.json
GOOGLE_SHEET_ID=your_sheet_id
```

---

## 🚀 Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/V2A0R0U4N/Sales-Intelligence-Automator.git
cd Sales-Intelligence-Automator
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 5. Run the application
```bash
./run.sh
# OR
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at **http://localhost:8000**

---

## 📲 Enabling the WhatsApp Bot

1. Create a Meta Developer App at [developers.facebook.com](https://developers.facebook.com).
2. Add the **WhatsApp** product via Use Cases → "Connect with customers through WhatsApp".
3. Copy your **Access Token** and **Phone Number ID** into `.env`.
4. Install and configure ngrok: `brew install ngrok/ngrok/ngrok && ngrok config add-authtoken <your_token>`
5. Expose your local server: `ngrok http 8000`
6. In Meta Dashboard → WhatsApp → Configuration:
   - **Callback URL**: `https://your-ngrok-url.ngrok-free.app/webhook/whatsapp`
   - **Verify Token**: the value from `WHATSAPP_VERIFY_TOKEN` in your `.env`
7. Subscribe to the **messages** webhook field.
8. Add your personal phone number to the authorized recipient list in API Setup.

---

## 🖥️ How to Use the Web Dashboard

1. Navigate to **http://localhost:8000**.
2. Fill in your **ICP profile** (company verticals, target services, sector focus) on the ICP Builder page.
3. On the Home page, paste company names or URLs (one per line) and set the target region.
4. Click **Start Discovery** — the pipeline runs fully autonomously in the background.
5. The **Processing** page shows real-time per-lead status updates.
6. On the **Results** page:
   - Scroll through lead cards to review ICP scores, sales briefs, and generated emails.
   - Click the **chat bubble** icon to open the floating RAG Chatbot for that lead.
   - Click the **microphone** icon to open the live Objection Whisperer.
   - Click **Open in Gmail** to launch a pre-filled compose window.

---

## 🧩 Design Decisions

### Asynchronous-First Architecture
Every stage runs using Python's `asyncio`. Discovery, scraping, LLM calls, and agent tasks all run concurrently using `asyncio.gather`, meaning a batch of 20 leads processes in roughly the time it takes to process 3 leads sequentially.

### Multi-Agent Parallelism
The three specialist agents (Pain Point, Personalization, Competitive) run simultaneously on each lead. Their combined runtime equals the slowest agent, not the sum of all three — typically under 5 seconds.

### RAG over Fine-tuning
The chatbot avoids fine-tuning entirely. Instead, scraped content is used as injected context in the system prompt at runtime. This means the chatbot has **zero hallucination risk** about company-specific facts — it can only answer from what was actually scraped from the company's website.

### Strict LLM Output Validation
Every LLM response goes through a Pydantic model before touching the database. If the LLM returns invalid JSON or a missing field, the system falls back gracefully instead of crashing or storing corrupt data.

### Ad Filtering at the Source
Rather than cleaning bad results after the fact, the discovery pipeline filters advertisements, tracking URLs, country placeholder pages, and directory listings **before** any scraping is attempted. This prevents wasted Playwright sessions and keeps the lead quality high.

---

## 🔮 Future Improvements

- **Redis-backed session store** — Replace in-memory `_sessions` dict with Redis to support multi-worker deployments and survive server restarts.
- **Celery task queue** — Decouple scraping and LLM processing into background workers for true horizontal scalability.
- **LinkedIn enrichment** — Cross-reference leads with LinkedIn's API for verified employee counts, funding rounds, and executive contact data.
- **Stealth proxy rotation** — Use commercial rotating proxy pools to eliminate 403 errors on heavily protected enterprise domains.
- **WhatsApp Discovery mode** — Background task that runs the full discovery pipeline in response to a WhatsApp command, messaging back when results are ready.
- **CRM sync** — Push enriched lead data directly to HubSpot, Salesforce, or Pipedrive via their APIs.
