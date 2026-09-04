"""Tests for the parts that do not need the network."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secedgar.client import MissingUserAgent, RateLimiter, _user_agent  # noqa: E402
from secedgar.facts import ReportedValue, deduplicate, latest_annual  # noqa: E402
from secedgar.filings import (  # noqa: E402
    FilingDocument,
    find_earnings_exhibit,
    find_xbrl_instance,
    normalize_cik,
    validate_accession,
)
from secedgar.xbrl import (  # noqa: E402
    Instance,
    dimension_shapes,
    segment_totals,
    summarize,
)

FIXTURE = Path(__file__).parent / "fixtures" / "segment_instance.xml"
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"


@pytest.fixture(scope="module")
def instance() -> Instance:
    return Instance.from_path(FIXTURE)


# -- XBRL parsing --------------------------------------------------------


def test_contexts_parsed(instance):
    assert len(instance.contexts) == 7
    assert instance.contexts["C_Q3_2026"].is_consolidated
    assert not instance.contexts["C_Q3_2026_GOV"].is_consolidated


def test_period_types(instance):
    duration = instance.contexts["C_Q3_2026"].period
    assert duration.is_duration
    assert duration.start == "2026-07-01"
    assert duration.end == "2026-09-30"

    instant = instance.contexts["C_INSTANT_2026"].period
    assert not instant.is_duration
    assert instant.instant == "2026-09-30"


def test_units_resolved(instance):
    assets = instance.query(concept="Assets")
    assert len(assets) == 1
    assert assets[0].unit == "USD"


def test_nil_facts_are_dropped(instance):
    """A nil fact must not be read as zero. This is the quiet one."""
    assert instance.query(concept="RestructuringCharges") == []


def test_consolidated_and_segment_are_separable(instance):
    consolidated = instance.query(concept=REVENUE, dimensional=False)
    segmented = instance.query(concept=REVENUE, dimensional=True)

    assert len(consolidated) == 2
    assert len(segmented) == 4
    assert {int(f.numeric) for f in consolidated} == {896_000_000, 840_000_000}


def test_segment_lookup_by_member(instance):
    gov = instance.query(
        concept=REVENUE,
        axis="StatementBusinessSegmentsAxis",
        member="GovernmentOperationsMember",
    )
    # Three: current quarter, prior quarter, and the US-only breakdown.
    assert len(gov) == 3


def test_multi_dimensional_context_is_not_confused_with_segment_total(instance):
    """The segment+geography fact must not be mistaken for the segment total.

    Summing every fact tagged GovernmentOperationsMember double counts, because
    the US-only row is a subset of the segment row. Filtering on the exact
    dimension set is the only safe way to pick the total.
    """
    current = instance.query(
        concept=REVENUE,
        member="GovernmentOperationsMember",
        period_end="2026-09-30",
    )
    assert len(current) == 2

    totals = [f for f in current if len(f.context.dimensions) == 1]
    assert len(totals) == 1
    assert int(totals[0].numeric) == 612_400_000


def test_growth_computation_from_segment_facts(instance):
    """The arithmetic Python does, not the model."""
    facts = instance.segment_facts(REVENUE)
    single_axis = [f for f in facts if len(f.context.dimensions) == 1]

    by_key = {
        (f.dimensions["us-gaap:StatementBusinessSegmentsAxis"], f.period.end): f.numeric
        for f in single_axis
    }
    gov = "demo:GovernmentOperationsMember"
    current = by_key[(gov, "2026-09-30")]
    prior = by_key[(gov, "2025-09-30")]

    growth = (current - prior) / prior
    assert round(growth * 100, 1) == 7.3


def test_axes_discovery(instance):
    axes = instance.axes()
    assert set(axes) == {"StatementBusinessSegmentsAxis", "StatementGeographicalAxis"}
    assert axes["StatementBusinessSegmentsAxis"] == [
        "CommercialOperationsMember",
        "GovernmentOperationsMember",
    ]


def test_concept_prefix_is_preserved(instance):
    concepts = instance.concepts()
    assert "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" in concepts
    assert "demo:SegmentDescription" in concepts


def test_text_fact_has_no_numeric(instance):
    text = instance.query(concept="SegmentDescription")
    assert len(text) == 1
    assert text[0].numeric is None
    assert text[0].unit is None


def test_numeric_only_filter(instance):
    assert instance.query(concept="SegmentDescription", numeric_only=True) == []


def test_summarize_flattens_dimensions(instance):
    rows = summarize(instance.query(concept=REVENUE, dimensional=True))
    assert all("StatementBusinessSegmentsAxis" in row for row in rows)
    us_row = [r for r in rows if r.get("StatementGeographicalAxis") == "US"]
    assert len(us_row) == 1


# -- filings helpers -----------------------------------------------------


def test_normalize_cik():
    assert normalize_cik(1156375) == "0001156375"
    assert normalize_cik("1156375") == "0001156375"
    assert normalize_cik("0001156375") == "0001156375"
    assert normalize_cik("CIK0001156375") == "0001156375"


def test_validate_accession():
    assert validate_accession("0001156375-26-000012")
    for bad in ("000115637526000012", "0001156375-26-12", "nonsense"):
        with pytest.raises(ValueError):
            validate_accession(bad)


def _doc(name: str) -> FilingDocument:
    return FilingDocument(name=name, url=f"https://example.com/{name}", size=1, last_modified=None)


def test_find_earnings_exhibit_prefers_991():
    docs = [_doc("bwxt-8k.htm"), _doc("ex99-2.htm"), _doc("ex99-1.htm")]
    assert find_earnings_exhibit(docs).name == "ex99-1.htm"


def test_find_earnings_exhibit_returns_none_when_absent():
    assert find_earnings_exhibit([_doc("bwxt-8k.htm")]) is None


def test_find_xbrl_instance_skips_linkbases():
    docs = [
        _doc("bwxt-20260930_cal.xml"),
        _doc("bwxt-20260930_lab.xml"),
        _doc("bwxt-20260930_htm.xml"),
    ]
    assert find_xbrl_instance(docs).name == "bwxt-20260930_htm.xml"


# -- facts helpers -------------------------------------------------------


def _value(end: str, filed: str, val: float, fp: str = "FY", form: str = "10-K"):
    return ReportedValue(
        concept="Revenues",
        taxonomy="us-gaap",
        unit="USD",
        value=val,
        start=None,
        end=end,
        fiscal_year=2026,
        fiscal_period=fp,
        form=form,
        accession="0001156375-26-000012",
        filed=filed,
    )


def test_deduplicate_prefers_latest_filing():
    values = [
        _value("2025-12-31", "2026-02-20", 100.0),
        _value("2025-12-31", "2026-05-01", 105.0),  # restated
        _value("2024-12-31", "2025-02-20", 90.0),
    ]
    deduped = deduplicate(values)
    assert len(deduped) == 2
    assert deduped[-1].value == 105.0


def test_latest_annual_ignores_quarters():
    values = [
        _value("2025-12-31", "2026-02-20", 100.0),
        _value("2026-03-31", "2026-05-01", 30.0, fp="Q1", form="10-Q"),
    ]
    assert latest_annual(values).value == 100.0


# -- client --------------------------------------------------------------


def test_missing_user_agent_raises(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(MissingUserAgent):
        _user_agent()


def test_user_agent_without_email_raises(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Just A Name")
    with pytest.raises(MissingUserAgent):
        _user_agent()


def test_user_agent_accepted(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Runner test@example.com")
    assert _user_agent() == "Test Runner test@example.com"


def test_rate_limiter_throttles():
    import time

    limiter = RateLimiter(max_per_second=5)
    start = time.monotonic()
    for _ in range(11):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 1.0, f"11 calls at 5/s should take over 1s, took {elapsed:.2f}s"


# -- regressions found against live BWXT filings ------------------------


DUPLICATE_FIXTURE = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:demo="http://www.example.com/20251231">
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:context id="SEG">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:GovernmentOperationsSegmentMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="SEG_GEO">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:GovernmentOperationsSegmentMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">country:US</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="SEG_PROD">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:GovernmentOperationsSegmentMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="us-gaap:ProductOrServiceAxis">demo:CommercialOperationsMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:Revenues contextRef="SEG" unitRef="usd">2350090000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="SEG" unitRef="usd">2350090000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="SEG" unitRef="usd">2350090000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="SEG_GEO" unitRef="usd">2323608000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="SEG_PROD" unitRef="usd">147138000</us-gaap:Revenues>
</xbrl>
"""


