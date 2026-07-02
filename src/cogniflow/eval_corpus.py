"""The labeled eval corpus - one corpus, three consumers.

Serves: (1) verify_fact / LLMFalsificationPolicy recall-precision (the recalibration of the
n=8 floor), (2) the F2 faithfulness checker's own precision/recall, (3) the expanded
benchmark's question pool. Design rules, preserved from the original benchmark:

- FICTIONAL entities throughout (companies, cities, people) so no model can answer from
  training - the temporal signal must come from the corpus, never from memory.
- Dates live in metadata (valid_at/invalid_at), never inside fact text.
- Balanced positives/negatives for falsification; negatives include the dangerous lookalikes
  (same predicate, DIFFERENT entity - must NOT supersede; a restatement - dedup, not
  contradiction; an unrelated fact about the same entity).

Label provenance (documented, honest): cases are template-authored across six fact types and
hand-reviewed; they are correlated within a template family, so treat per-family results as
the finer-grained signal. Standard library only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .core.types import Belief
from .eval import FalsificationCase

# Fictional universe: 12 companies, 14 cities, people. None exist; all invented.
_COMPANIES = [
    "Meridian Systems", "Orinoco Labs", "Zephyr Logistics", "Corvus Analytics",
    "Halcyon Grid", "Vantor Foods", "Ashgrove Metals", "Bluewick Energy",
    "Calder Dynamics", "Drayton Marine", "Ellsworth Biotech", "Foxbridge Capital",
]
_CITIES = [
    "Calderport", "Newhaven", "Westfall", "Kingsford", "Millbrook", "Fenwick",
    "Ashford", "Draymoor", "Sablewood", "Torbay", "Grelling", "Ostmere",
    "Pellworth", "Quillhaven",
]
_PEOPLE = [
    "Dana Voss", "Marcus Lund", "Priya Chandran", "Tomas Reiner", "Aiko Marsh",
    "Felix Okafor", "Greta Sandoval", "Ivo Lindqvist", "Nadia Ferris", "Owen Tulley",
    "Rhea Calloway", "Silas Munk",
]


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _b(bid: str, statement: str, vy: int, iy: int | None = None) -> Belief:
    return Belief(
        id=bid, statement=statement, created_at=_w(vy), valid_at=_w(vy),
        invalid_at=_w(iy) if iy else None,
    )


def verify_cases() -> list[FalsificationCase]:
    """56 labeled falsification cases across six fact-type families, ~balanced."""
    cases: list[FalsificationCase] = []

    def add(tgt: Belief, cand: Belief, expected: bool) -> None:
        cases.append(
            FalsificationCase(target=tgt, candidates=(cand,), expected_superseded=expected)
        )

    # Family A - HQ moves (concrete entity relocation). 8 positive, 8 negative.
    for k in range(8):
        co, c1, c2 = _COMPANIES[k], _CITIES[k], _CITIES[k + 2]
        add(
            _b(f"a{k}t", f"{co} is headquartered in {c1}", 2015, 2020),
            _b(f"a{k}c", f"{co} is headquartered in {c2}", 2020),
            True,
        )
        # dangerous lookalike: same predicate, DIFFERENT company - must NOT supersede
        other = _COMPANIES[(k + 5) % len(_COMPANIES)]
        add(
            _b(f"a{k}nt", f"{co} is headquartered in {c1}", 2015),
            _b(f"a{k}nc", f"{other} is headquartered in {c2}", 2020),
            False,
        )

    # Family B - role changes (CEO succession). 6 positive, 6 negative.
    for k in range(6):
        co, p1, p2 = _COMPANIES[k + 3], _PEOPLE[k], _PEOPLE[k + 4]
        add(
            _b(f"b{k}t", f"The CEO of {co} is {p1}", 2017, 2021),
            _b(f"b{k}c", f"The CEO of {co} is {p2}", 2021),
            True,
        )
        # unrelated fact about the same company - must NOT supersede
        add(
            _b(f"b{k}nt", f"The CEO of {co} is {p1}", 2017),
            _b(f"b{k}nc", f"{co} opened an office in {_CITIES[k + 6]}", 2021),
            False,
        )

    # Family C - quantitative updates (headcount/metric). 5 positive, 5 negative.
    for k in range(5):
        co = _COMPANIES[k + 6]
        add(
            _b(f"c{k}t", f"{co} employs {100 + 50 * k} people", 2018, 2022),
            _b(f"c{k}c", f"{co} employs {400 + 75 * k} people", 2022),
            True,
        )
        # restatement of the SAME value - dedup, not a contradiction
        add(
            _b(f"c{k}nt", f"{co} employs {100 + 50 * k} people", 2018),
            _b(f"c{k}nc", f"{co} employs {100 + 50 * k} people", 2019),
            False,
        )

    # Family D - definitional/metric redefinition. 4 positive, 4 negative.
    metrics = ["weekly active users", "churn rate", "gross margin", "uptime"]
    windows = [("7-day", "28-day"), ("monthly", "quarterly"), ("gross", "net"), ("99.9%", "99.99%")]
    for k, (m, (w1, w2)) in enumerate(zip(metrics, windows, strict=True)):
        co = _COMPANIES[k]
        add(
            _b(f"d{k}t", f"{co} defines {m} over a {w1} window", 2019, 2023),
            _b(f"d{k}c", f"{co} defines {m} over a {w2} window", 2023),
            True,
        )
        add(
            _b(f"d{k}nt", f"{co} defines {m} over a {w1} window", 2019),
            _b(f"d{k}nc", f"{co} reports {m} to its board annually", 2021),
            False,
        )

    # Family E - person-employment moves. 4 positive, 4 negative.
    for k in range(4):
        p, co1, co2 = _PEOPLE[k + 6], _COMPANIES[k], _COMPANIES[k + 7]
        add(
            _b(f"e{k}t", f"{p} works at {co1}", 2019, 2022),
            _b(f"e{k}c", f"{p} works at {co2}", 2022),
            True,
        )
        # a DIFFERENT person joining the same company - must NOT supersede
        add(
            _b(f"e{k}nt", f"{p} works at {co1}", 2019),
            _b(f"e{k}nc", f"{_PEOPLE[(k + 9) % len(_PEOPLE)]} works at {co1}", 2022),
            False,
        )

    # Family F - product/status transitions. 3 positive, 3 negative.
    for k in range(3):
        co, c = _COMPANIES[k + 9], _CITIES[k + 10]
        add(
            _b(f"f{k}t", f"{co}'s flagship product is in beta", 2020, 2022),
            _b(f"f{k}c", f"{co}'s flagship product is generally available", 2022),
            True,
        )
        add(
            _b(f"f{k}nt", f"{co}'s flagship product is in beta", 2020),
            _b(f"f{k}nc", f"{co} is headquartered in {c}", 2021),
            False,
        )

    return cases


# ---- the faithfulness labeled set : claim-level ground truth -----------------------
# Each case: served fact statements, one answer sentence, and whether that sentence is
# supported by the facts (strict entailment - anything added is unsupported).
FAITHFULNESS_CASES: list[tuple[list[str], str, bool]] = [
    # grounded restatements (exact and lightly rephrased)
    (["Meridian Systems is headquartered in Calderport"],
     "Meridian Systems is headquartered in Calderport.", True),
    (["Meridian Systems is headquartered in Calderport"],
     "According to the context facts, Meridian Systems is headquartered in Calderport.", True),
    (["Orinoco Labs is headquartered in Westfall"],
     "As of 2015, Orinoco Labs is headquartered in Westfall.", True),
    (["The CEO of Halcyon Grid is Dana Voss"],
     "The CEO of Halcyon Grid is Dana Voss.", True),
    (["Zephyr Logistics employs 250 people"],
     "Zephyr Logistics employs 250 people.", True),
    (["Vantor Foods defines churn rate over a monthly window"],
     "Vantor Foods defines churn rate over a monthly window.", True),
    (["Corvus Analytics is headquartered in Fenwick"],
     "Corvus Analytics is based in the city of Fenwick.", True),
    (["Priya Chandran works at Ashgrove Metals"],
     "Priya Chandran works at Ashgrove Metals.", True),
    # entity substitutions (the as-of-leak shape) - unsupported
    (["Meridian Systems is headquartered in Calderport"],
     "Meridian Systems is headquartered in Newhaven.", False),
    (["The CEO of Halcyon Grid is Dana Voss"],
     "The CEO of Halcyon Grid is Marcus Lund.", False),
    (["Zephyr Logistics employs 250 people"],
     "Zephyr Logistics employs 4000 people.", False),
    (["Orinoco Labs is headquartered in Westfall"],
     "Orinoco Labs is headquartered in Kingsford.", False),
    # added/invented content - unsupported
    (["Meridian Systems is headquartered in Calderport"],
     "Meridian Systems also operates a research campus in Sablewood.", False),
    (["The CEO of Halcyon Grid is Dana Voss"],
     "Dana Voss previously founded three logistics startups.", False),
    (["Corvus Analytics is headquartered in Fenwick"],
     "Corvus Analytics reported record quarterly revenue this year.", False),
    (["Vantor Foods defines churn rate over a monthly window"],
     "Vantor Foods plans to redefine churn rate next quarter.", False),
    # multi-fact grounded
    (["Meridian Systems is headquartered in Calderport",
      "The CEO of Meridian Systems is Greta Sandoval"],
     "Meridian Systems is headquartered in Calderport.", True),
    (["Meridian Systems is headquartered in Calderport",
      "The CEO of Meridian Systems is Greta Sandoval"],
     "The CEO of Meridian Systems is Greta Sandoval.", True),
    # cross-fact conflation - unsupported (right entities, wrong relation)
    (["Meridian Systems is headquartered in Calderport",
      "Foxbridge Capital is headquartered in Ostmere"],
     "Foxbridge Capital is headquartered in Calderport.", False),
    (["Dana Voss works at Halcyon Grid", "Marcus Lund works at Bluewick Energy"],
     "Dana Voss works at Bluewick Energy.", False),
]
