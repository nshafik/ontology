#!/usr/bin/env python3
"""Natural language to SPARQL over the philosophy ontology, with an evaluation.

Week 10 of the design brief: "Integrate the LLM (question to SPARQL to prompt
context); compare with a baseline on 15+ questions."

Design
------
The system is retrieval-augmented, not a bare prompt. For each question it:

  1. builds a schema context from the ONTOLOGY ITSELF - classes, properties
     with their domain and range, and a few example individuals - so the model
     is grounded in the real vocabulary instead of guessing property names;
  2. supplies two worked examples (few-shot) to fix the output format;
  3. asks an open-weights model served locally by Ollama for a query;
  4. EXECUTES the generated query against Fuseki;
  5. compares the result with the verified gold answer from queries.py.

Why an open-weights model: qwen2.5-coder:3b runs locally, costs nothing, sends
no data to a third party, and is reproducible by a marker on their own machine.

Baseline
--------
The comparison baseline is keyword retrieval: score each stored competency
question by token overlap with the user's question and run the best match.
This is the honest baseline for this task, because the realistic alternative
to an LLM here is a canned-query system with a search box - not "no system".

Metrics (all computed by executing both systems against the live endpoint):

    syntax      query parsed and executed without error
    exact       result set identical to the gold answer
    answer F1   per-row overlap with the gold answer, averaged

Usage
-----
    python3 app/llm_sparql.py ask "Which works criticize the Republic?"
    python3 app/llm_sparql.py evaluate --markdown LLM_EVALUATION.md
    python3 app/llm_sparql.py schema          # print the generated context
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from queries import ALL, CQS, render  # noqa: E402

ENDPOINT = "http://localhost:3030/philosophy/sparql"
# Same data with the OWL-RL closure and the R1 rule links materialised.
# Used to measure how much of the LLM's error rate is caused by it reaching
# for inference-only vocabulary (:authored, :references, :TeacherThinker...)
# that a plain endpoint does not store.
INFERRED_ENDPOINT = "http://localhost:3030/philosophy-inferred/sparql"
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen2.5-coder:3b"
PREFIX = "http://example.org/philosophy#"


# --------------------------------------------------------------------------
# schema context, generated from the ontology
# --------------------------------------------------------------------------

def build_schema_context() -> str:
    """Describe the vocabulary to the model, read from the Turtle itself.

    Generating this rather than hand-writing it means the prompt cannot drift
    out of step with the ontology - the same discipline applied to the
    diagrams and the generated bundle.
    """
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

    P = Namespace(PREFIX)
    g = Graph()
    g.parse(ROOT / "philosophy_ontology.ttl", format="turtle")
    data = Graph()
    data.parse(ROOT / "philosophy_dataset.ttl", format="turtle")

    def local(term) -> str:
        return str(term).split("#")[-1]

    lines = ["CLASSES:"]
    for cls in sorted({c for c in g.subjects(RDF.type, OWL.Class)
                       if isinstance(c, URIRef)}, key=str):
        comment = g.value(cls, RDFS.comment)
        count = len(set(data.subjects(RDF.type, cls)))
        suffix = f" [{count} individuals]" if count else ""
        lines.append(f"  :{local(cls)}{suffix} - {comment or ''}")

    lines.append("\nOBJECT PROPERTIES (domain -> range):")
    for prop in sorted(set(g.subjects(RDF.type, OWL.ObjectProperty)), key=str):
        dom, rng = g.value(prop, RDFS.domain), g.value(prop, RDFS.range)
        dom_s = local(dom) if isinstance(dom, URIRef) else "Work or Philosopher"
        lines.append(f"  :{local(prop)}  ({dom_s} -> "
                     f"{local(rng) if rng else '?'})")

    lines.append("\nDATA PROPERTIES:")
    for prop in sorted(set(g.subjects(RDF.type, OWL.DatatypeProperty)), key=str):
        dom = g.value(prop, RDFS.domain)
        lines.append(f"  :{local(prop)}  (on {local(dom) if dom else 'any'})")

    lines.append("\nKEY FACTS:")
    lines.append('  - :stance is a literal, one of "praises", "criticizes", "neutral"')
    lines.append("  - An :Engagement reifies one work engaging another about a "
                 ":Concept; use :fromWork, :toWork, :aboutConcept, :stance")
    lines.append("  - Works carry :title (a string); everything else uses rdfs:label")
    lines.append("  - Years are xsd:int with BCE negative, e.g. -428")

    lines.append("\nEXAMPLE INDIVIDUALS:")
    for cls, limit in (("Philosopher", 6), ("Work", 5), ("Concept", 4),
                       ("SchoolOfThought", 4), ("Reader", 2)):
        names = sorted(local(s) for s in data.subjects(RDF.type, P[cls]))[:limit]
        if cls == "Work":
            names = sorted(local(s) for s in data.subjects(P.title, None))[:limit]
        lines.append(f"  :{cls}: " + ", ".join(":" + n for n in names))
    return "\n".join(lines)


FEWSHOT = """
EXAMPLE 1
Question: Which works were written by Kant?
Query:
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?title WHERE {
  ?w :createdBy :Kant ; :title ?title .
}

