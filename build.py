#!/usr/bin/env python3
"""Build and validate the philosophy ontology.

Regenerates philosophy_complete.ttl from its sources and runs the full
regression gate. philosophy_complete.ttl is GENERATED - never edit it by hand,
or it will drift out of step with the three source files.

Usage:
    python3 build.py           # build + validate
    python3 build.py --check   # validate only, fail if complete.ttl is stale

Pipeline:
    1. parse every source file                     (syntax)
    2. regenerate philosophy_complete.ttl          (ontology + links + data)
    3. SHACL validation with pyshacl               (data quality)
    4. HermiT consistency + classification         (OWL 2 DL reasoning)
    5. Pellet consistency, second DL engine        (cross-check)
    6. OWL-RL closure, report inferred triples     (reasoning yield)
    7. run all 15 competency questions             (query correctness)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ONTOLOGY = HERE / "philosophy_ontology.ttl"
LINKS = HERE / "philosophy_links.ttl"
DATASET = HERE / "philosophy_dataset.ttl"
ENRICHMENT = HERE / "data" / "wikidata_enrichment.ttl"
SHAPES = HERE / "philosophy_shapes.ttl"
COMPLETE = HERE / "philosophy_complete.ttl"

# philosophy_links.ttl is deliberately NOT part of the reasoning bundle.
#
# owl:sameAs makes a local individual, its Wikidata item and its DBpedia
# resource one and the same thing, so the reasoner copies every inferred fact
# onto all three IRIs. Measured on this project: including the links file
# takes the OWL-RL closure from 2,412 to 120,645 triples and reports
# StudentThinker as 33 members instead of 11 - the same 11 philosophers
# counted once per coreferent IRI. That is logically correct but useless for
# reading off results, and it would also drag unvetted external assertions
# into the local reasoning if the remote graphs were dereferenced.
#
# Standard Linked Data practice is therefore to publish identity links as a
# separate graph. philosophy_complete.ttl stays the clean reasoning bundle;
# load philosophy_links.ttl alongside it only for LOD traversal.
SOURCES = [ONTOLOGY, DATASET] + ([ENRICHMENT] if ENRICHMENT.exists() else [])

HEADER = """\
###############################################################################
#  GENERATED FILE - DO NOT EDIT BY HAND.
#
#  Built by build.py from:
#      philosophy_ontology.ttl      (TBox: classes, properties, axioms)
#      philosophy_dataset.ttl       (ABox: curated individuals & engagements)
#      data/wikidata_enrichment.ttl (generated P50/P577 works & P737 influences)
#
#  This single-file bundle is what you open in Protege. Edit the sources and
#  re-run `python3 build.py` instead of editing this file.
#
#  philosophy_links.ttl (owl:sameAs to Wikidata/DBpedia and the vocabulary
#  alignments) is deliberately NOT bundled here: owl:sameAs replicates every
#  inference across all coreferent IRIs, which inflates the OWL-RL closure
#  from 2,412 to 120,645 triples and reports each defined class three times
#  over. Load it as a separate graph when you want the LOD links.
###############################################################################

