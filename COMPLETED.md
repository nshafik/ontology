# Work completed

Execution record for the plan in `PLAN.md`. The ontology layer is verified by
`python3 build.py` (**ALL CHECKS PASSED**); the application layer by
`python3 app/run_cqs.py` (**18/18**) and `app/llm_sparql.py`.

---

## Task record

| # | Task | Status | Evidence |
|---|---|---|---|
| T1 | Replace `xsd:gYear` with `xsd:int`; drop SHACL casts | done | HermiT now loads the ontology at all |
| T2 | `owl:NamedIndividual` + `owl:AllDifferent` | done | 109 individuals declared and pairwise distinct |
| T3 | Full pairwise disjointness | done | `owl:AllDisjointClasses` over 7 classes = 21 pairs |
| T4 | Data corrections | done | Heidegger Q8253→Q48301; Zarathustra retyped; BCE convention documented |
| T5 | Query doc status + open definitions | done | "executed and verified"; "master" and "impact" defined |
| T6 | Missing OWL constructs | done | 4 new defined classes + cardinality, hasKey, propertyDisjointWith |
| T7 | Axioms in Turtle **and** RDF/XML | done | `OWL_CONSTRUCTS.md`, 11 sections, line-by-line |
| T8 | Linked Open Data | done | `philosophy_links.ttl`: 119 `sameAs`, 61 `seeAlso`, 14 alignments |
| T9 | Bibliography with inline citations | done | `REPORT.md` §11, 15 sources, cited at point of use |
| T15 | Ontology diagrams | done | `DIAGRAMS.md`, 5 figures, generated from the Turtle |
| T16 | Report with validation evidence | done | `REPORT.md`, 11 sections |
| — | Build + regression gate | done | `build.py`, 7 stages, 3 reasoners |
| T10 | Fuseki triplestore + CQs over HTTP | done | 18/18, `FUSEKI_RESULTS.md` |
| T11 | Python reasoning + recommendation agent | done | `app/agent.py` |
| T12 | Web interface for ontology browsing | done | `app/server.py`, 7 pages |
| T13 | Visualisation of query results | done | 3 networks + 4 charts, live SPARQL |
| T14 | LLM NL→SPARQL + baseline comparison | done | `LLM_EVALUATION.md` |
| — | Pellet cross-check (brief §10) | done | `Consistent: Yes`, agrees with HermiT |

---

## The five findings that mattered

### 1. The ontology could not be reasoned over at all

`xsd:gYear` is **not in the OWL 2 datatype map**. HermiT and Pellet both abort:

```
UnsupportedDatatypeException: The datatype '...#gYear' is not part of the
OWL 2 datatype map ... therefore, HermiT cannot handle this datatype.
```

The brief promised "Protégé with HermiT … checked again with Pellet", and the rubric
requires work that "validates successfully in standard tools". Pressing *Start reasoner*
produced a stack trace. All years are now `xsd:int` with BCE negative, which also removed
the `xsd:integer(STR(?y))` casts from five SHACL constraints.

### 2. A wrong Wikidata identifier, and a verification method to prevent more

`:Heidegger :externalId "Q8253"` — **Q8253 is the Wikidata entity "fiction"**.

Rather than fix one ID by hand, all 61 entities were resolved programmatically and
**verified by a second property**, never by label alone:

- philosophers: filtered to `P31 = Q5` (human), confirmed by birth year `P569`
- works: confirmed by author `P50` matching the already-verified philosopher QID

This caught what label search would not: searching "Capital" returns *capital city*, and
"Ethics" returns *medical ethics*. 31/31 philosophers and 30/30 works resolved.

### 3. A reasoner bug, found because two engines were run

`owl:hasKey ( :externalId )` is correct OWL and HermiT handles it. **owlrl 7.6.2 does
not**: it inferred 4,352 spurious `owl:sameAs` triples, making every philosopher every
other philosopher and inflating `hasTeachingAncestor` from 19 to 961 (= 31 × 31).

Root cause, isolated to an off-by-one in the library's `prp-key` rule:

```python
for i in range(0, len(pis) - 1):      # owlrl/OWLRL.py
```

For a **single**-property key `range(0, 0)` is empty, so the comparison never runs.
Reproduced on a 3-individual toy ontology: 1-property key → 6 spurious `sameAs`;
2- and 3-property keys → correct.

The ontology is not at fault, so the axiom stays. `build.py` strips it for the OWL-RL
step and now asserts no non-reflexive `owl:sameAs` is ever inferred.

---

### 4. A real triplestore caught two bugs RDFLib hid

Moving the queries onto Fuseki changed two results:

- **CQ13 returned 0 rows.** `{ BIND(?from AS ?w) } UNION { BIND(?to AS ?w) }`
  binds `?w` inside a UNION branch, putting it out of scope for a later
  `FILTER NOT EXISTS`. Fuseki enforces that scoping; RDFLib does not. Rewritten
  with a property alternation; both engines now agree at 20.
- **CQ15 returned 11, not 8.** Fuseki's `DESCRIBE` spans the union of named
  graphs and picks up the LOD links. Both correct for their dataset.

An in-process library is not a substitute for the deployment target.

### 5. The LLM's main failure is a system-design problem, not a model problem

