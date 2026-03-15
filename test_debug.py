"""
Debug script — Tests the full pipeline on ONE website with headless=False
Run: python3 test_debug.py
"""
import asyncio
import os
import sys
import traceback

# Load API key from environment (.env)
from dotenv import load_dotenv
load_dotenv()
if not os.environ.get('GROQ_API_KEY'):
    print("WARNING: GROQ_API_KEY environment variable is not set. Please add it to your .env file.")

sys.path.insert(0, '.')

from playwright.async_api import async_playwright


async def main():
    test_url = "https://www.houstonroofingonline.com"

    # ========== Step 1: Scrape with VISIBLE browser ==========
    print("\n" + "=" * 60)
    print(f"STEP 1: Scraping {test_url}")
    print("=" * 60)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)  # VISIBLE
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720},
    )

    page = await context.new_page()

    try:
        print(f"  Navigating to {test_url}...")
        await page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        html = await page.content()
        title = await page.title()
        print(f"  Page title: {title}")
        print(f"  HTML length: {len(html)} chars")

        # Take screenshot
        await page.screenshot(path="/tmp/debug_screenshot.png")
        print(f"  Screenshot saved to /tmp/debug_screenshot.png")

    except Exception as e:
        print(f"  SCRAPE ERROR: {e}")
        traceback.print_exc()
        html = ""
        title = "Error"

    await context.close()
    await browser.close()
    await pw.stop()

    if not html or len(html) < 100:
        print("\n  FATAL: No HTML content scraped!")
        return

    # ========== Step 2: Clean content ==========
    print("\n" + "=" * 60)
    print("STEP 2: Cleaning content")
    print("=" * 60)

    from pipeline.content_cleaner import clean_multiple_pages

    pages_data = [{"url": test_url, "title": title, "html": html}]
    cleaned = clean_multiple_pages(pages_data)

    print(f"  Word count: {cleaned['word_count']}")
    print(f"  Thin content: {cleaned['thin_content']}")
    print(f"  Pages used: {cleaned['pages_used']}")
    print(f"  First 500 chars of cleaned text:")
    print(f"  {cleaned['text'][:500]}")

    if not cleaned['text']:
        print("\n  FATAL: No text after cleaning!")
        return

    # ========== Step 3: LLM Analysis ==========
    print("\n" + "=" * 60)
    print("STEP 3: Running LLM Analysis")
    print("=" * 60)

    try:
        from pipeline.llm_analyzer import analyze_lead
        analysis = await analyze_lead(
            company_name="Houston Roofing",
            website=test_url,
            content=cleaned['text'],
            thin_content=cleaned['thin_content'],
        )

        print(f"\n  ANALYSIS RESULT TYPE: {type(analysis)}")
        print(f"  ANALYSIS KEYS: {list(analysis.keys())}")

        for key, val in analysis.items():
            vtype = type(val).__name__
            if isinstance(val, dict):
                print(f"\n  [{key}] ({vtype}, {len(val)} keys):")
                for k2, v2 in val.items():
                    v2str = str(v2)[:80]
                    print(f"    {k2}: {v2str}")
            else:
                print(f"\n  [{key}] ({vtype}): {str(val)[:100]}")

        # Test the exact line that fails in main.py
        print("\n  Testing analysis['brief'].get('company_name')...")
        brief = analysis["brief"]
        print(f"  brief type: {type(brief)}")
        print(f"  brief is None: {brief is None}")
        if brief is not None:
            print(f"  company_name: {brief.get('company_name', 'FALLBACK')}")
        print("\n  SUCCESS! Pipeline completed without errors.")

    except Exception as e:
        print(f"\n  LLM ANALYSIS ERROR: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
