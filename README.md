# Philosophy and Intellectual History Curation Ontology

An OWL 2 DL ontology of philosophers, works, schools of thought, concepts and
the **engagements** through which one work criticises, praises or discusses
another, served over SPARQL and explored through a Flask web application.

ISM601 — Introduction to Web Science, 2026/27. Full write-up in `REPORT.md`.

## Layout

```
philosophy_ontology.ttl    TBox: 14 asserted + 4 defined classes, axioms
philosophy_dataset.ttl     ABox: 114 individuals, 13 engagements
philosophy_links.ttl       owl:sameAs / seeAlso to Wikidata and DBpedia
philosophy_shapes.ttl      SHACL: cardinality, year order, teaching cycles
philosophy_complete.ttl    GENERATED reasoning bundle (build.py)
build.py                   7-stage regression gate: SHACL, HermiT, Pellet, OWL-RL, CQs
export_rdf.py              RDF/XML exports for Protégé (exports/)
make_diagrams.py           ontology diagrams, generated from the Turtle

app/
  queries.py               competency questions (CQ1-CQ16) and rules (R1-R3)
  fuseki.py                start Apache Jena Fuseki and load the graphs
  run_cqs.py               run every CQ over HTTP and assert row counts
  agent.py                 R1/R3 rule materialisation, scored + explained recommendations
  ask.py                   grounded Q&A: LLM/keyword routing to a reviewed CQ
  llm_sparql.py            free-form NL->SPARQL evaluation against a baseline
  enrich_wikidata.py       batched Wikidata lookup + cache for works and influences
  sources.py               bounded clients for 18 cultural-heritage / LOD providers
  ingest_sources.py        import provider metadata as PROV-O records
  server.py                Flask web interface and JSON APIs
tests/test_app.py          33 tests; no Fuseki or network needed
```

## Quick start

```bash
pip install -r requirements.txt     # Java needed for HermiT/Pellet and Fuseki

python3 build.py                    # validate the ontology  -> ALL CHECKS PASSED
python3 -m unittest discover -s tests -v
python3 app/fuseki.py start         # optional: triplestore on :3030
python3 app/server.py               # http://127.0.0.1:5000
```

Without Fuseki the server falls back to an in-process RDFLib graph and says so
in the header.

## Web interface

| Route | Purpose |
|---|---|
| `/` | live counts from the endpoint |
| `/ask` | natural-language question → reviewed CQ → rows (+ optional LLM phrasing) |
| `/browse/<kind>` | philosophers, works, schools, concepts, readers |
| `/entity/<name>` | outgoing and incoming triples (CQ15 as a page) |
| `/cq/<id>` | run any competency question with editable parameters |
| `/recommend` | ranked recommendations, each with its engagement evidence |
| `/visualise` | teaching lineage, engagement and school networks; 4 charts |
| `/ontology` | classes, property domains/ranges/characteristics from the Turtle |
| `/sources` | imported external-source records and their provenance |

JSON: `POST /api/ask`, `GET /api/competencies`, `/api/ontology`, `/api/sources`,
`/health`, `/validation`, and the `/api/graph/*`, `/api/chart/*` feeds behind the
visualisations.

## Asking questions

`app/ask.py` keeps the LLM away from query authoring. `LLM_EVALUATION.md`
measured free-form generation at **0/13 exact** against **13/13** for retrieval
over the stored queries, so the LLM is only allowed to *choose*:

1. **Route.** With `GEMINI_API_KEY` set, Gemini maps the question to one CQ ID
   and one entity label, both from closed lists; anything outside the lists is
   rejected. Without a key, keyword retrieval and longest-label matching do the
   same job.
2. **Execute.** The reviewed query runs against Fuseki or the local fallback.
   Parameters must be local names like `:Republic`, so nothing user-supplied
   can alter the query.
3. **Phrase** (optional). Gemini rewrites only the returned rows. A missing
   fact is reported as *not recorded here*, never as false.

```bash
cp .env.example .env      # add GEMINI_API_KEY; .env is git-ignored
curl -s localhost:5000/api/ask -H 'Content-Type: application/json' \
     -d '{"question": "Has the Republic been criticized?"}'
```

## External sources

`app/sources.py` queries Wikidata, DBpedia, SEP, GeoNames, Pleiades, Open
Library, Library of Congress, VIAF, Gutendex, Perseus, The Met, Art Institute
of Chicago, Cleveland Museum of Art, Getty ULAN/AAT/TGN, Europeana and
Rijksmuseum. Records are stored in `data/imported_sources.ttl` as `prov:Entity`
with Dublin Core metadata. They are **not** merged into the reasoning bundle,
and never become `:Work`, `:City` or influence claims automatically: a
catalogue entry is evidence for curation, not a reviewed assertion.

```bash
python3 app/ingest_sources.py --source sep openlibrary viaf perseus --query "Plato" --limit 2
python3 app/ingest_sources.py --source pleiades --query "Athens" --limit 2 --append
```

A failing provider is reported and skipped; it does not abort the import.
Check each provider's terms before use. `EUROPEANA_API_KEY`,
`RIJKSMUSEUM_API_KEY` and `GEONAMES_USERNAME` go in `.env`.

## Credits

Ontology, validation pipeline, Fuseki integration, recommendation agent and
LLM evaluation: this repository. The grounded-routing design, the external
source clients, the ontology browser and the provenance views were adapted
from [Ingy77/Philosopher-ontology-](https://github.com/Ingy77/Philosopher-ontology-)
and re-targeted to this ontology's namespace and query registry.
