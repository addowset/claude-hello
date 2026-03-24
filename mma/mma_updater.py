#!/usr/bin/env python3
"""
MMA Fighting Hot Articles — Google Sheets Updater
==================================================
Scrapes mmafighting.com for articles with 20+ comments and syncs a Google Sheet.

Columns expected in the sheet:
  A: Date (DD/MM/YYYY)   B: Comments   C: Change (delta)
  D: Link (HYPERLINK)    E: Status     F: Read (Y/N)   G: Title

Row 1 is a frozen header and is never modified.

Usage:
    python mma_updater.py

Setup:
    1. pip install -r requirements.txt
    2. Create a Google Cloud service account and download its JSON key.
    3. Share the spreadsheet with the service account email (Editor role).
    4. Save the key as  service_account.json  in the same directory as this script.
"""

import json
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── Configuration ─────────────────────────────────────────────────────────────

SPREADSHEET_ID       = "1auFQ6vy-LYzMK1aVIEqpZ4DReRmjGR0BJEsMfgzFuak"
SHEET_NAME           = "Sheet1"
SERVICE_ACCOUNT_FILE = "service_account.json"
MMA_URL              = "https://www.mmafighting.com/"
MIN_COMMENTS         = 20

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Text colours as RGB floats (0-1 range, as required by Sheets API)
GREY  = {"red": 0.627, "green": 0.627, "blue": 0.627}   # #a0a0a0  (inactive rows)
BLACK = {"red": 0.0,   "green": 0.0,   "blue": 0.0}     # #000000  (active rows)

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}


# ── Google Sheets helpers ─────────────────────────────────────────────────────

def get_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def get_sheet_id(service):
    """Return the numeric sheetId for SHEET_NAME (required by batchUpdate requests)."""
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == SHEET_NAME:
            return sheet["properties"]["sheetId"]
    raise ValueError(f"Sheet '{SHEET_NAME}' not found in spreadsheet.")


# ── Scraping ──────────────────────────────────────────────────────────────────

CORAL_COUNTS_URL = "https://www.mmafighting.com/api/coral-counts"


def scrape_mma_fighting():
    """
    Return a dict of {permalink: {"comments": N, "title": "..."}} for all
    articles on the MMA Fighting homepage with MIN_COMMENTS or more comments.

    How it works:
      1. Fetch the homepage and extract the embedded Next.js JSON (__NEXT_DATA__).
      2. Pull all article nodes (coralId + permalink + title).
      3. POST all coralIds to mmafighting.com/api/coral-counts in one request.
      4. Filter to MIN_COMMENTS threshold and return.
    """
    resp = requests.get(MMA_URL, headers=SCRAPE_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract the embedded JSON data block
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag:
        raise RuntimeError("Could not find __NEXT_DATA__ script tag on homepage.")
    page_data = json.loads(script_tag.string)

    # Navigate to article nodes
    nodes = (
        page_data["props"]["pageProps"]["hydration"]
        ["responses"][0]["data"]["resource"]["hero"]["posts"]["nodes"]
    )

    # Build coral_id → article info mapping
    coral_id_to_article = {}
    for node in nodes:
        coral_id  = node.get("id")
        permalink = node.get("permalink", "")
        title     = node.get("title", "")
        if coral_id and permalink:
            coral_id_to_article[coral_id] = {"permalink": permalink, "title": title}

    if not coral_id_to_article:
        return {}

    # Fetch all comment counts in one API call
    params = [("c", cid) for cid in coral_id_to_article]
    counts_resp = requests.get(
        CORAL_COUNTS_URL, params=params, headers=SCRAPE_HEADERS, timeout=30
    )
    counts_resp.raise_for_status()
    counts_data = counts_resp.json().get("data", {})

    # Filter by threshold and return keyed by permalink
    results = {}
    for coral_id, count in counts_data.items():
        if count < MIN_COMMENTS:
            continue
        article = coral_id_to_article.get(coral_id)
        if not article:
            continue
        results[article["permalink"]] = {"comments": count, "title": article["title"]}

    return results


# ── Formatting helpers ────────────────────────────────────────────────────────

def title_from_url(url: str) -> str:
    """Derive a readable title from the URL slug, e.g. 'ufc-london' → 'Ufc London'."""
    slug = url.rstrip("/").split("/")[-1]
    return " ".join(w.capitalize() for w in slug.split("-"))


def parse_hyperlink_url(formula: str) -> str | None:
    """Extract the URL from a =HYPERLINK("url","Link") formula string."""
    m = re.match(r'=HYPERLINK\("([^"]+)"', formula or "", re.IGNORECASE)
    return m.group(1) if m else None


def hyperlink_formula(url: str) -> str:
    return f'=HYPERLINK("{url}","Link")'


# ── Sheets API request builders ───────────────────────────────────────────────

def make_color_request(sheet_id: int, row_num: int, color: dict) -> dict:
    """
    Build a repeatCell request that sets the text colour for an entire data row.
    row_num is 1-based (matches the sheet row number).
    """
    return {
        "repeatCell": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    row_num - 1,    # API uses 0-based indices
                "endRowIndex":      row_num,
                "startColumnIndex": 0,
                "endColumnIndex":   7,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"foregroundColor": color}
                }
            },
            "fields": "userEnteredFormat.textFormat.foregroundColor",
        }
    }


