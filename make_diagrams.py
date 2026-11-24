#!/usr/bin/env python3
"""Generate the ontology diagrams in DIAGRAMS.md directly from the Turtle.

Figure 1  class hierarchy, asserted and defined classes
Figure 2  object-property map between classes
Figure 3  datatype properties
Figure 4  teaching lineage in the dataset
Figure 5  engagement network, coloured by stance

Reading the diagrams out of the ontology rather than drawing them by hand means
they cannot drift out of step with the axioms. Re-run after any edit:

    python3 make_diagrams.py
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

HERE = Path(__file__).parent
P = Namespace("http://example.org/philosophy#")


def local(term) -> str:
    return str(term).split("#")[-1]


def load() -> tuple[Graph, Graph]:
    onto = Graph()
    onto.parse(HERE / "philosophy_ontology.ttl", format="turtle")
    data = Graph()
    data.parse(HERE / "philosophy_dataset.ttl", format="turtle")
    return onto, data


def defined_parent(onto: Graph, cls: URIRef) -> str | None:
    """The named class a defined class sits under.

    A defined class is written as an intersection whose first member is the
    genus, e.g. StudentThinker == Philosopher AND (studiedUnder some ...).
    That first member is its place in the hierarchy. SelfReferentialWork is a
    bare restriction with no genus, so it returns None.
    """
    eq = onto.value(cls, OWL.equivalentClass)
    if eq is None:
        return None
    inter = onto.value(eq, OWL.intersectionOf)
    if inter is None:
        return None
    for item in onto.items(inter):
        if isinstance(item, URIRef):
            return local(item)
    return None


def figure1(onto: Graph) -> list[str]:
    """Class hierarchy. Defined classes are drawn in a separate style."""
    defined = {s for s in onto.subjects(OWL.equivalentClass, None)
               if isinstance(s, URIRef)}
    defined_names = {local(s) for s in defined}
    named = sorted(local(c) for c in set(onto.subjects(RDF.type, OWL.Class))
                   if isinstance(c, URIRef))

    edges = {
        (local(s), local(o))
        for s, o in onto.subject_objects(RDFS.subClassOf)
        if isinstance(s, URIRef) and isinstance(o, URIRef)
        and str(o).startswith(str(P))
    }
    # place each defined class under the genus of its equivalence axiom
    for cls in defined:
        parent = defined_parent(onto, cls)
        if parent:
            edges.add((local(cls), parent))
    edges = sorted(edges)

    out = ["```mermaid", "graph TD"]
    out.append("    owlThing([owl:Thing])")
    for cls in named:
        out.append(f"    {cls}[{cls}]" if cls not in defined_names
                   else f"    {cls}[/{cls}/]")
    has_parent = {s for s, _ in edges}
    for cls in named:
        if cls not in has_parent:
            out.append(f"    owlThing --> {cls}")
    for sub, sup in edges:
        out.append(f"    {sup} --> {sub}")
    out.append("")
    for cls in sorted(defined_names):
        out.append(f"    class {cls} defined;")
    out.append("    classDef defined fill:#eef,stroke:#669,stroke-dasharray:4 3;")
    out.append("```")
    return out


def figure2(onto: Graph) -> list[str]:
    """Object properties as labelled edges between their domain and range."""
    rows = []
    for prop in sorted(set(onto.subjects(RDF.type, OWL.ObjectProperty)), key=str):
        dom = onto.value(prop, RDFS.domain)
        rng = onto.value(prop, RDFS.range)
        if dom is None or rng is None:
            continue
        if not isinstance(dom, URIRef):          # union domain
            members = []
            for _, _, lst in onto.triples((dom, OWL.unionOf, None)):
                members = [local(x) for x in onto.items(lst)]
            dom_label = " or ".join(members) if members else "?"
        else:
            dom_label = local(dom)
        rows.append((dom_label, local(prop), local(rng)))

    out = ["```mermaid", "graph LR"]
    for dom, prop, rng in rows:
        if " or " in dom:
            for part in dom.split(" or "):
                out.append(f"    {part} -- {prop} --> {rng}")
        else:
            out.append(f"    {dom} -- {prop} --> {rng}")
    out.append("```")
    return out


def figure3(onto: Graph) -> list[str]:
    """Datatype properties grouped by domain."""
    out = ["| Data property | Domain | Range | Characteristics |",
           "|---|---|---|---|"]
    for prop in sorted(set(onto.subjects(RDF.type, OWL.DatatypeProperty)), key=str):
        dom = onto.value(prop, RDFS.domain)
        rng = onto.value(prop, RDFS.range)
        if isinstance(rng, URIRef):
            rng_label = str(rng).split("#")[-1]
            rng_label = f"xsd:{rng_label}" if "XMLSchema" in str(rng) else rng_label
        elif rng is not None and onto.value(rng, OWL.oneOf) is not None:
            vals = list(onto.items(onto.value(rng, OWL.oneOf)))
            rng_label = "one of " + ", ".join(f'"{v}"' for v in vals)
        elif rng is not None and onto.value(rng, OWL.onDatatype) is not None:
            base = local(onto.value(rng, OWL.onDatatype))
            rng_label = f"xsd:{base} in [0, 1]"
        else:
            rng_label = "-"
        func = "functional" if (prop, RDF.type, OWL.FunctionalProperty) in onto else ""
        out.append(f"| `{local(prop)}` | {local(dom) if dom else '(any)'} "
                   f"| {rng_label} | {func} |")
    return out


def figure4(data: Graph) -> list[str]:
    """Teaching lineage actually present in the dataset."""
    out = ["```mermaid", "graph BT"]
    for pupil, teacher in sorted(data.subject_objects(P.studiedUnder), key=str):
        out.append(f"    {local(pupil)} -- studiedUnder --> {local(teacher)}")
    out.append("```")
    return out


def figure5(data: Graph) -> list[str]:
    """Engagement network, with each EDGE coloured by its stance.

    The stance belongs to the engagement, not to either work: the same work
    can praise one text and criticise another, and :WorldAsWill does both to
    the same target. Colouring nodes would therefore be wrong, so the link
    style is applied per edge in the order the edges are declared.
    """
    style = {"criticizes": "stroke:#c66,stroke-width:2px",
             "praises": "stroke:#6c6,stroke-width:2px",
             "neutral": "stroke:#999,stroke-width:1px,stroke-dasharray:4 3"}

    engagements = sorted(set(data.subjects(RDF.type, P.Engagement)), key=str)
    out = ["```mermaid", "graph LR"]
    stances = []
    for eng in engagements:
        src = data.value(eng, P.fromWork)
        dst = data.value(eng, P.toWork)
        stance = str(data.value(eng, P.stance))
        concept = data.value(eng, P.aboutConcept)
        stances.append(stance)
        out.append(f'    {local(src)} -- "{local(eng)}: {stance}'
                   f'<br/>({local(concept)})" --> {local(dst)}')
    out.append("")
    for index, stance in enumerate(stances):
        out.append(f"    linkStyle {index} {style[stance]};")
    out.append("```")
    return out


HEADER = """\
# Ontology diagrams

