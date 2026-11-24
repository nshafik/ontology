# Application layer

Everything that sits on top of the ontology: the triplestore, the reasoning and
recommendation agent, the web interface, and the natural-language query
evaluation.

```
app/
  fuseki.py       start Apache Jena Fuseki, load the graphs, verify
  queries.py      the 15 competency questions as data - single source of truth
  run_cqs.py      execute all CQs against the live endpoint, assert row counts
  agent.py        rule materialisation, recommendation scoring, lineage
  llm_sparql.py   natural language -> SPARQL, with a measured baseline comparison
  ask.py          grounded Q&A: LLM/keyword routing to a reviewed CQ
  sources.py      bounded clients for 18 external LOD / heritage providers
  ingest_sources.py  import provider metadata as PROV-O records (data/)
  server.py       Flask web interface and the JSON APIs behind the charts
  templates/      Jinja2 templates
```

`queries.py` is imported by `build.py`, `run_cqs.py`, `server.py` and
`llm_sparql.py`. A query cannot be corrected in the report and left broken in
the application.

## Quick start

```bash
pip install rdflib pyshacl owlrl owlready2 flask    # Java needed for Fuseki/HermiT

python3 build.py                 # validate the ontology (5 gates)
python3 app/fuseki.py start      # triplestore on :3030, loads both graphs
python3 app/run_cqs.py           # 18/18 competency checks over HTTP
python3 app/server.py            # web interface on :5000
```

## 1. Triplestore — `fuseki.py`

Starts Fuseki 6.2.0 with an in-memory dataset and loads two graphs:

| Graph | Contents |
|---|---|
| default | `philosophy_complete.ttl` — ontology + dataset |
| `http://example.org/philosophy/links` | `philosophy_links.ttl` — `owl:sameAs`, alignments |

They are separate on purpose. `owl:sameAs` makes a local individual, its
Wikidata item and its DBpedia resource the same thing, so a reasoning endpoint
replicates every inference across all three IRIs.

```bash
python3 app/fuseki.py start|stop|status|reload
```

## 2. Competency questions — `run_cqs.py`

Runs all 15 CQs plus the two derivation rules and the data-gap probe against the
HTTP endpoint and asserts each row count. **18/18 pass.** Writes
`FUSEKI_RESULTS.md`.

Running on a real triplestore exposed two defects RDFLib had hidden:

- **CQ13 returned 0 rows.** `{ BIND(?from AS ?w) } UNION { BIND(?to AS ?w) }`
  binds `?w` inside a UNION branch, which puts it out of scope for a later
  `FILTER NOT EXISTS`. Fuseki enforces that scoping rule; RDFLib does not.
  Rewritten as `?e (:fromWork|:toWork) ?w`; both engines now return 20.
- **CQ15 returned 11 instead of 8.** Fuseki's `DESCRIBE` spans the union of
  named graphs and picks up the three LOD triples. Both answers are right for
  their dataset, so the expected value is recorded per-target.

## 3. Agent — `agent.py`

```bash
python3 app/agent.py recommend :reader1
python3 app/agent.py rules            # materialise the R1 shortcut links
python3 app/agent.py lineage :Socrates
```

Three things that are outside OWL and plain SPARQL:

1. **Rule materialisation.** Derives the 9 `:criticizes` / `:praises` links from
   engagement stance. Not an OWL axiom: the conclusion depends on the *value* of
   a data property.
2. **Scoring.** `score = Σ confidence × stance_weight` over supporting
   engagements, with `praises 1.0`, `criticizes 0.8`, `neutral 0.6`. Criticism
   ranks below praise but well above nothing — a work attacking a concept you
   care about is still relevant. A judgement call, stated so it can be argued
   with.
3. **Explanation.** Every recommendation carries the engagements that produced
   it, so the ranking is auditable rather than a bare ordering.

## 4. Web interface — `server.py`

Ten pages and the JSON APIs behind them on `:5000`.

| Route | Purpose |
|---|---|
| `/` | live counts straight from the endpoint |
| `/browse/<kind>` | philosophers, works, schools, concepts, readers |
| `/entity/<name>` | CQ15 (`DESCRIBE`) as a page, plus incoming triples |
| `/cq/<id>` | run any competency question, with editable parameters |
| `/recommend` | ranked recommendations with their evidence |
| `/visualise` | 3 network graphs and 4 charts |
| `/ask` | natural-language question routed to a reviewed CQ (`ask.py`) |
| `/ontology` | class and property browser read from the Turtle |
| `/sources` | imported external-source records with provenance |

Visualisations: teaching lineage, engagement network (edges coloured by stance,
thickness = confidence), school hierarchy, plus impact (CQ9), works-per-period,
philosophers-per-school and stance-distribution charts. All driven by live
SPARQL — nothing hard-coded.

If Fuseki is down the app falls back to an in-process RDFLib graph and says so
in the header rather than showing a stack trace.

## 5. Natural language to SPARQL — `llm_sparql.py`

```bash
python3 app/llm_sparql.py ask "Which works criticize the Republic?"
python3 app/llm_sparql.py evaluate --markdown ../LLM_EVALUATION.md
python3 app/llm_sparql.py schema      # inspect the generated prompt context
```

Open-weights `qwen2.5-coder:3b` served locally by Ollama — no API key, no data
leaving the machine, reproducible by a marker. The schema context is **generated
from the ontology**, so the prompt cannot drift from the axioms.

Scoring executes both systems and compares result *sets* (values, ignoring
variable names and row order) against the verified gold answers.

**Result: baseline 13/13 exact, LLM 0/13 exact, 12/13 syntactically valid.**

The baseline — keyword retrieval over the same hand-written queries — is strong
by construction, and that is deliberate: it shows what an LLM must beat to be
worth adding, rather than a straw man.

The useful finding is *why* the LLM fails. 5 of 13 generated queries reached for
**inference-only vocabulary** (`:authored`, `:references`, `:TeacherThinker`)
that is never asserted and only exists after reasoning. Against a plain endpoint
those queries are valid and empty — the worst failure mode, because it looks
like a legitimate answer of zero. Re-running identical prompts against a
materialised endpoint cut empty results from 8 to 5.

That is a conclusion about system design, not model quality: **an endpoint
intended for LLM querying should serve the inferred closure.**

**Scale was tested and did not help.** Four runs crossing model size with
endpoint type:

| Run | Syntax OK | Exact | Mean F1 | Latency |
|---|---|---|---|---|
| 3B / plain | 12/13 | 0/13 | 0.014 | 1.8s |
| 3B / inferred | 12/13 | 0/13 | 0.014 | 1.8s |
| 7B / plain | 11/13 | 0/13 | 0.014 | 11.0s |
| 7B / inferred | 11/13 | 0/13 | 0.014 | 10.0s |
| baseline | 13/13 | 13/13 | 1.000 | 0.0s |

7B scored identically while running six times slower and producing *more*
malformed queries. The residual barrier is domain modelling - direction on
reified relations, when to join through `:Engagement` - not SPARQL syntax and
not model capacity.

```bash
python3 app/llm_sparql.py evaluate --model qwen2.5-coder:7b --json run.json
python3 app/llm_sparql.py evaluate --inferred --json run2.json
python3 app/compare_models.py run.json:7B/plain run2.json:3B/inferred --out cmp.md
```

Full analysis in `LLM_EVALUATION.md`.
