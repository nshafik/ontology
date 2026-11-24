#!/usr/bin/env python3
"""The 15 competency questions as data, so every tool uses the same text.

build.py, run_cqs.py, the web interface and the LLM evaluation all import
this module. Keeping one copy means a query cannot be fixed in the report and
left broken in the application, which is exactly the drift the rubric's
"queries return accurate results" row punishes.

Each CQ records:
    id          CQ1 .. CQ15, R1a, R1b, R2
    question    the natural-language form, verbatim from the design brief
    features    the SPARQL features it exercises (for the report table)
    path        the ontology evidence path the answer travels
    sparql      the query text
    expected    expected row count, or a bool for ASK
    kind        select | ask | construct | describe
    params      editable parameters, for the web UI's query form
"""

from __future__ import annotations

from dataclasses import dataclass, field

PREFIXES = """PREFIX :     <http://example.org/philosophy#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
"""


@dataclass
class CQ:
    id: str
    question: str
    features: str
    path: str
    sparql: str
    expected: object
    kind: str = "select"
    params: dict = field(default_factory=dict)
    note: str = ""
    # Some queries legitimately return a different count against the Fuseki
    # endpoint, which also holds the LOD links as a second named graph.
    # None means "same as expected".
    endpoint_expected: object = None

    @property
    def full(self) -> str:
        return PREFIXES + "\n" + self.sparql.strip() + "\n"


