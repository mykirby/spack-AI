"""Metrics shared by model training and the agent evals."""

from __future__ import annotations

from typing import Any

from spack_ai.recipe_ast import summarize


def exact_match(predictions: list[Any], targets: list[Any]) -> float:
    if not targets:
        return 0.0
    return sum(p == t for p, t in zip(predictions, targets, strict=True)) / len(targets)


def set_prf(predicted: set[str], reference: set[str]) -> dict[str, float]:
    if not predicted and not reference:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    hits = len(predicted & reference)
    precision = hits / len(predicted) if predicted else 0.0
    recall = hits / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


LANGUAGE_DEPS = {"c", "cxx", "fortran"}


def recipe_scores(source: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Score a generated package.py against an expectation.

    `expected` may contain: base_class, dependencies (Spack names), variants, and
    reference (the source of a known-good recipe, from which missing keys are derived).
    """
    summary = summarize(source)
    if reference := expected.get("reference"):
        ref = summarize(reference)
        expected = {
            "base_class": ref.base_classes[0].split(".")[-1] if ref.base_classes else None,
            "dependencies": sorted(ref.dependency_names - LANGUAGE_DEPS),
            "variants": ref.variants,
            **{k: v for k, v in expected.items() if k != "reference"},
        }
    scores: dict[str, Any] = {
        "syntax_ok": summary.syntax_error is None,
        "fixmes": len(summary.fixmes),
    }
    if expected.get("base_class"):
        bases = {b.split(".")[-1] for b in summary.base_classes}
        scores["base_class_ok"] = expected["base_class"] in bases
    if "dependencies" in expected:
        got = summary.dependency_names - LANGUAGE_DEPS
        scores["dependencies"] = set_prf(got, set(expected["dependencies"]))
    if "variants" in expected:
        scores["variants"] = set_prf(set(summary.variants), set(expected["variants"]))
    return scores
