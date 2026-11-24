#!/usr/bin/env python3
"""Enrich the knowledge graph with works and influences from Wikidata.

The curated dataset holds 30 works for 31 philosophers; Wikidata knows far
more. This script pulls two kinds of FACTUAL, well-structured statements:

    works       P50  (author)        -> :Work  :createdBy  :Philosopher
                P577 (published)     -> :creationYear, and :composedDuring
                                        when the year falls in a known period
    influences  P737 (influenced by) -> :influencedBy, between philosophers
                                        who are already in the curated data

and writes them to data/wikidata_enrichment.ttl, a GENERATED file kept apart
from the hand-curated philosophy_dataset.ttl. build.py folds it into the
reasoning bundle, so SHACL, HermiT, Pellet and the competency questions check
it like any other data.

What it never imports: engagements (criticism / praise of a work about a
concept). Wikidata has no property for that; it is interpretation, and stays
hand-curated with a cited source.

Why it uses the entity lookup API + a local cache instead of pure SPARQL:
    A single SPARQL query with P31/wdt:P279* (class-tree traversal) over all
    31 authors exceeded WDQS's 60 s limit (HTTP 504). Splitting the fetch into
    one cheap SPARQL query (P50 + sitelinks only, ~1.5 s) plus batched
    wbgetentities calls (50 items per request, ~1 s each) pulls everything in
    ~10 s. Responses are cached in data/.wikidata_cache.json so reruns after
    filter edits touch zero network endpoints; pass --refresh to re-fetch.

Every match is anchored on identifiers, never on labels:
    * authors are the QIDs already verified in philosophy_dataset.ttl
      (:externalId, checked by birth year when they were added);
    * works already curated are recognised by their owl:sameAs QID in
      philosophy_links.ttl, so nothing is duplicated.

Filters applied locally over the fetched claims:
    * P31 must include an allowed written-work type (written work, literary
      work, philosophical work, Platonic dialogue, treatise, monograph,
      manifesto, essay, posthumous work) and must NOT carry a rejected type
      (allegory, quotation, idea, chapter, book series, complete edition,
      periodical, lyrics, phrase, ...);
    * must not be part of (P361) another item by the same author;
    * must have an English label and at least --min-sitelinks Wikipedia
      articles;
    * a publication year is kept only at year precision or better, and only
      within the author's lifetime plus 30 years - drops edition dates such as
      the Republic's "1963".

Wikidata years are ISO-8601 (astronomical: 1 BCE = 0). The dataset uses
historical numbering (-428 = 428 BCE, no year zero), so BCE years are shifted
by one, matching the convention documented in philosophy_dataset.ttl.

Usage:
    python3 app/enrich_wikidata.py                 # use cache if present, write TTL
    python3 app/enrich_wikidata.py --refresh       # re-fetch from Wikidata
    python3 app/enrich_wikidata.py --dry-run       # print summary and samples only
    python3 build.py                               # rebuild + validate
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
from datetime import date
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, XSD

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATASET = ROOT / "philosophy_dataset.ttl"
LINKS = ROOT / "philosophy_links.ttl"
CACHE = ROOT / "data" / ".wikidata_cache.json"
OUTPUT = ROOT / "data" / "wikidata_enrichment.ttl"

P = Namespace("http://example.org/philosophy#")
WD = Namespace("http://www.wikidata.org/entity/")
PROV = Namespace("http://www.w3.org/ns/prov#")

WDQS = "https://query.wikidata.org/sparql"
WB_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = ("PhilosophyOntologyEnrichment/1.1 "
              "(ISM601 coursework; https://github.com/nshafik/ontology)")

# Written-work types inspected from the candidate Wikidata items rather than
# traversed via P279* on WDQS (which timed out).
ALLOW_TYPES = {
    "Q47461344",  # written work
    "Q7725634",   # literary work
    "Q12765855",  # philosophical work
    "Q3026037",   # Platonic dialogue
    "Q384515",    # treatise
    "Q35760",     # essay
    "Q193495",    # monograph
    "Q46337",     # manifesto
    "Q17518461",  # posthumous work
    "Q13408937",  # philosophical non-fiction literature
}

# Reject even when also tagged literary/written work (e.g. Allegory of the
# Cave is both literary work and allegory; Untimely Meditations is a series).
DENY_TYPES = {
    "Q18535",     # allegory
    "Q18534",     # metaphor
    "Q206287",    # quotation
    "Q283987",    # direct speech
    "Q483372",    # paradox
    "Q33104279",  # philosophical concept
    "Q131841",    # idea
    "Q1980247",   # chapter
    "Q277759",    # book series
    "Q16968990",  # complete edition
    "Q17518870",  # group of literary works
    "Q1002697",   # periodical
    "Q108163",    # proposition
    "Q187931",    # phrase
    "Q3062294",   # Latin phrase
    "Q3962655",   # opinion
    "Q12355361",  # Redewendung
    "Q602446",    # lyrics
    "Q484692",    # hymn
}

PLATONIC_DIALOGUE = "Q3026037"
TREATISE = "Q384515"
ESSAY = "Q35760"

# Known Wikidata misattributions caught during review.
EXCLUDE_QIDS = {
    "Q551020",   # Aurora consurgens: pseudo-Aquinas alchemical text, P50=Aquinas on Wikidata
}


def norm_title(title: str) -> str:
    """Normalise minor singular/plural and punctuation drift for dedup."""
    s = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    s = re.sub(r"\bmetaphysic\b", "metaphysics", s)
    return re.sub(r"\s+", "", s)


# --------------------------------------------------------------------------
# HTTP helpers with retry
# --------------------------------------------------------------------------

def http_json(req: urllib.request.Request, attempts: int = 4) -> dict:
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            wait = float(retry_after) if retry_after.isdigit() else delay
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError):
            if attempt == attempts:
                raise
            wait = delay
        print(f"  attempt {attempt} failed; retrying in {wait:.0f}s", file=sys.stderr)
        time.sleep(wait)
        delay *= 2
    raise RuntimeError("unreachable")


def fetch_candidate_pairs(author_qids: list[str], min_sitelinks: int) -> list[tuple[str, str]]:
    """Cheap SPARQL query: (author_qid, work_qid) with no class-tree walk."""
    values = " ".join(f"wd:{q}" for q in author_qids)
    query = (f"SELECT ?author ?w WHERE {{ VALUES ?author {{ {values} }} "
             f"?w wdt:P50 ?author ; wikibase:sitelinks ?s . "
             f"FILTER(?s >= {min_sitelinks}) }}")
    req = urllib.request.Request(
        WDQS, data=urllib.parse.urlencode({"query": query}).encode(), method="POST",
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": USER_AGENT})
    rows = http_json(req)["results"]["bindings"]
    return [(r["author"]["value"].rsplit("/", 1)[-1],
             r["w"]["value"].rsplit("/", 1)[-1]) for r in rows]


def fetch_entities(qids: list[str]) -> dict[str, dict]:
    """Batch wbgetentities lookup, 50 items per request."""
    entities: dict[str, dict] = {}
    ordered = sorted(set(qids))
    for i in range(0, len(ordered), 50):
        batch = ordered[i:i + 50]
        url = WB_API + "?" + urllib.parse.urlencode({
            "action": "wbgetentities",
            "format": "json",
            "props": "claims|labels|sitelinks",
            "languages": "en",
            "ids": "|".join(batch),
        })
        payload = http_json(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}))
        entities.update(payload.get("entities", {}))
        if i + 50 < len(ordered):
            time.sleep(0.3)
    return entities


def fetch_with_cache(author_qids: list[str], min_sitelinks: int,
                     refresh: bool) -> dict:
    if not refresh and CACHE.exists():
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if cached.get("min_sitelinks") <= min_sitelinks and set(author_qids) <= set(cached.get("authors", {})):
            print(f"using cached Wikidata snapshot ({CACHE.relative_to(ROOT)})")
            return cached

    print("querying Wikidata SPARQL for candidate works...")
    pairs = fetch_candidate_pairs(author_qids, min_sitelinks)
    work_qids = sorted({w for _, w in pairs})
    print(f"  {len(work_qids)} candidate works (>= {min_sitelinks} sitelinks)")

    print("fetching philosopher claims via wbgetentities...")
    authors = fetch_entities(author_qids)
    print(f"fetching {len(work_qids)} work records via wbgetentities...")
    works = fetch_entities(work_qids)

    payload = {
        "fetched": date.today().isoformat(),
        "min_sitelinks": min_sitelinks,
        "pairs": pairs,
        "authors": authors,
        "works": works,
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(payload), encoding="utf-8")
    return payload


# --------------------------------------------------------------------------
# claim extraction
# --------------------------------------------------------------------------

def item_claims(entity: dict, prop: str) -> list[str]:
    out = []
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        val = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(val, dict) and "id" in val:
            out.append(val["id"])
    return out


def time_claims(entity: dict, prop: str) -> list[tuple[int, int]]:
    out = []
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        val = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if not isinstance(val, dict) or "time" not in val:
            continue
        m = re.match(r"^([+-]?\d{1,6})-", val["time"])
        if m:
            out.append((int(m.group(1)), int(val.get("precision", 0))))
    return out


def en_label(entity: dict) -> str | None:
    return entity.get("labels", {}).get("en", {}).get("value")


def sitelink_count(entity: dict) -> int:
    return len(entity.get("sitelinks", {}))


# --------------------------------------------------------------------------
# local graph state
# --------------------------------------------------------------------------

@dataclass
class Local:
    philosophers: dict[str, URIRef]       # QID -> :Philosopher
    lifespans: dict[str, tuple[int | None, int | None]]
    curated_work_qids: set[str]
    curated_titles: set[str]
    curated_works: list[URIRef]
    local_names: set[str]
    influences: set[tuple[URIRef, URIRef]]
    periods: list[tuple[int, int, URIRef]]


def load_local() -> Local:
    data = Graph().parse(DATASET, format="turtle")
    links = Graph().parse(LINKS, format="turtle")

    philosophers, lifespans = {}, {}
    for person in data.subjects(RDF.type, P.Philosopher):
        ext = data.value(person, P.externalId)
        if ext is None:
            continue
        philosophers[str(ext)] = person
        birth, death = data.value(person, P.birthYear), data.value(person, P.deathYear)
        lifespans[str(ext)] = (int(birth) if birth is not None else None,
                               int(death) if death is not None else None)

    curated_works = sorted(set(data.subjects(P.title, None)), key=str)
    curated_work_qids = set()
    curated_titles = set()
    for work in curated_works:
        t = data.value(work, P.title)
        if t is not None:
            curated_titles.add(norm_title(str(t)))
        for same in links.objects(work, OWL.sameAs):
            if str(same).startswith(str(WD)):
                curated_work_qids.add(str(same).rsplit("/", 1)[-1])

    periods = []
    for period in data.subjects(RDF.type, P.TimePeriod):
        start, end = data.value(period, P.startYear), data.value(period, P.endYear)
        if start is not None and end is not None:
            periods.append((int(start), int(end), period))

    local_names = {str(s).split("#", 1)[1] for s in data.subjects()
                   if isinstance(s, URIRef) and str(s).startswith(str(P))}
    influences = set(data.subject_objects(P.influencedBy))
    return Local(philosophers, lifespans, curated_work_qids, curated_titles,
                 curated_works, local_names, influences,
                 sorted(periods, key=lambda t: t[0]))


# --------------------------------------------------------------------------
# cleaning & graph construction
# --------------------------------------------------------------------------

def historical_year(iso_year: int) -> int:
    """ISO-8601 astronomical year -> historical (no year zero)."""
    return iso_year if iso_year > 0 else iso_year - 1


def pick_year(years: list[tuple[int, int]],
              lifespan: tuple[int | None, int | None]) -> int | None:
    birth, death = lifespan
    candidates = []
    for iso, precision in years:
        if precision < 9:
            continue
        year = historical_year(iso)
        if birth is not None and year < birth + 10:
            continue
        if death is not None and year > death + 30:
            continue
        candidates.append(year)
    return min(candidates) if candidates else None


def period_for(year: int | None, periods) -> URIRef | None:
    if year is None:
        return None
    for start, end, period in periods:
        if start <= year <= end:
            return period
    return None


def work_class(types: set[str]) -> URIRef:
    if PLATONIC_DIALOGUE in types:
        return P.Dialogue
    if TREATISE in types:
        return P.Treatise
    if ESSAY in types:
        return P.Essay
    return P.Work


def local_name(title: str, taken: set[str], fallback: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title.replace("'", "").replace("’", ""))
    name = "".join(w[:1].upper() + w[1:] for w in words)
    if not name or not name[0].isalpha():
        name = "Work" + name
    if name in taken:
        name = f"{name}_{fallback}"
    taken.add(name)
    return name


HEADER = """\
###############################################################################
#  GENERATED FILE - DO NOT EDIT BY HAND. Regenerate with:
#      python3 app/enrich_wikidata.py && python3 build.py
#
#  Works (P50, P577) and influences (P737) from Wikidata, snapshot {fetched}.
#  Settings: min_sitelinks={min_sitelinks}, per_author={per_author}.
#
#  Provenance: every work carries prov:wasDerivedFrom <its Wikidata item>
#  and :externalId. Influence links are between philosophers already in
#  philosophy_dataset.ttl; each one is a Wikidata P737 statement.
#
#  These are bibliographic and biographical facts, not interpretations.
#  No :Engagement is ever generated here - see philosophy_dataset.ttl.
#
#  Works without a specific genre mapping stay typed :Work rather than
#  guessing a leaf class. Years are historical (BCE negative, no year zero).
###############################################################################

