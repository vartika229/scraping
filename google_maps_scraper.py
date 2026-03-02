import argparse
import io
import logging
import random
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd
from openpyxl.styles import Font
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Basic regex for email extraction
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

def is_place_url(url: str) -> bool:
    """Detect if the URL is for a single place listing."""
    return "/place/" in url or url.startswith("https://www.google.com/maps/place")

def random_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def extract_email_from_website(page: Page, website_url: str) -> Optional[str]:
    if not website_url or pd.isna(website_url):
        return None
    try:
        new_page = page.context.new_page()
        # Fast config: shorter timeout, wait until domcontentloaded to save time.
        new_page.goto(website_url, timeout=15000, wait_until="domcontentloaded")
        content = new_page.content()
        emails = re.findall(EMAIL_REGEX, content)
        new_page.close()
        
        # Filter out common false positives (e.g., image files)
        valid_emails = [e for e in emails if not e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))]
        if valid_emails:
            # Simple heuristic: prioritize info@, contact@, or just pick the first one
            for email in valid_emails:
                if email.lower().startswith(('info@', 'contact@', 'hello@', 'support@')):
                    return email
            return valid_emails[0]
    except Exception as e:
        logger.debug(f"Failed to extract email from {website_url}: {e}")
        try:
            new_page.close()
        except Exception:
            pass
    return None

def _dismiss_consent(page: Page):
    """Dismiss Google consent / cookie dialogs that block the page on servers."""
    consent_selectors = [
        "button:has-text('Accept all')",
        "button:has-text('Reject all')",
        "button:has-text('I agree')",
        "form[action*='consent'] button",
        "button[aria-label='Accept all']",
    ]
    for sel in consent_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                random_delay(1, 2)
                return
        except Exception:
            continue


def _safe_text(page: Page, selectors: list, timeout: int = 3000) -> Optional[str]:
    """Try multiple selectors in order, return the text of the first visible one."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=timeout):
                text = el.inner_text().strip()
                if text:
                    return text
        except Exception:
            continue
    return None


def _safe_attr(page: Page, selectors: list, attr: str, timeout: int = 3000) -> Optional[str]:
    """Try multiple selectors in order, return an attribute of the first visible one."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=timeout):
                val = el.get_attribute(attr)
                if val:
                    return val.strip()
        except Exception:
            continue
    return None


