#!/usr/bin/env python3
"""
Deterministic 10-K margin calculator using SEC XBRL companyfacts (no LLM).

Usage:
    python3 tenk_margins_xbrl.py TICKER [YEAR]

Examples:
    python3 tenk_margins_xbrl.py AAPL 2023
    python3 tenk_margins_xbrl.py PGR 2024   # insurers should also work
"""

import sys
import json
from typing import Dict, Any, Optional, Tuple, List

import requests

# ------------------ CONFIG ------------------

SEC_BASE = "https://data.sec.gov"

# IMPORTANT: replace with your email/contact as required by SEC
SEC_HEADERS = {
    "User-Agent": "MyXBRLMarginsScript/1.0 spreadhappinesstoall062@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

# ------------------ TICKER -> CIK ------------------

def get_ticker_cik_map() -> Dict[str, int]:
    """
    Download the official SEC ticker -> CIK mapping JSON and return a dict
    {ticker_upper: cik_int}.
    """
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    headers = {
        "User-Agent": SEC_HEADERS["User-Agent"],
        "Accept-Encoding": "gzip, deflate",
    }
    resp = requests.get(tickers_url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    mapping: Dict[str, int] = {}
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

# ------------------ 10-K METADATA (submissions API) ------------------

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
            "report_date": rdate,  # fiscal period end date, e.g. 2024-12-31
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
        exact.sort(key=lambda x: x["report_date"], reverse=True)
        return exact[0]

    before = [c for c in candidates if c["year"] <= year]
    if before:
        before.sort(key=lambda x: x["report_date"], reverse=True)
        return before[0]

    candidates.sort(key=lambda x: x["report_date"], reverse=True)
    return candidates[0]

# ------------------ XBRL COMPANYFACTS HELPERS ------------------

def fetch_companyfacts(cik: int) -> Dict[str, Any]:
    cik_str = str(cik).zfill(10)
    url = f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik_str}.json"
    resp = requests.get(url, headers=SEC_HEADERS)
    resp.raise_for_status()
    return resp.json()


def _flatten_facts_for_concept(concept_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Given a companyfacts concept object, flatten across units into one list of fact dicts,
    each annotated with its unit.
    """
    flat: List[Dict[str, Any]] = []
    units = concept_obj.get("units", {})
    for unit, fact_list in units.items():
        for f in fact_list:
            f2 = dict(f)
            f2["_unit"] = unit
            flat.append(f2)
    return flat


def pick_fact_value(
    facts_root: Dict[str, Any],
    concept_candidates: List[str],
    target_end: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    """
    Try each concept name in order and pick the best fact for the target_end date.

    Selection rules:
    - Use facts from 'us-gaap' namespace.
    - Prefer facts where:
        - end == target_end (if provided), and
        - form contains '10-K' (10-K or 10-K/A), and
        - fp == 'FY' (full year) if available.
    - If none match exactly, relax in stages.
    - Return (value, concept_name_used) or (None, None) if not found.
    """
    us_gaap = facts_root.get("us-gaap", {})

    for concept_name in concept_candidates:
        concept_obj = us_gaap.get(concept_name)
        if not concept_obj:
            continue

        flat = _flatten_facts_for_concept(concept_obj)
        if not flat:
            continue

        def filter_facts(
            facts: List[Dict[str, Any]],
            end: Optional[str] = None,
            require_10k: bool = True,
            require_fy: bool = True,
        ) -> List[Dict[str, Any]]:
            res = []
            for f in facts:
                if end is not None and f.get("end") != end:
                    continue
                form = f.get("form", "")
                if require_10k and "10-K" not in form:
                    continue
                if require_fy:
                    fp = f.get("fp")
                    # 'FY' or sometimes 'Y'
                    if fp not in ("FY", "Y", None):
                        continue
                res.append(f)
            return res

        candidates: List[Dict[str, Any]] = []

        # 1) Strict: end == target_end, form includes 10-K, fp FY
        if target_end is not None:
            candidates = filter_facts(flat, end=target_end, require_10k=True, require_fy=True)

        # 2) Relax fp FY
        if not candidates and target_end is not None:
            candidates = filter_facts(flat, end=target_end, require_10k=True, require_fy=False)

        # 3) Relax end but keep 10-K & FY
        if not candidates:
            candidates = filter_facts(flat, end=None, require_10k=True, require_fy=True)

        # 4) Relax FY as well (any 10-K)
        if not candidates:
            candidates = filter_facts(flat, end=None, require_10k=True, require_fy=False)

        # 5) Last resort: any fact with matching year of target_end
        if not candidates and target_end is not None:
            target_year = int(target_end[:4])
            for f in flat:
                end = f.get("end")
                if not end or len(end) < 4:
                    continue
                try:
                    year = int(end[:4])
                except Exception:
                    continue
                if year == target_year:
                    candidates.append(f)

        if not candidates:
            continue

        # Choose the most recently filed among candidates
        candidates.sort(key=lambda f: f.get("filed", "0000-00-00"), reverse=True)
        chosen = candidates[0]

        val = chosen.get("val")
        if val is None:
            continue

        try:
            return float(val), concept_name
        except Exception:
            continue

    return None, None

# ------------------ CONCEPT CANDIDATES ------------------

NET_SALES_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "PremiumsEarnedNet",  # insurers
    "TotalRevenuesAndOtherIncome",
]

COST_OF_REVENUE_CONCEPTS = [
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "CostOfGoodsSold",
    "CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization",
    "CostOfServices",
]

GROSS_PROFIT_CONCEPTS = [
    "GrossProfit",
    "GrossProfitExcludingDepreciationDepletionAndAmortization",
]

OPERATING_INCOME_CONCEPTS = [
    "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
]

NET_INCOME_CONCEPTS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "NetIncomeLossAvailableToCommonStockholdersDiluted",
]

DEPR_AMORT_CONCEPTS = [
    "DepreciationAndAmortization",
    "DepreciationDepletionAndAmortization",
    "Depreciation",
    "AmortizationOfIntangibleAssets",
]

EBITDA_CONCEPTS = [
    "EarningsBeforeInterestTaxesDepreciationAndAmortization",
    "EarningsBeforeInterestTaxesDepreciationAndAmortizationEBITDA",
]

# ------------------ MARGIN CALCULATIONS ------------------

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

# ------------------ MAIN LOGIC ------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tenk_margins_xbrl.py TICKER [YEAR]")
        sys.exit(1)

    ticker = sys.argv[1]
    year = int(sys.argv[2]) if len(sys.argv) >= 3 else None

    print(f"Ticker: {ticker}, Year: {year if year else 'latest available'}")

    cik = get_cik_for_ticker(ticker)
    print(f"CIK: {cik}")

    meta = get_10k_metadata(cik, year)
    print("Using 10-K (for aligning fiscal year):")
    print(f"  Accession:    {meta['accession_number']}")
    print(f"  Primary doc:  {meta['primary_document']}")
    print(f"  Report date:  {meta['report_date']}")

    target_end = meta["report_date"]

    print("\nFetching XBRL companyfacts...")
    cf = fetch_companyfacts(cik)
    facts_root = cf.get("facts", {})

    # Extract key financials
    results: Dict[str, Any] = {
        "fiscal_year_end": target_end,
        "currency": "USD",  # companyfacts values are in USD
        "net_sales": None,
        "net_sales_concept": None,
        "cost_of_revenue": None,
        "cost_of_revenue_concept": None,
        "gross_profit": None,
        "gross_profit_concept": None,
        "operating_income": None,
        "operating_income_concept": None,
        "net_income": None,
        "net_income_concept": None,
        "depreciation_and_amortization": None,
        "depr_amort_concept": None,
        "ebitda": None,
        "ebitda_concept": None,
    }

    # Net sales / revenue
    val, concept = pick_fact_value(facts_root, NET_SALES_CONCEPTS, target_end)
    results["net_sales"] = val
    results["net_sales_concept"] = concept

    # Cost of revenue / COGS
    val, concept = pick_fact_value(facts_root, COST_OF_REVENUE_CONCEPTS, target_end)
    results["cost_of_revenue"] = val
    results["cost_of_revenue_concept"] = concept

    # Gross profit
    val, concept = pick_fact_value(facts_root, GROSS_PROFIT_CONCEPTS, target_end)
    if val is None and results["net_sales"] is not None and results["cost_of_revenue"] is not None:
        # derive gross profit if not explicitly tagged
        val = results["net_sales"] - results["cost_of_revenue"]
        concept = "Derived: net_sales - cost_of_revenue"
    results["gross_profit"] = val
    results["gross_profit_concept"] = concept

    # Operating income
    val, concept = pick_fact_value(facts_root, OPERATING_INCOME_CONCEPTS, target_end)
    results["operating_income"] = val
    results["operating_income_concept"] = concept

    # Net income
    val, concept = pick_fact_value(facts_root, NET_INCOME_CONCEPTS, target_end)
    results["net_income"] = val
    results["net_income_concept"] = concept

    # Depreciation and amortization
    val, concept = pick_fact_value(facts_root, DEPR_AMORT_CONCEPTS, target_end)
    results["depreciation_and_amortization"] = val
    results["depr_amort_concept"] = concept

    # EBITDA: try explicit tag first, then derive
    val, concept = pick_fact_value(facts_root, EBITDA_CONCEPTS, target_end)
    if val is None:
        if results["operating_income"] is not None and results["depreciation_and_amortization"] is not None:
            val = results["operating_income"] + results["depreciation_and_amortization"]
            concept = "Derived: operating_income + depreciation_and_amortization"
    results["ebitda"] = val
    results["ebitda_concept"] = concept

    print("\nExtracted financials (XBRL-based):")
    print(json.dumps(results, indent=2))

    margins = compute_margins(results)

    print("\nComputed margins (fractional, e.g. 0.25 = 25%):")
    for k, v in margins.items():
        if v is None:
            print(f"  {k}: N/A")
        else:
            print(f"  {k}: {v:.4f} ({v*100:.2f}%)")


if __name__ == "__main__":
    main()
