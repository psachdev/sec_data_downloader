"""A small, honest SEC EDGAR toolkit.

Every network call goes through :class:`secedgar.client.EdgarClient`, which
owns the User-Agent and the rate limit so they cannot drift between call sites.

Quick start::

    export SEC_USER_AGENT="Your Name you@example.com"

    from secedgar import EdgarClient, iter_filings

    with EdgarClient() as client:
        for filing in iter_filings(client, "BWXT", forms=["8-K"], since="2026-01-01"):
            print(filing.accession, filing.filing_date, filing.items)
"""

from .client import EdgarClient, MissingUserAgent, RateLimiter
from .facts import (
    ReportedValue,
    company_concept,
    company_facts,
    deduplicate,
    fetch_instance,
    latest_annual,
)
from .filings import (
    Filing,
    FilingDocument,
    TickerNotFound,
    cik_for_ticker,
    company_name,
    find_earnings_exhibit,
    find_xbrl_instance,
    iter_filings,
    list_documents,
    normalize_cik,
    save_filings_index,
    validate_accession,
)
from .xbrl import (
    Context, Fact, Instance, Period,
    dimension_shapes, segment_totals, summarize,
)

__version__ = "0.2.0"

__all__ = [
    "EdgarClient",
    "MissingUserAgent",
    "RateLimiter",
    "Filing",
    "FilingDocument",
    "TickerNotFound",
    "cik_for_ticker",
    "company_name",
    "iter_filings",
    "list_documents",
    "find_earnings_exhibit",
    "find_xbrl_instance",
    "normalize_cik",
    "validate_accession",
    "save_filings_index",
    "ReportedValue",
    "company_concept",
    "company_facts",
    "deduplicate",
    "latest_annual",
    "fetch_instance",
    "Instance",
    "Fact",
    "Context",
    "Period",
    "dimension_shapes",
    "segment_totals",
    "summarize",
]
