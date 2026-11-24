"""Application-layer tests. Run: python3 -m unittest discover -s tests -v

Fuseki is not required: server.sparql() falls back to the in-process graph.
Network access is not required: Gemini and source providers are mocked.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import ask  # noqa: E402
import server  # noqa: E402
import sources  # noqa: E402
from agent import Agent  # noqa: E402
from queries import BY_ID, CQS, render  # noqa: E402

# Force the local fallback so results do not depend on a running Fuseki.
server.endpoint_alive = lambda: False


def gemini_reply(text: str):
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(body).encode()
    resp.__enter__.return_value = resp
    return resp


class CompetencyQueries(unittest.TestCase):
    """Every CQ returns its documented count against the built bundle."""

    @classmethod
    def setUpClass(cls):
        from rdflib import Graph
        cls.g = Graph()
        cls.g.parse(ROOT / "philosophy_complete.ttl")

    def test_expected_counts(self):
        for cq in CQS:
            with self.subTest(cq=cq.id):
                res = self.g.query(render(cq))
                if res.type == "ASK":
                    got = res.askAnswer
                elif cq.kind in ("construct", "describe"):
                    got = len(res.graph)
                else:
                    got = len(list(res))
                self.assertEqual(got, cq.expected)

    def test_wikidata_enrichment_present(self):
        from rdflib import Namespace
        p = Namespace("http://example.org/philosophy#")
        nietzsche_works = list(self.g.subjects(p.createdBy, p.Nietzsche))
        self.assertGreaterEqual(len(nietzsche_works), 7)
        self.assertIn((p.Nietzsche, p.influencedBy, p.Kant), self.g)


class Recommender(unittest.TestCase):
    def test_excludes_read_and_explains(self):
        agent = Agent()
        recs = agent.recommend(":reader1")
        self.assertTrue(recs)
        already = {agent.short(w) for w in agent.g.objects(
            server.agent_ns().reader1, server.agent_ns().hasRead)}
        for rec in recs:
            self.assertNotIn(rec.work, already)
            self.assertTrue(rec.evidence)
            self.assertAlmostEqual(rec.score, sum(e.contribution for e in rec.evidence))
        self.assertEqual(recs, sorted(recs, key=lambda r: (-r.score, r.title)))

    def test_rule_r1_and_r3_materialise(self):
        added = Agent().materialise_rules()
        r1 = [x for x in added if x[1] in ("criticizes", "praises")]
        r3 = [x for x in added if x[1] == "inferredInterestIn"]
        self.assertEqual(len(r1), 9)
        self.assertEqual(len(r3), 6)

    def test_russell_rescued_by_read_derived_interests(self):
        agent = Agent()
        agent.materialise_rules()
        recs = agent.recommend(":Russell")
        self.assertEqual([r.work for r in recs], [":PhilosophicalInvestigations"])
        self.assertAlmostEqual(recs[0].score, 0.95 * 0.8 * 0.5)
        self.assertEqual(recs[0].evidence[0].interest_kind, "inferred")
        self.assertIn("Tractatus", recs[0].evidence[0].sentence())

    def test_reader_with_no_reads_and_no_interests_explains_empty_state(self):
        from rdflib import RDF, RDFS, Literal
        agent = Agent()
        agent.g.add((server.agent_ns().nobody, RDF.type, server.agent_ns().Reader))
        agent.g.add((server.agent_ns().nobody, RDFS.label, Literal("Nobody")))
        self.assertEqual(agent.recommend(":nobody"), [])
        with mock.patch.object(server, "_fallback", agent):
            r = server.app.test_client().get("/recommend?reader=:nobody")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"no stated interests and none could be inferred", r.data)


class Routing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entities = ask.load_entities(server.sparql)

    def route(self, question):
        return ask.keyword_route(question, self.entities)

    def test_keyword_routes(self):
        cases = {
            "Has the Republic been criticized?": ("CQ14", ":Republic"),
            "Which philosophers studied under other philosophers?": ("CQ2", None),
            "Which concepts do Schopenhauer's works engage with?": ("CQ11", ":Schopenhauer"),
            "Which works reference Critique of Pure Reason?": ("CQ5", ":CritiquePureReason"),
            "Which schools are sub-schools of Medieval Philosophy?": ("CQ4", ":MedievalPhilosophy"),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(self.route(question), expected)

    def test_unrelated_question_is_not_forced(self):
        self.assertIsNone(self.route("What is the weather?"))

    def test_ambiguous_entity_not_guessed(self):
        ents = [ask.Entity("http://example.org/philosophy#A", "Ethics", "Work"),
                ask.Entity("http://example.org/philosophy#B", "Ethics", "Work")]
        self.assertIsNone(ask.find_entity("about Ethics", ents, "Work"))

    def test_injection_rejected(self):
        with self.assertRaises(ValueError):
            ask.validate_param(":Republic } . ?s ?p ?o")

    def test_missing_fact_is_not_false(self):
        result = ask.answer("q", server.sparql, self.entities,
                            cq_id="CQ14", focus=":Meno", use_llm=False)
        self.assertIn("absence does not prove", result["answer"])


class GeminiRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entities = ask.load_entities(server.sparql)

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch("ask.urllib.request.urlopen")
    def test_valid_route_and_grounded_answer(self, urlopen):
        urlopen.side_effect = [
            gemini_reply(json.dumps({"cq_id": "CQ14", "focus_label": "Republic"})),
            gemini_reply("Yes - two engagements criticise the Republic."),
        ]
        result = ask.answer("Is Plato's Republic criticised?", server.sparql, self.entities)
        self.assertEqual((result["route"], result["focus"]), ("CQ14", ":Republic"))
        self.assertEqual(result["router"], "gemini")
        self.assertEqual(result["answer_mode"], "llm-grounded")
        # the key travels in a header, never in the URL
        request = urlopen.call_args_list[0].args[0]
        self.assertNotIn("test-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")

    @mock.patch("ask.urllib.request.urlopen")
    def test_rejects_invented_entity(self, urlopen):
        urlopen.return_value = gemini_reply(
            json.dumps({"cq_id": "CQ14", "focus_label": "The Necronomicon"}))
        with self.assertRaises(RuntimeError):
            ask.answer("q", server.sparql, self.entities)

    @mock.patch("ask.urllib.request.urlopen")
    def test_rejects_unknown_cq(self, urlopen):
        urlopen.return_value = gemini_reply(json.dumps({"cq_id": "DROP", "focus_label": None}))
        with self.assertRaises(RuntimeError):
            ask.answer("q", server.sparql, self.entities)

    @mock.patch("ask.urllib.request.urlopen")
    def test_null_route_falls_back_to_keywords(self, urlopen):
        urlopen.side_effect = [
            gemini_reply(json.dumps({"cq_id": None, "focus_label": None})),
            gemini_reply("grounded"),
        ]
        result = ask.answer("Which philosophers studied under other philosophers?",
                            server.sparql, self.entities)
        self.assertEqual((result["route"], result["router"]), ("CQ2", "keyword"))


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = server.app.test_client()

    def test_pages(self):
        for path in ("/", "/ask", "/ontology", "/sources", "/recommend",
                     "/visualise", "/browse/works", "/entity/Plato", "/cq/CQ1"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_health_and_shacl(self):
        body = self.client.get("/health").get_json()
        self.assertTrue(body["shacl_conforms"])

    def test_ask_endpoint(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            r = self.client.post("/api/ask", json={"question": "Has the Republic been criticized?"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["route"], "CQ14")

    def test_ask_validation(self):
        bad = [None, {"question": ""}, {"question": "x" * 501},
               {"question": "x", "cq_id": "nope"},
               {"question": "x", "cq_id": "CQ14", "focus": ":A } ?s"}]
        for body in bad:
            with self.subTest(body=body):
                r = self.client.post("/api/ask", json=body)
                self.assertEqual(r.status_code, 400)

    def test_sparql_injection_on_pages(self):
        self.assertEqual(self.client.get("/entity/x%3E%20%3Fp").status_code, 400)
        self.assertEqual(self.client.get("/cq/CQ1?work=:a}%20UNION").status_code, 400)
        self.assertEqual(self.client.get("/recommend?reader=:a}").status_code, 400)

    def test_ontology_catalog(self):
        cat = self.client.get("/api/ontology").get_json()
        names = {c["name"] for c in cat["classes"]}
        self.assertTrue({":Work", ":Philosopher", ":Engagement", ":TeacherThinker"} <= names)
        studied = next(p for p in cat["properties"] if p["name"] == ":studiedUnder")
        self.assertIn(":hasTeachingAncestor", studied["parents"])


def http_reply(body: str):
    resp = mock.MagicMock()
    resp.read.return_value = body.encode()
    resp.__enter__.return_value = resp
    return resp


class FusekiBackend(unittest.TestCase):
    """server.sparql() with Fuseki 'live': urlopen is mocked, no server needed."""

    TURTLE = """@prefix : <http://example.org/philosophy#> .
