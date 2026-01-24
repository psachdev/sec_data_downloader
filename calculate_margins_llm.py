import os
import sys
import json
import textwrap
from typing import Optional, Dict, Any

import requests
from bs4 import BeautifulSoup

# ------------------ CONFIG ------------------

SEC_BASE = "https://data.sec.gov"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# IMPORTANT: SEC requires a descriptive User-Agent with contact
SEC_HEADERS = {
    "User-Agent": "MyResearchScript/1.0 your_email@example.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-chat"   # adjust if you use another model name
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"


# ------------------ SEC HELPERS ------------------

def get_ticker_cik_map() -> Dict[str, int]:
    """
    Download the official SEC ticker -> CIK mapping JSON and return a dict
    {ticker_upper: cik_int}.
    """
    tickers_url = "https://www.sec.gov/files/company_tickers.json"

    # Use proper headers for www.sec.gov
    headers = {
        "User-Agent": "MyResearchScript/1.0 your_email@example.com",
        "Accept-Encoding": "gzip, deflate",
    }

    resp = requests.get(tickers_url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    mapping = {}
    # Format: { "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    for _, entry in data.items():
        ticker = entry["ticker"].upper()
        cik = int(entry["cik_str"])
        mapping[ticker] = cik
    return mapping


def get_cik_for_ticker(ticker: str) -> int:
    mapping = get_ticker_cik_map()
    t = ticker.upper()
    if t not in mapping:
        raise ValueError(f"Ticker {ticker} not found in SEC ticker list.")
    return mapping[t]


def get_10k_metadata(cik: int, year: Optional[int] = None) -> Dict[str, Any]:
    """
    Fetch company submissions and return metadata for the relevant 10-K.
    If year is None: return most recent 10-K.
    If year is set: return the 10-K whose reportDate year matches (or nearest).
    """
    cik_str = str(cik).zfill(10)
    url = f"{SEC_BASE}/submissions/CIK{cik_str}.json"
    resp = requests.get(url, headers=SEC_HEADERS)
    resp.raise_for_status()
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    candidates = []
    for form, acc, doc, rdate in zip(forms, accession_numbers, primary_docs, report_dates):
        if form != "10-K":
            continue
        if not rdate:
            continue
        year_int = int(rdate[:4])
        candidates.append({
            "accession_number": acc,
            "primary_document": doc,
            "report_date": rdate,
            "year": year_int,
        })

    if not candidates:
        raise RuntimeError("No 10-K filings found for this CIK.")

    if year is None:
        # most recent
        candidates.sort(key=lambda x: x["report_date"], reverse=True)
        return candidates[0]

    # Find exact year if possible, else nearest past year
    exact = [c for c in candidates if c["year"] == year]
    if exact:
        # If multiple, pick latest report date within that year
        exact.sort(key=lambda x: x["report_date"], reverse=True)
        return exact[0]

    # fallback: choose latest filing before target year, or just latest
    before = [c for c in candidates if c["year"] <= year]
    if before:
        before.sort(key=lambda x: x["report_date"], reverse=True)
        return before[0]

    candidates.sort(key=lambda x: x["report_date"], reverse=True)
    return candidates[0]


def download_10k_html(cik: int, accession_number: str, primary_document: str) -> str:
    """
    Download the main 10-K HTML file for a given accession number.
    """
    cik_no_leading_zeros = str(cik)
    acc_no_dashes_removed = accession_number.replace("-", "")
    url = f"{EDGAR_ARCHIVES}/{cik_no_leading_zeros}/{acc_no_dashes_removed}/{primary_document}"

    headers = SEC_HEADERS.copy()
    headers["Host"] = "www.sec.gov"

    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text


# ------------------ HTML PARSING ------------------

def find_income_statement_table(html: str) -> Optional[str]:
    """
    Heuristic: find the table following a heading that contains
    'CONSOLIDATED STATEMENTS OF OPERATIONS', 'STATEMENTS OF INCOME', etc.
    Return the HTML of that table as a string.
    """
    soup = BeautifulSoup(html, "lxml")

    keywords = [
        "CONSOLIDATED STATEMENTS OF OPERATIONS",
        "CONSOLIDATED STATEMENTS OF INCOME",
        "CONSOLIDATED STATEMENTS OF EARNINGS",
        "STATEMENTS OF OPERATIONS",
        "STATEMENTS OF INCOME",
    ]

    # Look for elements containing our keywords
    for tag in soup.find_all(text=True):
        text = " ".join(tag.strip().split()).upper()
        if not text:
            continue
        if any(kw in text for kw in keywords):
            # Find the next table sibling
            # Usually the heading is in <p>, <b>, <font>, etc.
            heading_tag = tag.parent
            table = heading_tag.find_next("table")
            if table:
                return str(table)

    # Fallback: just pick the largest table (not ideal but a fallback)
    tables = soup.find_all("table")
    if tables:
        largest = max(tables, key=lambda t: len(t.get_text(separator=" ", strip=True)))
        return str(largest)

    return None


def html_table_to_text(table_html: str) -> str:
    """
    Convert an HTML table to a text representation suitable for LLM parsing.
    We'll create a simple tab-separated format.
    """
    soup = BeautifulSoup(table_html, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        row_text = [c.get_text(" ", strip=True) for c in cells]
        if any(cell.strip() for cell in row_text):
            rows.append("\t".join(row_text))
    return "\n".join(rows)


# ------------------ DEEPSEEK CALL ------------------


def call_deepseek_for_income_statement(table_text: str) -> Dict[str, Any]:
    """
    Send the income statement table to DeepSeek and ask for structured JSON.
    Tries to be robust to non‑pure‑JSON responses.
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set in environment.")

    system_prompt = textwrap.dedent("""
        You are an expert SEC financial statement parser.
        The user will give you a single income statement table from a US 10-K filing,
        in a tab-separated text format (rows separated by newlines).

        The company may be:
        - a typical non-financial issuer, or
        - a financial institution, or
        - an insurance company (e.g., with line items like "net premiums earned",
          "losses and loss adjustment expenses", "underwriting income", etc.).

        Your task:
        - Identify the column that corresponds to the latest fiscal year of the company.
        - Extract the following values for that column, in absolute numbers (not per-share):

          1) net_sales:
             - For non-financials: use "Net sales", "Sales", "Total revenue", "Revenues"
               (anything that clearly represents the top-line revenue).
             - For insurers: use "Total revenues" OR "Net premiums earned" as a proxy
               for net_sales, if standard "Net sales" is not present.

          2) cost_of_revenue:
             - For non-financials: "Cost of sales", "Cost of goods sold", "Cost of revenue".
             - For insurers: if there is no such line, leave as null.

          3) gross_profit:
             - If an explicit "Gross profit" line exists, use it.
             - Otherwise, you may compute it as [net_sales - cost_of_revenue]
               if those two are available.
             - For insurers, if there is no meaningful gross profit analogue,
               leave as null.

          4) operating_income:
             - Use "Operating income" or "Income from operations".
             - For insurers with an "Underwriting income" and then "Net investment income":
               prefer a line that represents total operating income if present.
             - If there is no explicit operating income, you may use
               "Income before income taxes" as a proxy.

          5) net_income:
             - Use "Net income" or "Net earnings" attributable to the company
               (exclude noncontrolling interests if available).

          6) depreciation_and_amortization:
             - Use a specific "Depreciation and amortization" or similar line if present.
             - If not visible in this table, leave as null.

        - Compute EBITDA if possible as:
          EBITDA = operating income + depreciation and amortization
          If EBITDA is explicitly provided as a separate line, you may use that instead.

        - Also return a brief label for the latest year column (e.g. "2024" or "Year ended December 31, 2024").

        Return a single JSON object with these keys:
        {
          "fiscal_year_label": string or null,
          "net_sales": number or null,
          "cost_of_revenue": number or null,
          "gross_profit": number or null,
          "operating_income": number or null,
          "net_income": number or null,
          "depreciation_and_amortization": number or null,
          "ebitda": number or null,
          "currency": string or null,
          "units_note": string or null
        }

        Additional rules:
        - Parse the numeric amounts as best as you can, stripping commas and parentheses.
        - If a value is not present or cannot be reasonably inferred, use null.
        - "units_note" should capture anything like "in millions", "in thousands", etc., if visible.
        - Only output JSON, with no additional text, no markdown, and no code fences.
    """)
    user_content = f"Here is the income statement table:\n\n{table_text}"

    payload = {
        "model": DEEPSEEK_MODEL,  # make sure this matches a real DeepSeek model
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
    }

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = requests.post(DEEPSEEK_ENDPOINT, headers=headers, data=json.dumps(payload))
    resp.raise_for_status()
    data = resp.json()

    # Surface any API-level error from DeepSeek
    if "error" in data:
        raise RuntimeError(f"DeepSeek API error: {data['error']}")

    # Depending on the API, adjust this path if needed.
    # This assumes OpenAI-compatible format:
    # { "choices": [ { "message": { "content": "..." } } ] }
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        print("Unexpected DeepSeek response structure:")
        print(json.dumps(data, indent=2))
        raise

    if not content or not content.strip():
        raise RuntimeError(f"Empty content from DeepSeek. Full response:\n{json.dumps(data, indent=2)}")

    # First try: assume it's pure JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Second try: extract the first {...} block from the text
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if not match:
            print("Non-JSON response content from DeepSeek:")
            print(content)
            raise RuntimeError("Could not find a JSON object in DeepSeek response.")

        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print("Failed to parse extracted JSON substring.")
            print("Extracted substring:")
            print(json_str)
            raise e


# ------------------ MARGIN CALC ------------------

def compute_margins(fin: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Given parsed financials, compute margins:
      - net_sales_margin   = net_income / net_sales
      - gross_margin       = gross_profit / net_sales
      - operating_margin   = operating_income / net_sales
      - ebitda_margin      = ebitda / net_sales
    Returns a dict of margins as floats (e.g. 0.23 for 23%) or None.
    """
    def safe_div(num, den):
        if num is None or den in (None, 0):
            return None
        try:
            return float(num) / float(den)
        except Exception:
            return None

    net_sales = fin.get("net_sales")
    gross_profit = fin.get("gross_profit")
    operating_income = fin.get("operating_income")
    net_income = fin.get("net_income")
    ebitda = fin.get("ebitda")

    margins = {
        "net_sales_margin": safe_div(net_income, net_sales),
        "gross_margin": safe_div(gross_profit, net_sales),
        "operating_margin": safe_div(operating_income, net_sales),
        "ebitda_margin": safe_div(ebitda, net_sales),
    }
    return margins


