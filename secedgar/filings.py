"""Filing discovery on EDGAR.

Covers the three things the old scripts got wrong or skipped:

1. The ``filings.recent`` block in a submissions JSON holds only the most
   recent ~1000 filings. Older ones live in separate files listed under
   ``filings.files``. ``iter_filings`` follows those when asked.
2. Form filtering is a parameter, not a hardcoded ``== '10-K'``.
3. Every filing keeps its accession number, which is the stable ID an
   append-only evidence log needs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .client import EdgarClient

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_DIR_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}"

_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class TickerNotFound(LookupError):
    """Ticker is not in SEC's company_tickers.json."""


@dataclass(frozen=True)
class Filing:
    """One filing. ``accession`` is the stable document ID."""

    accession: str
    form: str
    filing_date: str
    report_date: str | None
    primary_document: str
    primary_doc_description: str | None
    items: tuple[str, ...]
    is_xbrl: bool
    cik: str
    ticker: str | None = None

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def directory_url(self) -> str:
        return ARCHIVE_DIR_URL.format(
            cik_int=int(self.cik), accession_nodash=self.accession_nodash
        )

    @property
    def primary_document_url(self) -> str:
        return f"{self.directory_url}/{self.primary_document}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FilingDocument:
    """One file inside a filing directory (exhibit, instance document, etc.)."""

    name: str
    url: str
    size: int | None
    last_modified: str | None

    @property
    def extension(self) -> str:
        return Path(self.name).suffix.lower()


def normalize_cik(cik: str | int) -> str:
    """Zero-pad to the 10-digit form data.sec.gov expects."""
    return str(int(str(cik).lstrip("CIK").lstrip("cik"))).zfill(10)


def validate_accession(accession: str) -> str:
    if not _ACCESSION_RE.match(accession):
        raise ValueError(
            f"Malformed accession number: {accession!r}. "
            "Expected the dashed form, e.g. 0001156375-26-000012"
        )
    return accession


@lru_cache(maxsize=1)
def _ticker_table(client: EdgarClient) -> dict[str, tuple[str, str]]:
    """ticker -> (cik10, company title). Fetched once per client."""
    payload = client.get_json(TICKER_MAP_URL)
    table: dict[str, tuple[str, str]] = {}
    for row in payload.values():
        table[row["ticker"].upper()] = (
            normalize_cik(row["cik_str"]),
            row.get("title", ""),
        )
    return table


def cik_for_ticker(client: EdgarClient, ticker: str) -> str:
    """Resolve a ticker to its 10-digit CIK. Cached per client."""
    table = _ticker_table(client)
    key = ticker.upper().replace(".", "-")
    if key not in table:
        raise TickerNotFound(
            f"{ticker!r} is not in SEC's company_tickers.json. "
            "Check the spelling, or the company may not file with SEC."
        )
    return table[key][0]


def company_name(client: EdgarClient, ticker: str) -> str:
    return _ticker_table(client)[ticker.upper().replace(".", "-")][1]


def _rows_from_block(block: dict, cik: str, ticker: str | None) -> Iterator[Filing]:
    """Turn a columnar filings block into Filing objects."""
    forms: Sequence[str] = block.get("form", [])
    if not forms:
        return

    accessions = block["accessionNumber"]
    dates = block["filingDate"]
    report_dates = block.get("reportDate", [""] * len(forms))
    primary_docs = block.get("primaryDocument", [""] * len(forms))
    descriptions = block.get("primaryDocDescription", [""] * len(forms))
    items = block.get("items", [""] * len(forms))
    xbrl_flags = block.get("isXBRL", [0] * len(forms))

    for i, form in enumerate(forms):
        raw_items = items[i] if i < len(items) else ""
        yield Filing(
            accession=accessions[i],
            form=form,
            filing_date=dates[i],
            report_date=report_dates[i] or None if i < len(report_dates) else None,
            primary_document=primary_docs[i] if i < len(primary_docs) else "",
            primary_doc_description=(
                descriptions[i] or None if i < len(descriptions) else None
            ),
            items=tuple(x.strip() for x in raw_items.split(",") if x.strip()),
            is_xbrl=bool(xbrl_flags[i]) if i < len(xbrl_flags) else False,
            cik=cik,
            ticker=ticker.upper() if ticker else None,
        )