def extract_place_details(page: Page, url: str, extract_email: bool = False) -> Dict:
    """Extracts details from a single place listing."""
    logger.info(f"Extracting details for: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout while loading {url}, attempting to extract what is available.")

    # Handle consent dialogs (common on server IPs, especially in Europe)
    _dismiss_consent(page)
    random_delay(2, 4)

    # Wait for the place panel to be present before extracting
    try:
        page.locator("h1").first.wait_for(state="visible", timeout=8000)
    except Exception as e:
        logger.warning(f"Place title did not appear in time: {e}")

    data = {
        "Company Name": None,
        "Phone Number": None,
        "Email": None,
        "Website": None,
        "Rating": None,
        "Review Count": None,
        "Category": None,
        "Address": None,
        "Google Maps URL": url
    }

    # ── Company Name ──────────────────────────────────────
    data["Company Name"] = _safe_text(page, [
        "h1.DUwDvf",
        "h1[data-attrid='title']",
        "div[role='main'] h1",
        "h1",
    ])

    # ── Rating ────────────────────────────────────────────
    data["Rating"] = _safe_text(page, [
        "div.F7nice > span > span[aria-hidden='true']",
        "div.F7nice span[aria-hidden='true']",
        "span.ceNzKf[role='img']",
    ])
    # Fallback: extract from aria-label like "4.6 stars 247889 Reviews"
    if not data["Rating"]:
        try:
            role_img = page.locator("span[role='img'][aria-label*='stars']").first
            if role_img.is_visible(timeout=2000):
                label = role_img.get_attribute("aria-label") or ""
                m = re.search(r'([\d.]+)\s*stars?', label, re.IGNORECASE)
                if m:
                    data["Rating"] = m.group(1)
        except Exception:
            pass

    # ── Review Count ──────────────────────────────────────
    try:
        reviews_text = _safe_text(page, [
            "div.F7nice span[aria-label*='reviews']",
            "div.F7nice span[aria-label*='Reviews']",
            "span[aria-label*='reviews']",
        ])
        if reviews_text:
            cleaned = reviews_text.replace("(", "").replace(")", "").replace(",", "")
            nums = re.findall(r'\d+', cleaned)
            if nums:
                data["Review Count"] = int(''.join(nums))
    except Exception:
        pass
    # Fallback: parse from role=img aria-label
    if not data["Review Count"]:
        try:
            role_img = page.locator("span[role='img'][aria-label*='reviews']").first
            if role_img.is_visible(timeout=2000):
                label = role_img.get_attribute("aria-label") or ""
                m = re.search(r'([\d,]+)\s*reviews?', label, re.IGNORECASE)
                if m:
                    data["Review Count"] = int(m.group(1).replace(",", ""))
        except Exception:
            pass

    # ── Category ──────────────────────────────────────────
    data["Category"] = _safe_text(page, [
        "button.DkEaL",
        "button[jsaction*='category']",
        "[data-attrid='subtitle'] span",
    ])

    # ── Address ───────────────────────────────────────────
    data["Address"] = _safe_text(page, [
        "button[data-item-id='address'] div.Io6YTe",
        "button[data-item-id='address'] .rogA2c",
        "button[data-item-id='address']",
    ])
    # Fallback: extract from aria-label
    if not data["Address"]:
        try:
            addr_btn = page.locator("button[aria-label^='Address:']").first
            if addr_btn.is_visible(timeout=2000):
                label = addr_btn.get_attribute("aria-label") or ""
                data["Address"] = label.replace("Address:", "").strip()
        except Exception:
            pass

    # ── Phone Number ──────────────────────────────────────
    data["Phone Number"] = _safe_text(page, [
        "button[data-item-id^='phone:tel:'] div.Io6YTe",
        "button[data-item-id^='phone:tel:'] .rogA2c",
        "button[data-item-id^='phone:tel:']",
        "button[data-item-id^='phone'] div.Io6YTe",
    ])
    # Fallback: extract from aria-label
    if not data["Phone Number"]:
        try:
            phone_btn = page.locator("button[aria-label^='Phone:']").first
            if phone_btn.is_visible(timeout=2000):
                label = phone_btn.get_attribute("aria-label") or ""
                data["Phone Number"] = label.replace("Phone:", "").strip()
        except Exception:
            pass

    # ── Website ───────────────────────────────────────────
    data["Website"] = _safe_attr(page, [
        "a[data-item-id='authority']",
        "a[aria-label^='Website:']",
    ], "href")

    # ── Email (opt-in) ────────────────────────────────────
    if extract_email and data["Website"]:
        data["Email"] = extract_email_from_website(page, data["Website"])

    # Log which fields were successfully extracted
    filled = [k for k, v in data.items() if v is not None and k != "Google Maps URL"]
    logger.info(f"Extracted fields: {filled}")

    return data

def scrape_search_results(page: Page, url: str, max_results: int = 20, extract_email: bool = False) -> List[Dict]:
    """Scrolls down search results and extracts each listed place."""
    logger.info(f"Scraping search results for: {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout loading list view for {url}. Attempting to proceed with whatever loaded.")
    random_delay(2, 4)

    # Dismiss consent dialogs (common on server IPs)
    _dismiss_consent(page)

    # Wait for at least one result link to appear in the DOM (up to 10s)
    try:
        page.wait_for_selector("a[href*='/maps/place/'], a.hfpxzc", timeout=10000)
    except Exception:
        logger.warning("No place links appeared after 10 seconds.")
        
    places = []
    processed_urls = set()

    last_places_count = 0
    consecutive_no_new = 0

    while len(places) < max_results:
        # Get all links matching a place URL (works in both rich and lite modes)        
        # We do this FIRST, before checking for scrolling, to grab whatever is visible
        links = page.locator("a[href*='/maps/place/'], a.hfpxzc").all()
        
        for link in links:
            try:
                href = link.get_attribute("href")
                if href and href not in processed_urls:
                    processed_urls.add(href)
                    places.append(href)
                    if len(places) >= max_results:
                        break
            except Exception:
                continue
        
        if len(places) >= max_results:
            break
            
        if len(places) == last_places_count:
            consecutive_no_new += 1
            if consecutive_no_new >= 3:
                logger.info("No new places found after 3 scroll attempts. Breaking.")
                break
        else:
            consecutive_no_new = 0
            last_places_count = len(places)

        # Try to find the scrollable container dynamically
        feed_scrollable = page.locator("div[role='feed']").first
        if not feed_scrollable.is_visible():
            feed_scrollable = page.locator("div.m6QErb[aria-label*='Results']").first

        # Scroll down
        if feed_scrollable.is_visible():
            try:
                page.evaluate("element => element.scrollBy(0, 800)", feed_scrollable.element_handle())
                random_delay(1.5, 3.0)
                
                # Check for "You've reached the end of the list" element
                end_of_list = page.locator("text='You\\'ve reached the end of the list'").first
                if end_of_list.is_visible(timeout=1000):
                    logger.info("Reached end of list.")
                    break
            except Exception as e:
                logger.warning(f"Error scrolling: {e}")
                break
        else:
            logger.warning("Feed scrollable not found in DOM. Returning the visible results.")
            break

    logger.info(f"Collected {len(places)} listing URLs. Extracting specific details...")
    
    results = []
    for i, place_url in enumerate(places, 1):
        logger.info(f"Processing listing {i}/{len(places)}")
        try:
            details = extract_place_details(page, place_url, extract_email)
            results.append(details)
        except Exception as e:
            logger.error(f"Error extracting {place_url}: {e}")
            
    return results