@pytest.fixture(scope="module")
def dupes() -> Instance:
    return Instance.from_bytes(DUPLICATE_FIXTURE)


def test_repeated_facts_collapse(dupes):
    """Inline XBRL repeats a fact wherever the filer rendered it.

    BWXT's FY2025 10-K tags the same Government Operations revenue four times.
    Without collapsing on (concept, context) any sum or count is wrong.
    """
    assert len(dupes.query(concept="Revenues", period_end="2025-12-31")) == 3
    assert dupes.duplicate_count == 2


def test_segment_totals_excludes_breakdowns(dupes):
    totals = segment_totals(dupes, "Revenues")
    assert len(totals) == 1
    assert int(totals[0].numeric) == 2_350_090_000


def test_product_member_is_not_the_segment(dupes):
    """The wrong-level trap, from a real filing.

    BWXT tags a CommercialOperationsMember *product line* inside the
    Government Operations segment. Matching on the member name rather than
    the axis returns 147M where the Commercial segment total is 853M.
    """
    by_name = dupes.query(concept="Revenues", member="CommercialOperationsMember")
    assert len(by_name) == 1
    assert int(by_name[0].numeric) == 147_138_000
    # It is tagged to the Government segment, not the Commercial segment.
    assert any(
        "GovernmentOperationsSegmentMember" in m
        for _, m in by_name[0].context.dimensions
    )
    # segment_totals refuses it.
    assert by_name[0] not in segment_totals(dupes, "Revenues")


