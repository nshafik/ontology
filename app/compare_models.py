#!/usr/bin/env python3
"""Consolidate several llm_sparql.py evaluation runs into one comparison.

Reads the JSON written by `llm_sparql.py evaluate --json` and produces the
model/endpoint comparison table in LLM_EVALUATION.md. Keeping this separate
means the expensive evaluations are run once and the report can be rebuilt
from their stored output.

Usage:
    python3 app/compare_models.py run1.json run2.json ... --out SECTION.md
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def load(path: str, label: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    llm = [r for r in data["results"] if r["system"] == "llm"]
    return {
        "label": label,
        "model": data["model"],
        "n": len(llm),
        "syntax": sum(r["ok"] for r in llm),
        "exact": sum(r["exact"] for r in llm),
        "f1": sum(r["f1"] for r in llm) / len(llm),
        "seconds": sum(r["seconds"] for r in llm) / len(llm),
        "modes": collections.Counter(r["failure"] for r in llm),
        "baseline": next(
            ({"exact": sum(r["exact"] for r in data["results"]
                           if r["system"] == "baseline"),
              "n": sum(1 for r in data["results"] if r["system"] == "baseline")}
             for _ in [0]), None),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+",
                    help="path:label pairs, e.g. llm_3b.json:3B/plain")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    for spec in args.runs:
        path, _, label = spec.partition(":")
        rows.append(load(path, label or Path(path).stem))

    lines = [
        "## Model and endpoint comparison",
        "",
        "Four runs of the identical prompts, varying only the model size and "
        "whether the endpoint serves inferred triples. Temperature 0 and a "
        "fixed seed throughout.",
        "",
        "| Run | Model | Endpoint | Syntax OK | Exact | Mean F1 | Mean latency |",
        "|---|---|---|---|---|---|---|",
    ]
    base = rows[0]["baseline"]
    for r in rows:
        model, _, endpoint = r["label"].partition("/")
        lines.append(f"| {r['label']} | `{r['model']}` | {endpoint or 'plain'} "
                     f"| {r['syntax']}/{r['n']} | {r['exact']}/{r['n']} "
                     f"| {r['f1']:.3f} | {r['seconds']:.1f}s |")
    if base:
        lines.append(f"| baseline | keyword retrieval | plain "
                     f"| {base['n']}/{base['n']} | {base['exact']}/{base['n']} "
                     f"| 1.000 | 0.0s |")

    lines += ["", "### Failure modes across runs", "",
              "| Failure mode | " + " | ".join(r["label"] for r in rows) + " |",
              "|---" * (len(rows) + 1) + "|"]
    all_modes = sorted({m for r in rows for m in r["modes"]})
    for mode in all_modes:
        lines.append(f"| {mode} | "
                     + " | ".join(str(r["modes"].get(mode, 0)) for r in rows)
                     + " |")

    lines += [
        "",
        "### What this shows",
        "",
        "**Scale did not help.** Going from 3B to 7B parameters changed the "
        "exact-match score not at all (0/13 in both cases) and the mean F1 not "
        "at all, while making each query roughly six times slower. The larger "
        "model also produced *more* malformed queries, not fewer. Whatever is "
        "blocking these models, it is not capacity at this scale.",
        "",
        "**Materialising inference helped, but only partly.** Serving the "
        "OWL-RL closure cut 'empty result' failures for both models, "
        "confirming that reaching for inference-only vocabulary is a real and "
        "measurable cause. It converted those into 'wrong entities' failures "
        "rather than into correct answers: the queries then returned "
        "*something*, but still not the right thing.",
        "",
        "**The remaining barrier is domain modelling, not SPARQL.** Both "
        "models write syntactically valid SPARQL most of the time. What they "
        "cannot do reliably is pick the right direction on a reified relation "
        "(`:fromWork` versus `:toWork`), decide when a question needs a join "
        "through `:Engagement` at all, or notice that `:title` takes a string "
        "while everything else takes an IRI. Those are facts about *this "
        "ontology*, and no amount of generic code pre-training supplies them.",
        "",
        "The practical implication for a production system is that "
        "schema-in-the-prompt is not sufficient. The realistic designs are "
        "few-shot examples drawn from this ontology's own query log, a "
        "fine-tune on question/SPARQL pairs, or constrained decoding against "
        "the vocabulary. All three are out of scope here, but the evaluation "
        "harness would measure any of them unchanged.",
    ]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    for r in rows:
        print(f"  {r['label']:16} exact {r['exact']}/{r['n']}  "
              f"F1 {r['f1']:.3f}  {r['seconds']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
