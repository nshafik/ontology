#!/usr/bin/env python3
"""Reasoning and recommendation agent over the philosophy knowledge graph.

The design brief (week 9) asks for "the Python reasoning agent, recommendation
logic". This module provides both, with every recommendation carrying an
explanation traced back to concrete triples.

What the agent does that SPARQL alone does not:

  1. Materialises the :criticizes / :praises shortcut links from engagement
     stance (rule R1). These cannot be OWL axioms because they branch on a
     literal value.
  2. Scores and ranks unread works for a reader. Ranking is arithmetic, which
     is outside both OWL and plain SPARQL.
  3. Produces a human-readable justification for each recommendation, so the
     output is auditable rather than a bare ordering.

The scoring function is deliberately simple and fully documented, because an
unexplainable recommender would defeat the point of building a knowledge graph:

    score(work) = sum over supporting engagements of
                      confidence x stance_weight x interest_weight

    stance_weight    praises 1.0, neutral 0.6, criticizes 0.8
    interest_weight  1.0 when the engagement's concept is a stated interest

Criticism scores slightly below praise but well above nothing: a work that
attacks a concept you care about is still highly relevant to you. That is a
judgement call, stated here so it can be argued with.

Usage:
    python3 app/agent.py recommend :reader1
    python3 app/agent.py rules              # materialise R1 links
    python3 app/agent.py lineage :Plato
    python3 app/agent.py --json recommend :reader1
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

from rdflib import Graph, Namespace, RDFS, URIRef

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
P = Namespace("http://example.org/philosophy#")

STANCE_WEIGHT = {"praises": 1.0, "neutral": 0.6, "criticizes": 0.8}


# --------------------------------------------------------------------------

@dataclass
class Evidence:
    """One engagement supporting a recommendation."""
    engagement: str
    concept: str
    stance: str
    confidence: float
    other_work: str
    contribution: float

    def sentence(self) -> str:
        return (f"{self.engagement} {self.stance} in relation to "
                f"'{self.concept}' (vs {self.other_work}), "
                f"confidence {self.confidence:g} "
                f"-> +{self.contribution:.2f}")


@dataclass
class Recommendation:
    work: str
    title: str
    author: str
    score: float
    evidence: list[Evidence] = field(default_factory=list)

    def explain(self) -> str:
        lines = [f"{self.title}  ({self.author})   score {self.score:.2f}"]
        for item in self.evidence:
            lines.append("      because " + item.sentence())
        return "\n".join(lines)


class Agent:
    def __init__(self, graph: Graph | None = None) -> None:
        if graph is None:
            graph = Graph()
            graph.parse(ROOT / "philosophy_complete.ttl", format="turtle")
        self.g = graph

    # -- helpers ---------------------------------------------------------

    def label(self, node) -> str:
        if node is None:
            return "?"
        value = self.g.value(node, RDFS.label) or self.g.value(node, P.title)
        return str(value) if value else str(node).split("#")[-1]

    def short(self, node) -> str:
        return ":" + str(node).split("#")[-1]

    # -- rule layer ------------------------------------------------------

    def materialise_rules(self) -> list[tuple[str, str, str]]:
        """Rule R1: derive :criticizes / :praises from engagement stance.

        Adds the inferred triples to the in-memory graph and returns them.
        OWL cannot express this: the conclusion depends on the VALUE of a
        data property, which is outside description-logic class axioms.
        """
        added = []
        for stance, prop in (("criticizes", P.criticizes), ("praises", P.praises)):
            query = """
                PREFIX : <http://example.org/philosophy#>
                SELECT ?a ?b WHERE {
                  ?e a :Engagement ; :fromWork ?a ; :toWork ?b ; :stance ?s .
                  FILTER (?s = "%s")
                }""" % stance
            for row in self.g.query(query):
                source, target = row
                if (source, prop, target) not in self.g:
                    self.g.add((source, prop, target))
                    added.append((self.label(source), stance, self.label(target)))
        return added

    # -- recommendation --------------------------------------------------

    def recommend(self, reader: str, limit: int = 10) -> list[Recommendation]:
        """Rank unread works for a reader, with an explanation for each."""
        reader_node = URIRef(str(P) + reader.lstrip(":"))

        interests = set(self.g.objects(reader_node, P.hasInterestIn))
        already_read = set(self.g.objects(reader_node, P.hasRead))
        if not interests:
            return []

        # CQ12/CQ13 give the candidate set; the scoring below is the part
        # that neither OWL nor SPARQL can do.
        scored: dict[URIRef, Recommendation] = {}
        for engagement in self.g.subjects(P.aboutConcept, None):
            concept = self.g.value(engagement, P.aboutConcept)
            if concept not in interests:
                continue
            stance = str(self.g.value(engagement, P.stance))
            confidence = float(self.g.value(engagement, P.confidenceScore) or 0.5)
            source = self.g.value(engagement, P.fromWork)
            target = self.g.value(engagement, P.toWork)

            for work, other in ((source, target), (target, source)):
                if work is None or work in already_read:
                    continue
                contribution = confidence * STANCE_WEIGHT.get(stance, 0.5)
                rec = scored.get(work)
                if rec is None:
                    author = self.g.value(work, P.createdBy)
                    rec = Recommendation(
                        work=self.short(work),
                        title=self.label(work),
                        author=self.label(author),
                        score=0.0,
                    )
                    scored[work] = rec
                rec.score += contribution
                rec.evidence.append(Evidence(
                    engagement=self.short(engagement),
                    concept=self.label(concept),
                    stance=stance,
                    confidence=confidence,
                    other_work=self.label(other),
                    contribution=contribution,
                ))

        ranked = sorted(scored.values(), key=lambda r: (-r.score, r.title))
        return ranked[:limit]

    # -- lineage ---------------------------------------------------------

    def lineage(self, philosopher: str) -> dict:
        """Teaching lineage and works in that lineage, using inference."""
        node = URIRef(str(P) + philosopher.lstrip(":"))
        rows = self.g.query("""
            PREFIX : <http://example.org/philosophy#>
            SELECT ?a WHERE { <%s> :studiedUnder+ ?a }""" % node)
        ancestors = [self.label(r[0]) for r in rows]
        rows = self.g.query("""
            PREFIX : <http://example.org/philosophy#>
            SELECT ?d WHERE { ?d :studiedUnder+ <%s> }""" % node)
        descendants = [self.label(r[0]) for r in rows]
        rows = self.g.query("""
            PREFIX : <http://example.org/philosophy#>
            SELECT ?t WHERE { ?w :createdBy/:studiedUnder+ <%s> ; :title ?t }""" % node)
        lineage_works = sorted({str(r[0]) for r in rows})
        return {
            "philosopher": self.label(node),
            "taught_by": sorted(ancestors),
            "taught": sorted(descendants),
            "works_in_lineage": lineage_works,
        }


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["recommend", "rules", "lineage"])
    ap.add_argument("target", nargs="?", default=":reader1")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    agent = Agent()

    if args.command == "rules":
        added = agent.materialise_rules()
        if args.json:
            print(json.dumps(added, indent=2))
        else:
            print(f"materialised {len(added)} shortcut links from engagement stance\n")
            for source, stance, target in sorted(added):
                print(f"  {source}  --{stance}-->  {target}")
        return 0

    if args.command == "lineage":
        result = agent.lineage(args.target)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{result['philosopher']}")
            print(f"  studied under : {', '.join(result['taught_by']) or '-'}")
            print(f"  taught        : {', '.join(result['taught']) or '-'}")
            print(f"  works by pupils in the lineage ({len(result['works_in_lineage'])}):")
            for title in result["works_in_lineage"]:
                print(f"      {title}")
        return 0

    agent.materialise_rules()
    recs = agent.recommend(args.target)
    if args.json:
        print(json.dumps([asdict(r) for r in recs], indent=2))
        return 0

    reader_label = agent.label(URIRef(str(P) + args.target.lstrip(":")))
    interests = [agent.label(c) for c in
                 agent.g.objects(URIRef(str(P) + args.target.lstrip(":")),
                                 P.hasInterestIn)]
    read = [agent.label(w) for w in
            agent.g.objects(URIRef(str(P) + args.target.lstrip(":")), P.hasRead)]
    print(f"Recommendations for {reader_label} ({args.target})")
    print(f"  interests    : {', '.join(sorted(interests)) or '-'}")
    print(f"  already read : {', '.join(sorted(read)) or '-'}")
    print()
    if not recs:
        print("  no unread works match the recorded interests")
    for rank, rec in enumerate(recs, 1):
        print(f"  {rank}. {rec.explain()}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
