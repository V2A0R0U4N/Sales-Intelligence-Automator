# Sales Intelligence Automator

An intelligent, autonomous lead research and sales brief generation system designed for B2B sales teams. 

This platform takes a list of company leads (names or URLs), autonomously finds their official websites, scrapes and cleans their content, and uses advanced LLM analysis (powered by Groq and LLaMA 3.1 8B) to produce structured, actionable sales intelligence.

---

## 2. Setup Instructions

### Project Architecture
The system operates on a robust 6-stage asynchronous pipeline:
1. **Input Parser** — Classifies incoming leads (mixed URLs, company names, or partial data) and extracts actionable search hints.
2. **Resilient URL Resolver** — Autonomously finds official websites for "name-only" leads using intelligent guessing and search engines while filtering out directory domains.
3. **Smart Scraper** — Uses HTTP requests and falls back to headless Chromium (Playwright) to handle modern JS-rendered Single Page Applications (SPAs).
4. **Content Extractor** — Uses a multi-strategy algorithm to extract only meaningful content and strip out navigational noise.
5. **LLM Analyzer** — Runs sequential Groq/LLaMA 3.1 8B calls per lead to generate: Sales Brief, ICP matching, Market Context, Outreach Email, and Objection Prep.
6. **Storage & Web UI** — Data is stored asynchronously in MongoDB. A FastAPI + Jinja2 frontend provides a responsive dashboard to track progress and view results.

### Dependencies
- **Python 3.10+**: Core programming language.
- **FastAPI + Uvicorn**: Async-native, high-performance web framework for concurrent lead processing.
- **Requests & Playwright**: For high-speed HTTP fetches and robust headless browser scraping.
- **BeautifulSoup4 & lxml**: Fast HTML parsing and sophisticated DOM noise reduction.
- **Groq & LLaMA 3.1 8B**: For exceptional LLM inference speed and reliable JSON structuring.
- **MongoDB (Motor Async)**: Document database for persisting nested lead analysis data.
- **Pydantic v2**: Strict validation of LLM JSON outputs.

### How to Install and Run the Project
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
   Create a `.env` file (you can copy from `.env.example` if available) and add:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   MONGODB_URI=mongodb://localhost:27017
   DB_NAME=sales_intelligence
   ```

6. **Run the Application:**
   Using the script (Mac/Linux):
   ```bash
   ./run.sh
   ```
   Or using Uvicorn directly:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

### How to Use the Web Interface
1. After starting the server, open your browser and navigate to **http://localhost:8000**.
2. On the main dashboard, you will find a text area where you can paste a list of leads (mixed URLs or raw company names, one per line).
3. Click the **"Start Processing"** button to initiate the background pipeline.
4. The dashboard will automatically update in real-time. You can monitor the progress of the scraper and LLM analysis for each lead.
5. Once a lead's status changes to completed, you can view the detailed Sales Brief, ICP match score, market context, generated outreach emails, and objection handling battlecards directly in the UI.

---

## 3. Design Notes

**Overall System Architecture & Tool Selection**
The system is built around a highly concurrent, asynchronous pipeline utilizing FastAPI and Motor (Async MongoDB) to maximize the number of leads processed simultaneously without blocking the main event loop. For the extraction layer, standard HTTP `Requests` paired with `BeautifulSoup` provide extreme speed, while `Playwright` acts as an automated headless fallback to handle modern JS-driven apps (SPAs) and sites with anti-bot measures. I chose Groq combined with the LLaMA 3.1 8B model because of its unparalleled inference speed, allowing the system to run complex multi-stage prompts (for outreach drafts, ICP matches, and objection handling) in fractions of a second. Additionally, `Pydantic` ensures all LLM outputs perfectly adhere to the required JSON schema.

**Handling Edge Cases & Ensuring Strict LLM Evaluation**
Web scraping and AI evaluation are inherently fragile, so the system is designed to gracefully handle edge cases like missing company specifications, unpredictable page layout differences, and bot deterrents. The HTML extraction algorithm relies on text density scoring rather than rigid CSS selectors, allowing it to adapt to almost any layout and reliably strip away headers, footers, and cookie banners to isolate the core company message. When critical data points are absent from the scraped text, the LLM prompt evaluates the available context to explicitly output "Information not found" instead of hallucinating facts. To ensure the LLM evaluation remains exceptionally strict and reliable, the prompts enforce a "chain-of-thought" structure requiring the model to justify its extraction first. Finally, structured output validation via Pydantic guarantees the returned JSON never deviates from the exact schema required by the core application.

**Future Improvements**
If given more time, several enhancements would further improve scalability and utility. I would decouple the scraping and LLM processing stages into a dedicated distributed task queue (such as Celery backed by Redis or RabbitMQ) to guarantee 100% resilience against server restarts during massive batch jobs. I would also integrate commercial stealth proxy rotators to completely eliminate 403 Forbidden errors when scraping heavily protected enterprise domains. Lastly, adding a mechanism to cross-reference scraped company names with official LinkedIn API data would significantly enrich the firmographic details, providing exact employee counts and verified executive contact information out of the box.
