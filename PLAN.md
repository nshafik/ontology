# ISM601 Ontology Project — Evaluation and Remediation Plan

> **STATUS (2026-11-21): the ontology-layer plan is COMPLETE.**
> Tasks T1–T9 and T15–T16 are implemented and verified; `python3 build.py` reports
> **ALL CHECKS PASSED** (SHACL, HermiT, OWL-RL, 19/19 query checks).
> See `REPORT.md` §6 for the evidence and `COMPLETED.md` for the task-by-task summary.
>
> **Not done, by instruction:** the application layer (T10–T14 — Fuseki deployment,
> Python agent, web interface, visualisation, LLM comparison). Those remain the
> largest outstanding block of marks; see §Part 2, P2 below.

---

Date: 2026-11-21
Scope: `philosophy_ontology.ttl`, `philosophy_dataset.ttl`, `philosophy_shapes.ttl`,
`philosophy_complete.ttl`, `philosophy_sparql_queries.md`, assessed against the
ISM601 rubric, the design brief (`input.txt`), and the Week-9 / SEM603 lecture content.

Everything in Part 1 was *executed*, not read. Tooling used: rdflib 7.6.0,
pyshacl 0.40.2, owlrl 7.6.2, owlready2 0.51 + HermiT (Java), live Wikidata SPARQL endpoint.

---

## Part 1 — Verified findings

### 1.1 What already works (confirmed by execution)

| Check | Command / method | Result |
|---|---|---|
| Turtle syntax, all 4 files | `rdflib.Graph.parse` | PASS — 332 / 535 / 124 / 867 triples |
| Ontology + dataset merge | rdflib | 867 triples (brief asks for 300+) |
| SHACL validation | `pyshacl -s shapes -e ontology -i rdfs dataset` | **Conforms: True** |
| OWL-RL closure | owlrl `OWLRL_Semantics` | 867 → 2412 triples |
| All 15 competency questions | rdflib SPARQL | all execute, all match the documented "Expected result" tables |
| R1 CONSTRUCT rules | rdflib | 6 `criticizes`, 3 `praises` — exactly as documented |
| R2 probe | rdflib | 10 philosophers with no school — as documented |

Counts match the brief exactly: 14 asserted + 4 defined classes (18 named `owl:Class`),
21 object properties (20 + inverse `authored`), 9 datatype properties.

Inference actually produced (OWL-RL closure):

| Inferred | Count |
|---|---|
| `hasTeachingAncestor` | 19 |
| `influencedBy` | 28 (17 asserted) |
| `isWithinSchool` | 26 |
| `authored` | 30 |
| `createdInLineageOf` | 27 |
| `createdIn` (incl. country level) | 20 (10 asserted) |
| `StudentThinker` / `TeacherThinker` / `InfluencerThinker` / `CriticizedWork` | 11 / 10 / 18 / 5 |

That clears the brief's "at least 10 inferred properties" target. The CQ document's
status line ("have **not yet been executed on a SPARQL engine**") is now obsolete.

### 1.2 BLOCKER — the ontology does not load in HermiT

This is the single most damaging finding, because the brief itself (Section 10) promises
"Protégé with HermiT will test reasoning and it will be checked again with Pellet".

```
org.semanticweb.HermiT.datatypes.UnsupportedDatatypeException:
The datatype 'http://www.w3.org/2001/XMLSchema#gYear' is not part of the
OWL 2 datatype map ... therefore, HermiT cannot handle this datatype.
```

`xsd:gYear` is **not in the OWL 2 datatype map**. Any marker opening
`philosophy_complete.ttl` in Protégé and pressing "Start reasoner" gets an exception,
not a classification. Pellet behaves the same way for the same reason.

Verified fix: replacing `xsd:gYear` with `xsd:int` (or `xsd:integer`) everywhere →
**HermiT: CONSISTENT, 0 unsatisfiable classes, 18 classes, 109 individuals**, and the
four defined classes classify correctly (11 / 10 / 18 / 5 — identical to the OWL-RL result).
SHACL still conforms after the same substitution.

This also removes the `xsd:integer(STR(?y))` casting hack that currently pollutes five
SHACL SPARQL constraints and the date-comparison queries.

### 1.3 Second ordering issue — no `owl:NamedIndividual`, no `owl:AllDifferent`

