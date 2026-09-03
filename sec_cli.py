#!/usr/bin/env python3
"""Command-line access to EDGAR.

    export SEC_USER_AGENT="Your Name you@example.com"

    python sec_cli.py filings BWXT --forms 8-K,10-Q --since 2026-01-01
    python sec_cli.py documents BWXT 0001156375-26-000012
    python sec_cli.py axes BWXT 0001156375-26-000012
    python sec_cli.py segment BWXT 0001156375-26-000012 \\
        --concept RevenueFromContractWithCustomerExcludingAssessedTax
    python sec_cli.py concept BWXT Revenues
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

from secedgar import (
    EdgarClient,
    MissingUserAgent,
    TickerNotFound,
    company_concept,
    deduplicate,
    fetch_instance,
    find_earnings_exhibit,
    iter_filings,
    list_documents,
    normalize_cik,
    dimension_shapes,
    segment_totals,
    summarize,
    validate_accession,
)


def _find_filing(client, ticker: str, accession: str):
    validate_accession(accession)
    for filing in iter_filings(client, ticker, include_history=True):
        if filing.accession == accession:
            return filing
    raise SystemExit(f"Accession {accession} not found for {ticker}")


def cmd_filings(client, args) -> None:
    forms = [f.strip() for f in args.forms.split(",")] if args.forms else None
    filings = list(
        iter_filings(
            client,
            args.ticker,
            forms=forms,
            since=args.since,
            until=args.until,
            include_history=args.history,
        )
    )
    if args.limit:
        filings = filings[: args.limit]

    if args.json:
        print(json.dumps([f.to_dict() for f in filings], indent=2))
        return

    if not filings:
        print("No filings matched.")
        return

    print(f"{'ACCESSION':<22} {'FORM':<8} {'FILED':<12} {'PERIOD':<12} ITEMS")
    for filing in filings:
        items = ",".join(filing.items) if filing.items else "-"
        print(
            f"{filing.accession:<22} {filing.form:<8} {filing.filing_date:<12} "
            f"{(filing.report_date or '-'):<12} {items}"
        )
    print(f"\n{len(filings)} filings.")


def cmd_documents(client, args) -> None:
    filing = _find_filing(client, args.ticker, args.accession)
    documents = list_documents(client, filing)
    exhibit = find_earnings_exhibit(documents)

    for doc in documents:
        marker = "  <-- likely earnings release" if doc is exhibit else ""
        size = f"{doc.size:>10,}" if doc.size is not None else " " * 10
        print(f"{size}  {doc.name}{marker}")
    print(f"\n{filing.directory_url}")


def cmd_axes(client, args) -> None:
    """Discovery: what does this filer actually tag?"""
    filing = _find_filing(client, args.ticker, args.accession)
    instance = fetch_instance(client, filing)
    if instance is None:
        raise SystemExit(
            f"No XBRL instance was found in {args.accession}. Run "
            f"'documents {args.ticker} {args.accession}' to see what the "
            "filing actually contains -- an original filing is sometimes "
            "superseded by an amendment (10-Q/A) that carries the XBRL."
        )
    axes = instance.axes()
    if not axes:
        print("No dimensional contexts. This filing reports consolidated only.")
        return
    for axis, members in axes.items():
        print(f"{axis}")
        for member in members:
            print(f"    {member}")
    print(f"\n{len(instance.facts)} facts, {len(instance.contexts)} contexts.")


def cmd_segment(client, args) -> None:
    filing = _find_filing(client, args.ticker, args.accession)
    instance = fetch_instance(client, filing)
    if instance is None:
        raise SystemExit(f"{args.accession} has no XBRL instance document.")

    if args.shapes:
        shapes = dimension_shapes(instance, args.concept)
        if not shapes:
            print(f"No numeric facts for {args.concept}.")
            return
        print(f"Dimension shapes for {args.concept}:\n")
        for axes, count in shapes:
            label = " + ".join(axes) if axes else "(consolidated, no dimensions)"
            print(f"{count:>5}  {label}")
        return

    if args.totals:
        facts = segment_totals(instance, args.concept, args.axis)
    else:
        facts = instance.query(
            concept=args.concept,
            axis=args.axis,
            member=args.member,
            dimensional=True,
            numeric_only=True,
        )
    if not facts:
        print(f"No matching facts for {args.concept}.")
        print("Run the same command with --shapes to see how this filer "
              "tags it, or 'axes' for every dimension in the filing.")
        return

    rows = summarize(facts)
    if args.json:
        print(json.dumps(rows, indent=2))
        return

    for row in rows:
        dims = {
            k: v
            for k, v in row.items()
            if k
            not in {
                "concept",
                "value",
                "unit",
                "period_start",
                "period_end",
                "context_id",
            }
        }
        dim_text = ", ".join(f"{k}={v}" for k, v in dims.items())
        period = (
            f"{row['period_start']}..{row['period_end']}"
            if row["period_start"]
            else row["period_end"]
        )
        print(f"{row['value']:>18,.0f} {row['unit'] or '':<5} {period:<24} {dim_text}")

    if args.totals:
        print(
            "\nSegment totals. These should sum to the consolidated figure, "
            "less intersegment eliminations."
        )
    else:
        print(
            "\nNote: these rows sit at different levels of aggregation. A fact "
            "carrying an extra axis is a subset of the row without it -- do not "
            "sum them. Use --totals for segment totals only."
        )


def cmd_concept(client, args) -> None:
    cik = normalize_cik(args.cik) if args.cik else None
    if cik is None:
        from secedgar import cik_for_ticker

        cik = cik_for_ticker(client, args.ticker)

    values = deduplicate(company_concept(client, cik, args.concept, args.taxonomy))
    if args.annual:
        values = [v for v in values if (v.fiscal_period or "").upper() == "FY"]
    if args.limit:
        values = values[-args.limit :]

    if args.json:
        print(json.dumps([v.__dict__ for v in values], indent=2))
        return

    for value in values:
        period = f"{value.start}..{value.end}" if value.start else value.end
        print(
            f"{value.value:>20,.0f} {value.unit:<5} {period:<24} "
            f"{value.form:<8} filed {value.filed}"
        )
    print(
        f"\n{len(values)} values. This endpoint returned no dimensional "
        "breakdown; use 'segment' to read segment-level facts from a filing."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sec_cli.py",
        description="SEC EDGAR filings, documents, and XBRL facts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("filings", help="List filings")
    p.add_argument("ticker")
    p.add_argument("--forms", help="Comma-separated, e.g. 8-K,10-Q,10-K")
    p.add_argument("--since", help="YYYY-MM-DD, inclusive")
    p.add_argument("--until", help="YYYY-MM-DD, inclusive")
    p.add_argument("--history", action="store_true", help="Include pre-2001 pages")
    p.add_argument("--limit", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_filings)

    p = sub.add_parser("documents", help="List files inside a filing")
    p.add_argument("ticker")
    p.add_argument("accession")
    p.set_defaults(func=cmd_documents)

    p = sub.add_parser("axes", help="Show dimensions a filing tags")
    p.add_argument("ticker")
    p.add_argument("accession")
    p.set_defaults(func=cmd_axes)

    p = sub.add_parser("segment", help="Dimensional facts from a filing")
    p.add_argument("ticker")
    p.add_argument("accession")
    p.add_argument("--concept", required=True)
    p.add_argument("--axis", default="StatementBusinessSegmentsAxis")
    p.add_argument("--member")
    p.add_argument(
        "--shapes",
        action="store_true",
        help="Show how this filer tags the concept, then exit",
    )
    p.add_argument(
        "--totals",
        action="store_true",
        help="Segment totals only; exclude breakdowns within each segment",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_segment)

    p = sub.add_parser("concept", help="Consolidated history for one concept")
    p.add_argument("ticker")
    p.add_argument("concept")
    p.add_argument("--cik")
    p.add_argument("--taxonomy", default="us-gaap")
    p.add_argument("--annual", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_concept)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with EdgarClient() as client:
            args.func(client, args)
    except MissingUserAgent as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except TickerNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        print(f"EDGAR returned {status}. {exc}", file=sys.stderr)
        if status == 403:
            print(
                "A 403 usually means the User-Agent was rejected or you are "
                "being rate limited. Check SEC_USER_AGENT contains a real "
                "contact address.",
                file=sys.stderr,
            )
        return 4
    except requests.RequestException as exc:
        print(f"Network error reaching EDGAR: {exc}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