"""


def build_graph(local: Local, cache: dict, per_author: int, min_sitelinks: int):
    g = Graph()
    g.bind("", P)
    g.bind("owl", OWL)
    g.bind("xsd", XSD)
    g.bind("prov", PROV)
    g.bind("wd", WD)

    report = {"skipped_curated": 0, "skipped_type": 0, "skipped_part": 0,
              "skipped_cap": 0, "year_dropped": 0, "works": 0, "influences": 0}
    taken = set(local.local_names)
    new_works: list[URIRef] = []

    raw_works: dict[str, dict] = cache["works"]
    # Build (work_qid -> set of author_qids) from the fetched pairs, then keep
    # only works whose P31 types pass the allow/deny lists and are not part of
    # another item by the same author (by checking all fetched work claims or P361).
    all_work_authors = {w: set(item_claims(ent, "P50")) for w, ent in raw_works.items()}
    by_author: dict[str, list[tuple[str, str, int, set[str], list[tuple[int, int]]]]] = {}

    seen_pairs: set[tuple[str, str]] = set()
    for author_qid, work_qid in cache["pairs"]:
        if (author_qid, work_qid) in seen_pairs:
            continue
        seen_pairs.add((author_qid, work_qid))
        if work_qid in local.curated_work_qids or work_qid in EXCLUDE_QIDS:
            report["skipped_curated"] += 1
            continue
        ent = raw_works.get(work_qid)
        if not ent or "missing" in ent:
            continue
        title = en_label(ent)
        links_n = sitelink_count(ent)
        if not title or links_n < min_sitelinks:
            continue
        if norm_title(title) in local.curated_titles:
            report["skipped_curated"] += 1
            continue
        types = set(item_claims(ent, "P31"))
        if not (types & ALLOW_TYPES) or (types & DENY_TYPES):
            report["skipped_type"] += 1
            continue
        wholes = set(item_claims(ent, "P361"))
        if any(author_qid in all_work_authors.get(w, set()) for w in wholes):
            report["skipped_part"] += 1
            continue
        years = time_claims(ent, "P577")
        by_author.setdefault(author_qid, []).append(
            (work_qid, title.strip(), links_n, types, years))

    for author_qid in sorted(by_author):
        ranked = sorted(by_author[author_qid], key=lambda item: (-item[2], item[0]))
        report["skipped_cap"] += max(0, len(ranked) - per_author)
        for work_qid, title, _, types, years in sorted(ranked[:per_author], key=lambda x: x[0]):
            node = P[local_name(title, taken, work_qid)]
            new_works.append(node)
            g.add((node, RDF.type, work_class(types)))
            g.add((node, RDF.type, OWL.NamedIndividual))
            g.add((node, P.title, Literal(title, datatype=XSD.string)))
            g.add((node, P.createdBy, local.philosophers[author_qid]))
            g.add((node, P.externalId, Literal(work_qid, datatype=XSD.string)))
            g.add((node, PROV.wasDerivedFrom, WD[work_qid]))
            year = pick_year(years, local.lifespans.get(author_qid, (None, None)))
            if year is None and years:
                report["year_dropped"] += 1
            if year is not None:
                g.add((node, P.creationYear, Literal(year, datatype=XSD.int)))
                period = period_for(year, local.periods)
                if period is not None:
                    g.add((node, P.composedDuring, period))
            report["works"] += 1

    # P737 influences among philosophers already in philosophy_dataset.ttl
    known = set(local.philosophers)
    seen_inf: set[tuple[str, str]] = set()
    for a_qid, ent in sorted(cache["authors"].items()):
        if a_qid not in known:
            continue
        for b_qid in item_claims(ent, "P737"):
            if b_qid in known and b_qid != a_qid and (a_qid, b_qid) not in seen_inf:
                seen_inf.add((a_qid, b_qid))
                pair = (local.philosophers[a_qid], local.philosophers[b_qid])
                if pair not in local.influences:
                    g.add((pair[0], P.influencedBy, pair[1]))
                    report["influences"] += 1

    return g, new_works, report


def serialise(g: Graph, all_works: list[URIRef], meta: dict) -> str:
    body = g.serialize(format="turtle")
    members = "\n".join(f"      :{str(w).split('#', 1)[1]}" for w in all_works)
    distinct = ("\n# All works, curated and generated, are pairwise distinct.\n"
                "[] a owl:AllDifferent ;\n   owl:distinctMembers (\n"
                f"{members}\n   ) .\n")
    return HEADER.format(**meta) + body + distinct


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-author", type=int, default=6,
                    help="max new works per philosopher (default 6)")
    ap.add_argument("--min-sitelinks", type=int, default=12,
                    help="min Wikipedia articles for a work (default 12)")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore data/.wikidata_cache.json and re-fetch")
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    local = load_local()
    authors = sorted(local.philosophers)
    cache = fetch_with_cache(authors, args.min_sitelinks, args.refresh)
    g, new_works, report = build_graph(local, cache, args.per_author, args.min_sitelinks)
    for key, value in report.items():
        print(f"  {key:16} {value}")
    if args.dry_run:
        return 0

    meta = {"fetched": cache["fetched"],
            "min_sitelinks": args.min_sitelinks,
            "per_author": args.per_author}
    text = serialise(g, local.curated_works + new_works, meta)
    Graph().parse(data=text, format="turtle")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output.relative_to(ROOT)}  ({len(g)} triples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
