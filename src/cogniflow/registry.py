"""Policy registry + config selection - the plugin seam (L3).

A name-keyed factory registry per policy family. Config selects an implementation by
name; the framework constructs it. This is where a contributor plugs in a new policy,
and where selection fails LOUD: a misnamed policy raises ``PolicyNotFoundError`` at
construction time, never silently falls back. The per-family default is itself a
*named* policy ("strict" / "default" / "none" / "never"), selected explicitly - not a
silent fallback at a divergence point.

Standard library only; no dependency on the policy implementations (they import this
module to register, not the other way around).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

FAMILIES = ("validity", "retrieval", "falsification", "writeback")

# The default for each family is a registered, named policy - chosen explicitly.
DEFAULT_POLICIES: dict[str, str] = {
    "validity": "strict",
    "retrieval": "default",
    "falsification": "none",
    "writeback": "never",
}


class PolicyNotFoundError(KeyError):
    """Raised when a config names a policy that is not registered (fail-loud)."""


class UnknownFamilyError(KeyError):
    """Raised when a policy family is not one of FAMILIES."""


_REGISTRY: dict[str, dict[str, Callable[..., Any]]] = {fam: {} for fam in FAMILIES}
_LOADED = False


def _ensure_loaded() -> None:
    # Import the reference policies once so their registration runs. Done lazily to
    # avoid an import cycle (policies import this module).
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from . import core  # noqa: F401  (triggers cogniflow.core.policies registration)


def register_policy(family: str, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a factory (often a class) under a family + name."""
    if family not in _REGISTRY:
        raise UnknownFamilyError(f"unknown policy family {family!r}; expected one of {FAMILIES}")

    def decorator(factory: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[family][name] = factory
        return factory

    return decorator


def create_policy(family: str, name: str, **kwargs: Any) -> Any:
    """Construct a policy by family + name. Raises if the family or name is unknown."""
    _ensure_loaded()
    if family not in _REGISTRY:
        raise UnknownFamilyError(f"unknown policy family {family!r}; expected one of {FAMILIES}")
    family_registry = _REGISTRY[family]
    if name not in family_registry:
        raise PolicyNotFoundError(
            f"no {family} policy named {name!r}; available: {sorted(family_registry)}"
        )
    return family_registry[name](**kwargs)


def available_policies(family: str) -> list[str]:
    _ensure_loaded()
    if family not in _REGISTRY:
        raise UnknownFamilyError(f"unknown policy family {family!r}; expected one of {FAMILIES}")
    return sorted(_REGISTRY[family])


def build_policies(
    config: dict[str, str] | None = None,
    params: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one policy instance per family from a config mapping.

    ``config`` maps family -> policy name; an omitted family uses its named default.
    ``params`` maps family -> kwargs for that policy's factory. Misnamed policies
    raise (fail-loud).
    """
    config = config or {}
    params = params or {}
    return {
        fam: create_policy(fam, config.get(fam, DEFAULT_POLICIES[fam]), **params.get(fam, {}))
        for fam in FAMILIES
    }