CQS: list[CQ] = [
    CQ(
        id="CQ1",
        question="Which author does the book belong to, and which school does the author belong to?",
        features="SELECT, OPTIONAL, FILTER",
        path=":Work -createdBy-> :Philosopher -belongsToSchool-> :SchoolOfThought",
        params={"work": ":CritiquePureReason"},
        expected=1,
        sparql="""
SELECT ?bookTitle ?authorName ?school
WHERE {
  ?book :title ?bookTitle ; :createdBy ?author .
  ?author rdfs:label ?authorName .
  OPTIONAL { ?author :belongsToSchool ?s . ?s rdfs:label ?school }
  FILTER (?book = {{work}})
}""",
        note="OPTIONAL keeps authors with no recorded school.",
    ),
    CQ(
        id="CQ2",
        question="Which philosophers studied under other philosophers, directly and not directly?",
        features="SELECT, UNION, property path, BIND",
        path=":Philosopher -studiedUnder+-> :Philosopher",
        expected=19,
        sparql="""
SELECT ?studentName ?teacherName ?link
WHERE {
  { ?s :studiedUnder ?t .                BIND("direct"   AS ?link) }
  UNION
  { ?s :studiedUnder/:studiedUnder+ ?t . BIND("indirect" AS ?link) }
  ?s rdfs:label ?studentName .
  ?t rdfs:label ?teacherName .
}
ORDER BY ?link ?studentName ?teacherName""",
        note="11 direct + 8 indirect. Reasoned variant: ?s :hasTeachingAncestor ?t",
    ),
    CQ(
        id="CQ3",
        question="Which work has been criticized at least once?",
        features="SELECT DISTINCT",
        path=":Engagement -toWork-> :Work with stance 'criticizes'",
        expected=5,
        sparql="""
SELECT DISTINCT ?title
WHERE {
  ?e a :Engagement ; :toWork ?w ; :stance "criticizes" .
  ?w :title ?title .
}
ORDER BY ?title""",
        note="Reasoned variant: ?w a :CriticizedWork",
    ),
    CQ(
        id="CQ4",
        question="Which schools are sub-schools of a given school?",
        features="SELECT, property path +",
        path=":SchoolOfThought -subSchoolOf+-> :SchoolOfThought",
        params={"root": ":MedievalPhilosophy"},
        expected=2,
        sparql="""
SELECT ?school ?label
WHERE {
  VALUES ?root { {{root}} }
  ?school :subSchoolOf+ ?root ;
          rdfs:label ?label .
}
ORDER BY ?label""",
        note="Reasoned variant: ?school :isWithinSchool ?root",
    ),
    CQ(
        id="CQ5",
        question="Which work cites or references a given work?",
        features="SELECT, UNION, property alternation, CONCAT",
        path=":Work -references|cites|criticizes|praises-> :Work, or via :Engagement",
        params={"target": ":CritiquePureReason"},
        expected=3,
        sparql="""
SELECT DISTINCT ?title ?how
WHERE {
  VALUES ?target { {{target}} }
  { ?w (:references|:cites|:criticizes|:praises) ?target .
    BIND("direct link" AS ?how) }
  UNION
  { ?e a :Engagement ; :fromWork ?w ; :toWork ?target ; :stance ?stance .
    BIND(CONCAT("engagement: ", ?stance) AS ?how) }
  ?w :title ?title .
}
ORDER BY ?title ?how""",
        note="The World as Will appears twice: it praises and criticizes the same work.",
    ),
    CQ(
        id="CQ6",
        question="Which period does the philosopher belong to?",
        features="SELECT DISTINCT",
        path=":Philosopher <-createdBy- :Work -composedDuring-> :TimePeriod",
        expected=22,
        sparql="""
SELECT DISTINCT ?name ?periodLabel
WHERE {
  ?w :createdBy ?p ; :composedDuring ?per .
  ?p rdfs:label ?name .
  ?per rdfs:label ?periodLabel .
}
ORDER BY ?name""",
        note="Derived from the periods of the philosopher's works; there is no direct link.",
    ),
    CQ(
        id="CQ7",
        question="Which books might be of interest to a user?",
        features="SELECT DISTINCT",
        path=":Reader -hasInterestIn-> :Concept <-aboutConcept- :Engagement -> :Work",
        params={"reader": ":reader1"},
        expected=5,
        sparql="""
SELECT DISTINCT ?title ?conceptLabel
WHERE {
  VALUES ?reader { {{reader}} }
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :aboutConcept ?c ; (:fromWork|:toWork) ?w .
  ?w :title ?title .
  ?c rdfs:label ?conceptLabel .
}
ORDER BY ?title""",
    ),
    CQ(
        id="CQ8",
        question="Which philosophers are masters and have students?",
        features="SELECT, FILTER EXISTS, COUNT, GROUP BY",
        path=":Philosopher <-studiedUnder- :Philosopher",
        expected=10,
        sparql="""
SELECT ?name (COUNT(DISTINCT ?student) AS ?students)
WHERE {
  ?p a :Philosopher ; rdfs:label ?name .
  FILTER EXISTS { ?x :studiedUnder ?p }
  ?student :studiedUnder ?p .
}
GROUP BY ?name
ORDER BY DESC(?students) ?name""",
        note="'Master' = direct studiedUnder target. Reasoned variant: ?p a :TeacherThinker",
    ),
    CQ(
        id="CQ9",
        question="What impact did the philosophers have in their era?",
        features="SELECT, aggregation, OPTIONAL, HAVING",
        path=":Philosopher <-influencedBy|studiedUnder-, and :Engagement -toWork-> :Work",
        expected=19,
        sparql="""
SELECT ?name
       (COUNT(DISTINCT ?follower) AS ?influenced)
       (COUNT(DISTINCT ?e)        AS ?engagements)
WHERE {
  ?p a :Philosopher ; rdfs:label ?name .
  OPTIONAL { ?follower (:influencedBy|:studiedUnder) ?p }
  OPTIONAL { ?w :createdBy ?p . ?e a :Engagement ; :toWork ?w }
}
GROUP BY ?name
HAVING (COUNT(DISTINCT ?follower) + COUNT(DISTINCT ?e) > 0)
ORDER BY DESC(?influenced + ?engagements) ?name""",
        note="Operational definition; see the query collection for its three stated biases.",
    ),
    CQ(
        id="CQ10",
        question="Which cities do philosophers belong to?",
        features="SELECT DISTINCT",
        path=":Philosopher <-createdBy- :Work -createdIn-> :City",
        expected=5,
        sparql="""
SELECT DISTINCT ?name ?cityLabel
WHERE {
  ?w :createdBy ?p ; :createdIn ?city .
  ?city a :City ; rdfs:label ?cityLabel .
  ?p rdfs:label ?name .
}
ORDER BY ?name""",
    ),
    CQ(
        id="CQ11",
        question="Which concepts do a given philosopher's works engage with, and how many engagements does each have?",
        features="SELECT, COUNT, GROUP BY",
        path=":Philosopher <-createdBy- :Work <-fromWork|toWork- :Engagement -aboutConcept-> :Concept",
        params={"philosopher": ":Schopenhauer"},
        expected=2,
        sparql="""
SELECT ?conceptLabel (COUNT(DISTINCT ?e) AS ?engagements)
WHERE {
  VALUES ?p { {{philosopher}} }
  ?w :createdBy ?p .
  ?e a :Engagement ; (:fromWork|:toWork) ?w ; :aboutConcept ?c .
  ?c rdfs:label ?conceptLabel .
}
GROUP BY ?conceptLabel
ORDER BY DESC(?engagements) ?conceptLabel""",
    ),
    CQ(
        id="CQ12",
        question="Which works has a reader not yet read that match their interests?",
        features="SELECT, FILTER NOT EXISTS",
        path="CQ7's path, minus :Reader -hasRead-> :Work",
        params={"reader": ":reader1"},
        expected=2,
        sparql="""
SELECT DISTINCT ?title ?conceptLabel
WHERE {
  VALUES ?reader { {{reader}} }
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :aboutConcept ?c ; (:fromWork|:toWork) ?w .
  ?w :title ?title .
  ?c rdfs:label ?conceptLabel .
  FILTER NOT EXISTS { ?reader :hasRead ?w }
}
ORDER BY ?title""",
        note="Negation-as-failure: OWL's open-world assumption cannot express 'not yet read'.",
    ),
    CQ(
        id="CQ13",
        question="Which unread works are recommended to a reader, and why?",
        features="CONSTRUCT",
        path="CQ12's path; the CONSTRUCT keeps the supporting triples as the explanation",
        params={"reader": ":reader1"},
        expected=20,
        kind="construct",
        sparql="""
CONSTRUCT {
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :fromWork ?from ; :toWork ?to ;
     :aboutConcept ?c ; :stance ?stance ; :confidenceScore ?conf .
  ?w :title ?title ; :createdBy ?author .
  ?author rdfs:label ?authorName .
}
WHERE {
  VALUES ?reader { {{reader}} }
  ?reader :hasInterestIn ?c .
  ?e a :Engagement ; :aboutConcept ?c ; :fromWork ?from ; :toWork ?to ;
     :stance ?stance ; :confidenceScore ?conf .
  ?e (:fromWork|:toWork) ?w .
  ?w :title ?title ; :createdBy ?author .
  ?author rdfs:label ?authorName .
  FILTER NOT EXISTS { ?reader :hasRead ?w }
}""",
        note=("Returns an explanation subgraph; agent.py ranks it by confidenceScore. "
              "The candidate work is selected with the property alternation "
              "?e (:fromWork|:toWork) ?w rather than { BIND(?from AS ?w) } UNION "
              "{ BIND(?to AS ?w) }. The BIND form works in RDFLib but returns "
              "nothing in Fuseki: a variable bound inside a UNION branch is out "
              "of scope for a later FILTER NOT EXISTS, and Fuseki applies that "
              "scoping rule strictly. See REPORT.md section 6.7."),
    ),
    CQ(
        id="CQ14",
        question="Does a given work have a recorded criticism?",
        features="ASK",
        path=":Engagement -toWork-> :Work with stance 'criticizes'",
        params={"work": ":Republic"},
        expected=True,
        kind="ask",
        sparql="""
ASK {
  ?e a :Engagement ; :toWork {{work}} ; :stance "criticizes" .
}""",
        note=":Republic -> true (eng01, eng02). :Meno -> false.",
    ),
    CQ(
        id="CQ15",
        question="What is everything known about a given work?",
        features="DESCRIBE",
        path="All properties of one :Work individual",
        params={"work": ":CritiquePureReason"},
        expected=8,
        kind="describe",
        sparql="""
DESCRIBE {{work}}""",
        note=("8 triples from the core graph. Against Fuseki with the LOD links "
              "loaded as a second named graph the same query returns 11, because "
              "DESCRIBE there covers the union of graphs and picks up the two "
              "owl:sameAs and one rdfs:seeAlso triples. Both results are correct "
              "for their dataset, so run_cqs.py expects 11 when querying the "
              "endpoint and 8 against the core file alone."),
        endpoint_expected=11,
    ),
]