def save_data(data: List[Dict], output_file: str, file_format: str):
    """Save extracted data to an output file."""
    if not data:
        logger.warning("No data to save.")
        return

    df = pd.DataFrame(data)
    
    try:
        if file_format == "csv":
            df.to_csv(output_file, index=False)
        elif file_format == "json":
            df.to_json(output_file, orient="records", indent=4)
        elif file_format == "xlsx":
            _write_excel_with_bold_headers(df, output_file)
        else:
            logger.error(f"Unsupported format: {file_format}")
            return
            
        logger.info(f"Successfully saved {len(data)} records to {output_file}")
    except Exception as e:
        logger.error(f"Failed to save data: {e}")

def _write_excel_with_bold_headers(df: pd.DataFrame, output):
    """Write a DataFrame to Excel with bold header row.
    
    Args:
        df: The DataFrame to write.
        output: A file path string or a file-like object (e.g. io.BytesIO).
    """
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
        ws = writer.sheets["Results"]
        bold_font = Font(bold=True)
        for cell in ws[1]:
            cell.font = bold_font


def generate_file_bytes(data: List[Dict], file_format: str) -> bytes:
    """Generate file content as bytes for download (used by web app)."""
    df = pd.DataFrame(data)
    if file_format == "csv":
        return df.to_csv(index=False).encode("utf-8")
    elif file_format == "json":
        return df.to_json(orient="records", indent=4).encode("utf-8")
    elif file_format == "xlsx":
        buf = io.BytesIO()
        _write_excel_with_bold_headers(df, buf)
        buf.seek(0)
        return buf.read()
    return b""


def run_scrape(url: str, max_results: int = 20, extract_email: bool = False) -> List[Dict]:
    """Run the full scraping pipeline and return results as a list of dicts.
    
    This is the entry point used by the web app.
    """
    logger.info("Starting up browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US"
        )
        page = context.new_page()
        # Block unnecessary resources to save bandwidth (do NOT block stylesheets or scripts, it breaks the DOM structure)
        excluded_resource_types = ["image", "media", "font"]
        page.route("**/*", lambda route: route.continue_() if route.request.resource_type not in excluded_resource_types else route.abort())

        try:
            if is_place_url(url):
                logger.info("Detected Single Place URL")
                data = extract_place_details(page, url, extract_email=extract_email)
                results = [data]
            else:
                logger.info("Detected Search Results URL")
                results = scrape_search_results(page, url, max_results=max_results, extract_email=extract_email)
        finally:
            context.close()
            browser.close()
    return results