# ------------------ MAIN ------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python tenk_margins.py TICKER [YEAR]")
        sys.exit(1)

    ticker = sys.argv[1]
    year = int(sys.argv[2]) if len(sys.argv) >= 3 else None

    print(f"Ticker: {ticker}, Year: {year if year else 'latest available'}")

    cik = get_cik_for_ticker(ticker)
    print(f"CIK: {cik}")

    meta = get_10k_metadata(cik, year)
    print("Using 10-K:")
    print(f"  Accession:    {meta['accession_number']}")
    print(f"  Primary doc:  {meta['primary_document']}")
    print(f"  Report date:  {meta['report_date']}")

    html = download_10k_html(cik, meta["accession_number"], meta["primary_document"])
    table_html = find_income_statement_table(html)
    if not table_html:
        print("Could not find an income statement table in the filing.")
        sys.exit(1)

    table_text = html_table_to_text(table_html)

    # --- DEBUG: write table text to a file so you can inspect it ---
    debug_filename = f"income_table_{ticker}_{meta['report_date']}.tsv"
    with open(debug_filename, "w", encoding="utf-8") as f:
        f.write(table_text)
    print(f"\nSaved candidate income statement table to: {debug_filename}")
    # --- END DEBUG ---

    print("\nSending income statement table to DeepSeek for parsing...")
    fin = call_deepseek_for_income_statement(table_text)

    print("\nParsed financials (as returned by DeepSeek):")
    print(json.dumps(fin, indent=2))

    margins = compute_margins(fin)

    print("\nComputed margins (fractional, e.g. 0.25 = 25%):")
    for k, v in margins.items():
        if v is None:
            print(f"  {k}: N/A")
        else:
            print(f"  {k}: {v:.4f} ({v*100:.2f}%)")


if __name__ == "__main__":
    main()
