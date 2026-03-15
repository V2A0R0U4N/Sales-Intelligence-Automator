# Sales Intelligence Automator

An intelligent, autonomous lead research and sales brief generation system designed for B2B sales teams. 

This platform takes a list of company leads (names or URLs), autonomously finds their official websites, scrapes and cleans their content, and uses advanced LLM analysis (powered by Groq and LLaMA 3.1 8B) to produce structured, actionable sales intelligence. 

## 🚀 Why Use This?
Manual lead research is slow and tedious. Sales reps spend hours digging through company websites, trying to figure out what a company does, who their ideal customer is, and how to pitch them. 
**Sales Intelligence Automator** reduces this to seconds:
- **Instant Intelligence:** Get structured sales briefs, Ideal Customer Profile (ICP) match scores, and market context instantly.
- **Ready-to-Use Outreach:** Generates highly personalized cold emails based on the prospect's actual website language and services.
- **Objection Handling:** Pre-generates likely objections a prospect might have, along with prepared counter-responses.
- **Resilient Data Gathering:** Handles broken links, parked domains, and bot-blocking websites automatically.

---

## 🏗 Architecture & Pipeline

The system operates on a robust 6-stage asynchronous pipeline:

1. **Input Parser** — Classifies incoming leads (mixed URLs, company names, or partial data) and extracts actionable search hints.
2. **Resilient URL Resolver** — Autonomously finds official websites for "name-only" leads.
   - *Strategy 1:* DuckDuckGo HTML Search (HTTP)
   - *Strategy 2:* Playwright-based DuckDuckGo Search (bypasses bot detection/captchas)
   - *Strategy 3:* Google Search
   - *Strategy 4:* Intelligent Domain Guessing
   - *Filtering:* Automatically rejects known directory domains (Yelp, Facebook, ZoomInfo, etc.).
3. **Smart Scraper** — Uses HTTP requests (Requests) and falls back to headless Chromium (Playwright) to handle modern JS-rendered Single Page Applications (SPAs). It fetches the homepage and autonomously discovers and scrapes high-priority internal pages (About, Services, Contact, etc.).
4. **Content Extractor** — Uses a 4-strategy algorithm (Readability, Semantic HTML blocks, Text Density scoring, and Raw text) to extract only the meaningful content. Automatically strips noise (nav, footers, cookie banners) and generates a quality "signal score".
5. **LLM Analyzer** — Runs 5 sequential Groq/LLaMA 3.1 8B calls per lead to generate: Sales Brief, ICP matching, Market Context, Outreach Email, and Objection Prep.
6. **Storage & Web UI** — Data is stored asynchronously in MongoDB (with an in-memory fallback). A FastAPI + Jinja2 frontend provides a modern, responsive pastel-themed dashboard to track progress and view results.

---

## 💻 Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| **Backend** | FastAPI + Uvicorn | Async-native, high-performance concurrent lead processing. |
| **Scraping** | Requests + Playwright | High-speed HTTP fetches with robust headless browser fallbacks for JS sites and bot protections. |
| **Content Extraction** | BeautifulSoup + lxml | Fast HTML parsing and sophisticated noise reduction. |
| **AI / LLM** | Groq + LLaMA 3.1 8B | Exceptional inference speed (5-10x faster than cloud alternatives) and reliable JSON mode. |
| **Database** | MongoDB (Motor Async) | Document database perfectly suited for nested CRM-style lead data. |
| **Validation** | Pydantic v2 | Strict validation of LLM JSON outputs to prevent application crashes. |
| **Frontend** | HTML5, Vanilla CSS, Jinja2 | Clean, lightweight, server-side rendered UI with real-time polling. No JavaScript build step needed. |

---

## 🛠 Prerequisites

To run this project, you will need:
- **Python 3.10+**
- **Groq API Key:** Get a free API key from [console.groq.com](https://console.groq.com).
- **MongoDB:** (Optional but recommended) Have MongoDB installed locally or an Atlas connection string. *Note: The app will safely fall back to in-memory storage if MongoDB is not detected.*

---

## ⚙️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd assignment-1-sales_intelligence_automator
   ```

2. **Create a virtual environment (Recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers:**
   ```bash
   playwright install chromium
   ```

5. **Set up Environment Variables:**
   ```bash
   cp .env.example .env
   ```
   Open the `.env` file and add your configuration:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   MONGODB_URI=mongodb://localhost:27017  # Change if using Atlas
   DB_NAME=sales_intelligence
   ```

---

## ▶️ How to Run

You can run the application directly using the provided shell script or Uvicorn:

**Option 1: Using the run script (Mac/Linux)**
```bash
./run.sh
```

**Option 2: Using Uvicorn manually**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Once running, open your browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

---

## 📊 Viewing the Database

If you are using MongoDB, the app creates a database named `sales_intelligence` with two collections:
1. `jobs`: Tracks the overall batch processing status.
2. `leads`: Stores the granular scraped text, LLM analysis, and generated emails for each lead.

You can view your data using:
- **MongoDB Compass:** Connect to `mongodb://localhost:27017` and use the visual interface.
- **MongoDB Shell (`mongosh`):**
  ```bash
  mongosh "mongodb://localhost:27017/sales_intelligence"
  ```

---

## ✨ Key Features

- **Mixed Lead Inputs:** Paste a mix of direct URLs (e.g., `https://example.com`) and raw company names (e.g., `Acme Corp NYC`). The system handles the resolution automatically.
- **ICP Vertical Matching:** Scores each lead against predefined business verticals, providing a best-fit recommendation and tailored pitch angle.
- **Market Contextualization:** Extracts competitive positioning and pain points directly from the prospect's website. Falls back to AI inferences if content is too thin.
- **Personalized Outreach:** Instantly drafts ready-to-send cold emails formulated around the prospect's specific services and industry language.
- **Battlecard Generation:** Prepares sales reps for live calls by predicting likely prospect objections and drafting strong, contextual rebuttals.
- **Robust Error Handling:** Granular error tracking for DNS failures, SSL issues, parked domains, 404s, and scraper bot blocks.

---

## 🔮 Future Improvements

1. **LinkedIn Profile Enrichment:** Cross-reference scraped domain data with LinkedIn to fetch employee headcount and exact contact details.
2. **Native CRM Integrations:** One-click push to Salesforce/HubSpot via standard REST APIs.
3. **Custom ICP Configuration:** Allow users to define their own specific ICP scoring matrices via the UI instead of relying on generalized verticals.
4. **Batch CSV Upload:** Support importing and exporting massive lists of leads via CSV files directly on the frontend.