No individual is declared `owl:NamedIndividual` and nothing is asserted distinct.
Consequences measured, not guessed:

- With individuals declared but *not* distinct, a `minQualifiedCardinality 3` test class
  (`ProlificPhilosopher`) returned **1** member.
- After adding `owl:AllDifferent` over all 109 individuals, it returned **2**.

Under OWL's no-unique-name assumption the reasoner may collapse individuals, so every
cardinality-based inference is currently unreliable. The Week-9 deck teaches exactly this
pattern (`owl:AllDifferent` / `owl:distinctMembers` in the StringInstruments example).

### 1.4 OWL construct coverage versus what the lectures taught

Audit of `philosophy_ontology.ttl`:

| Construct | Used | Taught in deck |
|---|---|---|
| `someValuesFrom` | 4 | Example #3 |
| `intersectionOf` | 5 | Example #1 |
| `unionOf` | 1 | — |
| `hasValue` | 1 | Example #5 |
| `oneOf` | 1 | Example #2 |
| `propertyChainAxiom` | 2 | — |
| `disjointWith` | 9 | — |
| `FunctionalProperty` | 10 | — |
| `TransitiveProperty` / `Asymmetric` / `Irreflexive` | 3 / 2 / 3 | — |
| `inverseOf` | 4 | — |
| **`allValuesFrom`** | **0** | **Example #1, Example #4** |
| **`complementOf`** | **0** | **Example #1** |
| **`hasSelf`** | **0** | **Example #6** |
| **`NamedIndividual`** | **0** | **Example #2** |
| **`AllDifferent`** | **0** | **Example #2** |
| cardinality / qualified cardinality | 0 | — |
| `hasKey`, `AllDisjointClasses`, `propertyDisjointWith` | 0 | — |

