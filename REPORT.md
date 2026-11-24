# Philosophy and Intellectual History Curation Ontology

**ISM601 — Introduction to Web Science, 2026/27**
Part 2: Ontology Documentation and Validation Report

---

## Contents

1. [Scope and purpose](#1-scope-and-purpose)
2. [Artefacts](#2-artefacts)
3. [Class design](#3-class-design)
4. [Property design](#4-property-design)
5. [Constraints and design decisions](#5-constraints-and-design-decisions)
6. [Validation and reasoning evidence](#6-validation-and-reasoning-evidence)
7. [Linked Open Data](#7-linked-open-data)
8. [Data provenance and quality](#8-data-provenance-and-quality)
9. [Competency questions](#9-competency-questions)
10. [Application layer](#10-application-layer)
11. [Natural language to SPARQL](#11-natural-language-to-sparql)
12. [Limitations](#12-limitations)
13. [References](#13-references)

---

## 1. Scope and purpose

The ontology models philosophers, the works they wrote, the schools of thought they
belonged to, and — centrally — the **engagements** through which one work criticises,
praises or neutrally discusses another in relation to a named concept.

The domain was chosen because its interesting content is *relational*. A flat table can
record that Kant wrote the *Critique of Pure Reason* in 1781; it cannot easily answer
"which works were written by someone in Plato's teaching line?" or "recommend an unread
work to this reader, and explain why". Those require traversal and inference, which is
what an ontology provides.

**Target users.** Students and researchers in philosophy and digital humanities who need
linked data to discover material and trace intellectual lineage.

**In scope.** Works, authorship, schools and sub-schools, concepts, engagements between
works, time periods, places, readers and their interests.

**Out of scope.** Full text of works, the internal structure of arguments, and
non-philosophical authors.

This scoping follows the competency-question method of Grüninger and Fox [6] and the
"determine the domain and scope" first step of Noy and McGuinness [10]: the fifteen
competency questions in §9 were written *before* the classes, and every class and
property in the ontology exists because at least one of them needs it.

---

## 2. Artefacts

| File | Role | Triples |
|---|---|---|
| `philosophy_ontology.ttl` | TBox: classes, properties, axioms | 419 |
| `philosophy_dataset.ttl` | ABox: 109 individuals | 885 |
| `philosophy_links.ttl` | Linked Open Data: `owl:sameAs`, vocabulary alignment | 226 |
| `philosophy_shapes.ttl` | SHACL shapes for data validation | 124 |
| `philosophy_complete.ttl` | **Generated** bundle for Protégé (ontology + dataset) | 1,304 |
| `philosophy_sparql_queries.md` | CQ1–CQ15 with verified expected results | — |
| `OWL_CONSTRUCTS.md` | Every OWL construct in Turtle **and** RDF/XML | — |
| `DIAGRAMS.md` | **Generated** figures 1–5 | — |
| `build.py` | Build + full regression gate (5 checks) | — |
| `make_diagrams.py` | Regenerates `DIAGRAMS.md` from the Turtle | — |
| `app/fuseki.py` | Start Fuseki, load both graphs, verify | — |
| `app/queries.py` | The 15 CQs as data: one source of truth | — |
| `app/run_cqs.py` | Execute every CQ against the live endpoint | — |
| `app/agent.py` | Rule materialisation, recommendation, lineage | — |
| `app/server.py` | Web interface and visualisation APIs | — |
| `app/llm_sparql.py` | NL→SPARQL with a measured baseline comparison | — |
| `FUSEKI_RESULTS.md` | **Generated** 18/18 endpoint evidence | — |
| `LLM_EVALUATION.md` | **Generated** LLM vs baseline results | — |

`philosophy_complete.ttl` and `DIAGRAMS.md` are generated. Editing them by hand would let
them drift from the sources, so `build.py --check` fails the build if the bundle is stale.

**Why `philosophy_links.ttl` is not in the bundle.** `owl:sameAs` makes a local
individual, its Wikidata item and its DBpedia resource one and the same thing, so a
reasoner replicates every inference across all three IRIs. Measured here: including the
links takes the OWL-RL closure from 3,490 to 120,645 triples and reports `StudentThinker`
as 33 members rather than 11 — the same 11 philosophers counted once per coreferent IRI.
Publishing identity links as a separate graph is standard practice [7, §4.4].

### Reproducing the validation

```bash
pip install rdflib pyshacl owlrl owlready2     # Java required for HermiT
python3 build.py
```

---

## 3. Class design

22 named classes: **14 asserted** and **8 defined** (members inferred by the reasoner).
See `DIAGRAMS.md` Figure 1.

### Asserted classes

| Class | Parent | Description |
|---|---|---|
| `Work` | `owl:Thing` | An intellectual creation, such as a book or essay |
| `Treatise` | `Work` | A systematic philosophical exposition |
| `Dialogue` | `Work` | A work written as a dialogue |
| `Commentary` | `Work` | A work that interprets or discusses another work |
| `Essay` | `Work` | A focused philosophical text |
| `Philosopher` | `owl:Thing` | A thinker who writes works or teaches |
| `Engagement` | `owl:Thing` | A recorded relation in which one work engages another about a concept, with a stance |
| `Concept` | `owl:Thing` | A philosophical concept or thesis |
| `SchoolOfThought` | `owl:Thing` | A tradition or school, which may have sub-schools |
| `Location` | `owl:Thing` | A place with a position in a place hierarchy |
| `Country` | `Location` | A country |
| `City` | `Location` | A city, located in a country |
| `TimePeriod` | `owl:Thing` | A span of years |
| `Reader` | `owl:Thing` | A user with interests and a reading history |

### Defined classes

Each is an `owl:equivalentClass` axiom, so membership is **inferred**, never asserted.
The member counts are what HermiT actually computes.

| Class | Definition | Members |
|---|---|---|
| `StudentThinker` | `Philosopher ⊓ ∃studiedUnder.Philosopher` | 11 |
| `TeacherThinker` | `Philosopher ⊓ ∃studiedUnder⁻.Philosopher` | 10 |
| `InfluencerThinker` | `Philosopher ⊓ ∃influencedBy⁻.Philosopher` | 18 |
| `CriticizedWork` | `Work ⊓ ∃toWork⁻.(Engagement ⊓ ∃stance.{"criticizes"})` | 5 |
| `ProlificPhilosopher` | `Philosopher ⊓ ≥3 authored.Work` | 2 |
| `Criticism` | `Engagement ⊓ ∃stance.{"criticizes"}` | 6 |
| `UncriticizedWork` | `Work ⊓ ∀toWork⁻.¬(∃stance.{"criticizes"})` | 0 |
| `SelfReferentialWork` | `∃references.Self` | 0 |

The two empty classes are empty **by design** and are discussed in §6.5 and §10.

### The reification decision

`Engagement` is the central modelling choice. The naive alternative is a direct property
`:criticizes` between works. That cannot carry the *concept* the criticism is about, nor a
confidence score, and it cannot represent the fact that Schopenhauer's *World as Will*
**both praises and criticises** Kant's *Critique* — praising transcendental idealism while
attacking the categories.

Reifying the relation as a class with its own properties (`fromWork`, `toWork`,
`aboutConcept`, `stance`, `confidenceScore`) solves all three problems. It is the n-ary
relation pattern recommended by the W3C Working Group Note on n-ary relations [12], and
it mirrors how CIDOC-CRM models events as first-class entities [3].

The convenience shortcuts `:criticizes` and `:praises` are *derived from* engagements by
SPARQL `CONSTRUCT` (rule R1 in the query collection), not by OWL — see §5.4.

---

## 4. Property design

21 object properties and 9 datatype properties. See `DIAGRAMS.md` Figures 2 and 3.
Property names are chosen to read as sentences (`belongsToSchool`, `studiedUnder`), as
recommended in [10, §4].

### The simple/non-simple property split

The most important structural decision. OWL 2 DL classifies a transitive property as
**non-simple**, and forbids declaring a non-simple property asymmetric or irreflexive —
permitting it would make reasoning undecidable [9, §11].

`studiedUnder` genuinely *is* asymmetric and irreflexive (nobody is their own teacher),
and we also want its transitive closure for lineage queries. Both at once is illegal, so
the relation is split:

| Direct (simple) | Transitive super-property | Asserted → inferred |
|---|---|---|
| `studiedUnder` (asymmetric, irreflexive) | `hasTeachingAncestor` | 11 → 19 |
| `subSchoolOf` (asymmetric, irreflexive) | `isWithinSchool` | 15 → 26 |

Asserting `studiedUnder` yields `hasTeachingAncestor` by sub-property inference, and
transitivity then closes the chain. The direct property keeps its characteristics; the
super-property does the reasoning.

`influencedBy` is deliberately **not** transitive. Influence attenuates along a chain, and
a transitive reading would assert that Socrates directly influenced every later
philosopher in the graph — technically consistent, but substantively false.

### Property chains

| Property | Chain | Asserted → inferred |
|---|---|---|
| `createdInLineageOf` | `createdBy ∘ hasTeachingAncestor` | 0 → 27 |
| `createdIn` | `createdIn ∘ locatedIn` | 10 → 20 |

The first answers "works by anyone in X's teaching line" with no stored triples at all.
The second propagates a work's location up the place hierarchy, so a work created in
Athens is also a work created in Greece — which is what makes country-level
recommendation possible.

### Union domain

`belongsToSchool` applies to both works and philosophers, expressed as a **single** domain
axiom over a union:

```turtle
rdfs:domain [ a owl:Class ; owl:unionOf ( :Work :Philosopher ) ]
```

Two separate `rdfs:domain` axioms would be a modelling error: RDFS domain axioms are
*conjunctive*, so the reasoner would infer that every subject is **both** a Work and a
Philosopher — and since those two classes are disjoint, the ontology would become
inconsistent. This is a classic beginner trap [1, §5].

---

## 5. Constraints and design decisions

### 5.1 Disjointness

The seven top-level categories are **pairwise disjoint**, stated with the OWL 2 n-ary
form, which is equivalent to 21 separate `owl:disjointWith` axioms:

```turtle
[] a owl:AllDisjointClasses ;
   owl:members ( :Philosopher :Work :Engagement :Concept
                 :SchoolOfThought :Location :TimePeriod ) .
```

`Reader` is the deliberate exception: disjoint from the other six, but **not** from
`Philosopher`, because philosophers read each other's work. `:Russell` is asserted as both.

`Treatise`, `Dialogue`, `Commentary` and `Essay` are intentionally **not** disjoint: a text
can reasonably be read as more than one genre.

### 5.2 Cardinality, and why SHACL is still needed

`owl:FunctionalProperty` gives "at most one". The brief claims each `Engagement` has
*exactly* one source, target and concept, so qualified exact-cardinality axioms state
the stronger claim.

This does **not** make the SHACL shapes redundant. Under the **open-world assumption** OWL
will never report a *missing* `fromWork`; it simply assumes one exists that has not been
written down. Only a closed-world language can fail validation for an absent value, which
is precisely what SHACL [8] is for. The two are complementary:

| Requirement | Mechanism | Why |
|---|---|---|
| At most one source work | OWL functional + qualified cardinality | expressible in DL |
| **At least** one source work | SHACL `sh:minCount 1` | OWA: OWL cannot detect absence |
| `stance` ∈ {praises, criticizes, neutral} | OWL `owl:oneOf` datatype | a 4th value makes the ontology *inconsistent* |
| `deathYear ≥ birthYear` | SHACL SPARQL constraint | OWL cannot compare two literal values |
| No cycle in `studiedUnder` | SHACL `$this :studiedUnder+ $this` | needs negation-as-failure |
| Works a reader has **not** read | SPARQL `FILTER NOT EXISTS` | OWA again |

This division of labour follows the guidance in the SHACL specification [8] and the
treatment of OWA versus CWA in Hitzler et al. [1, §4.3].

### 5.3 No unique-name assumption

OWL makes **no unique-name assumption**: absent an explicit statement, two differently
named individuals may be the same thing. All 109 individuals are therefore declared
`owl:NamedIndividual` and asserted pairwise distinct with `owl:AllDifferent`.

This is not decorative. Measured on this ontology, `ProlificPhilosopher` (`≥3 authored`)
classifies **1 member without** the `AllDifferent` axiom and **2 with** it: without it the
reasoner may identify `:Republic`, `:Phaedo` and `:Meno` with one another, leaving Plato
one work instead of three. Every cardinality-based inference depends on it.

### 5.4 What is deliberately *not* OWL

| Requirement | Handled by | Reason |
|---|---|---|
| `criticizes` / `praises` shortcuts | SPARQL `CONSTRUCT` (R1) | needs to branch on a *literal value*; not an OWL axiom |
| "not yet read" | SPARQL `FILTER NOT EXISTS` | negation-as-failure, closed-world |
| Year comparisons | SHACL SPARQL constraints | OWL cannot order two literals |
| Recommendation ranking | application code | arithmetic scoring |

Being explicit about the boundary matters more than maximising OWL usage. Each row is a
case where OWL is the *wrong* tool, not a case where the modelling fell short.

---

## 6. Validation and reasoning evidence

Everything below is **executed output**, reproducible with `python3 build.py`.

Tooling: RDFLib 7.6.0, pyshacl 0.40.2, owlrl 7.6.2, owlready2 0.51, HermiT (via
owlready2), Python 3.10. Last full run: 2026-11-21.

### 6.1 Syntax and SHACL

```
[1] Parsing sources
  philosophy_ontology.ttl      OK   419 triples
  philosophy_dataset.ttl       OK   885 triples
  philosophy_shapes.ttl        OK   124 triples

[3] SHACL validation (pyshacl)
  Conforms: True
```

### 6.2 HermiT: consistency and classification

```
[4] OWL 2 DL reasoning (HermiT)
  loaded 22 classes, 109 individuals
  HermiT: CONSISTENT, 0 unsatisfiable classes
      StudentThinker          11 members
      TeacherThinker          10 members
      InfluencerThinker       18 members
      CriticizedWork           5 members
      ProlificPhilosopher      2 members
      Criticism                6 members
      UncriticizedWork         0 members
      SelfReferentialWork      0 members
```

#### The `xsd:gYear` blocker

An earlier revision typed every year as `xsd:gYear`. HermiT refused to load it at all:

```
org.semanticweb.HermiT.datatypes.UnsupportedDatatypeException:
The datatype 'http://www.w3.org/2001/XMLSchema#gYear' is not part of the
OWL 2 datatype map ... therefore, HermiT cannot handle this datatype.
```

`xsd:gYear` is **not in the OWL 2 datatype map** [9, §4]. Pellet fails identically. The
ontology could not be classified in Protégé at all — pressing *Start reasoner* produced a
stack trace rather than an inference.

All years are now `xsd:int`, with BCE as a negative number. The fix removed a second
problem for free: `xsd:gYear` is not numerically ordered, so the SHACL shapes had to wrap
every comparison in `xsd:integer(STR(?y))`. Those casts are gone and the constraints now
read `FILTER (?d < ?b)`.

This is the clearest practical lesson of the project: *a datatype that serialises fine in
Turtle may still be outside the OWL 2 profile your reasoner implements.*

### 6.3 Pellet: independent confirmation

The brief asks for a cross-check with a second DL reasoner. Pellet [16] agrees with
HermiT:

```
[5] OWL 2 DL reasoning (Pellet, second engine)
  Pellet: CONSISTENT (agrees with HermiT)
```

Two practical notes, since both initially looked like problems and neither was:

**Invocation.** `owlready2.sync_reasoner_pellet()` cannot be used here. owlready2 0.51
ships `jena-arq-fixed2.10.0.jar` containing three classes compiled for **Java 25** (class
file version 69), so Pellet's Jena-based loader aborts with
`UnsupportedClassVersionError` on any JRE below 25 — including the Java 11 and Java 21
available here. This is an owlready2 packaging defect, unrelated to the ontology. Pellet's
own command line does not use that loader, so `build.py` calls it directly.

**Apparent count mismatch.** `pellet realize` initially reported `InfluencerThinker` with
8 members against HermiT's 18. This is **not** a disagreement: `realize` prints only each
individual's *most specific* type, so the 10 philosophers who are also `TeacherThinker`
are listed only there. Checked against the data — the set of objects of `influencedBy`
and its sub-property `studiedUnder` is exactly 18 — and the 10 "missing" names are
precisely the `TeacherThinker` members. Both reasoners agree.

The lesson generalises: comparing reasoner outputs means comparing *semantics*, not
printed line counts.

### 6.4 OWL-RL closure

```
[5] OWL-RL closure
  OWL-RL closure: 1301 -> 3490 triples (+2189 inferred)
      ok   hasTeachingAncestor    expected  19  got 19
      ok   influencedBy           expected  28  got 28
      ok   isWithinSchool         expected  26  got 26
      ok   authored               expected  30  got 30
      ok   createdInLineageOf     expected  27  got 27
      ok   createdIn              expected  20  got 20
```

Well above the brief's target of ten inferred properties. Note `createdInLineageOf`: 27
triples inferred from **zero** asserted.

#### A reasoner disagreement worth reporting

`owl:hasKey ( :externalId )` on `Philosopher` is correct OWL, and HermiT handles it
correctly. **owlrl 7.6.2 does not.** Running its OWL-RL closure produced 4,352 spurious
`owl:sameAs` triples — every philosopher identified with every other — which inflated
`hasTeachingAncestor` from 19 to 961 (= 31 × 31).

The cause is an off-by-one in the library's `prp-key` rule:

```python
for i in range(0, len(pis) - 1):      # owlrl/OWLRL.py
```

With a **single**-property key, `range(0, 0)` is empty, the comparison loop never runs,
`same` is never falsified, and all individuals of the class collapse. Reproduced on a
three-individual toy ontology with all-distinct keys: a 1-property key yields 6 spurious
`sameAs`; 2- and 3-property keys behave correctly.

The ontology is not at fault, so the axiom stays. `build.py` strips it for the OWL-RL step
only, and now **asserts that no non-reflexive `owl:sameAs` is ever inferred**, so the same
class of bug cannot pass silently again.

Two methodological points follow. First, a DL reasoner and a profile-specific rule engine
can disagree, and testing with only one hides real behaviour. Second, `owl:hasKey` was
only made sound here by first making `externalId` **total** on `Philosopher` — all 31 now
carry a verified Wikidata QID, where previously only 10 did. `Work` deliberately has no
key, because its `externalId` is partial.

### 6.5 Two deliberately empty classes

`UncriticizedWork` and `SelfReferentialWork` both infer zero members, and both are
retained because the zero is informative.

`SelfReferentialWork` (`∃references.Self`) is an OWL-level mirror of the SHACL rule "a
work must not reference itself". Two independent mechanisms check the same constraint and
both agree it is satisfied.

`UncriticizedWork` is the more interesting case. A `∀` restriction is vacuously true for
anything with no incoming engagement, so one might expect the 17 works that appear in no
engagement at all to classify here. They do not, because of the **open-world
assumption**: the reasoner cannot rule out an unrecorded criticism. Making the class
non-empty would require explicitly closing the world per work:

```turtle
:Meno a [ a owl:Restriction ; owl:onProperty [ owl:inverseOf :toWork ] ;
          owl:maxCardinality "0"^^xsd:nonNegativeInteger ] .
```

The class documents the OWA boundary rather than hiding it, and it is the same limitation
that forces CQ12 into SPARQL.

### 6.6 Competency questions

All 19 checks (CQ1–CQ15 plus rules R1 and R2) pass with exact row counts asserted:

```
[6] Competency questions
  ok   CQ1 ... CQ15, R1-criticizes, R1-praises, R2-no-school
  SHACL PASS | HermiT PASS | OWL-RL PASS | Queries PASS
  ALL CHECKS PASSED
```

A useful cross-check: the defined class `Criticism` has 6 members and the independent
`CONSTRUCT` rule R1 produces 6 `criticizes` links. The OWL axiom and the SPARQL rule agree.

---

## 7. Linked Open Data

Week 9, Lecture 9 states Linked Data Principle 4 as *"Include links to other URIs, so that
they can discover more things"*, and distinguishes identity, relationship and vocabulary
links. Berners-Lee's original note [2] and Heath and Bizer [7] give the same four
principles. `philosophy_links.ttl` implements all three link types.

### Vocabulary links

Rather than minting every term locally, the classes are aligned with established
vocabularies:

| Local class | Aligned with |
|---|---|
| `Philosopher` | `foaf:Person`, `crm:E21_Person` |
| `Work` | `crm:E73_Information_Object` |
| `Location` | `crm:E53_Place` |
| `TimePeriod` | `crm:E4_Period` |
| `Engagement` | `crm:E7_Activity` |
| `Concept`, `SchoolOfThought` | `skos:Concept` |

Properties align to Dublin Core [4] and SKOS [11]: `:title ⊑ dcterms:title`,
`:createdBy ⊑ dcterms:creator`, `:subSchoolOf ⊑ skos:broader`.

The alignments are `rdfs:subClassOf`, **not** `owl:equivalentClass`. Our classes are
*narrower* than the external ones: every `Philosopher` is a `foaf:Person`, but not every
`foaf:Person` is a philosopher. Asserting equivalence would be a common and damaging
error — it would let any `foaf:Person` anywhere on the web be inferred a philosopher. The
CIDOC-CRM alignment follows the event-centric modelling of [3].

### Identity links

`owl:sameAs` to Wikidata and DBpedia for **all 31 philosophers and all 30 works**
(119 `sameAs` triples, 61 `rdfs:seeAlso`). DBpedia IRIs are derived from the
en.wikipedia sitelink, which is how DBpedia mints resource IRIs [5]. Three works have no
en.wikipedia article and therefore carry a Wikidata link only.

This directly addresses the "failure addressed secondary" in the design brief —
reconciling the different vocabularies different sources use for the same concept.

---

## 8. Data provenance and quality

### Verification method

Identifiers were **not** accepted on a label match. Label search alone returns "capital
city" for *Capital* and "medical ethics" for *Ethics*. Instead:

- **Philosophers (31/31).** Candidates filtered to `P31 = Q5` (human), then confirmed by
  comparing Wikidata's birth year `P569` against the `birthYear` asserted locally.
- **Works (30/30).** Candidates confirmed by `P50` (author) pointing at the
  already-verified QID of that work's `:createdBy` philosopher.
- Where several items shared a label, the one with an en.wikipedia sitelink was preferred;
  the others are individual editions and translations rather than the work itself.

### Errors found and corrected

| Issue | Resolution |
|---|---|
| `:Heidegger :externalId "Q8253"` — **Q8253 is the entity "fiction"** | Corrected to **Q48301** |
| `:Zarathustra` typed as bare `:Work` | Retyped `:Dialogue`; every work now has a leaf type |
| `externalId` present on only 10 of 31 philosophers | Now total: all 31, all distinct, all verified |

### The BCE numbering question

Wikidata reports Aristotle's birth as `-0383` where this dataset says `-384`. This is
**not** an error in either source. Wikidata serialises dates in ISO-8601 **astronomical**
numbering, which includes a year zero; this dataset uses **historical** numbering, which
does not. The two therefore differ by exactly one for every BCE date.

The historical convention is kept because it matches how the secondary literature cites
these dates, and the offset is documented in the dataset header so the comparison can be
reproduced.

### Known data characteristics

These are **recorded, not errors**:

- *Philosophical Investigations* (1953) postdates Wittgenstein's death (1951). The work is
  genuinely posthumous. The SHACL shape flags author-lifetime mismatches as a `sh:Warning`
  rather than a violation for exactly this reason.
- 9 philosophers have no work recorded; 20 of 30 works have no `createdIn`. These gaps are
  retained deliberately so that `OPTIONAL` and `FILTER NOT EXISTS` patterns are genuinely
  exercised rather than trivially satisfied.
- 7 properties (`authored`, `createdInLineageOf`, `hasTeachingAncestor`, `isWithinSchool`,
  `references`, `criticizes`, `praises`) have **zero** asserted triples. This is by design:
  they are inference-only, populated by the reasoner or by rule R1.

---

## 9. Competency questions

The fifteen questions, the SPARQL features each exercises, and the ontology path each
traverses are given in full, with verified expected results, in
`philosophy_sparql_queries.md`.

| CQ | Question | Features |
|---|---|---|
| CQ1 | Author and school of a book | SELECT, OPTIONAL, FILTER |
| CQ2 | Who studied under whom, directly and indirectly | UNION, property path |
| CQ3 | Works criticised at least once | SELECT DISTINCT |
| CQ4 | Sub-schools of a school | property path `+` |
| CQ5 | Works citing or referencing a work | UNION, property alternation |
| CQ6 | Period of a philosopher | SELECT DISTINCT |
| CQ7 | Books of interest to a reader | SELECT DISTINCT |
| CQ8 | Masters who have students | FILTER EXISTS, COUNT, GROUP BY |
| CQ9 | Impact of philosophers | aggregation, HAVING, OPTIONAL |
| CQ10 | Cities of philosophers | SELECT DISTINCT |
| CQ11 | Concepts a philosopher engages with | COUNT, GROUP BY |
| CQ12 | Unread works matching interests | FILTER NOT EXISTS |
| CQ13 | Recommendations with explanation | CONSTRUCT |
| CQ14 | Does a work have a recorded criticism | ASK |
| CQ15 | Everything known about a work | DESCRIBE |

Two questions required an operational definition the brief did not supply. Both are now
stated explicitly in the query collection rather than left implicit:

- **"Master"** = a philosopher who is the *direct* `studiedUnder` target of at least one
  other. Transitive ancestry is excluded: Socrates did not teach Theophrastus.
- **"Impact"** = distinct later thinkers citing *p* as influence or teacher, plus
  engagements targeting *p*'s works. The two components are reported separately because
  they measure different things, and three biases are documented with the definition.

---

## 10. Application layer

The ontology is not the deliverable on its own. This section records the system
built on top of it, all of which runs locally with open-source components.

```
Fuseki 6.2.0  <--SPARQL 1.1 HTTP-->  Flask UI  +  agent  +  LLM translator
   default graph: ontology + dataset
   links graph:   owl:sameAs and vocabulary alignments
```

### 10.1 Triplestore

`app/fuseki.py` starts Apache Jena Fuseki and loads two graphs: the reasoning
bundle into the default graph, and the Linked Data links into
`http://example.org/philosophy/links`. They are kept apart because `owl:sameAs`
would otherwise replicate every inference across all coreferent IRIs (§2).

`app/run_cqs.py` then executes all 15 competency questions plus the two
derivation rules and the data-gap probe over HTTP, asserting each row count:
**18/18 pass** (`FUSEKI_RESULTS.md`).

#### Two defects only a real triplestore revealed

Running the queries on Fuseki rather than in-process with RDFLib exposed two
problems that had been invisible:

**CQ13 returned zero rows.** The original query selected its candidate work
with `{ BIND(?from AS ?w) } UNION { BIND(?to AS ?w) }`. A variable bound inside
a UNION branch is out of scope for a later `FILTER NOT EXISTS`, and Fuseki
enforces that scoping rule strictly where RDFLib does not. Rewritten using the
property alternation `?e (:fromWork|:toWork) ?w`, which is also the idiom CQ12
already used; both engines now return 20 triples.

**CQ15 returned 11 triples instead of 8.** Fuseki's `DESCRIBE` covers the union
of named graphs, so it picks up the two `owl:sameAs` and one `rdfs:seeAlso`
triples from the links graph. Both answers are correct for their dataset, so the
expected count is now recorded per target rather than one value being declared
wrong.

The lesson is worth stating plainly: *an in-process library is not a substitute
for the deployment target.* Two of eighteen queries behaved differently, and
neither difference was a typo.

### 10.2 Single source of truth for the queries

The fifteen questions now live once, in `app/queries.py`, as structured data
carrying the question text, SPARQL, expected row count, ontology evidence path
and editable parameters. `build.py`, the Fuseki runner, the web interface and
the LLM evaluation all import it. A query cannot be fixed in the report and left
broken in the application.

### 10.3 Reasoning and recommendation agent

`app/agent.py` does three things that are outside both OWL and plain SPARQL:

1. **Rule materialisation.** Derives the 9 `:criticizes` / `:praises` shortcut
   links from engagement stance (rule R1). Not expressible as an OWL axiom
   because the conclusion depends on the *value* of a data property.
2. **Scoring.** Ranks unread works:

   > score(work) = Σ over supporting engagements of confidence × stance_weight
   > with praises 1.0, criticizes 0.8, neutral 0.6

   Criticism is weighted below praise but well above nothing: a work attacking a
   concept the reader cares about is still highly relevant. That is a judgement
   call, stated so it can be disagreed with.
3. **Explanation.** Every recommendation carries the engagements that produced
   it, with each one's contribution, so the ranking is auditable.

For `:reader1` the agent returns *The World as Will and Representation* (0.80)
and *Prolegomena* (0.70) — the same two works CQ12 identifies, now ordered and
justified.

### 10.4 Web interface and visualisation

`app/server.py` serves seven pages and seven JSON APIs. Entity pages are CQ15
rendered for a browser; the competency-question page runs any CQ live with
editable parameters; the recommendation page exposes the agent.

Visualisations, all driven by live SPARQL rather than fixtures:

| Figure | Query behind it |
|---|---|
| Teaching lineage network | `:studiedUnder` edges (CQ2) |
| Engagement network | engagements, edges coloured by stance, width = confidence |
| School hierarchy | `:subSchoolOf` (CQ4) |
| Impact bar chart | CQ9 |
| Works per period | `:composedDuring` grouped by period |
| Philosophers per school | `:belongsToSchool` |
| Stance distribution | 6 criticizes / 3 praises / 1 neutral |

If Fuseki is unreachable the interface falls back to an in-process graph and
says so in the header, rather than failing.

## 11. Natural language to SPARQL

Week 10 of the brief asks for an LLM integration compared against a baseline on
15+ questions. `app/llm_sparql.py` implements both and scores them by
**execution**, never by eye. Full detail in `LLM_EVALUATION.md`.

**Model.** `qwen2.5-coder:3b`, open weights, served locally by Ollama. No API
key, no data leaving the machine, and reproducible by a marker on their own
hardware. The prompt's schema context is *generated from the ontology*, so it
cannot drift from the axioms.

**Baseline.** Keyword retrieval over the stored competency questions — the
realistic non-LLM alternative is a canned-query app with a search box, not an
empty straw man.

**Scoring.** Both systems' queries are executed against Fuseki and their result
*sets* compared with the verified gold answers, ignoring variable names and row
order, since `?title` and `?t` are equally valid choices.

| System | Syntax OK | Exact match | Mean F1 | Mean latency |
|---|---|---|---|---|
| baseline | 13/13 | 13/13 | 1.000 | 0.0s |
| LLM `qwen2.5-coder:3b` | 12/13 | 0/13 | 0.014 | 1.8s |
| LLM `qwen2.5-coder:7b` | 11/13 | 0/13 | 0.014 | 11.0s |

### Why the LLM scores zero, and what that actually shows

A bare 0/13 is not a finding. The breakdown is:

| Count | Failure mode |
|---|---|
| 8 | empty result (over-constrained or wrong property) |
| 2 | wrong entities returned |
| 1 | type error (IRI used as a string literal) |
| 1 | partially correct (direction or filter wrong) |
| 1 | syntax: aggregate misuse |

12 of 13 queries *parsed and executed*. The model has learned SPARQL form; what
it has not learned is this ontology's shape.

**The dominant cause is inference-only vocabulary.** Seven properties and eight
classes here are never asserted and exist only after reasoning — `:authored`,
`:references`, `:hasTeachingAncestor`, `:isWithinSchool`, `:createdInLineageOf`,
`:criticizes`, `:praises`, and defined classes such as `:TeacherThinker`. They
appear in the schema context, so the model reasonably reaches for them:
`:authored` for "works by", `:TeacherThinker` for "masters". Against a
non-reasoning endpoint those queries are **valid and empty** — the worst failure
mode, because an empty result looks like a legitimate answer of zero.

Measured: 5 of 13 generated queries used at least one such term. Re-running the
identical prompts against a materialised endpoint (the OWL-RL closure plus the
R1 links, 2,735 triples, published as a second Fuseki dataset) cut empty results
from **8 to 5**.

That is a conclusion about **system design, not model quality**: a SPARQL
endpoint intended to be queried by an LLM should serve the inferred closure, or
hide inference-only terms from the prompt. A human query author falls into
exactly the same trap.

Materialisation helped but did not rescue the score: it converted "empty
result" failures into "wrong entities" failures. The queries then returned
*something*, just not the right thing.

**What actually blocks these models is domain modelling, not SPARQL.** Both
write valid SPARQL most of the time. What neither does reliably is pick the
right direction on a reified relation (`:fromWork` versus `:toWork`), recognise
when a question needs a join through `:Engagement` at all, or remember that
`:title` takes a string while every other label takes an IRI. Those are facts
about *this* ontology, and generic code pre-training does not supply them. The
realistic fixes - few-shot examples from a real query log, a fine-tune on
question/SPARQL pairs, or constrained decoding against the vocabulary - are out
of scope here, but the harness would measure any of them unchanged.

The residual errors are genuine comprehension failures and honest losses for a
3B model: confusing `:fromWork` with `:toWork`, treating an IRI as a literal,
dropping a requested projection, and misplacing an aggregate.

### Three caveats on these numbers

1. **The baseline is strong by construction** — it retrieves from the same
   verified queries the questions were drawn from, so on exact phrasing it is
   near-perfect. That is the point: it shows what an LLM must beat.
2. **The LLM's advantage is not on this test set.** Its value is on *unseen*
   phrasings, where keyword retrieval can only return whichever canned query
   shares the most words. Demonstrating that needs a held-out paraphrase set,
   which this evaluation does not yet have.
3. **Scale was tested, and did not help.** The obvious objection is that a 3B
   model is simply too small. It was checked: `qwen2.5-coder:7b` scored
   *identically* (0/13 exact, same mean F1) while running roughly six times
   slower, and produced more malformed queries rather than fewer. Four runs
   were made in total, crossing model size with endpoint type; all four gave
   0/13. The barrier is not capacity at this scale.

## 12. Limitations

1. **Open-world assumption.** Absence of evidence is never evidence of absence. A missing
   criticism, school or date cannot be distinguished from one that is simply unrecorded.
   This is why `UncriticizedWork` is empty (§6.5) and why "not yet read" must be SPARQL.

2. **Scale.** 109 individuals, 30 works, 10 engagements. Enough to exercise every axiom
   and every query, but far too small for any quantitative claim about intellectual
   history. The `impact` measure in CQ9 reflects curation effort as much as influence.

3. **Engagements are hand-curated.** Each of the 10 is a scholarly judgement with a
   `confidenceScore`, not a fact extracted from text. Disputed attributions and contested
   influence claims are modelled as confidence, not resolved.

4. **Coverage bias.** The dataset is Western and canonical. Non-Western traditions and
   non-canonical figures are absent, which would materially distort any analysis of
   "influence" taken at face value.

5. **Western-only vocabulary alignment.** The CIDOC-CRM and SKOS alignments are asserted
   but not validated against those ontologies' own constraints; a full alignment check
   would require loading CIDOC-CRM itself.

6. **Tooling.** Verified with three engines: HermiT, Pellet and owlrl (§6.2, §6.3). The
   remaining gap is that Pellet is checked for consistency only, not for a full
   classification diff against HermiT, because its CLI prints only most-specific types.

7. **The endpoint does not reason.** Fuseki serves the asserted triples, so
   inference-only properties return nothing unless the materialised dataset is
   queried instead. §11 shows this is the single largest cause of LLM query
   failure, and it would affect human users equally. Serving the closure by
   default, or configuring a Fuseki reasoner, is the obvious next step.

8. **The LLM evaluation has no held-out paraphrases.** Both systems are scored
   on the exact competency-question wording, which structurally favours the
   retrieval baseline. The claim that an LLM generalises better to unseen
   phrasings is plausible but, on this evidence, **unproven**.

9. **The web interface has no tests and no authentication.** It is a
   demonstrator: single-user, read-only, and not hardened for deployment.

---

## 13. References

[1] Hitzler, P., Krötzsch, M. and Rudolph, S. (2010) *Foundations of Semantic Web
Technologies*. Boca Raton, FL: Chapman & Hall/CRC. — The module's set text. Used for the
treatment of OWA versus CWA (§4.3) and for the domain/range conjunction trap (§5) cited
in §4.

[2] Berners-Lee, T. (2006) *Linked Data — Design Issues*. W3C. Available at:
https://www.w3.org/DesignIssues/LinkedData.html — The four Linked Data principles applied
in §7.

[3] Doerr, M. (2003) 'The CIDOC Conceptual Reference Module: An Ontological Approach to
Semantic Interoperability of Metadata', *AI Magazine*, 24(3), pp. 75–92. — Basis for the
event-centric treatment of `Engagement` and the CRM alignment in §7.

[4] DCMI Usage Board (2020) *DCMI Metadata Terms*. Dublin Core Metadata Initiative.
Available at: https://www.dublincore.org/specifications/dublin-core/dcmi-terms/

[5] Lehmann, J. et al. (2015) 'DBpedia — A large-scale, multilingual knowledge base
extracted from Wikipedia', *Semantic Web*, 6(2), pp. 167–195. — Source for how DBpedia
mints resource IRIs from Wikipedia titles, used in §7.

[6] Grüninger, M. and Fox, M.S. (1995) 'Methodology for the Design and Evaluation of
Ontologies', *IJCAI Workshop on Basic Ontological Issues in Knowledge Sharing*. — The
competency-question method used to scope the ontology in §1.

[7] Heath, T. and Bizer, C. (2011) *Linked Data: Evolving the Web into a Global Data
Space*. San Rafael, CA: Morgan & Claypool. — Vocabulary reuse (§4.4) and the practice of
publishing identity links in a separate graph, both applied in §2 and §7.

[8] Knublauch, H. and Kontokostas, D. (eds.) (2017) *Shapes Constraint Language (SHACL)*.
W3C Recommendation. Available at: https://www.w3.org/TR/shacl/ — Basis for the
closed-world validation layer in §5.2.

[9] Motik, B., Patel-Schneider, P.F. and Parsia, B. (eds.) (2012) *OWL 2 Web Ontology
Language: Structural Specification and Functional-Style Syntax*. 2nd edn. W3C
Recommendation. Available at: https://www.w3.org/TR/owl2-syntax/ — §4 defines the OWL 2
datatype map (the `xsd:gYear` blocker, §6.2); §11 defines property simplicity (the
simple/non-simple split, §4).

[10] Noy, N.F. and McGuinness, D.L. (2001) *Ontology Development 101: A Guide to Creating
Your First Ontology*. Stanford Knowledge Systems Laboratory Technical Report KSL-01-05. —
Scoping method and naming conventions, §1 and §4.

[11] Miles, A. and Bechhofer, S. (eds.) (2009) *SKOS Simple Knowledge Organization System
Reference*. W3C Recommendation. Available at: https://www.w3.org/TR/skos-reference/ —
Used for the `skos:broader` alignment of `subSchoolOf`, §7.

[12] Noy, N. and Rector, A. (eds.) (2006) *Defining N-ary Relations on the Semantic Web*.
W3C Working Group Note. Available at: https://www.w3.org/TR/swbp-n-aryRelations/ — The
reification pattern used for `Engagement`, §3.

[13] Glimm, B., Horrocks, I., Motik, B., Stoilos, G. and Wang, Z. (2014) 'HermiT: An OWL 2
Reasoner', *Journal of Automated Reasoning*, 53(3), pp. 245–269. — The reasoner used for
all consistency and classification results in §6.

[14] Vrandečić, D. and Krötzsch, M. (2014) 'Wikidata: A Free Collaborative Knowledgebase',
*Communications of the ACM*, 57(10), pp. 78–85. — The identifier source verified in §8.

[15] Horridge, M. and Bechhofer, S. (2011) 'The OWL API: A Java API for OWL Ontologies',
*Semantic Web*, 2(1), pp. 11–21. — The API underlying Protégé and the HermiT invocation
used in `build.py`.

[16] Sirin, E., Parsia, B., Cuenca Grau, B., Kalyanpur, A. and Katz, Y. (2007) 'Pellet: A
practical OWL-DL reasoner', *Journal of Web Semantics*, 5(2), pp. 51–53. — The second DL
reasoner, used in §6.3 to cross-check HermiT's consistency result.