QUALIFIER_FIXTURE = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:demo="http://www.example.com/20251231">
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>

  <xbrli:context id="OPSEG_GOV">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:ConsolidationItemsAxis">us-gaap:OperatingSegmentsMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:GovernmentOperationsSegmentMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>

  <xbrli:context id="ELIM_GOV">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:ConsolidationItemsAxis">us-gaap:IntersegmentEliminationMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:GovernmentOperationsSegmentMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>

  <xbrli:context id="TIMING_GOV">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:GovernmentOperationsSegmentMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="us-gaap:TimingOfTransferOfGoodOrServiceAxis">us-gaap:TransferredOverTimeMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>

  <us-gaap:Revenues contextRef="OPSEG_GOV" unitRef="usd">2350090000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="ELIM_GOV" unitRef="usd">99000000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="TIMING_GOV" unitRef="usd">2337024000</us-gaap:Revenues>
</xbrl>
"""


@pytest.fixture(scope="module")
def qualified() -> Instance:
    return Instance.from_bytes(QUALIFIER_FIXTURE)


def test_qualifier_axis_does_not_disqualify_a_total(qualified):
    """BWXT tags no fact with the segment axis alone.

    Every segment figure also carries ConsolidationItemsAxis=OperatingSegments,
    which qualifies rather than partitions. Requiring exactly one axis matched
    nothing against the real filing.
    """
    totals = segment_totals(qualified, "Revenues")
    assert len(totals) == 1
    assert int(totals[0].numeric) == 2_350_090_000


def test_eliminations_are_excluded(qualified):
    """IntersegmentEliminationMember on the same axis DOES partition."""
    values = {int(f.numeric) for f in segment_totals(qualified, "Revenues")}
    assert 99_000_000 not in values


def test_timing_breakdown_is_excluded(qualified):
    """Two axes, but the second is a real breakdown -- a subset, not a total."""
    values = {int(f.numeric) for f in segment_totals(qualified, "Revenues")}
    assert 2_337_024_000 not in values


def test_dimension_shapes_reports_all_combinations(qualified):
    shapes = dict(dimension_shapes(qualified, "Revenues"))
    assert (
        "ConsolidationItemsAxis",
        "StatementBusinessSegmentsAxis",
    ) in shapes
    assert (
        "StatementBusinessSegmentsAxis",
        "TimingOfTransferOfGoodOrServiceAxis",
    ) in shapes


FORECAST_FIXTURE = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025"
      xmlns:demo="http://www.example.com/20251231">
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:context id="ACTUAL">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:ConsolidationItemsAxis">us-gaap:OperatingSegmentsMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:EInfrastructureSolutionsSegmentMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="FORECAST">
    <xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier><xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:ConsolidationItemsAxis">us-gaap:OperatingSegmentsMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">demo:EInfrastructureSolutionsSegmentMember</xbrldi:explicitMember>
      <xbrldi:explicitMember dimension="us-gaap:StatementScenarioAxis">us-gaap:ScenarioForecastMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:Revenues contextRef="ACTUAL" unitRef="usd">1466777000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="FORECAST" unitRef="usd">1600000000</us-gaap:Revenues>
</xbrl>
"""


@pytest.fixture(scope="module")
def forecasts() -> Instance:
    return Instance.from_bytes(FORECAST_FIXTURE)


def test_forecast_excluded_from_segment_totals(forecasts):
    """Guidance carries the same concept and period as the actual.

    Sterling tags StatementScenarioAxis=ScenarioForecastMember. Resolving a
    kill criterion against a forecast settles it on a number that has not
    happened yet.
    """
    totals = segment_totals(forecasts, "Revenues")
    assert len(totals) == 1
    assert int(totals[0].numeric) == 1_466_777_000


def test_forecast_reachable_when_asked(forecasts):
    both = segment_totals(forecasts, "Revenues", include_non_actual=True)
    assert len(both) == 2
    assert sum(1 for f in both if not f.is_actual) == 1


def test_is_actual_flag(forecasts):
    facts = forecasts.query(concept="Revenues")
    assert sorted(f.is_actual for f in facts) == [False, True]