def iter_filings(
    client: EdgarClient,
    ticker: str | None = None,
    cik: str | None = None,
    forms: Iterable[str] | None = None,
    since: str | date | None = None,
    until: str | date | None = None,
    include_history: bool = False,
) -> Iterator[Filing]:
    """Yield filings newest first.

    Args:
        forms: e.g. ``["8-K", "10-Q", "10-K"]``. ``None`` means every form.
        since: inclusive lower bound on filing date, ``YYYY-MM-DD``. This is
            the parameter that turns a full re-download into an incremental run.
        include_history: follow ``filings.files`` for filings older than the
            ~1000 most recent. Off by default because it costs extra requests.
    """
    if cik is None:
        if ticker is None:
            raise ValueError("Provide either ticker or cik")
        cik = cik_for_ticker(client, ticker)
    cik = normalize_cik(cik)

    form_set = {f.upper() for f in forms} if forms else None
    since_str = since.isoformat() if isinstance(since, date) else since
    until_str = until.isoformat() if isinstance(until, date) else until

    payload = client.get_json(SUBMISSIONS_URL.format(cik=cik))
    blocks = [payload.get("filings", {}).get("recent", {})]

    if include_history:
        for page in payload.get("filings", {}).get("files", []):
            # Skip whole pages that end before our window starts.
            if since_str and page.get("filingTo", "") < since_str:
                continue
            blocks.append(
                client.get_json(SUBMISSIONS_PAGE_URL.format(name=page["name"]))
            )

    for block in blocks:
        for filing in _rows_from_block(block, cik, ticker):
            if form_set and filing.form.upper() not in form_set:
                continue
            if since_str and filing.filing_date < since_str:
                continue
            if until_str and filing.filing_date > until_str:
                continue
            yield filing


def list_documents(client: EdgarClient, filing: Filing) -> list[FilingDocument]:
    """Every file in the filing directory, including exhibits and XBRL."""
    index = client.get_json(f"{filing.directory_url}/index.json")
    documents = []
    for item in index.get("directory", {}).get("item", []):
        name = item.get("name", "")
        if not name or name.endswith("/"):
            continue
        size = item.get("size")
        documents.append(
            FilingDocument(
                name=name,
                url=f"{filing.directory_url}/{name}",
                size=int(size) if size not in (None, "") else None,
                last_modified=item.get("last-modified") or None,
            )
        )
    return documents


def find_earnings_exhibit(
    documents: Sequence[FilingDocument],
) -> FilingDocument | None:
    """Best guess at the EX-99.1 earnings release inside an 8-K.

    Segment revenue shows up here weeks before it reaches the 10-Q, so this is
    usually the document a quarterly kill criterion actually resolves against.
    """
    candidates = [
        d
        for d in documents
        if d.extension in {".htm", ".html", ".txt"}
        and re.search(r"ex[-_]?99", d.name, re.IGNORECASE)
    ]
    if not candidates:
        return None
    # ex99-1 / ex99_1 / ex991 sort ahead of ex99-2 naturally by name.
    return sorted(candidates, key=lambda d: d.name.lower())[0]


def find_xbrl_instance(
    documents: Sequence[FilingDocument],
) -> FilingDocument | None:
    """The inline-XBRL or standalone instance document, if present."""
    for doc in documents:
        if doc.name.lower().endswith("_htm.xml"):
            return doc
    for doc in documents:
        lowered = doc.name.lower()
        if lowered.endswith(".xml") and not any(
            lowered.endswith(suffix)
            for suffix in (
                "_cal.xml",
                "_def.xml",
                "_lab.xml",
                "_pre.xml",
                "-index.xml",
                "filingsummary.xml",
            )
        ):
            return doc
    return None


def save_filings_index(filings: Iterable[Filing], path: str | Path) -> Path:
    """Write a filing list to JSON. Accession numbers survive, so a later run
    can diff against this instead of re-downloading everything."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([f.to_dict() for f in filings], indent=2), encoding="utf-8"
    )
    return path