**Generated file** - produced by `make_diagrams.py` directly from
`philosophy_ontology.ttl` and `philosophy_dataset.ttl`. Do not edit by hand;
re-run the script after changing the ontology so the figures cannot drift out
of step with the axioms.

The diagrams are Mermaid, which GitHub, VS Code and Typora render natively. For
the report, export each one as PNG/SVG (VS Code: *Markdown: Open Preview*, then
right-click the diagram). WebVOWL (`webvowl.visualdataweb.org`) and Protege's
OntoGraf tab will also read `philosophy_complete.ttl` directly if an
automatically laid-out VOWL diagram is preferred.
"""


def main() -> None:
    onto, data = load()
    parts = [HEADER]

    parts.append("\n## Figure 1 - Class hierarchy\n")
    parts.append("Rectangles are asserted classes; slanted boxes are **defined** "
                 "classes whose members the reasoner infers from an "
                 "`owl:equivalentClass` axiom.\n")
    parts += figure1(onto)

    parts.append("\n## Figure 2 - Object property map\n")
    parts.append("Each edge is an object property, drawn from its `rdfs:domain` "
                 "to its `rdfs:range`. `belongsToSchool` has a union domain, so "
                 "it appears twice.\n")
    parts += figure2(onto)

    parts.append("\n## Figure 3 - Datatype properties\n")
    parts += figure3(onto)

    parts.append("\n## Figure 4 - Teaching lineage in the dataset\n")
    parts.append("The 11 asserted `studiedUnder` links. The transitive "
                 "super-property `hasTeachingAncestor` closes these into 19 "
                 "ancestor pairs.\n")
    parts += figure4(data)

    parts.append("\n## Figure 5 - Engagement network\n")
    parts.append("The 10 recorded engagements. Red = criticizes, green = "
                 "praises, grey = neutral. Note the double edge from *The World "
                 "as Will* to the *Critique*: praise on one concept, criticism "
                 "on another. This is why `:criticizes` and `:praises` are not "
                 "declared disjoint.\n")
    parts += figure5(data)

    out = "\n".join(parts) + "\n"
    (HERE / "DIAGRAMS.md").write_text(out, encoding="utf-8")
    print(f"wrote DIAGRAMS.md ({len(out.splitlines())} lines)")


if __name__ == "__main__":
    main()