The five bolded rows are constructs the module explicitly walked through line-by-line in
both Turtle and RDF/XML. Their absence is the most visible "did not engage with the
course material" signal to a marker, and it maps directly onto the
**OWL Constructs Usage** rubric row ("sophisticated use of OWL constructs
(property characteristics, class expressions)").

I built and reasoned over an enriched version to prove the additions are safe:
`UncriticizedWork` (allValuesFrom + complementOf), `ProlificPhilosopher`
(minQualifiedCardinality), `Criticism` (hasValue), `SelfReferentialWork` (hasSelf),
exact qualified cardinality on `Engagement`, `hasKey` on `Philosopher`,
`AllDisjointClasses`, `propertyDisjointWith`. Result: **HermiT CONSISTENT,
no unsatisfiable classes.**

### 1.5 Disjointness is weaker than the brief claims

The brief (Figure 2 notes and Section 9) states: "Philosopher, Work, Engagement, Concept,
SchoolOfThought, Location and TimePeriod are **pairwise** disjoint."

The ontology asserts only three pairs: `Work ⊥ Philosopher`, `Location ⊥ TimePeriod`,
`Country ⊥ City`, plus `Reader ⊥ {6 classes}`. Missing pairs include
`Engagement ⊥ Concept`, `Concept ⊥ SchoolOfThought`, `Work ⊥ Engagement`, and so on.

Tested: asserting the full `owl:AllDisjointClasses` over all seven classes keeps the
dataset **consistent** under HermiT. There is no reason not to do it, and the document
currently over-claims relative to the code — a direct hit on
"Ontology Design and Modeling / Justified design decisions with evidence".

### 1.6 Zero Linked-Data interlinking — contradicts the brief and Lecture 9

- External vocabulary IRIs used in the ontology: **NONE**.
- `owl:sameAs`: 0. `rdfs:seeAlso`: 0. `owl:imports`: 0. No SKOS, no Dublin Core,
  no FOAF, no CIDOC-CRM.
- `externalId` is a bare `xsd:string` ("Q859"), not a dereferenceable HTTP URI.

Week 9 is entirely about Linked Open Data and spends four slides on Principle 4
("Include links to other URIs… Relationship Links / Identity Links / Vocabulary Links").
The brief's own Section 2 names cross-vocabulary alignment (CIDOC-CRM, Wikidata) as the
"failure addressed secondary". The current artefacts do not do this at all.

### 1.7 Data errors found by live Wikidata cross-check

Queried `query.wikidata.org` for the 10 asserted `externalId` values:

| Issue | Detail |
|---|---|
| **`:Heidegger :externalId "Q8253"` is wrong** | Q8253 is the entity **"fiction"**. Martin Heidegger is **Q48301**. |
| `:Aristotle` birth/death | asserted -384/-322; Wikidata gives -383/-321 |
| `:Socrates` birth/death | asserted -470/-399; Wikidata gives -469/-398 |

Q859, Q868, Q913, Q9191, Q9235, Q9312, Q9358, Q9391, Q37160 all resolve correctly.

### 1.8 Internal data-quality issues (SPARQL probes)

| Probe | Result |
|---|---|
| Work created outside author's lifetime | **1 hit — "Philosophical Investigations" (1953) vs Wittgenstein d. 1951.** Posthumous, so factually right, but no modelling distinguishes it and no shape catches it. |
| Philosophers with no work | 9 (Socrates, Zeno, Augustine, Albertus Magnus, Thomasius, Berkeley, Knutzen, Kierkegaard, Brentano) |
| Works with no `createdIn` | 20 of 30 |
| `:Zarathustra` | typed as bare `:Work`, not one of the four subclasses |
| Concepts unused in engagements | 0 (clean) |
| `creationYear` outside `composedDuring` | 0 (clean) |

Asserted-usage audit — properties declared but never instantiated in the dataset:
`authored`, `createdInLineageOf`, `hasTeachingAncestor`, `isWithinSchool`, `references`,
`criticizes`, `praises`. That is *correct by design* (they are inference-only), but it
must be stated in the report or a marker will read it as dead vocabulary.

### 1.9 Deliverables that do not exist

Against the brief's own Section 5 timeline:

| Week | Required output | Status |
|---|---|---|
| 5 | Diagram + final documentation (Deliverable 1) | **MISSING** — no diagram file |
| 9 | Python reasoning agent, recommendation logic, **web interface** | **MISSING** |
| 10 | LLM integration (NL → SPARQL), baseline comparison on 15+ questions | **MISSING** |
| 11 | Report, two presentations, packaged files | **MISSING** |
| — | Scholarly references / bibliography | **MISSING** — no citation anywhere in any file |

### 1.10 Rubric position as of today

| Rubric row | Current | Why |
|---|---|---|
| Clarity & Scope | A | Scope and boundaries are explicit in the brief |
| Understanding of Core Concepts | B | Strong, but gYear blocker and OWA/CWA handling is asserted rather than demonstrated |
| **Research Depth and References** | **D/F** | **Zero citations in any artefact** |
| **OWL Constructs Usage** | **C** | No allValuesFrom / complementOf / cardinality / hasSelf / hasKey |
| Ontology Design and Modeling | B | Consistent and well structured, but disjointness under-asserted vs. the documentation |
| **Implementation of RDF/OWL** | **C** | **"validates successfully in standard tools" fails — HermiT rejects it** |
| Query Correctness | A | All 15 verified against expected results |
| Query Complexity & Efficiency | A | FILTER, OPTIONAL, UNION, property paths, aggregates, NOT EXISTS all present |
| Result Presentation | A | Expected-result tables, ORDER BY throughout |
| SPARQL Query Design and Execution | A | Good coverage of SELECT/CONSTRUCT/ASK/DESCRIBE |
| Use of Reasoning | B | Chains and defined classes are real, but unusable in the named reasoner |
| **Integration and Application (web interface)** | **F** | **Nothing exists** |
| **Application (Integration)** | **F** | **Nothing exists** |
| **Application (demonstration)** | **F** | **Nothing exists** |
| **Application (Visualisation)** | **F** | **Nothing exists** |
| Clarity of Documentation | B | Query doc is excellent; no overall report |
| Presentation and Documentation | D | No report, no diagrams |

**Blunt summary: the ontology-and-query half is A-grade work. Roughly 6 of 17 rubric
rows — about 35% of the mark, concentrated in Application and References — currently
score zero, and one row (Implementation of RDF/OWL) fails its explicit "validates in
standard tools" test.** The highest marginal return is not more ontology work.

---

## Part 2 — Remediation plan

Ordered by marks-per-hour. P0 items are cheap and unblock rubric rows that currently fail.

### P0 — Make it validate in the named tools (half a day)

**T1. Replace `xsd:gYear` with `xsd:int` across all four TTL files.**
Affects `creationYear`, `birthYear`, `deathYear`, `startYear`, `endYear` ranges and all
~95 literals. Verified: HermiT consistent, SHACL conforms, all 15 CQs unaffected.
Then delete the `xsd:integer(STR(?x))` casts from the five SHACL SPARQL constraints
— they become plain `?x < ?y` comparisons.
Add a one-line `rdfs:comment` on each year property recording the BCE-as-negative convention.

**T2. Declare every individual `owl:NamedIndividual` and add `owl:AllDifferent`.**
109 individuals. Script it with rdflib. Required for any cardinality inference to be sound,
and both constructs were taught in the deck.

**T3. Assert the full pairwise disjointness the documentation already claims.**
One `owl:AllDisjointClasses` axiom over Philosopher, Work, Engagement, Concept,
SchoolOfThought, Location, TimePeriod. Verified consistent.

**T4. Fix the data errors.** `:Heidegger :externalId "Q48301"` (not Q8253). Decide and
document a single policy for the Aristotle/Socrates date discrepancies — either adopt
Wikidata's values or add a provenance note explaining the divergence. Type `:Zarathustra`
as `:Treatise` (or add a `:PhilosophicalNovel` subclass).

**T5. Update the status line in `philosophy_sparql_queries.md`.** Replace "have not yet
been executed on a SPARQL engine" with the actual execution evidence and engine version.
Also resolve the two open "confirm this with your partner" notes in CQ8 and CQ9 by stating
the operational definitions of "master" and "impact" in the report.

### P1 — Close the OWL-construct gap (one day)

**T6. Add the course-taught constructs that are missing.** All already proven consistent:

- `:UncriticizedWork` — `allValuesFrom` + `complementOf`. This mirrors the deck's
  `AvailableBook` example *exactly* and is pedagogically the strongest single addition.
  It currently infers **0** members under OWA — use that as a deliberate, documented
  demonstration of the open-world assumption, then add closure axioms for a handful of
  works to show the contrast.
- `:ProlificPhilosopher` — `minQualifiedCardinality 3` on `authored`. Requires T2;
  with `AllDifferent` it infers 2 members, without it 1. Document that delta — it is
  concrete evidence of understanding the no-unique-name assumption.
- `:Criticism` — `hasValue "criticizes"` on `stance` (mirrors `FirstClassPassengers`).
- `:SelfReferentialWork` — `hasSelf` on `references` (mirrors `SelfEvaluator`).
- Exact qualified cardinality `= 1` on `Engagement.fromWork` / `toWork`, to back the
  "exactly one" claim in Section 9 with an OWL axiom rather than only a SHACL shape.
- `owl:hasKey ( :externalId )` on `:Philosopher` — the natural-key / entity-matching story
  the brief promises in Section 2.
- `owl:propertyDisjointWith` between `:studiedUnder` and `:hasRead`.

**T7. Document each new axiom in both Turtle and RDF/XML.** The lecture deck presents every
example in both serialisations with a line-by-line breakdown. Mirroring that format in the
report is the cheapest way to hit "integrates theoretical and practical perspectives".

### P1 — Linked Open Data (half a day)

**T8. Interlink the graph.** Directly addresses Week 9 and the brief's secondary failure case:

- `owl:sameAs` from each philosopher to `http://www.wikidata.org/entity/Q…` and
  `http://dbpedia.org/resource/…` (identity links).
- Reuse external vocabulary instead of minting everything: `dcterms:title` alongside
  `:title`, `skos:prefLabel` / `skos:broader` on `SchoolOfThought` and `Concept`,
  `foaf:Person` as a superclass of `Philosopher`, and alignment notes to CIDOC-CRM
  (`crm:E73_Information_Object` ≈ `:Work`, `crm:E21_Person` ≈ `:Philosopher`).
- Replace the opaque `externalId` string with (or add alongside it) a dereferenceable
  HTTP URI, per Linked Data Principle 2.
- Add `owl:versionIRI` and a licence statement.

This one task moves **Research Depth**, **Understanding of Core Concepts**, and
**Ontology Design** simultaneously, and it is the clearest demonstration that the
Week-9 material was absorbed.

### P1 — References (half a day)

**T9. Write the bibliography and cite it inline.** Currently the weakest row and the
easiest to fix. Minimum set: Hitzler et al. *Foundations of Semantic Web Technologies*
(the module's own reference), Noy & McGuinness *Ontology Development 101*,
Gruber (1993), the W3C OWL 2 Primer and SPARQL 1.1 specs, SHACL spec, the CIDOC-CRM
specification, Doerr on CIDOC-CRM, Horridge & Bechhofer on OWL API / Protégé, and at
least two papers on philosophy/digital-humanities knowledge graphs for the comparison
of approaches. Cite them where design decisions are justified, not in a dangling list —
the rubric says "uses scholarly references to **justify methods and compare approaches**".

### P2 — The application layer (the biggest missing block, 3–5 days)

Four rubric rows currently score zero. Nothing here needs to be elaborate.

**T10. Triplestore.** Load into Apache Jena Fuseki (named in the brief). Script the load
so it is reproducible. Run the 15 CQs against the HTTP endpoint and capture the output —
this is the evidence for "validates successfully in standard tools".

**T11. Python reasoning agent + recommendation logic.** The brief already specifies it:
run the R1 CONSTRUCT rules to materialise `criticizes`/`praises`, run CQ12/CQ13, then score
candidates by `confidenceScore` × interest overlap and rank. Keep it small and tested.

**T12. Web interface for ontology browsing.** Flask or FastAPI + a single page is enough
for the rubric's "Web-based interface for ontology browsing":
- entity pages for Philosopher / Work / School driven by DESCRIBE (CQ15),
- a CQ picker that runs the stored queries and renders the result table,
- a reader page showing recommendations with their explanation (CQ13).

**T13. Visualisation.** The rubric has a dedicated row. Minimum viable set:
- the teaching-lineage graph (`studiedUnder+`) and the school hierarchy
  (`subSchoolOf+`) as interactive node-link diagrams (vis.js / Cytoscape.js / pyvis),
- the engagement network coloured by stance,
- a timeline of works by `creationYear`,
- a bar chart of the CQ9 impact scores.

**T14. LLM / NL-to-SPARQL layer and baseline comparison** (brief week 10). Optional for a
pass but it is the "innovation" the Application rows reward. The CQ document's closing
"Evidence-path summary" section is already written as the gold standard for exactly this
evaluation — the groundwork is done, only the harness is missing.

### P2 — Report and diagrams (2–3 days)

**T15. Ontology diagrams.** Export from WebVOWL or Protégé OntoGraf: the class hierarchy
(Figure 1 in the brief) and the object-property map (Figure 2). Both figures are referenced
by the brief and neither exists as a file.

**T16. The report.** Follow the brief's existing Part 1 / Part 2 structure, but add what is
currently absent: a validation chapter with the actual tool output (HermiT classification,
pyshacl report, inferred-triple counts before/after), a design-decisions chapter that
justifies each choice against a cited source, and a limitations chapter. The brief's English
needs a careful editing pass — several sentences in Sections 1, 2 and 9 are ungrammatical
or unclear, and "Presentation and Documentation" is an explicit rubric row.

**T17. Two presentations** per the week-11 timeline.

### Suggested order

```
Day 1      T1 T2 T3 T4 T5          -> HermiT and Pellet classify cleanly
Day 2      T6 T7                   -> OWL Constructs row moves C -> A
Day 3      T8 T9                   -> LOD interlinking + references
Day 4-5    T10 T11                 -> Fuseki endpoint + Python agent
Day 6-8    T12 T13                 -> web UI + visualisation (4 zero rows)
Day 9      T14                     -> LLM comparison (innovation marks)
Day 10-12  T15 T16 T17             -> diagrams, report, presentations
```

### Regression gate

After every change, all of the following must stay green:

```bash
python3 -c "from rdflib import Graph; [Graph().parse(f) for f in \
  ['philosophy_ontology.ttl','philosophy_dataset.ttl','philosophy_shapes.ttl','philosophy_complete.ttl']]"

python3 -m pyshacl -s philosophy_shapes.ttl -e philosophy_ontology.ttl \
                   -i rdfs -f human philosophy_dataset.ttl        # Conforms: True

# HermiT via owlready2 (after converting to RDF/XML) -> CONSISTENT, 0 unsatisfiable
# all 15 CQs -> row counts unchanged vs. the Expected tables
```

`philosophy_complete.ttl` is a concatenation of the ontology and dataset files and must be
regenerated from them after every edit — editing it by hand will desynchronise the sources.
Consider generating it in a build script rather than maintaining it as a fourth file.