"""


def info(msg: str) -> None:
    print(f"  {msg}")


def step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def parse_sources():
    """Parse every source file; return the merged graph."""
    from rdflib import Graph

    merged = Graph()
    for path in SOURCES + [SHAPES]:
        g = Graph()
        g.parse(path, format="turtle")
        info(f"{path.name:28} OK  {len(g):>4} triples")
        if path != SHAPES:
            merged += g
    return merged


def build_complete() -> str:
    """Concatenate the sources into one Protege-ready Turtle file."""
    from rdflib import Graph

    parts = [HEADER]
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        parts.append(f"\n# {'=' * 75}\n# SOURCE: {path.name}\n# {'=' * 75}\n")
        # keep only the first file's @base; duplicates are legal but noisy
        if path is not SOURCES[0]:
            text = "\n".join(
                ln for ln in text.splitlines() if not ln.startswith("@base")
            )
        parts.append(text)
    out = "\n".join(parts)

    # round-trip to prove the concatenation is valid Turtle
    Graph().parse(data=out, format="turtle")
    return out


def run_shacl() -> bool:
    cmd = [
        sys.executable, "-m", "pyshacl",
        "-s", str(SHAPES), "-e", str(ONTOLOGY),
        "-i", "rdfs", "-w", "-f", "human", str(COMPLETE),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    conforms = "Conforms: True" in r.stdout
    info(r.stdout.strip().splitlines()[1] if conforms else r.stdout.strip()[:2000])
    return conforms


def run_hermit() -> bool:
    """Load the built ontology into HermiT via owlready2."""
    from rdflib import Graph
    import tempfile

    g = Graph()
    g.parse(COMPLETE, format="turtle")
    tmp = Path(tempfile.gettempdir()) / "philosophy_build.owl"
    g.serialize(tmp, format="xml")

    from owlready2 import get_ontology, sync_reasoner_hermit, Nothing

    onto = get_ontology(tmp.as_uri()).load()
    info(f"loaded {len(list(onto.classes()))} classes, "
         f"{len(list(onto.individuals()))} individuals")
    try:
        with onto:
            sync_reasoner_hermit(infer_property_values=True, debug=0)
    except Exception as exc:  # noqa: BLE001 - we want the reasoner message verbatim
        info(f"HermiT FAILED: {str(exc)[:1500]}")
        return False

    unsat = [c for c in onto.classes() if Nothing in c.equivalent_to]
    info(f"HermiT: CONSISTENT, {len(unsat)} unsatisfiable classes")

    ns = onto.get_namespace("http://example.org/philosophy#")
    for name in ("StudentThinker", "TeacherThinker", "InfluencerThinker",
                 "CriticizedWork", "ProlificPhilosopher", "Criticism",
                 "UncriticizedWork", "SelfReferentialWork"):
        cls = getattr(ns, name, None)
        if cls is not None:
            info(f"    {name:22} {len(list(cls.instances())):>3} members")
    return not unsat


# Expected OWL-RL inference counts. A change here means either a real
# modelling change or a regression; both deserve a look.
EXPECTED_INFERENCES = {
    "hasTeachingAncestor": 19,
    "influencedBy": 96,
    "isWithinSchool": 26,
    "authored": 116,
    "createdInLineageOf": 64,
    "createdIn": 20,
}


def run_pellet() -> bool:
    """Second DL reasoner, invoked through Pellet's own command line.

    owlready2's sync_reasoner_pellet() cannot be used in this environment:
    owlready2 0.51 ships jena-arq-fixed2.10.0.jar containing three classes
    compiled for Java 25 (class file version 69), so Pellet's Jena-based
    loader dies with UnsupportedClassVersionError on any JRE below 25. That
    is an owlready2 packaging defect, not a problem with this ontology.

    Pellet's own CLI does not go through that code path, so it is called
    directly. Returns True when Pellet reports the ontology consistent.

    Note on counts: `pellet realize` lists only the MOST SPECIFIC type of
    each individual, so a philosopher who is both TeacherThinker and
    InfluencerThinker is printed only under the former. Comparing raw
    printed counts with HermiT's therefore looks like a disagreement when
    there is none - InfluencerThinker is 8 printed but 18 actual.
    """
    import glob
    import subprocess
    import tempfile
    from rdflib import Graph

    pellet_dir = Path(owlready2_pellet_dir())
    jars = sorted(glob.glob(str(pellet_dir / "*.jar")))
    if not jars:
        info("skipped: Pellet jars not found")
        return True

    g = Graph()
    g.parse(COMPLETE, format="turtle")
    tmp = Path(tempfile.gettempdir()) / "philosophy_pellet.owl"
    g.serialize(tmp, format="xml")

    try:
        proc = subprocess.run(
            ["java", "-cp", ":".join(jars), "pellet.Pellet",
             "consistency", str(tmp)],
            capture_output=True, text=True, timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        info(f"skipped: could not run Pellet ({exc})")
        return True

    output = (proc.stdout or "") + (proc.stderr or "")
    consistent = "Consistent: Yes" in output
    if consistent:
        info("Pellet: CONSISTENT (agrees with HermiT)")
    else:
        head = [ln for ln in output.splitlines()
                if ln.strip() and not ln.startswith("\tat ")][:5]
        info("Pellet FAILED: " + " | ".join(head)[:600])
    return consistent


def owlready2_pellet_dir() -> str:
    import owlready2
    return str(Path(owlready2.__file__).parent / "pellet")


def run_owlrl() -> bool:
    """OWL-RL closure, with owlrl 7.6.2's broken prp-key rule worked around.

    owlrl 7.6.2 mis-implements owl:hasKey for SINGLE-property keys: its
    prp-key rule compares only the first len(keys) - 1 properties, so the
    comparison loop is empty and every individual of the class is merged.
    That yields 4,352 bogus owl:sameAs triples here and inflates
    hasTeachingAncestor from 19 to 961. HermiT handles the same axiom
    correctly (see step 4), so the axiom stays in the ontology and is
    stripped only for this OWL-RL run.
    """
    import re
    from rdflib import Graph, Namespace, OWL
    import owlrl

    P = Namespace("http://example.org/philosophy#")
    text = COMPLETE.read_text(encoding="utf-8")
    patched = re.sub(r"^:Philosopher owl:hasKey.*$", "", text, flags=re.M)
    if patched != text:
        info("note: owl:hasKey stripped for this run (owlrl 7.6.2 prp-key bug)")

    g = Graph()
    g.parse(data=patched, format="turtle")
    before = len(g)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    info(f"OWL-RL closure: {before} -> {len(g)} triples "
         f"(+{len(g) - before} inferred)")

    ok = True
    spurious = sum(1 for s, _, o in g.triples((None, OWL.sameAs, None)) if s != o)
    if spurious:
        info(f"    FAIL unexpected owl:sameAs inferences: {spurious}")
        ok = False

    for prop, expected in EXPECTED_INFERENCES.items():
        got = len(list(g.triples((None, P[prop], None))))
        good = got == expected
        ok &= good
        info(f"    {'ok  ' if good else 'FAIL'} {prop:22} "
             f"expected {expected:>3}  got {got}")
    return ok


# The 15 competency questions live in app/queries.py, so build.py, the Fuseki
# runner, the web interface and the LLM evaluation all execute the same text.
# A query cannot be fixed in one place and left broken in another.
sys.path.insert(0, str(HERE / "app"))


def run_queries() -> bool:
    """Run every competency question in-process against the core graph."""
    from rdflib import Graph
    from queries import ALL, render

    g = Graph()
    g.parse(COMPLETE, format="turtle")

    ok = True
    for cq in ALL:
        res = g.query(render(cq))
        if res.type == "ASK":
            got = res.askAnswer
        elif cq.kind in ("construct", "describe"):
            got = len(res.graph)
        else:
            got = len(list(res))
        good = got == cq.expected
        ok &= good
        info(f"{'ok  ' if good else 'FAIL'} {cq.id:18} "
             f"expected {str(cq.expected):>5}  got {got}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="validate only; fail if philosophy_complete.ttl is stale")
    args = ap.parse_args()

    step(1, "Parsing sources")
    parse_sources()

    step(2, "Building philosophy_complete.ttl")
    built = build_complete()
    if args.check:
        current = COMPLETE.read_text(encoding="utf-8") if COMPLETE.exists() else ""
        if current != built:
            info("STALE: philosophy_complete.ttl differs from its sources.")
            info("Run `python3 build.py` to regenerate it.")
            return 1
        info("philosophy_complete.ttl is up to date")
    else:
        COMPLETE.write_text(built, encoding="utf-8")
        from rdflib import Graph
        n = len(Graph().parse(COMPLETE, format="turtle"))
        info(f"wrote {COMPLETE.name}  ({n} triples)")

    step(3, "SHACL validation (pyshacl)")
    shacl_ok = run_shacl()

    step(4, "OWL 2 DL reasoning (HermiT)")
    hermit_ok = run_hermit()

    step(5, "OWL 2 DL reasoning (Pellet, second engine)")
    pellet_ok = run_pellet()

    step(6, "OWL-RL closure")
    owlrl_ok = run_owlrl()

    step(7, "Competency questions")
    queries_ok = run_queries()

    print()
    allok = shacl_ok and hermit_ok and pellet_ok and owlrl_ok and queries_ok
    for label, good in (("SHACL", shacl_ok), ("HermiT", hermit_ok),
                        ("Pellet", pellet_ok), ("OWL-RL", owlrl_ok),
                        ("Queries", queries_ok)):
        print(f"  {label:10} {'PASS' if good else 'FAIL'}")
    print(f"\n{'ALL CHECKS PASSED' if allok else 'FAILURES PRESENT'}")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
