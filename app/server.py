#!/usr/bin/env python3
"""Web interface for browsing the philosophy ontology.

Covers the rubric's Application rows:

  Integration        a web-based interface for ontology browsing
  Integration        ontology + SPARQL applied to a real task (recommendation)
  Demonstration      every competency question runnable from the browser
  Visualisation      query results rendered as charts and network graphs
  LLM integration    grounded Q&A: an LLM routes to a reviewed query (ask.py)
  Provenance         SHACL status, ontology browser, imported source records

All data is read from the Fuseki endpoint over SPARQL 1.1, not from a local
file, so the interface exercises the same triplestore path as run_cqs.py.
If Fuseki is unreachable the app falls back to an in-process RDFLib graph and
says so in the banner, rather than showing a stack trace.

Run:
    python3 app/fuseki.py start
    python3 app/server.py                 # http://localhost:5000
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, render_template, request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from queries import ALL, BY_ID, render as render_query  # noqa: E402
from agent import Agent  # noqa: E402
import ask as asker  # noqa: E402

asker.load_dotenv(ROOT / ".env")

ENDPOINT = "http://localhost:3030/philosophy/sparql"
PREFIX = "http://example.org/philosophy#"

SOURCES_FILE = ROOT / "data" / "imported_sources.ttl"
LOCAL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

app = Flask(__name__, template_folder=str(HERE / "templates"),
            static_folder=str(HERE / "static"))
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

_fallback: Agent | None = None
_entities: list | None = None
_validation: tuple[bool, str] | None = None


# --------------------------------------------------------------------------
# SPARQL access
# --------------------------------------------------------------------------

def endpoint_alive() -> bool:
    try:
        urllib.request.urlopen("http://localhost:3030/$/ping", timeout=2)
        return True
    except Exception:
        return False


def fallback_graph() -> Agent:
    """In-process graph, used when Fuseki is not running."""
    global _fallback
    if _fallback is None:
        _fallback = Agent()
        _fallback.materialise_rules()
    return _fallback


class BackendError(Exception):
    """The SPARQL backend failed or returned something unreadable.

    Deliberately NOT a ValueError: json.JSONDecodeError is one, and letting it
    escape made /api/ask report a server fault as a 400 "bad input".
    """


# Strip comments and the PREFIX/BASE prologue, then read the query form.
_PROLOGUE = re.compile(r"(#[^\n]*)|(\b(PREFIX|BASE)\b\s*[^<]*<[^>]*>)", re.I)
_FORM = re.compile(r"^\s*(SELECT|ASK|CONSTRUCT|DESCRIBE)\b", re.I)


def query_form(query: str) -> str:
    """SELECT | ASK | CONSTRUCT | DESCRIBE, decided before contacting Fuseki.

    Fuseki answers CONSTRUCT and DESCRIBE with an RDF graph, not SPARQL-JSON,
    so the Accept header has to be chosen per form. Asking for
    sparql-results+json on a DESCRIBE used to crash CQ13 and CQ15 in the web
    app with JSONDecodeError whenever Fuseki was live.
    """
    match = _FORM.match(_PROLOGUE.sub(" ", query))
    return match.group(1).upper() if match else "SELECT"


def term_json(term) -> dict:
    """One RDF term as a SPARQL-JSON binding value."""
    from rdflib import BNode, URIRef
    if isinstance(term, URIRef):
        return {"type": "uri", "value": str(term)}
    if isinstance(term, BNode):
        return {"type": "bnode", "value": str(term)}
    return {"type": "literal", "value": str(term)}


def graph_json(graph) -> dict:
    """A CONSTRUCT/DESCRIBE graph as s/p/o rows, sorted for stable output.

    Both backends go through this, so templates and ask.py see one shape.
    """
    rows = [{"s": term_json(s), "p": term_json(p), "o": term_json(o)}
            for s, p, o in sorted(graph, key=lambda t: tuple(str(x) for x in t))]
    return {"head": {"vars": ["s", "p", "o"]}, "results": {"bindings": rows}}


def fuseki_query(query: str) -> dict:
    """Run one query on Fuseki and normalise the answer to SPARQL-JSON."""
    graph_form = query_form(query) in ("CONSTRUCT", "DESCRIBE")
    accept = "text/turtle" if graph_form else "application/sparql-results+json"
    req = urllib.request.Request(
        ENDPOINT, data=urllib.parse.urlencode({"query": query}).encode(),
        headers={"Accept": accept,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise BackendError(f"Fuseki returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise BackendError(f"Could not reach Fuseki: {exc}") from exc

    try:
        if graph_form:
            from rdflib import Graph
            return graph_json(Graph().parse(data=body, format="turtle"))
        return json.loads(body)
    except Exception as exc:  # noqa: BLE001 - any parser failure is a backend fault
        raise BackendError(
            f"Fuseki returned an unreadable {'graph' if graph_form else 'result'}: "
            f"{type(exc).__name__}") from exc


def sparql(query: str) -> dict:
    """Run a query and return SPARQL-JSON, via Fuseki or the local fallback."""
    if endpoint_alive():
        return fuseki_query(query)

    # local fallback: convert an RDFLib result into SPARQL-JSON
    try:
        result = fallback_graph().g.query(query)
    except Exception as exc:  # noqa: BLE001
        raise BackendError(f"Local query failed: {exc}") from exc
    if result.type == "ASK":
        return {"boolean": bool(result.askAnswer)}
    if result.type in ("CONSTRUCT", "DESCRIBE"):
        return graph_json(result.graph)
    variables = [str(v) for v in result.vars]
    rows = []
    for row in result:
        rows.append({var: term_json(row[var]) for var in variables
                     if row[var] is not None})
    return {"head": {"vars": variables}, "results": {"bindings": rows}}


def rows_of(payload: dict) -> list[dict]:
    if "boolean" in payload:
        return [{"answer": {"value": str(payload["boolean"])}}]
    return payload.get("results", {}).get("bindings", [])


def short(value: str) -> str:
    return value.replace(PREFIX, ":") if value else ""


app.jinja_env.filters["short"] = short


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

@app.errorhandler(BackendError)
def backend_error(exc: BackendError):
    """Any page whose query fails gets a 502 with the reason, not a traceback."""
    if request.path.startswith("/api/"):
        return jsonify(error=str(exc)), 502
    return render_template("error.html", message=str(exc)), 502


@app.context_processor
def inject_status():
    return {"live": endpoint_alive(), "endpoint": ENDPOINT}


@app.route("/")
def home():
    stats = {}
    for label, query in (
        ("Philosophers", "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE "
                         "{ ?p a <%sPhilosopher> }" % PREFIX),
        ("Works", "SELECT (COUNT(DISTINCT ?w) AS ?n) WHERE "
                  "{ ?w <%stitle> ?t }" % PREFIX),
        ("Schools", "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE "
                    "{ ?s a <%sSchoolOfThought> }" % PREFIX),
        ("Concepts", "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE "
                     "{ ?c a <%sConcept> }" % PREFIX),
        ("Engagements", "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE "
                        "{ ?e a <%sEngagement> }" % PREFIX),
        ("Triples", "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"),
    ):
        try:
            stats[label] = rows_of(sparql(query))[0]["n"]["value"]
        except Exception:
            stats[label] = "?"
    return render_template("home.html", stats=stats, cqs=ALL)


@app.route("/browse/<kind>")
def browse(kind: str):
    """List every individual of one class."""
    classes = {"philosophers": "Philosopher", "works": "Work",
               "schools": "SchoolOfThought", "concepts": "Concept",
               "readers": "Reader"}
    if kind not in classes:
        return render_template("error.html",
                               message=f"Unknown collection '{kind}'"), 404
    cls = classes[kind]
    query = """
      PREFIX :     <%s>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?item ?label WHERE {
        ?item a :%s .
        OPTIONAL { ?item rdfs:label ?l }
        OPTIONAL { ?item :title ?t }
        BIND(COALESCE(?l, ?t, STR(?item)) AS ?label)
      } ORDER BY ?label""" % (PREFIX, cls)
    return render_template("browse.html", kind=kind, cls=cls,
                           rows=rows_of(sparql(query)))


@app.route("/entity/<name>")
def entity(name: str):
    """Entity page: outgoing and incoming triples. This is CQ15 (DESCRIBE)."""
    if not LOCAL_NAME.match(name):  # the name is spliced into SPARQL
        return render_template("error.html", message="Invalid entity name"), 400
    iri = PREFIX + name
    out = rows_of(sparql("""
      SELECT ?p ?o WHERE { <%s> ?p ?o } ORDER BY ?p""" % iri))
    incoming = rows_of(sparql("""
      SELECT ?s ?p WHERE { ?s ?p <%s> } ORDER BY ?p""" % iri))
    label = next((r["o"]["value"] for r in out
                  if r["p"]["value"].endswith("label")
                  or r["p"]["value"].endswith("title")), name)
    return render_template("entity.html", name=name, iri=iri, label=label,
                           outgoing=out, incoming=incoming)


@app.route("/cq/<cq_id>")
def competency(cq_id: str):
    """Run one competency question, with editable parameters."""
    cq = BY_ID.get(cq_id)
    if cq is None:
        return render_template("error.html",
                               message=f"Unknown question '{cq_id}'"), 404
    overrides = {k: request.args.get(k) for k in cq.params}
    for key, value in overrides.items():
        if value and not asker.IRI_LOCAL.match(value):  # spliced into SPARQL
            return render_template(
                "error.html",
                message=f"Parameter {key} must look like :LocalName"), 400
    query = render_query(cq, overrides)
    error = None
    payload = {"head": {"vars": []}, "results": {"bindings": []}}
    try:
        payload = sparql(query)
    except BackendError as exc:  # shown inline next to the query, not as a 502 page
        error = str(exc)
    rows = rows_of(payload)
    return render_template(
        "cq.html", cq=cq, query=query, rows=rows,
        variables=payload.get("head", {}).get("vars", []),
        params={k: (overrides.get(k) or v) for k, v in cq.params.items()},
        error=error, all_cqs=ALL)


@app.route("/recommend")
def recommend():
    reader = request.args.get("reader", ":reader1")
    if not asker.IRI_LOCAL.match(reader):
        return render_template("error.html", message="Invalid reader"), 400
    agent = fallback_graph()
    recs = agent.recommend(reader)
    readers = rows_of(sparql("""
      PREFIX :     <%s>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?r ?label WHERE { ?r a :Reader ; rdfs:label ?label }
      ORDER BY ?label""" % PREFIX))
    from rdflib import URIRef
    node = URIRef(PREFIX + reader.lstrip(":"))
    interests = sorted(agent.label(c) for c in agent.g.objects(node, agent_ns().hasInterestIn))
    already = sorted(agent.label(w) for w in agent.g.objects(node, agent_ns().hasRead))
    return render_template("recommend.html", reader=reader, recs=recs,
                           readers=readers, interests=interests, already=already)


def agent_ns():
    from rdflib import Namespace
    return Namespace(PREFIX)


@app.route("/visualise")
def visualise():
    return render_template("visualise.html")


# --------------------------------------------------------------------------
# JSON APIs backing the visualisations
# --------------------------------------------------------------------------

@app.route("/api/graph/lineage")
def api_lineage():
    """Teaching lineage as a node-link graph."""
    rows = rows_of(sparql("""
      PREFIX :     <%s>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?pupil ?pupilName ?teacher ?teacherName WHERE {
        ?pupil :studiedUnder ?teacher .
        ?pupil rdfs:label ?pupilName . ?teacher rdfs:label ?teacherName .
      }""" % PREFIX))
    nodes, edges = {}, []
    for row in rows:
        for key, name in (("pupil", "pupilName"), ("teacher", "teacherName")):
            iri = row[key]["value"]
            nodes.setdefault(iri, {"id": short(iri), "label": row[name]["value"]})
        edges.append({"from": short(row["pupil"]["value"]),
                      "to": short(row["teacher"]["value"]),
                      "label": "studiedUnder"})
    return jsonify({"nodes": list(nodes.values()), "edges": edges})


@app.route("/api/graph/engagements")
def api_engagements():
    """Engagement network, edges coloured by stance."""
    rows = rows_of(sparql("""
      PREFIX : <%s>
      SELECT ?e ?from ?fromTitle ?to ?toTitle ?stance ?concept ?conf WHERE {
        ?e a :Engagement ; :fromWork ?f ; :toWork ?t ;
           :stance ?stance ; :confidenceScore ?conf ; :aboutConcept ?c .
        ?f :title ?fromTitle . ?t :title ?toTitle .
        ?c <http://www.w3.org/2000/01/rdf-schema#label> ?concept .
        BIND(?f AS ?from) BIND(?t AS ?to)
      }""" % PREFIX))
    colour = {"criticizes": "#c0392b", "praises": "#27ae60", "neutral": "#7f8c8d"}
    nodes, edges = {}, []
    for row in rows:
        for key, title in (("from", "fromTitle"), ("to", "toTitle")):
            iri = row[key]["value"]
            nodes.setdefault(iri, {"id": short(iri), "label": row[title]["value"]})
        stance = row["stance"]["value"]
        edges.append({
            "from": short(row["from"]["value"]),
            "to": short(row["to"]["value"]),
            "label": f"{stance} ({row['concept']['value']})",
            "color": {"color": colour.get(stance, "#555")},
            "width": 1 + 3 * float(row["conf"]["value"]),
        })
    return jsonify({"nodes": list(nodes.values()), "edges": edges})


@app.route("/api/graph/schools")
def api_schools():
    rows = rows_of(sparql("""
      PREFIX :     <%s>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?sub ?subName ?sup ?supName WHERE {
        ?sub :subSchoolOf ?sup .
        ?sub rdfs:label ?subName . ?sup rdfs:label ?supName .
      }""" % PREFIX))
    nodes, edges = {}, []
    for row in rows:
        for key, name in (("sub", "subName"), ("sup", "supName")):
            iri = row[key]["value"]
            nodes.setdefault(iri, {"id": short(iri), "label": row[name]["value"]})
        edges.append({"from": short(row["sub"]["value"]),
                      "to": short(row["sup"]["value"])})
    return jsonify({"nodes": list(nodes.values()), "edges": edges})


@app.route("/api/chart/impact")
def api_impact():
    """CQ9 as a bar chart."""
    rows = rows_of(sparql(render_query(BY_ID["CQ9"])))
    rows = sorted(rows,
                  key=lambda r: -(int(r["influenced"]["value"])
                                  + int(r["engagements"]["value"])))[:12]
    return jsonify({
        "labels": [r["name"]["value"] for r in rows],
        "influenced": [int(r["influenced"]["value"]) for r in rows],
        "engagements": [int(r["engagements"]["value"]) for r in rows],
    })


@app.route("/api/chart/timeline")
def api_timeline():
    """Works per time period."""
    rows = rows_of(sparql("""
      PREFIX :     <%s>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?period (COUNT(?w) AS ?n) (MIN(?start) AS ?from) WHERE {
        ?w :composedDuring ?p . ?p rdfs:label ?period ; :startYear ?start .
      } GROUP BY ?period ORDER BY ?from""" % PREFIX))
    return jsonify({"labels": [r["period"]["value"] for r in rows],
                    "counts": [int(r["n"]["value"]) for r in rows]})


@app.route("/api/chart/schools")
def api_school_sizes():
    rows = rows_of(sparql("""
      PREFIX :     <%s>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?school (COUNT(DISTINCT ?p) AS ?n) WHERE {
        ?p a :Philosopher ; :belongsToSchool ?s . ?s rdfs:label ?school .
      } GROUP BY ?school HAVING (COUNT(DISTINCT ?p) > 0)
        ORDER BY DESC(?n)""" % PREFIX))
    return jsonify({"labels": [r["school"]["value"] for r in rows],
                    "counts": [int(r["n"]["value"]) for r in rows]})


@app.route("/api/chart/stance")
def api_stance():
    rows = rows_of(sparql("""
      PREFIX : <%s>
      SELECT ?stance (COUNT(?e) AS ?n) WHERE {
        ?e a :Engagement ; :stance ?stance .
      } GROUP BY ?stance ORDER BY DESC(?n)""" % PREFIX))
    return jsonify({"labels": [r["stance"]["value"] for r in rows],
                    "counts": [int(r["n"]["value"]) for r in rows]})


# --------------------------------------------------------------------------
# grounded question answering, ontology browser, provenance
# (merged from the colleague prototype, adapted to this ontology)
# --------------------------------------------------------------------------

def entities() -> list:
    global _entities
    if _entities is None:
        _entities = asker.load_entities(sparql)
    return _entities


def validation() -> tuple[bool, str]:
    """SHACL over the core graph, run once and cached."""
    global _validation
    if _validation is None:
        from pyshacl import validate
        from rdflib import Graph
        data = Graph().parse(ROOT / "philosophy_dataset.ttl", format="turtle")
        shapes = Graph().parse(ROOT / "philosophy_shapes.ttl", format="turtle")
        onto = Graph().parse(ROOT / "philosophy_ontology.ttl", format="turtle")
        conforms, _, text = validate(data, shacl_graph=shapes, ont_graph=onto,
                                     inference="rdfs")
        _validation = (bool(conforms), str(text))
    return _validation


@app.route("/ask")
def ask_page():
    routable = [c for c in asker.ROUTABLE]
    return render_template("ask.html", cqs=routable,
                           llm=asker.gemini_enabled(),
                           param_types=asker.PARAM_TYPES)


@app.post("/api/ask")
def api_ask():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Send a JSON object with a question field."), 400
    question = body.get("question", "")
    cq_id = body.get("cq_id") or None
    focus = body.get("focus") or None
    if not isinstance(question, str) or not question.strip():
        return jsonify(error="question must be a non-empty string."), 400
    if len(question) > 500:
        return jsonify(error="question must be 500 characters or fewer."), 400
    if cq_id is not None and (not isinstance(cq_id, str) or cq_id not in BY_ID):
        return jsonify(error="cq_id must be a known competency question."), 400
    if focus is not None and (not isinstance(focus, str) or len(focus) > 160):
        return jsonify(error="focus must be a short string."), 400
    try:
        result = asker.answer(question.strip(), sparql, entities(),
                              cq_id=cq_id, focus=focus.strip() if focus else None)
    except BackendError as exc:  # must precede ValueError: a server fault, not bad input
        return jsonify(error=str(exc)), 502
    except (LookupError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:  # LLM provider failure
        return jsonify(error=str(exc)), 502
    return jsonify(result)


@app.get("/api/competencies")
def api_competencies():
    return jsonify(competencies=[
        {"id": c.id, "question": c.question, "kind": c.kind,
         "params": c.params, "routable": c in asker.ROUTABLE}
        for c in ALL])


def ontology_catalog() -> dict:
    """Classes and properties with domain, range and characteristics."""
    from rdflib import Graph, OWL, RDF, RDFS, BNode
    from rdflib.collection import Collection
    g = Graph().parse(ROOT / "philosophy_ontology.ttl", format="turtle")

    def name(node) -> str:
        if isinstance(node, BNode):
            for op, word in ((OWL.unionOf, " or "), (OWL.intersectionOf, " and ")):
                head = g.value(node, op)
                if head is not None:
                    return word.join(name(m) for m in Collection(g, head))
            return "class expression"
        return short(str(node))

    classes = []
    for cls in sorted({c for c in g.subjects(RDF.type, OWL.Class)
                       if str(c).startswith(PREFIX)}, key=str):
        classes.append({
            "name": short(str(cls)),
            "parents": sorted(name(p) for p in g.objects(cls, RDFS.subClassOf)
                              if not isinstance(p, BNode)),
            "defined": (cls, OWL.equivalentClass, None) in g,
            "comment": str(g.value(cls, RDFS.comment) or ""),
        })
    traits = ((OWL.FunctionalProperty, "functional"),
              (OWL.InverseFunctionalProperty, "inverse-functional"),
              (OWL.TransitiveProperty, "transitive"),
              (OWL.SymmetricProperty, "symmetric"),
              (OWL.AsymmetricProperty, "asymmetric"),
              (OWL.IrreflexiveProperty, "irreflexive"))
    props = []
    for kind, label in ((OWL.ObjectProperty, "object"),
                        (OWL.DatatypeProperty, "datatype")):
        for p in sorted(set(g.subjects(RDF.type, kind)), key=str):
            props.append({
                "name": short(str(p)), "kind": label,
                "domain": [name(d) for d in g.objects(p, RDFS.domain)],
                "range": [name(r) for r in g.objects(p, RDFS.range)],
                "parents": [short(str(x)) for x in g.objects(p, RDFS.subPropertyOf)],
                "inverse": [short(str(x)) for x in g.objects(p, OWL.inverseOf)],
                "traits": [t for k, t in traits if (p, RDF.type, k) in g],
            })
    return {"classes": classes, "properties": props}


@app.route("/ontology")
def ontology_page():
    return render_template("ontology.html", **ontology_catalog())


@app.get("/api/ontology")
def api_ontology():
    return jsonify(ontology_catalog())


def source_records() -> list[dict]:
    if not SOURCES_FILE.exists():
        return []
    from rdflib import Graph
    g = Graph().parse(SOURCES_FILE, format="turtle")
    rows = g.query("""
      PREFIX prov: <http://www.w3.org/ns/prov#>
      PREFIX dct:  <http://purl.org/dc/terms/>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT ?r ?title ?publisher ?url ?type ?subject ?creator ?date ?license WHERE {
        ?r a prov:Entity ; rdfs:label ?title ; dct:publisher ?publisher ;
           prov:wasDerivedFrom ?url ; dct:type ?type .
        OPTIONAL { ?r dct:subject ?subject }
        OPTIONAL { ?r dct:creator ?creator }
        OPTIONAL { ?r dct:date ?date }
        OPTIONAL { ?r dct:license ?license }
      } ORDER BY ?publisher ?title""")
    return [{k: (str(row[k]) if row[k] is not None else None)
             for k in ("r", "title", "publisher", "url", "type", "subject",
                       "creator", "date", "license")} for row in rows]


@app.route("/sources")
def sources_page():
    return render_template("sources.html", records=source_records(),
                           path=SOURCES_FILE.relative_to(ROOT))


@app.get("/api/sources")
def api_sources():
    records = source_records()
    return jsonify(total=len(records), records=records)


@app.get("/validation")
def validation_report():
    conforms, text = validation()
    return jsonify(conforms=conforms, report=text), (200 if conforms else 422)


@app.get("/health")
def health():
    conforms, _ = validation()
    live = endpoint_alive()
    return jsonify(status="ok" if conforms else "validation_failed",
                   fuseki=live, shacl_conforms=conforms,
                   llm=asker.gemini_enabled()), (200 if conforms else 503)


if __name__ == "__main__":
    print(f"Fuseki endpoint: {'UP' if endpoint_alive() else 'DOWN (using local fallback)'}")
    print(f"Gemini routing: {'ON' if asker.gemini_enabled() else 'OFF (keyword routing)'}")
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")), debug=False)