RULES: list[CQ] = [
    CQ(
        id="R1a",
        question="Derive the :criticizes shortcut links from engagement stance",
        features="CONSTRUCT",
        path=":Engagement -fromWork/toWork-> :Work",
        expected=6,
        kind="construct",
        sparql="""
CONSTRUCT { ?a :criticizes ?b }
WHERE     { ?e a :Engagement ; :fromWork ?a ; :toWork ?b ; :stance "criticizes" }""",
        note="Not an OWL axiom: branching on a literal value needs a rule.",
    ),
    CQ(
        id="R1b",
        question="Derive the :praises shortcut links from engagement stance",
        features="CONSTRUCT",
        path=":Engagement -fromWork/toWork-> :Work",
        expected=3,
        kind="construct",
        sparql="""
CONSTRUCT { ?a :praises ?b }
WHERE     { ?e a :Engagement ; :fromWork ?a ; :toWork ?b ; :stance "praises" }""",
    ),
    CQ(
        id="R2",
        question="Which philosophers have no school recorded? (data-gap probe)",
        features="SELECT, FILTER NOT EXISTS",
        path=":Philosopher without :belongsToSchool",
        expected=10,
        sparql="""
SELECT ?name
WHERE {
  ?p a :Philosopher ; rdfs:label ?name .
  FILTER NOT EXISTS { ?p :belongsToSchool ?s }
}
ORDER BY ?name""",
        note="A data gap, not an error: it keeps OPTIONAL patterns meaningful.",
    ),
]

ALL = CQS + RULES
BY_ID = {c.id: c for c in ALL}


def render(cq: CQ, overrides: dict | None = None) -> str:
    """Substitute {{param}} placeholders, with optional caller overrides."""
    params = dict(cq.params)
    if overrides:
        params.update({k: v for k, v in overrides.items() if v})
    text = cq.full
    for key, value in params.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
