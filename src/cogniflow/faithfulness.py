"""Post-hoc faithfulness check (F2) - the answer is CHECKED against the served facts.

Grounding by prompt-instruction alone is a request, not a guarantee: the temporal guarantee has
a model-dependent half. This layer moves the guarantee from "we asked the model nicely" to "we
checked": decompose the generated answer into claims, verify each claim against the exact
served (as-of-filtered) facts, and attach a per-claim report to the response.

Design decisions (the F2 contract):
  A. Post-hoc verification, not prompt trust. The prompt constraint stays (defense in depth);
     the report is computed AFTER generation against the response's own facts.
  B. Flag, don't silently fix - and be honest about the checker. Unsupported claims are
     surfaced (never silently rewritten, never silently shipped). The checker itself is a
     bounded instrument: 'lexical' is deterministic token-coverage (strict; paraphrase beyond
     token overlap can flag as unsupported), 'llm-judge' is model-driven (bounded, measured).
     Its own precision/recall is measured and published (PROJECT_STATUS), never presented as
     deterministic truth.

Fail-loud plug (same discipline as embedders/generators/rerankers): the checker is selected by
name; an unknown name raises; "off" is VISIBLY off (the report says "unchecked") - never a
silent absence of checking.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .context import ServedFact

GeneratorFn = Callable[[str], "str | Awaitable[str]"]

_DEFAULT_CHECKER = "lexical"
# Strict by design: at 0.75 an entity substitution ("...in Austin" against a Palo-Alto fact,
# coverage 2/3) is flagged; a faithful restatement with an as-of date (4/5) passes. Errs toward
# flagging - never toward silently passing. Tune per deployment; measured in PROJECT_STATUS.
_DEFAULT_THRESHOLD = 0.75

# Words that carry no claim content (articles, copulas, query scaffolding, citation words).
_STOP = frozenset(
    """a an the is are was were be been being of in on at to as by for from with and or not
    it its this that these those there here now then when where which who whom whose what
    how why do does did done has have had having will would shall should can could may
    might must according context fact facts source sources cited say says said state
    states stated""".split()
)

_REFUSAL_RE = re.compile(
    r"(do(es)? not (have|contain)|don't have|no (information|answer)|cannot answer|"
    r"not available in the (context|facts))",
    re.IGNORECASE,
)
# citation tails and source-only fragments injected by the generation prompt format
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_SOURCE_LINE_RE = re.compile(r"^\s*(source|sources|citations?)\s*[:\-]", re.IGNORECASE)


class FaithfulnessError(RuntimeError):
    """Fail-loud checker selection/configuration error."""


@dataclass(frozen=True)
class ClaimVerdict:
    claim: str
    status: str  # "supported" | "unsupported" | "uncheckable"
    best_fact: str | None = None  # belief_id of the best-supporting fact
    score: float | None = None  # checker-specific support score (lexical: token coverage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "status": self.status,
            "best_fact": self.best_fact,
            "score": self.score,
        }


@dataclass(frozen=True)
class FaithfulnessReport:
    """The response-attached verdict. ``status`` is the overall flag:
    - "grounded"            every checkable claim is supported
    - "unsupported_claims"  at least one claim is not supported by the served facts
    - "no_checkable_claims" nothing checkable (e.g. a refusal) - honest, not a pass
    - "unchecked"           the checker is off (visibly off, never silently absent)
    """

    checker: str
    status: str
    claims: list[ClaimVerdict] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker": self.checker,
            "status": self.status,
            "claims": [c.to_dict() for c in self.claims],
            "unsupported_claims": list(self.unsupported_claims),
            "note": self.note,
        }


# ---- claim decomposition (deterministic, sentence-level) ---------------------------------
def _tokens(text: str) -> set[str]:
    return {
        w
        for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
        if w and w not in _STOP and len(w) > 1
    }


def decompose(answer: str) -> list[str]:
    """Split an answer into checkable claims. Deterministic sentence-level decomposition:
    strip citation tails and source-only lines, split on sentence boundaries, drop fragments
    with too little content to check. (Proposition-level decomposition is a future checker
    concern; sentence-level is honest about its granularity.)"""
    cleaned = _BRACKET_RE.sub(" ", answer)
    claims: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip().lstrip("-*• ").strip()
        if not line or _SOURCE_LINE_RE.match(line):
            continue
        for sent in re.split(r"(?<=[.!?])\s+", line):
            sent = sent.strip().rstrip(".!?").strip()
            if sent and len(_tokens(sent)) >= 2:
                claims.append(sent)
    return claims


# ---- checkers -----------------------------------------------------------------------------
class LexicalChecker:
    """Deterministic, key-free support check: a claim is supported when the best served fact
    covers >= ``threshold`` of the claim's content tokens (fact statement + its date tokens).
    STRICT by construction - a paraphrase beyond token overlap can be flagged unsupported; that
    errs toward flagging, never toward silently passing. Measured, not assumed (PROJECT_STATUS)."""

    name = "lexical"

    def __init__(self, threshold: float = _DEFAULT_THRESHOLD) -> None:
        if not 0.0 < threshold <= 1.0:
            raise FaithfulnessError(f"lexical threshold must be in (0, 1], got {threshold}")
        self.threshold = threshold

    async def check(self, answer: str, facts: list[ServedFact]) -> FaithfulnessReport:
        claims = decompose(answer)
        if not claims:
            return FaithfulnessReport(
                checker=self.name,
                status="no_checkable_claims",
                note="refusal or no factual sentences" if _REFUSAL_RE.search(answer) else None,
            )
        fact_tokens: list[tuple[str, set[str]]] = []
        for f in facts:
            toks = _tokens(f.statement)
            if f.valid_at is not None:
                toks |= {str(f.valid_at.year)}
            fact_tokens.append((f.belief_id, toks))

        verdicts: list[ClaimVerdict] = []
        for claim in claims:
            if _REFUSAL_RE.search(claim):
                verdicts.append(ClaimVerdict(claim=claim, status="uncheckable"))
                continue
            ct = _tokens(claim)
            best_id, best_cov = None, 0.0
            for belief_id, ft in fact_tokens:
                cov = len(ct & ft) / len(ct)
                if cov > best_cov:
                    best_id, best_cov = belief_id, cov
            status = "supported" if best_cov >= self.threshold else "unsupported"
            verdicts.append(
                ClaimVerdict(
                    claim=claim, status=status, best_fact=best_id, score=round(best_cov, 3)
                )
            )
        return _finalize(self.name, verdicts)


class LLMJudgeChecker:
    """Model-driven support check: one strict-rubric call judges every claim against the served
    facts. Better on paraphrase than 'lexical'; bounded by the judge model (measured like
    verify_fact, never presented as deterministic). Requires a generator callable - fail-loud."""

    name = "llm-judge"

    _PROMPT = """You are a strict faithfulness auditor. For each CLAIM below, decide whether it \