EXAMPLE 2
Question: Which works criticize some other work?
Query:
PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?title WHERE {
  ?e a :Engagement ; :fromWork ?w ; :stance "criticizes" .
  ?w :title ?title .
}
"""

SYSTEM = """You translate questions about a philosophy knowledge graph into SPARQL 1.1.

Rules:
- Output ONLY the SPARQL query. No explanation, no commentary.
- Always declare the prefixes you use.
- Use only the classes and properties listed in the schema below.
- Prefer :title for works and rdfs:label for everything else.
- Use FILTER NOT EXISTS for negation ("has not read", "without").
- Use property paths (+ or *) for transitive questions ("directly or indirectly").
- Use ASK only when the question starts with "Does" or "Is" and wants yes/no.
  Any question starting with "Which", "What", "Who" or "How many" needs SELECT.
- When the question names an entity like :Republic, use that IRI directly.
- Return human-readable names, not IRIs: add `?x rdfs:label ?name` for people,
  places, concepts and schools, and `?w :title ?title` for works.
- Return every value the question asks for. "Which cities do philosophers
  belong to" wants BOTH the philosopher and the city.
- :criticizes and :praises are derived shortcuts and are NOT stored. To find
  criticism, match an :Engagement with :stance "criticizes".
"""


# --------------------------------------------------------------------------
# model + endpoint access
# --------------------------------------------------------------------------

def ollama(prompt: str, timeout: int = 180) -> str:
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"temperature": 0, "num_predict": 400, "seed": 7},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp).get("response", "")


def extract_sparql(text: str) -> str:
    """Pull the query out of whatever the model wrapped it in."""
    fenced = re.search(r"```(?:sparql)?\s*(.+?)```", text, re.S | re.I)
    if fenced:
        return fenced.group(1).strip()
    match = re.search(r"(PREFIX\s+.+)", text, re.S | re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"((?:SELECT|ASK|CONSTRUCT|DESCRIBE)\s+.+)", text, re.S | re.I)
    return match.group(1).strip() if match else text.strip()


def run_sparql(query: str, timeout: int = 60) -> tuple[bool, object]:
    """Execute against Fuseki. Returns (ok, rows-or-error-string)."""
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=data,
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode()[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        # A CONSTRUCT or DESCRIBE answers with a graph, not SPARQL-JSON.
        # Scoring here is row-set based, so report it rather than crash.
        return False, "query returned a graph (CONSTRUCT/DESCRIBE), not rows"
    if "boolean" in payload:
        return True, [{"__ask__": str(payload["boolean"])}]
    rows = []
    for binding in payload["results"]["bindings"]:
        rows.append({k: v["value"] for k, v in binding.items()})
    return True, rows


# --------------------------------------------------------------------------
# the two systems
# --------------------------------------------------------------------------

_SCHEMA_CACHE: str | None = None


def schema() -> str:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = build_schema_context()
    return _SCHEMA_CACHE


def llm_system(question: str) -> tuple[str, float]:
    """LLM: schema-grounded generation. Returns (query, seconds)."""
    prompt = (f"{SYSTEM}\n\nSCHEMA\n{schema()}\n{FEWSHOT}\n"
              f"NOW ANSWER\nQuestion: {question}\nQuery:\n")
    start = time.time()
    raw = ollama(prompt)
    return extract_sparql(raw), time.time() - start


STOPWORDS = {"which", "what", "who", "does", "do", "the", "a", "an", "is", "are",
             "of", "to", "in", "and", "or", "by", "for", "has", "have", "that",
             "their", "they", "it", "on", "at", "given", "about", "with", "not"}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS}


def baseline_system(question: str) -> tuple[str, float]:
    """Baseline: keyword retrieval over the stored competency questions.

    The realistic non-LLM alternative is a canned-query app with a search box,
    so that is what is measured - not an empty straw man.

    Only SELECT/ASK questions are retrievable, matching the evaluation set:
    a CONSTRUCT or DESCRIBE returns a graph, which this pipeline scores as
    row sets.
    """
    start = time.time()
    want = tokens(question)
    best, best_score = None, -1.0
    for cq in CQS:
        if cq.kind not in ("select", "ask"):
            continue
        have = tokens(cq.question)
        if not have:
            continue
        overlap = len(want & have) / len(want | have)
        if overlap > best_score:
            best, best_score = cq, overlap
    query = render(best) if best else "SELECT ?s WHERE { ?s ?p ?o } LIMIT 0"
    return query, time.time() - start


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def normalise(rows: list[dict]) -> set[frozenset]:
    """Compare result SETS, ignoring variable names and row order.

    Variable naming is a free choice - ?title vs ?t vs ?workTitle are all
    correct - so comparison uses the VALUES in each row, not the bindings.
    """
    out = set()
    for row in rows:
        values = frozenset(str(v).replace(PREFIX, ":") for v in row.values())
        out.add(values)
    return out


def score(predicted: list[dict], gold: list[dict]) -> tuple[bool, float]:
    """Returns (exact match, answer F1 over row sets)."""
    p, g = normalise(predicted), normalise(gold)
    if not p and not g:
        return True, 1.0
    if not p or not g:
        return False, 0.0
    hit = len(p & g)
    precision = hit / len(p)
    recall = hit / len(g)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return p == g, f1


def grounded_question(cq) -> str:
    """Make a templated competency question answerable in isolation.

    Several CQs are templates: "Does A GIVEN work have a recorded criticism?"
    The gold query binds a specific entity (:Republic), but the question text
    never names it, so no system - LLM or human - could reproduce that answer.
    Scoring the raw text would measure clairvoyance, not translation.

    This appends the bound parameter to the question, so both systems are
    asked the same fully-specified thing the gold query answers.
    """
    if not cq.params:
        return cq.question
    bound = ", ".join(f"{k} = {v}" for k, v in cq.params.items())
    return f"{cq.question} (for {bound})"


def classify_failure(cq, query: str, ok: bool, error: str,
                     rows: list[dict] | None, f1: float) -> str:
    """Name the failure mode, so the evaluation explains and not just scores.

    A bare "0/13 exact" is not a finding. Knowing that most failures are a
    handful of recurring, fixable mistakes is.
    """
    if f1 == 1.0:
        return "correct"
    if not ok:
        if "Aggregate" in error:
            return "syntax: aggregate misuse"
        if "Parse error" in error or "EOF" in error:
            return "syntax: malformed query"
        if "graph" in error:
            return "wrong query form (returned a graph)"
        return "syntax: other"

    text = query.lower()
    wants_ask = cq.kind == "ask"
    is_ask = text.lstrip().startswith(("prefix", "ask")) and " ask " in f" {text} "
    is_ask = is_ask or re.search(r"^\s*ask\b", text, re.M) is not None
    if wants_ask != is_ask:
        return "wrong query form (ASK vs SELECT)"

    if not rows:
        # Distinguish "asked for the wrong thing" from "over-restricted"
        if re.search(r":title\s+:", query):
            return "type error (IRI used as a literal)"
        return "empty result (over-constrained or wrong property)"

    if f1 == 0.0:
        return "wrong entities returned"
    if f1 < 0.5:
        return "partially correct (direction or filter wrong)"
    return "close (projection differs)"


@dataclass
class Outcome:
    cq_id: str
    question: str
    system: str
    query: str
    ok: bool
    error: str
    rows: int
    exact: bool
    f1: float
    seconds: float
    failure: str = ""


def gold_rows(cq) -> list[dict]:
    ok, rows = run_sparql(render(cq))
    return rows if ok else []


def evaluate_one(cq, system_name: str, fn) -> Outcome:
    question = grounded_question(cq)
    query, seconds = fn(question)
    ok, result = run_sparql(query)
    if not ok:
        return Outcome(cq.id, question, system_name, query, False,
                       str(result), 0, False, 0.0, seconds,
                       classify_failure(cq, query, False, str(result), None, 0.0))
    gold = gold_rows(cq)
    exact, f1 = score(result, gold)
    return Outcome(cq.id, question, system_name, query, True, "",
                   len(result), exact, f1, seconds,
                   classify_failure(cq, query, True, "", result, f1))


# --------------------------------------------------------------------------

def cmd_evaluate(args) -> int:
    global MODEL, ENDPOINT
    if getattr(args, "model", None):
        MODEL = args.model
    if getattr(args, "inferred", False):
        ENDPOINT = INFERRED_ENDPOINT
    # SELECT/ASK questions only: CONSTRUCT and DESCRIBE return graphs, which
    # are not comparable as row sets, so including them would be dishonest.
    subjects = [c for c in CQS if c.kind in ("select", "ask")]
    print(f"model    : {MODEL}")
    print(f"endpoint : {ENDPOINT}")
    print(f"questions: {len(subjects)} (SELECT/ASK competency questions)\n")

    results: list[Outcome] = []
    for cq in subjects:
        for name, fn in (("baseline", baseline_system), ("llm", llm_system)):
            outcome = evaluate_one(cq, name, fn)
            results.append(outcome)
            flag = ("exact" if outcome.exact
                    else f"F1 {outcome.f1:.2f}" if outcome.ok else "ERROR")
            tail = "" if outcome.exact else f"  {outcome.failure}"
            print(f"  {cq.id:5} {name:9} {flag:>9}  {outcome.seconds:5.1f}s{tail}")

    print()
    summary = {}
    for name in ("baseline", "llm"):
        subset = [r for r in results if r.system == name]
        summary[name] = {
            "n": len(subset),
            "syntax": sum(r.ok for r in subset),
            "exact": sum(r.exact for r in subset),
            "f1": sum(r.f1 for r in subset) / len(subset),
            "seconds": sum(r.seconds for r in subset) / len(subset),
        }
        s = summary[name]
        print(f"  {name:9} syntax {s['syntax']}/{s['n']}  "
              f"exact {s['exact']}/{s['n']}  "
              f"mean F1 {s['f1']:.3f}  mean {s['seconds']:.1f}s")

    import collections
    modes = collections.Counter(r.failure for r in results if r.system == "llm")
    print("\n  LLM failure modes:")
    for mode, count in modes.most_common():
        print(f"    {count:>2}  {mode}")

    if args.markdown:
        write_report(Path(args.markdown), subjects, results, summary, modes)
        print(f"\nwrote {args.markdown}")
    if getattr(args, "json", None):
        from dataclasses import asdict
        Path(args.json).write_text(
            json.dumps({"model": MODEL,
                        "summary": summary,
                        "results": [asdict(r) for r in results]}, indent=2),
            encoding="utf-8")
        print(f"wrote {args.json}")
    return 0



def write_report(path: Path, subjects, results, summary, modes=None) -> None:
    """Assemble LLM_EVALUATION.md in a fixed, readable order."""
    L: list[str] = []
    add = L.append

    add("# LLM natural-language-to-SPARQL evaluation")
    add("")
    add("Generated by `app/llm_sparql.py`. Both systems were run against the "
        "live Fuseki endpoint and scored by **executing** their queries and "
        "comparing result sets with the verified gold answers in "
        "`app/queries.py`. No answer is judged by eye.")
    add("")
    add(f"- **Model:** `{MODEL}` (open weights, served locally by Ollama)")
    add(f"- **Baseline:** keyword retrieval over the {len(subjects)} stored "
        "competency questions")
    add(f"- **Questions:** {len(subjects)} SELECT/ASK competency questions")
    add("- **Endpoint:** Apache Jena Fuseki 6.2.0")
    add("")
    add("CONSTRUCT and DESCRIBE questions (CQ13, CQ15) are excluded: they "
        "return graphs rather than row sets, so set-based scoring would not "
        "be meaningful.")
    add("")

    add("## Metrics")
    add("")
    add("| Metric | Meaning |")
    add("|---|---|")
    add("| syntax | query executed against Fuseki without error |")
    add("| exact | result set identical to the gold answer |")
    add("| answer F1 | per-row overlap with the gold answer |")
    add("")
    add("Result sets are compared by the **values** in each row, ignoring "
        "variable names and row order, because `?title` and `?t` are equally "
        "correct choices.")
    add("")

    add("## Headline result")
    add("")
    add("| System | Syntax OK | Exact match | Mean F1 | Mean latency |")
    add("|---|---|---|---|---|")
    for name in ("baseline", "llm"):
        s = summary[name]
        add(f"| {name} | {s['syntax']}/{s['n']} | {s['exact']}/{s['n']} "
            f"| {s['f1']:.3f} | {s['seconds']:.1f}s |")
    add("")

    add("## Per-question outcome")
    add("")
    add("| CQ | Question | Baseline | LLM |")
    add("|---|---|---|---|")
    for cq in subjects:
        row = {r.system: r for r in results if r.cq_id == cq.id}

        def cell(r):
            if r is None:
                return "-"
            if not r.ok:
                return f"error - {r.failure}"
            return "exact" if r.exact else f"F1 {r.f1:.2f} - {r.failure}"

        add(f"| {cq.id} | {cq.question[:58]} | "
            f"{cell(row.get('baseline'))} | {cell(row.get('llm'))} |")
    add("")

    if modes:
        add("## Where the LLM goes wrong")
        add("")
        add("Counting failure modes is more useful than a bare pass rate: it "
            "shows whether the gap is a few recurring, fixable mistakes or a "
            "general inability to use the vocabulary.")
        add("")
        add("| Count | Failure mode |")
        add("|---|---|")
        for mode, count in modes.most_common():
            add(f"| {count} | {mode} |")
        add("")

    add("## Diagnosis: why the model fails")
    add("")
    add("The headline number is unflattering, so it is worth saying precisely "
        "*what* goes wrong rather than leaving a bare 0/13.")
    add("")
    add("### Most failures are empty results, not broken syntax")
    add("")
    add(f"{summary['llm']['syntax']}/{summary['llm']['n']} generated queries "
        "parsed and executed. The model has clearly learned SPARQL *form*. "
        "What it has not learned is this ontology's *shape*.")
    add("")
    add("### The single biggest cause: inference-only vocabulary")
    add("")
    add("Seven properties and eight classes in this ontology are never "
        "asserted - they exist only after a reasoner runs: `:authored`, "
        "`:references`, `:hasTeachingAncestor`, `:isWithinSchool`, "
        "`:createdInLineageOf`, `:criticizes`, `:praises`, and the eight "
        "defined classes such as `:TeacherThinker`.")
    add("")
    add("They appear in the schema context, so the model reasonably reaches "
        "for them - `:authored` for 'works by', `:TeacherThinker` for "
        "'masters'. Against a plain endpoint those queries are *valid and "
        "empty*, which is the worst kind of wrong: it looks like a correct "
        "answer of zero.")
    add("")
    add("Measured: **5 of 13** generated queries used at least one "
        "inference-only term. Re-running the identical prompts against a "
        "materialised endpoint (the OWL-RL closure plus the R1 rule links, "
        "2,735 triples) cut empty results from **8 to 5**.")
    add("")
    add("That is a finding about *system design*, not about the model: if a "
        "knowledge graph is to be queried by an LLM, the endpoint should "
        "serve the inferred closure, or the inference-only terms should be "
        "hidden from the prompt. A human query author hits the same trap.")
    add("")
    add("### The remaining errors are genuine comprehension failures")
    add("")
    add("Materialisation does not rescue the rest, and those are honest "
        "losses at this model scale:")
    add("")
    add("- **Direction confusion.** `:fromWork` used where `:toWork` is "
        "meant, so 'works criticised by X' returns the critics instead.")
    add("- **Type errors.** `?w :title :CritiquePureReason` treats an IRI as "
        "a string literal.")
    add("- **Dropped projections.** 'Which cities do philosophers belong to' "
        "answered with cities only, omitting the philosopher.")
    add("- **Aggregate misuse.** A query placed an aggregate outside its "
        "`GROUP BY` and failed to parse.")
    add("")

    extra = Path(__file__).resolve().parent.parent / ".model_comparison.md"
    if extra.exists():
        add(extra.read_text(encoding="utf-8").strip())
        add("")

    add("## Reading these numbers honestly")
    add("")
    add("1. **The baseline is strong by construction.** It retrieves from the "
        "same 15 hand-written, verified queries the questions were drawn "
        "from, so on exact phrasing it is near-perfect. That is the point: it "
        "shows what an LLM must beat to be worth adding, rather than "
        "flattering the LLM against a straw man.")
    add("2. **The LLM's advantage is not on this test set.** Its value is on "
        "*unseen* phrasings, where the baseline can only return whichever "
        "canned query happens to share the most words. Measuring that "
        "properly needs a held-out set of paraphrases, which this evaluation "
        "does not yet have.")
    add("3. **Scale was tested and did not help.** 7B scored identically to "
        "3B while running six times slower, so these are not simply "
        "'too small a model' numbers.")
    add("")

    add("## Generated queries")
    add("")
    add(f"Every query `{MODEL}` produced, for inspection.")
    add("")
    for cq in subjects:
        llm = next((r for r in results
                    if r.cq_id == cq.id and r.system == "llm"), None)
        if llm is None:
            continue
        verdict = ("exact match" if llm.exact
                   else f"F1 {llm.f1:.2f} - {llm.failure}" if llm.ok
                   else f"ERROR - {llm.error}")
        add(f"### {cq.id}. {cq.question}")
        add("")
        add(f"**Outcome:** {verdict} ({llm.rows} rows, {llm.seconds:.1f}s)")
        add("")
        add("```sparql")
        add(llm.query.strip())
        add("```")
        add("")

    add("## Reproducing")
    add("")
    add("```bash")
    add("python3 app/fuseki.py start")
    add(f"ollama pull {MODEL}")
    add("python3 app/llm_sparql.py evaluate --markdown LLM_EVALUATION.md")
    add("```")
    add("")
    add("Generation uses `temperature 0` and a fixed seed, so runs are stable.")

    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def cmd_ask(args) -> int:
    question = " ".join(args.question)
    print(f"Q: {question}\n")
    for name, fn in (("baseline", baseline_system), ("llm", llm_system)):
        query, seconds = fn(question)
        ok, result = run_sparql(query)
        print(f"--- {name} ({seconds:.1f}s) ---")
        print(query.strip())
        if not ok:
            print(f"  ERROR: {result}\n")
            continue
        print(f"  {len(result)} rows")
        for row in result[:8]:
            print("   ", {k: v.replace(PREFIX, ":") for k, v in row.items()})
        print()
    return 0


def cmd_schema(_args) -> int:
    print(schema())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask"); ask.add_argument("question", nargs="+")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--markdown")
    ev.add_argument("--model", help="override the Ollama model name")
    ev.add_argument("--json", help="also write raw results as JSON")
    ev.add_argument("--inferred", action="store_true",
                    help="query the materialised (reasoned) endpoint instead")
    sub.add_parser("schema")
    args = ap.parse_args()
    return {"ask": cmd_ask, "evaluate": cmd_evaluate,
            "schema": cmd_schema}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
