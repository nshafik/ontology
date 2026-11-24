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
    """Every CQ returns its documented count against the core graph."""

    @classmethod
    def setUpClass(cls):
        from rdflib import Graph
        cls.g = Graph()
        cls.g.parse(ROOT / "philosophy_ontology.ttl")
        cls.g.parse(ROOT / "philosophy_dataset.ttl")

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

    def test_rule_r1_materialises_shortcuts(self):
        added = Agent().materialise_rules()
        self.assertEqual(len(added), 9)


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