5 of 13 generated queries used **inference-only vocabulary** (`:authored`,
`:references`, `:TeacherThinker`) that is never asserted and only exists after
reasoning. Against a plain endpoint these are *valid and empty* — the worst
failure mode, because zero rows looks like a legitimate answer.

Re-running identical prompts against a materialised endpoint (OWL-RL closure +
R1 links, 2,735 triples) cut empty results from 8 to 5. The conclusion is that
an endpoint meant for LLM querying should serve the closure. A human query
author hits the same trap.

**Scale was tested and did not help.** Four runs crossing model size with
endpoint type - 3B/plain, 3B/inferred, 7B/plain, 7B/inferred - all gave 0/13
exact and the same mean F1, with 7B running six times slower and producing
*more* malformed queries. The residual barrier is domain modelling, not
capacity: direction on reified relations, when to join through `:Engagement`,
and `:title` taking a string where everything else takes an IRI.

## Before and after

| | Before | After |
|---|---|---|
| HermiT | **fails to load** | consistent, 0 unsatisfiable |
| Named classes | 18 | 22 |
| Defined classes | 4 | 8 |
| `allValuesFrom` / `complementOf` / `hasSelf` | 0 / 0 / 0 | 1 / 1 / 1 |
| Cardinality axioms | 0 | 4 |
| `NamedIndividual` / `AllDifferent` | 0 / 0 | 109 / 1 |
| Disjointness pairs | 3 asserted (21 claimed) | 21 |
| `owl:sameAs` | 0 | 119 |
| External vocabularies | 0 | 5 (FOAF, SKOS, DC, CIDOC-CRM, Wikidata/DBpedia) |
| Citations | 0 | 15 |
| Diagrams | 0 | 5 |
| Automated checks | 0 | 7-stage gate + 18 endpoint assertions |
| SPARQL endpoint | none | Fuseki 6.2.0, 18/18 CQs over HTTP |
| Web interface | none | 7 pages, 7 JSON APIs |
| Visualisations | none | 3 network graphs + 4 charts, live SPARQL |
| Recommendation agent | none | scored + explained, `app/agent.py` |
| NL→SPARQL | none | open-weights LLM, measured vs baseline |

Inference yield (OWL-RL, verified): `hasTeachingAncestor` 19, `influencedBy` 28,
`isWithinSchool` 26, `authored` 30, `createdInLineageOf` 27, `createdIn` 20 — against the
brief's target of 10.

---

## Two classes that are deliberately empty

`UncriticizedWork` (`allValuesFrom` + `complementOf`) and `SelfReferentialWork`
(`hasSelf`) both infer **0 members**, and both are kept.

`SelfReferentialWork` is an OWL mirror of a SHACL rule — two mechanisms, same answer.

`UncriticizedWork` is empty because of the **open-world assumption**: OWL cannot conclude
a work is uncriticised merely because no criticism is recorded. That is the same
limitation that forces CQ12 into SPARQL `FILTER NOT EXISTS`, and the class documents the
boundary instead of hiding it. Both are explained in `REPORT.md` §6.4.

---

## Files

**New (ontology):** `philosophy_links.ttl`, `REPORT.md`, `OWL_CONSTRUCTS.md`,
`DIAGRAMS.md`, `build.py`, `make_diagrams.py`, `COMPLETED.md`

**New (application):** `app/fuseki.py`, `app/queries.py`, `app/run_cqs.py`,
`app/agent.py`, `app/server.py`, `app/llm_sparql.py`, `app/templates/`,
`app/README.md`, `FUSEKI_RESULTS.md`, `LLM_EVALUATION.md`

**Modified:** `philosophy_ontology.ttl`, `philosophy_dataset.ttl`,
`philosophy_shapes.ttl`, `philosophy_sparql_queries.md`, `PLAN.md`

**Generated — do not hand-edit:** `philosophy_complete.ttl`, `DIAGRAMS.md`

```bash
pip install rdflib pyshacl owlrl owlready2     # Java required for HermiT
python3 build.py            # build + validate
python3 build.py --check    # fail if the generated bundle is stale
python3 make_diagrams.py    # regenerate the figures

python3 app/fuseki.py start # triplestore on :3030
python3 app/run_cqs.py      # 18/18 competency checks over HTTP
python3 app/server.py       # web interface on :5000
python3 app/agent.py recommend :reader1
python3 app/llm_sparql.py evaluate --markdown LLM_EVALUATION.md
```

---

## What is still missing

| Item | Status |
|---|---|
| Two presentations (brief, week 11) | not done |
| Held-out paraphrase set for the LLM evaluation | not done |
| Few-shot-from-query-log or fine-tune for NL→SPARQL | not done |
| Reasoning-enabled endpoint as the default | prototyped, not default |
| Prose edit of the original brief (Sections 1, 2, 9) | not done |

Three honest caveats on what *is* done:

1. **The LLM scores 0/13 exact.** That is a real measurement, not a setup
   error — 12 of 13 queries executed fine, they just answered the wrong
   question. The diagnosis (inference-only vocabulary, §11 of the report) is
   the useful output, not the score.
2. **The LLM evaluation favours the baseline by construction.** Both systems
   are tested on the exact competency-question wording. The case for an LLM
   rests on unseen phrasings, which is not yet measured.
3. **The web interface is a demonstrator**: no tests, no auth, single-user.