:CritiquePureReason :title "Critique of Pure Reason" ; :createdBy :Kant ."""

    def setUp(self):
        alive = mock.patch.object(server, "endpoint_alive", return_value=True)
        alive.start()
        self.addCleanup(alive.stop)

    def sent_accept(self, urlopen) -> str:
        return urlopen.call_args.args[0].get_header("Accept")

    def test_query_form_detection(self):
        cases = {
            render(BY_ID["CQ1"]): "SELECT",
            render(BY_ID["CQ13"]): "CONSTRUCT",
            render(BY_ID["CQ14"]): "ASK",
            render(BY_ID["CQ15"]): "DESCRIBE",
            "# describe in a comment\nSELECT ?s WHERE { ?s ?p ?o }": "SELECT",
            "prefix x: <http://x/describe#>\nDESCRIBE x:a": "DESCRIBE",
        }
        for query, form in cases.items():
            with self.subTest(form=form):
                self.assertEqual(server.query_form(query), form)

    @mock.patch("server.urllib.request.urlopen")
    def test_describe_requests_turtle_and_returns_spo_rows(self, urlopen):
        urlopen.return_value = http_reply(self.TURTLE)
        payload = server.sparql(render(BY_ID["CQ15"]))
        self.assertEqual(self.sent_accept(urlopen), "text/turtle")
        self.assertEqual(payload["head"]["vars"], ["s", "p", "o"])
        rows = payload["results"]["bindings"]
        self.assertEqual(len(rows), 2)
        title = next(r for r in rows if r["p"]["value"].endswith("#title"))
        self.assertEqual(title["o"], {"type": "literal", "value": "Critique of Pure Reason"})
        creator = next(r for r in rows if r["p"]["value"].endswith("#createdBy"))
        self.assertEqual(creator["o"]["type"], "uri")

    @mock.patch("server.urllib.request.urlopen")
    def test_construct_requests_turtle(self, urlopen):
        urlopen.return_value = http_reply(self.TURTLE)
        payload = server.sparql(render(BY_ID["CQ13"]))
        self.assertEqual(self.sent_accept(urlopen), "text/turtle")
        self.assertEqual(len(payload["results"]["bindings"]), 2)

    @mock.patch("server.urllib.request.urlopen")
    def test_select_and_ask_request_json(self, urlopen):
        urlopen.return_value = http_reply(json.dumps(
            {"head": {"vars": ["n"]}, "results": {"bindings": [{"n": {"type": "literal", "value": "3"}}]}}))
        self.assertEqual(server.sparql(render(BY_ID["CQ1"]))["results"]["bindings"][0]["n"]["value"], "3")
        self.assertEqual(self.sent_accept(urlopen), "application/sparql-results+json")
        urlopen.return_value = http_reply('{"head": {}, "boolean": true}')
        self.assertTrue(server.sparql(render(BY_ID["CQ14"]))["boolean"])
        self.assertEqual(self.sent_accept(urlopen), "application/sparql-results+json")

    @mock.patch("server.urllib.request.urlopen")
    def test_same_shape_as_local_fallback(self, urlopen):
        with mock.patch.object(server, "endpoint_alive", return_value=False):
            local = server.sparql(render(BY_ID["CQ15"]))
        # serialise the local DESCRIBE graph and feed it back as Fuseki's answer
        result = server.fallback_graph().g.query(render(BY_ID["CQ15"]))
        urlopen.return_value = http_reply(result.graph.serialize(format="turtle"))
        remote = server.sparql(render(BY_ID["CQ15"]))
        self.assertEqual(remote, local)

    @mock.patch("server.urllib.request.urlopen")
    def test_unreadable_reply_is_backend_error(self, urlopen):
        urlopen.return_value = http_reply("<html>proxy error</html>")
        with self.assertRaises(server.BackendError):
            server.sparql(render(BY_ID["CQ1"]))
        self.assertFalse(issubclass(server.BackendError, ValueError))

    @mock.patch("server.urllib.request.urlopen")
    def test_api_ask_maps_backend_failure_to_502(self, urlopen):
        server._entities = None
        urlopen.side_effect = [
            http_reply(json.dumps({"head": {"vars": ["e", "name", "kind"]}, "results": {"bindings": [
                {"e": {"type": "uri", "value": "http://example.org/philosophy#CritiquePureReason"},
                 "name": {"type": "literal", "value": "Critique of Pure Reason"},
                 "kind": {"type": "literal", "value": "Work"}}]}})),
            http_reply("not turtle {{{"),
        ]
        try:
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
                r = server.app.test_client().post("/api/ask", json={
                    "question": "Tell me everything about Critique of Pure Reason"})
        finally:
            server._entities = None  # do not leak the one-entity cache
        self.assertEqual(r.status_code, 502)
        self.assertIn("Fuseki", r.get_json()["error"])

    @mock.patch("server.urllib.request.urlopen")
    def test_cq_page_renders_describe_from_fuseki(self, urlopen):
        urlopen.return_value = http_reply(self.TURTLE)
        r = server.app.test_client().get("/cq/CQ15")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Critique of Pure Reason", r.data)
        self.assertNotIn(b"JSONDecodeError", r.data)


class SourceRecords(unittest.TestCase):
    def test_records_are_provenance_not_domain_claims(self):
        from rdflib import RDF
        rec = sources.SourceRecord("sep", "SEP", "https://plato.stanford.edu/",
                                   "plato", "Plato", "https://plato.stanford.edu/entries/plato/")
        g = sources.records_to_graph([rec], "Plato")
        subject = sources._project_uri(rec)
        self.assertIn((subject, RDF.type, sources.PROV.Entity), g)
        types = set(g.objects(subject, RDF.type))
        self.assertFalse(any(str(t).startswith(str(sources.EX)) for t in types))

    def test_bad_url_rejected(self):
        rec = sources.SourceRecord("x", "X", "https://x.org/", "1", "t", "javascript:alert(1)")
        with self.assertRaises(sources.SourceError):
            sources.records_to_graph([rec], "q")

    def test_one_failing_provider_does_not_abort(self):
        from http.client import RemoteDisconnected
        with mock.patch("sources.urlopen", side_effect=RemoteDisconnected("gone")):
            _, statuses = sources.fetch_sources(["openlibrary"], "Plato", 1)
        self.assertTrue(statuses["openlibrary"].startswith("FAILED"))


if __name__ == "__main__":
    unittest.main()
