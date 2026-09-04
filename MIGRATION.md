# Migrating from the 0.1 scripts

The old entry points and their replacements.

## `get_10k_filings(ticker, num_filings)` / `download_10k_filings(...)`

Old: resolve CIK, filter `form == '10-K'`, write raw HTML to
`10K_downloads/{ticker}/`.

New:

```python
from secedgar import EdgarClient, iter_filings

with EdgarClient() as client:
    filings = list(iter_filings(client, "PGR", forms=["10-K"]))[:5]
    for filing in filings:
        html = client.get_text(filing.primary_document_url)
```

Differences that matter:

- `SEC_USER_AGENT` must be set. There is no placeholder fallback.
- Filings are returned, not written to disk. You choose the path and format.
- `filing.accession` is available, so a second run can skip what it already has.

## `get_cik_from_ticker(ticker)`

```python
from secedgar import EdgarClient, cik_for_ticker

with EdgarClient() as client:
    cik = cik_for_ticker(client, "BWXT")   # "0001156375"
```

Raises `TickerNotFound` instead of returning `None`, so a typo fails loudly.
The ticker table is fetched once per client and cached.

## The sec-api.io path

`sec_api_download.py` wrapped a paid third-party service. Nothing here depends
on it. Delete it unless you have a key and a reason.

## Removed without replacement

- `sec_company_facts_api_download.py` — duplicated the 10-K downloader under a
  misleading name. The capability the name described now lives in
  `secedgar/facts.py`.
- `sec_downloader_download.py` — a thin wrapper over `sec-edgar-downloader`.
  Use that library directly if you want it.