is FULLY supported by the FACTS alone (strict entailment - no outside or background knowledge; \
a claim that adds anything not in the facts is UNSUPPORTED).

FACTS:
{facts}

CLAIMS:
{claims}

Reply with EXACTLY one line per claim, nothing else:
<claim number>: SUPPORTED
or
<claim number>: UNSUPPORTED"""

    def __init__(self, generator: GeneratorFn | None = None) -> None:
        if generator is None:
            raise FaithfulnessError(
                "checker 'llm-judge' needs a generator callable (the generation-LLM plug); "
                "pass generator=..., or select 'lexical' for the deterministic key-free checker."
            )
        self.generator = generator

    async def check(self, answer: str, facts: list[ServedFact]) -> FaithfulnessReport:
        claims = decompose(answer)
        if not claims:
            return FaithfulnessReport(checker=self.name, status="no_checkable_claims")
        facts_text = "\n".join(f"- {f.statement}" for f in facts) or "(no facts)"
        claims_text = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))
        raw = self.generator(self._PROMPT.format(facts=facts_text, claims=claims_text))
        if hasattr(raw, "__await__"):
            raw = await raw  # type: ignore[misc]
        verdict_by_index: dict[int, str] = {}
        for m in re.finditer(r"(\d+)\s*[:.\-]\s*(SUPPORTED|UNSUPPORTED)", str(raw), re.IGNORECASE):
            verdict_by_index[int(m.group(1))] = m.group(2).lower()
        verdicts = []
        for i, claim in enumerate(claims):
            v = verdict_by_index.get(i + 1)
            status = "supported" if v == "supported" else (
                "unsupported" if v == "unsupported" else "uncheckable"
            )
            verdicts.append(ClaimVerdict(claim=claim, status=status))
        report = _finalize(self.name, verdicts)
        if any(v.status == "uncheckable" for v in verdicts):
            return FaithfulnessReport(
                checker=report.checker,
                status=report.status,
                claims=report.claims,
                unsupported_claims=report.unsupported_claims,
                note="judge output unparseable for some claims (marked uncheckable)",
            )
        return report


class OffChecker:
    """Visibly off: the report says 'unchecked'. Off must never look like grounded."""

    name = "off"

    async def check(self, answer: str, facts: list[ServedFact]) -> FaithfulnessReport:
        return FaithfulnessReport(
            checker=self.name, status="unchecked", note="faithfulness checking is disabled"
        )


def _finalize(checker: str, verdicts: list[ClaimVerdict]) -> FaithfulnessReport:
    unsupported = [v.claim for v in verdicts if v.status == "unsupported"]
    if unsupported:
        status = "unsupported_claims"
    elif any(v.status == "supported" for v in verdicts):
        status = "grounded"
    else:
        status = "no_checkable_claims"
    return FaithfulnessReport(
        checker=checker, status=status, claims=verdicts, unsupported_claims=unsupported
    )


# ---- the fail-loud plug -------------------------------------------------------------------
def available_checkers() -> list[str]:
    return ["lexical", "llm-judge", "off"]


def create_checker(
    name: str | None = _DEFAULT_CHECKER,
    *,
    generator: GeneratorFn | None = None,
    threshold: float = _DEFAULT_THRESHOLD,
):
    """Construct a faithfulness checker by name. Fail-loud: an unknown name raises - never a
    silent no-op (which would leave answers unchecked while claiming a checker is active)."""
    name = (name or _DEFAULT_CHECKER).strip()
    if name == "lexical":
        return LexicalChecker(threshold=threshold)
    if name == "llm-judge":
        return LLMJudgeChecker(generator=generator)
    if name == "off":
        return OffChecker()
    raise FaithfulnessError(
        f"unknown faithfulness checker {name!r}; available: {available_checkers()}"
    )
