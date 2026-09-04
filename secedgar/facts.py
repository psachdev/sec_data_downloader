"""XBRL company facts from data.sec.gov.

This is what ``sec_company_facts_api_download.py`` was named for and never did.

Scope note worth reading before you rely on it: the companyfacts endpoint
serves consolidated figures. Segment-level values — the ones a claim about a
named business segment resolves against — are not reliably available here and
should be read from the filing's own instance document via
:mod:`secedgar.xbrl`. ``fetch_instance`` below is the bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .client import EdgarClient
from .filings import (
    Filing,
    find_xbrl_instance,
    list_documents,
    normalize_cik,
)
from .xbrl import Instance

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
COMPANY_CONCEPT_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"
)


@dataclass(frozen=True)
class ReportedValue:
    """One reported figure with the filing it came from."""

    concept: str
    taxonomy: str
    unit: str
    value: float
    start: str | None
    end: str
    fiscal_year: int | None
    fiscal_period: str | None
    form: str
    accession: str
    filed: str
    frame: str | None = None

    @property
    def is_quarterly(self) -> bool:
        return (self.fiscal_period or "").upper().startswith("Q")


def _rows(payload: dict, taxonomy: str, concept: str) -> list[ReportedValue]:
    values: list[ReportedValue] = []
    units = payload.get("units", {})
    for unit, entries in units.items():
        for entry in entries:
            if "val" not in entry or "end" not in entry:
                continue
            values.append(
                ReportedValue(
                    concept=concept,
                    taxonomy=taxonomy,
                    unit=unit,
                    value=entry["val"],
                    start=entry.get("start"),
                    end=entry["end"],
                    fiscal_year=entry.get("fy"),
                    fiscal_period=entry.get("fp"),
                    form=entry.get("form", ""),
                    accession=entry.get("accn", ""),
                    filed=entry.get("filed", ""),
                    frame=entry.get("frame"),
                )
            )
    return values


def company_concept(
    client: EdgarClient,
    cik: str,
    concept: str,
    taxonomy: str = "us-gaap",
) -> list[ReportedValue]:
    """Full reported history for one concept. Cheaper than companyfacts."""
    url = COMPANY_CONCEPT_URL.format(
        cik=normalize_cik(cik), taxonomy=taxonomy, concept=concept
    )
    payload = client.get_json(url)
    return _rows(payload, taxonomy, concept)


def company_facts(
    client: EdgarClient,
    cik: str,
    concepts: Iterable[str] | None = None,
    taxonomy: str | None = None,
) -> dict[str, list[ReportedValue]]:
    """Every reported concept for a company.

    The raw response is large — several megabytes for a mature filer — so pass
    ``concepts`` to keep only what you need.
    """
    payload = client.get_json(COMPANY_FACTS_URL.format(cik=normalize_cik(cik)))
    wanted = {c for c in concepts} if concepts else None

    out: dict[str, list[ReportedValue]] = {}
    for tax, concept_map in payload.get("facts", {}).items():
        if taxonomy and tax != taxonomy:
            continue
        for concept, body in concept_map.items():
            if wanted and concept not in wanted:
                continue
            out[concept] = _rows(body, tax, concept)
    return out


def latest_annual(values: Iterable[ReportedValue]) -> ReportedValue | None:
    """Most recently filed full-year figure."""
    annual = [
        v
        for v in values
        if v.form.startswith("10-K") and (v.fiscal_period or "").upper() == "FY"
    ]
    if not annual:
        return None
    return max(annual, key=lambda v: (v.end, v.filed))


def deduplicate(values: Iterable[ReportedValue]) -> list[ReportedValue]:
    """Keep one row per (start, end, unit), preferring the latest filing.

    The same period is reported again in later filings, sometimes restated.
    Without this you get duplicate periods and silently double-count.
    """
    best: dict[tuple[str | None, str, str], ReportedValue] = {}
    for value in values:
        key = (value.start, value.end, value.unit)
        current = best.get(key)
        if current is None or value.filed > current.filed:
            best[key] = value
    return sorted(best.values(), key=lambda v: v.end)


def fetch_instance(client: EdgarClient, filing: Filing) -> Instance | None:
    """Download and parse the filing's XBRL instance, dimensions intact.

    Returns ``None`` when the filing has no instance document, which is normal
    for many 8-Ks — the earnings release exhibit inside them is usually plain
    HTML with no tagging at all.
    """
    documents = list_documents(client, filing)
    instance_doc = find_xbrl_instance(documents)
    if instance_doc is None:
        return None
    return Instance.from_bytes(client.get_bytes(instance_doc.url))
