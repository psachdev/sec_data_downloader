"""Parse an XBRL instance document, keeping dimensions.

Why this exists: ``data.sec.gov/api/xbrl/companyfacts`` is convenient but
returns consolidated figures. Facts that carry a dimension — anything reported
per business segment, per geography, per product line — are the ones a
segment-level claim resolves against, and those have to come from the filing's
own instance document.

The parser is namespace-agnostic. Filers use their own prefixes, and the XBRL
namespace URIs have changed across versions, so everything matches on local
names rather than hardcoded prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from lxml import etree

# Attributes that appear on facts, never on a concept we care about.
_CONTEXT_ATTR = "contextRef"
_UNIT_ATTR = "unitRef"
_NIL_ATTR = "{http://www.w3.org/2001/XMLSchema-instance}nil"


def _localname(element) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def _prefixed_name(element) -> str:
    """Return ``prefix:LocalName`` as the document itself declares it.

    Use the element's own prefix rather than guessing from the namespace URI.
    Deriving it from the URI breaks on the standard taxonomies, because
    ``http://fasb.org/us-gaap/2025`` ends in the year, not in ``us-gaap``.
    """
    tag = element.tag
    if not isinstance(tag, str):
        return str(tag)
    if "}" not in tag:
        return tag

    namespace, _, local = tag[1:].partition("}")
    prefix = element.prefix
    if prefix:
        return f"{prefix}:{local}"

    # Default namespace, or a prefix lxml could not resolve. Fall back to the
    # last non-numeric path segment of the URI.
    segments = [s for s in namespace.rstrip("/").split("/") if s]
    for segment in reversed(segments):
        if not segment.isdigit():
            return f"{segment}:{local}"
    return local


@dataclass(frozen=True)
class Period:
    start: str | None = None
    end: str | None = None
    instant: str | None = None

    @property
    def is_duration(self) -> bool:
        return self.instant is None

    def __str__(self) -> str:
        if self.instant:
            return self.instant
        return f"{self.start}..{self.end}"


@dataclass(frozen=True)
class Context:
    context_id: str
    period: Period
    dimensions: tuple[tuple[str, str], ...]  # ordered (axis, member) pairs

    @property
    def is_consolidated(self) -> bool:
        """No dimensions means the figure covers the whole entity."""
        return not self.dimensions

    def dimension_dict(self) -> dict[str, str]:
        return dict(self.dimensions)


@dataclass(frozen=True)
class Fact:
    concept: str  # e.g. "us-gaap:RevenueFromContractWithCustomer..."
    value: str
    context: Context
    unit: str | None
    decimals: str | None

    @property
    def local_concept(self) -> str:
        return self.concept.rpartition(":")[2]

    @property
    def numeric(self) -> float | None:
        try:
            return float(self.value)
        except (TypeError, ValueError):
            return None

    @property
    def dimensions(self) -> dict[str, str]:
        return self.context.dimension_dict()

    @property
    def period(self) -> Period:
        return self.context.period


def _parse_period(context_element) -> Period:
    for child in context_element:
        if _localname(child) != "period":
            continue
        start = end = instant = None
        for node in child:
            name = _localname(node)
            text = (node.text or "").strip()
            if name == "startDate":
                start = text
            elif name == "endDate":
                end = text
            elif name == "instant":
                instant = text
        return Period(start=start, end=end, instant=instant)
    return Period()


def _parse_dimensions(context_element) -> tuple[tuple[str, str], ...]:
    """Pull explicit members out of segment and scenario containers."""
    pairs: list[tuple[str, str]] = []
    for entity_or_scenario in context_element.iter():
        if _localname(entity_or_scenario) != "explicitMember":
            continue
        axis = entity_or_scenario.get("dimension", "")
        member = (entity_or_scenario.text or "").strip()
        if axis and member:
            pairs.append((axis, member))
    return tuple(sorted(pairs))


def _parse_units(root) -> dict[str, str]:
    units: dict[str, str] = {}
    for element in root.iter():
        if _localname(element) != "unit":
            continue
        unit_id = element.get("id")
        if not unit_id:
            continue
        measures = [
            (node.text or "").strip().rpartition(":")[2]
            for node in element.iter()
            if _localname(node) == "measure"
        ]
        units[unit_id] = "/".join(measures) if measures else ""
    return units


class Instance:
    """A parsed XBRL instance document."""

    def __init__(self, root) -> None:
        self._root = root
        self.contexts: dict[str, Context] = {}
        self.units: dict[str, str] = _parse_units(root)
        self.facts: list[Fact] = []
        self._build()

    # -- construction ----------------------------------------------------

    @classmethod
    def from_bytes(cls, payload: bytes) -> "Instance":
        parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
        root = etree.fromstring(payload, parser=parser)
        if root is None:
            raise ValueError("Could not parse XBRL instance: empty document")
        return cls(root)

    @classmethod
    def from_path(cls, path) -> "Instance":
        with open(path, "rb") as handle:
            return cls.from_bytes(handle.read())

    def _build(self) -> None:
        for element in self._root.iter():
            name = _localname(element)
            if name == "context":
                context_id = element.get("id")
                if context_id:
                    self.contexts[context_id] = Context(
                        context_id=context_id,
                        period=_parse_period(element),
                        dimensions=_parse_dimensions(element),
                    )

        seen: set[tuple[str, str]] = set()
        self.duplicate_count = 0

        for element in self._root.iter():
            context_id = element.get(_CONTEXT_ATTR)
            if not context_id:
                continue
            if element.get(_NIL_ATTR) == "true":
                continue
            context = self.contexts.get(context_id)
            if context is None:
                continue
            value = (element.text or "").strip()
            if not value:
                continue

            concept = _prefixed_name(element)
            # An extracted inline-XBRL instance repeats the same fact wherever
            # the filer rendered it -- income statement and segment note both
            # tag the same value. Identity is (concept, context).
            key = (concept, context_id)
            if key in seen:
                self.duplicate_count += 1
                continue
            seen.add(key)

            self.facts.append(
                Fact(
                    concept=concept,
                    value=value,
                    context=context,
                    unit=self.units.get(element.get(_UNIT_ATTR, ""), None),
                    decimals=element.get("decimals"),
                )
            )

    # -- queries ---------------------------------------------------------

    def query(
        self,
        concept: str | None = None,
        axis: str | None = None,
        member: str | None = None,
        dimensional: bool | None = None,
        period_end: str | None = None,
        numeric_only: bool = False,
        exact_axes: Sequence[str] | None = None,
    ) -> list[Fact]:
        """Filter facts.

        Args:
            concept: local name or ``prefix:LocalName``. Substring-insensitive
                exact match on the local name when no prefix is given.
            axis: e.g. ``StatementBusinessSegmentsAxis``. Matched on local name.
            member: e.g. ``GovernmentOperationsMember``. Matched on local name.
            dimensional: ``True`` for segment-level facts only, ``False`` for
                consolidated only, ``None`` for both.
            period_end: exact match on the period end (or instant) date.
            exact_axes: require the fact's dimension set to be *exactly* these
                axes, no more. This is how you isolate a segment total from
                its own breakdowns -- a fact tagged with segment AND geography
                is a subset of the segment row, and summing both double counts.
        """
        results = []
        for fact in self.facts:
            if concept:
                if ":" in concept:
                    if fact.concept != concept:
                        continue
                elif fact.local_concept != concept:
                    continue
            if dimensional is True and fact.context.is_consolidated:
                continue
            if dimensional is False and not fact.context.is_consolidated:
                continue
            if axis and not any(
                a.rpartition(":")[2] == axis for a, _ in fact.context.dimensions
            ):
                continue
            if member and not any(
                m.rpartition(":")[2] == member for _, m in fact.context.dimensions
            ):
                continue
            if exact_axes is not None:
                present = {a.rpartition(":")[2] for a, _ in fact.context.dimensions}
                if present != set(exact_axes):
                    continue
            if period_end:
                period = fact.context.period
                if (period.instant or period.end) != period_end:
                    continue
            if numeric_only and fact.numeric is None:
                continue
            results.append(fact)
        return results

    def concepts(self, dimensional: bool | None = None) -> list[str]:
        """Distinct concept names present, sorted. Useful for discovery."""
        seen = set()
        for fact in self.facts:
            if dimensional is True and fact.context.is_consolidated:
                continue
            if dimensional is False and not fact.context.is_consolidated:
                continue
            seen.add(fact.concept)
        return sorted(seen)

    def axes(self) -> dict[str, list[str]]:
        """Every dimension axis in the filing mapped to its members.

        Run this first against a new company. It tells you what the filer
        actually tags, which is the grounding a segment-level criterion needs.
        """
        found: dict[str, set[str]] = {}
        for context in self.contexts.values():
            for axis, member in context.dimensions:
                found.setdefault(axis.rpartition(":")[2], set()).add(
                    member.rpartition(":")[2]
                )
        return {axis: sorted(members) for axis, members in sorted(found.items())}

    def segment_facts(
        self,
        concept: str,
        axis: str = "StatementBusinessSegmentsAxis",
        durations_only: bool = True,
    ) -> list[Fact]:
        """Convenience wrapper for the common case: one concept, per segment."""
        facts = self.query(concept=concept, axis=axis, numeric_only=True)
        if durations_only:
            facts = [f for f in facts if f.period.is_duration]
        return facts


# Axes that qualify a figure without partitioning it. A fact tagged
# ConsolidationItemsAxis=OperatingSegmentsMember is still the segment total --
# the axis only says "this is segment-level, not corporate or eliminations".
# Other members on the same axis (IntersegmentEliminationMember,
# CorporateNonSegmentMember) DO partition, so the member is checked too.
QUALIFIER_AXES: dict[str, frozenset[str]] = {
    "ConsolidationItemsAxis": frozenset({"OperatingSegmentsMember"}),
}


def dimension_shapes(
    instance: "Instance", concept: str
) -> list[tuple[tuple[str, ...], int]]:
    """Distinct dimension-axis combinations for a concept, most common first.

    Discovery, not guesswork. Filers differ in how many axes they hang on a
    segment figure, so look at the shapes before deciding which one is the
    total you want.
    """
    counts: dict[tuple[str, ...], int] = {}
    for fact in instance.query(concept=concept, numeric_only=True):
        key = tuple(sorted(a.rpartition(":")[2] for a, _ in fact.context.dimensions))
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _strip_qualifiers(fact: Fact) -> set[str] | None:
    """Axes remaining after removing pure qualifiers. None if a qualifier axis
    carries a partitioning member, which disqualifies the fact entirely."""
    remaining = set()
    for axis, member in fact.context.dimensions:
        axis_name = axis.rpartition(":")[2]
        member_name = member.rpartition(":")[2]
        allowed = QUALIFIER_AXES.get(axis_name)
        if allowed is not None:
            if member_name not in allowed:
                return None  # e.g. IntersegmentEliminationMember
            continue
        remaining.add(axis_name)
    return remaining


def segment_totals(
    instance: "Instance",
    concept: str,
    axis: str = "StatementBusinessSegmentsAxis",
) -> list[Fact]:
    """Segment totals only, excluding breakdowns within each segment.

    Keeps facts whose only partitioning axis is ``axis``, after removing
    qualifier axes (see :data:`QUALIFIER_AXES`). Guards two live traps:

    1. A fact tagged with the segment axis *and* a geography, product, or
       timing axis is a subset of the segment total. Summing both double counts.
    2. A filer may use a product-line member resembling a segment name. BWXT
       tags a ``CommercialOperationsMember`` product line inside its
       Government Operations *segment*, distinct from
       ``CommercialOperationsSegmentMember``. Matching on the member name
       rather than the axis picks a figure roughly six times too small.

    If this returns nothing, call :func:`dimension_shapes` to see how the
    filer actually tags the concept.
    """
    results = []
    for fact in instance.query(concept=concept, axis=axis, numeric_only=True):
        remaining = _strip_qualifiers(fact)
        if remaining == {axis}:
            results.append(fact)
    return results


def summarize(facts: Sequence[Fact]) -> list[dict]:
    """Flatten facts into plain dicts, ready for JSON or a DataFrame."""
    rows = []
    for fact in facts:
        row = {
            "concept": fact.concept,
            "value": fact.numeric if fact.numeric is not None else fact.value,
            "unit": fact.unit,
            "period_start": fact.period.start,
            "period_end": fact.period.instant or fact.period.end,
            "context_id": fact.context.context_id,
        }
        for axis, member in fact.context.dimensions:
            row[axis.rpartition(":")[2]] = member.rpartition(":")[2]
        rows.append(row)
    return rows


def iter_periods(facts: Iterable[Fact]) -> Iterator[Period]:
    seen = set()
    for fact in facts:
        key = str(fact.period)
        if key not in seen:
            seen.add(key)
            yield fact.period
