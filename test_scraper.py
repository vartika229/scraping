import logging
from playwright.sync_api import sync_playwright
logging.basicConfig(level=logging.INFO)
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    # Don't set a custom user_agent and see if it gives the rich view
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = context.new_page()
    page.goto("https://www.google.com/maps/search/hospitals+in+Agra", wait_until="networkidle")
    
    print("Links via a.hfpxzc:", page.locator("a.hfpxzc").count())
    print("Links via href:", page.locator("a[href*='/maps/place/']").count())
    print("Feed container:", page.locator("div[role='feed']").count())
    print("Lite mode text:", page.locator("text='You\\'re seeing a limited view'").count())
    
    browser.close()
