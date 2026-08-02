"""
Checks DuPage County Recorder of Deeds public records for anything filed
against a specific property that isn't already accounted for in
baseline.json, and writes the result to docs/data.json for the static
frontend to read.

The property address is read from environment variables (GitHub Actions
secrets in CI) rather than hardcoded, so this file and baseline.json
don't have to contain anyone's PII even though the repo is public.

Required env vars:
  PROPERTY_HOUSE_NUMBER
  PROPERTY_STREET
  PROPERTY_CITY
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SEARCH_URL = "https://recorder.dupageco.org/Search.aspx"
REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
DATA_PATH = REPO_ROOT / "docs" / "data.json"

# A real, always-present property record we expect to find on every
# successful run. Used as a sanity check: if a search for this doesn't
# come back, something about the site or our scraper broke, and we
# should NOT report that as "no new records."
BASELINE_SANITY_ANCHOR = "R1999-232329"


def parse_results_table(page):
    """Parses the DuPage recorder address-search results grid: 6 columns of
    [DocNumber, DateRecorded, Address, City, DocType, LegalDescription].
    """
    records = []
    rows = page.query_selector_all("#MainContent_gvData tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 6:
            continue
        texts = [c.inner_text().strip() for c in cells]
        doc_number = texts[0]
        if not doc_number.startswith("R"):
            continue
        records.append(
            {
                "doc_number": doc_number,
                "date_recorded": texts[1],
                "doc_type": texts[-2],
                "legal_description": texts[-1],
            }
        )
    return records


def best_effort_networkidle(page, timeout=15000):
    """The recorder site has third-party analytics requests that can keep
    the network from ever going fully idle. domcontentloaded is enough for
    our form interactions to work, so a networkidle timeout here is fine
    to ignore rather than treat as a failure.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def goto_search_page(page):
    # Using wait_until="networkidle" directly on goto() has been observed to
    # abort the navigation outright on this site. domcontentloaded + a
    # separate best-effort networkidle wait is reliable.
    page.goto(SEARCH_URL, wait_until="domcontentloaded")
    best_effort_networkidle(page)


def run_address_search(page, house_number, street, city):
    goto_search_page(page)
    page.fill("#MainContent_txtHouseNumber", house_number)
    page.fill("#MainContent_txtStreet", street)
    page.fill("#MainContent_txtCity", city)
    page.wait_for_timeout(500)
    page.click("#MainContent_btnSearch")
    best_effort_networkidle(page)
    page.wait_for_timeout(1500)
    return parse_results_table(page)


def collect_all_records_once(config):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        records = run_address_search(
            page,
            config["house_number"],
            config["street"],
            config["city"],
        )
        browser.close()
    return records


def collect_all_records(config, attempts=3, backoff_seconds=20):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return collect_all_records_once(config)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"Attempt {attempt}/{attempts} failed: {exc}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)
    raise last_error


def load_config_from_env():
    missing = [
        var
        for var in (
            "PROPERTY_HOUSE_NUMBER",
            "PROPERTY_STREET",
            "PROPERTY_CITY",
        )
        if not os.environ.get(var)
    ]
    if missing:
        print(f"Missing required environment variables: {missing}", file=sys.stderr)
        sys.exit(1)

    return {
        "house_number": os.environ["PROPERTY_HOUSE_NUMBER"],
        "street": os.environ["PROPERTY_STREET"],
        "city": os.environ["PROPERTY_CITY"],
    }


def load_baseline():
    with open(BASELINE_PATH) as f:
        return set(json.load(f)["known_document_numbers"])


def load_previous_data():
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return None


def write_data(payload):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def main():
    config = load_config_from_env()
    baseline = load_baseline()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        records = collect_all_records(config)
    except Exception as exc:  # noqa: BLE001 - want to catch anything Playwright throws
        print(f"Scrape failed: {exc}", file=sys.stderr)
        previous = load_previous_data() or {}
        previous["last_check_attempted_at"] = now_iso
        previous["last_check_error"] = str(exc)
        write_data(previous)
        sys.exit(1)

    found_doc_numbers = {r["doc_number"] for r in records}

    if BASELINE_SANITY_ANCHOR not in found_doc_numbers:
        # We know this document has been on file since 1999. If it's missing,
        # the scraper broke (site changed, search returned nothing, etc) --
        # don't report that as "no new records," report a check failure.
        print(
            f"Sanity check failed: expected anchor record {BASELINE_SANITY_ANCHOR} "
            "not found. Treating as a scrape failure rather than reporting status.",
            file=sys.stderr,
        )
        previous = load_previous_data() or {}
        previous["last_check_attempted_at"] = now_iso
        previous["last_check_error"] = (
            "Sanity check failed: baseline anchor record was not found in results. "
            "The site's markup may have changed, or the search returned no results."
        )
        write_data(previous)
        sys.exit(1)

    new_records = [r for r in records if r["doc_number"] not in baseline]
    new_records.sort(key=lambda r: r["date_recorded"], reverse=True)

    payload = {
        "status": "Yes" if new_records else "No",
        "checked_at": now_iso,
        "total_records_on_file": len(records),
        "baseline_record_count": len(baseline),
        "new_records": new_records,
        "source_search_url": SEARCH_URL,
        "official_fraud_alert_signup": "https://www.propertyfraudalert.com/ILDupage",
        "last_check_error": None,
    }
    write_data(payload)
    print(f"Check complete. Status: {payload['status']}. New records: {len(new_records)}.")


if __name__ == "__main__":
    main()