def validate_google_maps_url(url: str) -> bool:
    """Validate that the provided URL is a Google Maps URL."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    valid_hosts = ["www.google.com", "google.com", "maps.google.com", "www.google.co.in", "google.co.in"]
    if parsed.hostname not in valid_hosts:
        return False
    if "/maps" not in parsed.path and "/maps/" not in url:
        return False
    return True


def interactive_input() -> dict:
    """Prompt the user interactively for scraping configuration."""
    print("\n" + "=" * 60)
    print("       Google Maps Scraper -- Interactive Mode")
    print("=" * 60)

    # --- URL input ---
    while True:
        url = input("\n[URL] Paste a Google Maps URL (search results or business listing):\n> ").strip()
        if not url:
            print("   [!] URL cannot be empty. Please try again.")
            continue
        if not validate_google_maps_url(url):
            print("   [!] That doesn't look like a valid Google Maps URL.")
            print("      Example search URL  : https://www.google.com/maps/search/restaurants+in+delhi")
            print("      Example listing URL  : https://www.google.com/maps/place/Some+Business/...")
            continue
        break

    # --- Output format ---
    print("\n[FORMAT] Select output format:")
    print("   1) CSV   (default)")
    print("   2) JSON")
    print("   3) Excel (.xlsx)")
    fmt_choice = input("> ").strip()
    fmt_map = {"1": "csv", "2": "json", "3": "xlsx", "": "csv"}
    file_format = fmt_map.get(fmt_choice, "csv")

    # --- Output file name ---
    default_name = f"scraped_data.{file_format}"
    output = input(f"\n[OUTPUT] Output file name (default: {default_name}):\n> ").strip()
    if not output:
        output = default_name
    if not output.endswith(f".{file_format}"):
        file_name = output.split('.')[0] if '.' in output else output
        output = f"{file_name}.{file_format}"

    # --- Max results (only for search URLs) ---
    max_results = 20
    if not is_place_url(url):
        max_input = input("\n[MAX] Max results to scrape (default: 20):\n> ").strip()
        if max_input.isdigit() and int(max_input) > 0:
            max_results = int(max_input)

    # --- Email extraction ---
    email_input = input("\n[EMAIL] Extract emails from business websites? (y/N):\n> ").strip().lower()
    extract_emails = email_input in ("y", "yes")

    # --- Visible browser ---
    visible_input = input("\n[BROWSER] Show browser window while scraping? (y/N):\n> ").strip().lower()
    visible = visible_input in ("y", "yes")

    print("\n" + "-" * 60)
    print(f"   URL      : {url}")
    print(f"   Format   : {file_format}")
    print(f"   Output   : {output}")
    if not is_place_url(url):
        print(f"   Max      : {max_results}")
    print(f"   Emails   : {'Yes' if extract_emails else 'No'}")
    print(f"   Visible  : {'Yes' if visible else 'No'}")
    print("-" * 60)

    confirm = input("\nStart scraping? (Y/n): ").strip().lower()
    if confirm in ("n", "no"):
        print("Cancelled.")
        exit(0)

    return {
        "url": url,
        "output": output,
        "format": file_format,
        "max": max_results,
        "emails": extract_emails,
        "visible": visible,
    }


def main():
    parser = argparse.ArgumentParser(description="Google Maps Scraper")
    parser.add_argument("--url", required=False, default=None, help="Google Maps Search or Place URL")
    parser.add_argument("--output", required=False, default=None, help="Output file name")
    parser.add_argument("--format", choices=["csv", "json", "xlsx"], default="csv", help="Output format (default: csv)")
    parser.add_argument("--max", type=int, default=20, help="Max results for search mode (default: 20)")
    parser.add_argument("--emails", action="store_true", help="Opt-in email extraction (scans business websites)")
    parser.add_argument("--visible", action="store_true", help="Show browser window for debugging")
    args = parser.parse_args()

    # If no URL provided, enter interactive mode
    if args.url is None:
        config = interactive_input()
        url = config["url"]
        output = config["output"]
        file_format = config["format"]
        max_results = config["max"]
        extract_emails = config["emails"]
        visible = config["visible"]
    else:
        url = args.url
        file_format = args.format
        max_results = args.max
        extract_emails = args.emails
        visible = args.visible

        # Determine output file name
        if args.output:
            output = args.output
        else:
            output = f"scraped_data.{file_format}"

        # Automatically ensure output has correct extension
        if not output.endswith(f".{file_format}"):
            file_name = output.split('.')[0] if '.' in output else output
            output = f"{file_name}.{file_format}"

    logger.info("Starting up browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not visible,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US"
        )
        page = context.new_page()

        # Try to block images to improve performance
        page.route("**/*", lambda route: route.continue_() if route.request.resource_type not in ["image", "media", "font"] else route.abort())

        try:
            if is_place_url(url):
                logger.info("Detected Single Place URL")
                data = extract_place_details(page, url, extract_email=extract_emails)
                results = [data]
            else:
                logger.info("Detected Search Results URL")
                results = scrape_search_results(page, url, max_results=max_results, extract_email=extract_emails)
                
            save_data(results, output, file_format)
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    main()