def make_sort_request(sheet_id: int, last_data_row: int) -> dict:
    """
    Build a sortRange request:
      Primary   → column A descending (date, stored as DD/MM/YYYY text)
      Secondary → column B descending (comment count)

    Note: dates are stored as DD/MM/YYYY text strings, so text sort is used.
    This is correct for comparisons within the same month/year. Articles
    spanning multiple months in the same calendar year may sort incorrectly
    only if the day-number digit order conflicts (e.g. "05/04" vs "28/03").
    For a news-scraper refreshed daily this is rarely a practical concern.
    """
    return {
        "sortRange": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    1,              # row 2 onward (skip frozen header)
                "endRowIndex":      last_data_row,  # exclusive
                "startColumnIndex": 0,
                "endColumnIndex":   7,
            },
            "sortSpecs": [
                {"dimensionIndex": 0, "sortOrder": "DESCENDING"},   # A: Date
                {"dimensionIndex": 1, "sortOrder": "DESCENDING"},   # B: Comments
            ],
        }
    }


# ── Main logic ────────────────────────────────────────────────────────────────

def run():
    today = datetime.now().strftime("%d/%m/%Y")
    print(f"MMA Fighting Updater - {today}")
    print()

    # 1. Scrape
    print("Scraping mmafighting.com...")
    scraped = scrape_mma_fighting()
    print(f"  {len(scraped)} article(s) found with {MIN_COMMENTS}+ comments")

    # 2. Connect to Sheets
    print("Connecting to Google Sheets...")
    service  = get_service()
    sheet_id = get_sheet_id(service)
    svc      = service.spreadsheets()

    # 3. Read current sheet data (two calls: formatted values + raw formulas for col D)
    rows_resp = svc.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:G",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    formulas_resp = svc.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!D:D",
        valueRenderOption="FORMULA",
    ).execute()

    rows     = rows_resp.get("values", [])      # row 0 = header
    formulas = formulas_resp.get("values", [])  # row 0 = header formula (usually just "Link")

    # 4. Build an index of existing articles: url → {row, comments, status}
    existing = {}
    for i, row in enumerate(rows):
        if i == 0:
            continue    # skip header
        sheet_row = i + 1   # convert to 1-based sheet row number
        formula   = formulas[i][0] if i < len(formulas) and formulas[i] else ""
        url       = parse_hyperlink_url(formula)
        if not url:
            continue
        existing[url] = {
            "row":      sheet_row,
            "comments": int(row[1]) if len(row) > 1 and str(row[1]).isdigit() else 0,
            "status":   row[4] if len(row) > 4 else "Active",
        }

    print(f"  {len(existing)} existing article(s) in sheet")

    # 5. Reconcile: build update lists
    value_updates   = []    # for values().batchUpdate
    format_requests = []    # for spreadsheets().batchUpdate
    new_rows        = []    # rows to append

    added = updated = inactivated = 0

    # 5a. Process articles currently on the page
    for url, info in scraped.items():
        new_comments = info["comments"]
        if url in existing:
            ex      = existing[url]
            delta   = new_comments - ex["comments"]
            row_num = ex["row"]

            # Update comment count and delta
            value_updates.append({
                "range":  f"{SHEET_NAME}!B{row_num}:C{row_num}",
                "values": [[new_comments, delta]],
            })

            # Reactivate if it was previously marked Inactive
            if ex["status"] == "Inactive":
                value_updates.append({
                    "range":  f"{SHEET_NAME}!E{row_num}",
                    "values": [["Active"]],
                })
                format_requests.append(make_color_request(sheet_id, row_num, BLACK))

            updated += 1

        else:
            # Brand-new article — queue it for appending
            new_rows.append([
                today,
                new_comments,
                0,
                hyperlink_formula(url),
                "Active",
                "N",
                info["title"],
            ])
            added += 1

    # 5b. Mark Active articles no longer on the page as Inactive (grey)
    for url, ex in existing.items():
        if url not in scraped and ex["status"] == "Active":
            row_num = ex["row"]
            value_updates.append({
                "range":  f"{SHEET_NAME}!E{row_num}",
                "values": [["Inactive"]],
            })
            format_requests.append(make_color_request(sheet_id, row_num, GREY))
            inactivated += 1

    # 6. Apply value changes
    if value_updates:
        svc.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": value_updates},
        ).execute()

    # 7. Append new rows
    if new_rows:
        svc.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:G",
            valueInputOption="USER_ENTERED",
            body={"values": new_rows},
        ).execute()

    # 8. Apply colour formatting + sort in a single batchUpdate
    last_data_row   = len(rows) + len(new_rows)     # header row counts; endRowIndex is exclusive
    format_requests.append(make_sort_request(sheet_id, last_data_row))
    svc.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": format_requests},
    ).execute()

    # 9. Print summary
    print()
    print(f"Done")
    print(f"  Added:           {added}")
    print(f"  Updated:         {updated}")
    print(f"  Marked inactive: {inactivated}")


if __name__ == "__main__":
    run()
