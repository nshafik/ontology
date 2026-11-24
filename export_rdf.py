#!/usr/bin/env python3
"""Export the ontology and knowledge graph as RDF/XML (.owl / .rdf).

Protégé and most OWL tooling prefer RDF/XML. This writes:

    exports/philosophy_ontology.owl     TBox only
    exports/philosophy_complete.owl     ontology + dataset (the reasoning bundle)
    exports/philosophy_inferred.rdf     the same with the R1 rule links and the
                                        OWL-RL closure materialised

The inferred export strips owl:hasKey before running owlrl, for the reason
documented in build.py (owlrl 7.6.2 prp-key bug).

    python3 export_rdf.py [--output exports]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from rdflib import Graph

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "app"))


def inferred() -> Graph:
    import owlrl
    from agent import Agent

    text = (HERE / "philosophy_complete.ttl").read_text(encoding="utf-8")
    text = re.sub(r"^:Philosopher owl:hasKey.*$", "", text, flags=re.M)
    agent = Agent(Graph().parse(data=text, format="turtle"))
    agent.materialise_rules()
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(agent.g)
    return agent.g


def export(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("philosophy_ontology.owl", lambda: Graph().parse(HERE / "philosophy_ontology.ttl")),
        ("philosophy_complete.owl", lambda: Graph().parse(HERE / "philosophy_complete.ttl")),
        ("philosophy_inferred.rdf", inferred),
    ]
    written = []
    for name, build in jobs:
        path = out / name
        graph = build()
        graph.serialize(destination=str(path), format="xml", encoding="utf-8")
        print(f"{path.relative_to(HERE) if path.is_relative_to(HERE) else path}"
              f"  {len(graph)} triples")
        written.append(path)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path, default=HERE / "exports")
    export(ap.parse_args().output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
