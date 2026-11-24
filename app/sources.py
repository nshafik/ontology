"""Small, bounded clients for the project's public cultural-data sources."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from html.parser import HTMLParser
from http.client import HTTPException
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, XSD

# Same namespace as philosophy_ontology.ttl; source records get their own
# path so they never collide with curated individuals.
EX = Namespace("http://example.org/philosophy#")
PROV = Namespace("http://www.w3.org/ns/prov#")
SCHEMA = Namespace("https://schema.org/")
WGS84 = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
SOURCE_NS = Namespace("http://example.org/philosophy/source-record/")
USER_AGENT = "PhilosophyCurationPrototype/0.1 (educational research project)"
TIMEOUT_SECONDS = 20
MAX_LIMIT = 25
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class SourceError(RuntimeError):
    """A selected source could not be queried or returned invalid data."""


class MissingCredential(SourceError):
    """A source requires an API credential that is not configured."""


@dataclass(frozen=True)
class SourceRecord:
    source_key: str
    source_name: str
    source_home: str
    external_id: str
    title: str
    record_url: str
    kind: str = "authority"
    description: str | None = None
    creator: str | None = None
    date: str | None = None
    license_url: str | None = None
    image_url: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    retrieved_for: str | None = None


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    home: str
    fetch: Callable[[str, int], list[SourceRecord]]


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and self._href is None:
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None
            self._text = []


def _html_request(url: str) -> str:
    request = Request(
        url,
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw_payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw_payload) > MAX_RESPONSE_BYTES:
                raise SourceError(f"Response from {urlsplit(url).netloc} exceeded the size limit.")
            charset = response.headers.get_content_charset() or "utf-8"
            return raw_payload.decode(charset, errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SourceError(f"HTTP {exc.code} from {urlsplit(url).netloc}: {detail}") from exc
    except URLError as exc:
        raise SourceError(f"Could not reach {urlsplit(url).netloc}: {exc.reason}") from exc
    except (TimeoutError, ConnectionError, HTTPException) as exc:
        raise SourceError(f"Connection to {urlsplit(url).netloc} failed: {exc!r}") from exc


def _json_request(url: str, *, accept: str = "application/json") -> dict:
    request = Request(
        url,
        headers={"Accept": accept, "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw_payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw_payload) > MAX_RESPONSE_BYTES:
                raise SourceError(f"Response from {url.split('/')[2]} exceeded the size limit.")
            payload = json.loads(raw_payload.decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SourceError(f"HTTP {exc.code} from {url.split('/')[2]}: {detail}") from exc
    except URLError as exc:
        raise SourceError(f"Could not reach {url.split('/')[2]}: {exc.reason}") from exc
    except (TimeoutError, ConnectionError, HTTPException) as exc:
        raise SourceError(f"Connection to {url.split('/')[2]} failed: {exc!r}") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"Received invalid JSON from {url.split('/')[2]}.") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"Unexpected JSON response from {url.split('/')[2]}.")
    return payload


def _get_json(base_url: str, params: dict[str, object] | None = None) -> dict:
    query = urlencode(params or {})
    return _json_request(f"{base_url}?{query}" if query else base_url)


def _get_sparql(endpoint: str, query: str) -> list[dict[str, dict[str, str]]]:
    url = f"{endpoint}?{urlencode({'query': query})}"
    payload = _json_request(url, accept="application/sparql-results+json")
    try:
        return payload["results"]["bindings"]
    except (KeyError, TypeError) as exc:
        raise SourceError(f"SPARQL endpoint {endpoint} returned an invalid result set.") from exc


def _first(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        for item in value:
            candidate = _first(item)
            if candidate:
                return candidate
    if isinstance(value, dict):
        for key in ("url", "value", "name", "content"):
            candidate = _first(value.get(key))
            if candidate:
                return candidate
    return None


def _is_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sparql_value(row: dict[str, dict[str, str]], key: str) -> str | None:
    value = row.get(key)
    return value.get("value") if value else None


def _literal_string(value: str) -> str:
    return Literal(value).n3()


def _wikidata(query: str, limit: int) -> list[SourceRecord]:
    term = _literal_string(query.casefold())
    sparql = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT DISTINCT ?item ?itemLabel ?itemDescription WHERE {{
  ?item rdfs:label ?matchedLabel .
  FILTER(LANG(?matchedLabel) = "en")
  FILTER(CONTAINS(LCASE(STR(?matchedLabel)), {term}))
  OPTIONAL {{
    ?item schema:description ?itemDescription .
    FILTER(LANG(?itemDescription) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""
    results = _get_sparql("https://query.wikidata.org/sparql", sparql)
    records = []
    for row in results:
        item = _sparql_value(row, "item")
        title = _sparql_value(row, "itemLabel")
        if not item or not title:
            continue
        records.append(SourceRecord(
            "wikidata", "Wikidata", "https://www.wikidata.org/",
            item.rsplit("/", 1)[-1], title, item, "authority",
            _sparql_value(row, "itemDescription"), retrieved_for=query,
        ))
    return records


def _met(query: str, limit: int) -> list[SourceRecord]:
    search = _get_json(
        "https://collectionapi.metmuseum.org/public/collection/v1/search",
        {"q": query, "hasImages": "true"},
    )
    object_ids = search.get("objectIDs") or []
    if not isinstance(object_ids, list):
        raise SourceError("The Met search response did not contain an object ID list.")
    records = []
    for object_id in object_ids[:limit]:
        item = _get_json(
            f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{int(object_id)}"
        )
        title = _first(item.get("title"))
        record_url = _first(item.get("objectURL"))
        if not title or not record_url:
            continue
        is_public_domain = item.get("isPublicDomain") is True
        records.append(SourceRecord(
            "met", "The Metropolitan Museum of Art",
            "https://www.metmuseum.org/", str(item.get("objectID", object_id)),
            title, record_url, "collection-object",
            description=_first(item.get("medium")) or _first(item.get("culture")),
            creator=_first(item.get("artistDisplayName")),
            date=_first(item.get("objectDate")),
            license_url="https://creativecommons.org/publicdomain/zero/1.0/"
            if is_public_domain else None,
            image_url=_first(item.get("primaryImageSmall")) or _first(item.get("primaryImage")),
            retrieved_for=query,
        ))
    return records


def _artic(query: str, limit: int) -> list[SourceRecord]:
    fields = "id,title,date_display,artist_title,api_link,is_public_domain,image_id,thumbnail"
    payload = _get_json(
        "https://api.artic.edu/api/v1/artworks/search",
        {"q": query, "limit": limit, "fields": fields},
    )
    items = payload.get("data") or []
    if not isinstance(items, list):
        raise SourceError("The Art Institute of Chicago API returned an invalid artworks list.")
    records = []
    for item in items[:limit]:
        external_id = item.get("id")
        title = _first(item.get("title"))
        if external_id is None or not title:
            continue
        public_domain = item.get("is_public_domain") is True
        image_id = item.get("image_id")
        thumbnail = item.get("thumbnail")
        image_url = _first(thumbnail.get("lqip")) if isinstance(thumbnail, dict) else None
        if not image_url and image_id:
            image_url = f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
        records.append(SourceRecord(
            "artic", "Art Institute of Chicago", "https://www.artic.edu/",
            str(external_id), title,
            f"https://www.artic.edu/artworks/{external_id}", "collection-object",
            description=_first(item.get("date_display")),
            creator=_first(item.get("artist_title")),
            date=_first(item.get("date_display")),
            license_url="https://creativecommons.org/publicdomain/zero/1.0/"
            if public_domain else None,
            image_url=image_url,
            retrieved_for=query,
        ))
    return records


def _cleveland(query: str, limit: int) -> list[SourceRecord]:
    fields = "id,title,creators,creation_date,url,share_license_status,share_license_url,images"
    payload = _get_json(
        "https://openaccess-api.clevelandart.org/api/artworks/",
        {"q": query, "limit": limit, "fields": fields},
    )
    items = payload.get("data") or []
    if not isinstance(items, list):
        raise SourceError("The Cleveland Museum API returned an invalid artworks list.")
    records = []
    for item in items[:limit]:
        external_id = item.get("id")
        title = _first(item.get("title"))
        record_url = _first(item.get("url"))
        if external_id is None or not title or not record_url:
            continue
        creators = item.get("creators")
        creator = None
        if isinstance(creators, list) and creators:
            creator = _first(creators[0].get("description") or creators[0].get("role"))
        images = item.get("images")
        image_url = _first(images.get("web")) if isinstance(images, dict) else None
        license_url = _first(item.get("share_license_url"))
        records.append(SourceRecord(
            "cleveland", "Cleveland Museum of Art",
            "https://www.clevelandart.org/", str(external_id), title,
            record_url, "collection-object",
            description=_first(item.get("creation_date")),
            creator=creator, date=_first(item.get("creation_date")),
            license_url=license_url, image_url=image_url,
            retrieved_for=query,
        ))
    return records


def _getty(vocabulary: str, query: str, limit: int) -> list[SourceRecord]:
    term = _literal_string(query.casefold())
    sparql = f"""
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?subject ?label ?description WHERE {{
  ?subject skos:prefLabel ?label .
  FILTER(LANG(?label) = "en")
  FILTER(STRSTARTS(STR(?subject), "http://vocab.getty.edu/{vocabulary}/"))
  FILTER(CONTAINS(LCASE(STR(?label)), {term}))
  OPTIONAL {{
    ?subject skos:scopeNote ?description .
    FILTER(LANG(?description) = "en")
  }}
}}
LIMIT {limit}
"""
    results = _get_sparql("https://vocab.getty.edu/sparql", sparql)
    names = {"ulan": "Getty ULAN", "aat": "Getty AAT", "tgn": "Getty TGN"}
    records = []
    for row in results:
        uri = _sparql_value(row, "subject")
        title = _sparql_value(row, "label")
        if not uri or not title:
            continue
        records.append(SourceRecord(
            f"getty-{vocabulary}", names[vocabulary],
            "https://www.getty.edu/research/tools/vocabularies/",
            uri.rsplit("/", 1)[-1], title, uri, "authority",
            description=_sparql_value(row, "description"), retrieved_for=query,
        ))
    return records


def _europeana(query: str, limit: int) -> list[SourceRecord]:
    api_key = os.environ.get("EUROPEANA_API_KEY", "").strip()
    if not api_key:
        raise MissingCredential("EUROPEANA_API_KEY is required for Europeana.")
    payload = _get_json(
        "https://api.europeana.eu/record/v2/search.json",
        {"wskey": api_key, "query": query, "rows": limit, "qf": "TYPE:IMAGE"},
    )
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise SourceError("Europeana returned an invalid item list.")
    records = []
    for item in items[:limit]:
        external_id = _first(item.get("id"))
        title = _first(item.get("title"))
        record_url = _first(item.get("guid")) or _first(item.get("edmIsShownAt"))
        if not external_id or not title or not record_url:
            continue
        rights = _first(item.get("edmRights"))
        preview = _first(item.get("edmPreview"))
        records.append(SourceRecord(
            "europeana", "Europeana", "https://www.europeana.eu/",
            external_id, title, record_url, "collection-object",
            description=_first(item.get("dcDescription")),
            creator=_first(item.get("dcCreator")),
            date=_first(item.get("year")),
            license_url=rights if _is_http_url(rights) else None,
            image_url=preview, retrieved_for=query,
        ))
    return records


def _rijksmuseum(query: str, limit: int) -> list[SourceRecord]:
    api_key = os.environ.get("RIJKSMUSEUM_API_KEY", "").strip()
    if not api_key:
        raise MissingCredential("RIJKSMUSEUM_API_KEY is required for Rijksmuseum.")
    payload = _get_json(
        "https://www.rijksmuseum.nl/api/en/collection",
        {"key": api_key, "q": query, "ps": limit, "format": "json"},
    )
    items = payload.get("artObjects") or []
    if not isinstance(items, list):
        raise SourceError("Rijksmuseum returned an invalid artObjects list.")
    records = []
    for item in items[:limit]:
        external_id = _first(item.get("objectNumber"))
        title = _first(item.get("title")) or _first(item.get("longTitle"))
        record_url = _first(item.get("links", {}).get("web")) if isinstance(item.get("links"), dict) else None
        if not record_url and external_id:
            record_url = f"https://www.rijksmuseum.nl/en/collection/{external_id}"
        if not external_id or not title or not record_url:
            continue
        records.append(SourceRecord(
            "rijksmuseum", "Rijksmuseum", "https://www.rijksmuseum.nl/",
            external_id, title, record_url, "collection-object",
            creator=_first(item.get("principalOrFirstMaker")),
            image_url=_first(item.get("webImage")),
            retrieved_for=query,
        ))
    return records


def _geonames(query: str, limit: int) -> list[SourceRecord]:
    username = os.environ.get("GEONAMES_USERNAME", "").strip()
    if not username:
        raise MissingCredential("GEONAMES_USERNAME is required for GeoNames.")
    payload = _get_json(
        "https://api.geonames.org/searchJSON",
        {"q": query, "maxRows": limit, "username": username, "style": "FULL"},
    )
    items = payload.get("geonames") or []
    if not isinstance(items, list):
        raise SourceError("GeoNames returned an invalid geonames list.")
    records = []
    for item in items[:limit]:
        external_id = _first(item.get("geonameId"))
        title = _first(item.get("name"))
        if not external_id or not title:
            continue
        place_url = f"https://www.geonames.org/{external_id}/"
        details = ", ".join(
            part for part in (_first(item.get("fcodeName")), _first(item.get("countryName")))
            if part
        )
        records.append(SourceRecord(
            "geonames", "GeoNames", "https://www.geonames.org/",
            external_id, title, place_url, "place",
            description=details or None,
            latitude=_first(item.get("lat")),
            longitude=_first(item.get("lng")),
            retrieved_for=query,
        ))
    return records


def _dbpedia(query: str, limit: int) -> list[SourceRecord]:
    term = _literal_string(query.casefold())
    sparql = f"""
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?resource ?label ?description WHERE {{
  ?resource rdfs:label ?label .
  FILTER(LANG(?label) = "en")
  FILTER(CONTAINS(LCASE(STR(?label)), {term}))
  OPTIONAL {{
    ?resource dbo:abstract ?description .
    FILTER(LANG(?description) = "en")
  }}
}}
LIMIT {limit}
"""
    results = _get_sparql(
        "https://dbpedia.org/sparql",
        sparql,
    )
    records = []
    for row in results:
        uri = _sparql_value(row, "resource")
        title = _sparql_value(row, "label")
        if not uri or not title:
            continue
        records.append(SourceRecord(
            "dbpedia", "DBpedia", "https://www.dbpedia.org/",
            uri.rsplit("/", 1)[-1], title, uri, "authority",
            description=_sparql_value(row, "description"), retrieved_for=query,
        ))
    return records


def _sep(query: str, limit: int) -> list[SourceRecord]:
    url = "https://plato.stanford.edu/search/searcher.py?" + urlencode({
        "query": query,
        "pagesize": limit,
    })
    parser = _LinkParser()
    parser.feed(_html_request(url))
    records = []
    seen: set[str] = set()
    for href, title in parser.links:
        parsed = urlsplit(href)
        entry = parse_qs(parsed.query).get("entry", [None])[0]
        if not entry and parsed.path.startswith("/entries/"):
            entry = parsed.path
        if not entry:
            continue
        entry_path = urlsplit(entry).path
        if not entry_path.startswith("/entries/"):
            continue
        record_url = urljoin("https://plato.stanford.edu/", entry_path)
        if record_url in seen:
            continue
        seen.add(record_url)
        title = title or entry_path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
        records.append(SourceRecord(
            "sep", "Stanford Encyclopedia of Philosophy",
            "https://plato.stanford.edu/", entry_path.rstrip("/").rsplit("/", 1)[-1],
            title, record_url, "scholarly-reference", retrieved_for=query,
        ))
        if len(records) >= limit:
            break
    return records


def _pleiades(query: str, limit: int) -> list[SourceRecord]:
    url = "https://pleiades.stoa.org/@@search?" + urlencode({
        "SearchableText": query,
        "portal_type": "Place",
    })
    parser = _LinkParser()
    parser.feed(_html_request(url))
    data_uri = next(
        (href for href, _ in parser.links if href.startswith("data:application/json,")),
        None,
    )
    if not data_uri:
        raise SourceError("Pleiades search did not return its JSON results link.")
    header, encoded_payload = data_uri.split(",", 1)
    try:
        raw_payload = (
            base64.b64decode(encoded_payload)
            if ";base64" in header
            else unquote(encoded_payload).encode("utf-8")
        )
        payload = json.loads(raw_payload.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SourceError("Pleiades returned invalid embedded JSON results.") from exc
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise SourceError("Pleiades search returned no feature list.")

    records = []
    for feature in features[:limit]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        record_url = _first(properties.get("link"))
        title = _first(properties.get("title"))
        if not record_url or not title or not _is_http_url(record_url):
            continue
        external_id = urlsplit(record_url).path.rstrip("/").rsplit("/", 1)[-1]
        geometry = feature.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        longitude = str(coordinates[0]) if isinstance(coordinates, list) and len(coordinates) >= 2 else None
        latitude = str(coordinates[1]) if isinstance(coordinates, list) and len(coordinates) >= 2 else None
        records.append(SourceRecord(
            "pleiades", "Pleiades", "https://pleiades.stoa.org/",
            external_id, title, record_url, "place",
            description=_first(properties.get("description")),
            license_url="https://creativecommons.org/licenses/by/3.0/",
            latitude=latitude, longitude=longitude, retrieved_for=query,
        ))
    return records


def _openlibrary(query: str, limit: int) -> list[SourceRecord]:
    payload = _get_json(
        "https://openlibrary.org/search.json",
        {
            "q": query,
            "limit": limit,
            "fields": "key,title,author_name,first_publish_year",
        },
    )
    items = payload.get("docs") or []
    if not isinstance(items, list):
        raise SourceError("Open Library returned an invalid documents list.")
    records = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        key = _first(item.get("key"))
        title = _first(item.get("title"))
        if not key or not title or not key.startswith("/works/"):
            continue
        records.append(SourceRecord(
            "openlibrary", "Open Library", "https://openlibrary.org/",
            key.rsplit("/", 1)[-1], title, urljoin("https://openlibrary.org/", key),
            "bibliographic", creator=_first(item.get("author_name")),
            date=_first(item.get("first_publish_year")), retrieved_for=query,
        ))
    return records


def _library_of_congress(query: str, limit: int) -> list[SourceRecord]:
    payload = _get_json(
        "https://www.loc.gov/search/",
        {"q": query, "fo": "json", "c": limit},
    )
    items = payload.get("results") or []
    if not isinstance(items, list):
        raise SourceError("Library of Congress returned an invalid results list.")
    records = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        record_url = _first(item.get("id"))
        title = _first(item.get("title"))
        if not record_url or not title or not _is_http_url(record_url):
            continue
        records.append(SourceRecord(
            "loc", "Library of Congress", "https://www.loc.gov/",
            record_url.rstrip("/").rsplit("/", 1)[-1], title, record_url,
            "bibliographic", description=_first(item.get("description")),
            creator=_first(item.get("contributor")), date=_first(item.get("date")),
            retrieved_for=query,
        ))
    return records


def _viaf(query: str, limit: int) -> list[SourceRecord]:
    payload = _get_json(
        "https://viaf.org/viaf/AutoSuggest",
        {"query": query},
    )
    items = payload.get("result") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise SourceError("VIAF returned an invalid authority result list.")
    records = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        identifier = _first(item.get("viafid")) or _first(item.get("nsid"))
        title = _first(item.get("term"))
        if not identifier or not title:
            continue
        record_url = f"https://viaf.org/viaf/{identifier}"
        records.append(SourceRecord(
            "viaf", "VIAF", "https://viaf.org/", identifier, title,
            record_url, "authority", retrieved_for=query,
        ))
    return records


def _gutenberg(query: str, limit: int) -> list[SourceRecord]:
    payload = _get_json(
        "https://gutendex.com/books/",
        {"search": query, "languages": "en"},
    )
    items = payload.get("results") or []
    if not isinstance(items, list):
        raise SourceError("Project Gutenberg search returned an invalid results list.")
    records = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        identifier = _first(item.get("id"))
        title = _first(item.get("title"))
        if not identifier or not title:
            continue
        authors = item.get("authors")
        author = _first(authors[0].get("name")) if isinstance(authors, list) and authors else None
        records.append(SourceRecord(
            "gutenberg", "Project Gutenberg via Gutendex", "https://gutendex.com/",
            identifier, title, f"https://www.gutenberg.org/ebooks/{identifier}",
            "bibliographic", creator=author, retrieved_for=query,
        ))
    return records


def _perseus(query: str, limit: int) -> list[SourceRecord]:
    url = "https://catalog.perseus.org/catalog?" + urlencode({
        "search_field": "all_fields",
        "q": query,
    })
    parser = _LinkParser()
    parser.feed(_html_request(url))
    records = []
    seen: set[str] = set()
    for href, title in parser.links:
        parsed = urlsplit(href)
        if not parsed.path.startswith("/catalog/urn:") or not title:
            continue
        record_url = urljoin("https://catalog.perseus.org/", parsed.path)
        if record_url in seen:
            continue
        seen.add(record_url)
        external_id = parsed.path.rsplit("/", 1)[-1]
        records.append(SourceRecord(
            "perseus", "Perseus Digital Library", "https://catalog.perseus.org/",
            external_id, title, record_url, "bibliographic", retrieved_for=query,
        ))
        if len(records) >= limit:
            break
    return records


SOURCES = {
    "wikidata": Source("wikidata", "Wikidata", "https://www.wikidata.org/", _wikidata),
    "met": Source("met", "The Metropolitan Museum of Art", "https://www.metmuseum.org/", _met),
    "artic": Source("artic", "Art Institute of Chicago", "https://www.artic.edu/", _artic),
    "cleveland": Source("cleveland", "Cleveland Museum of Art", "https://www.clevelandart.org/", _cleveland),
    "getty-ulan": Source("getty-ulan", "Getty ULAN", "https://www.getty.edu/research/tools/vocabularies/", lambda q, n: _getty("ulan", q, n)),
    "getty-aat": Source("getty-aat", "Getty AAT", "https://www.getty.edu/research/tools/vocabularies/", lambda q, n: _getty("aat", q, n)),
    "getty-tgn": Source("getty-tgn", "Getty TGN", "https://www.getty.edu/research/tools/vocabularies/", lambda q, n: _getty("tgn", q, n)),
    "europeana": Source("europeana", "Europeana", "https://www.europeana.eu/", _europeana),
    "rijksmuseum": Source("rijksmuseum", "Rijksmuseum", "https://www.rijksmuseum.nl/", _rijksmuseum),
    "geonames": Source("geonames", "GeoNames", "https://www.geonames.org/", _geonames),
    "dbpedia": Source("dbpedia", "DBpedia", "https://www.dbpedia.org/", _dbpedia),
    "sep": Source("sep", "Stanford Encyclopedia of Philosophy", "https://plato.stanford.edu/", _sep),
    "pleiades": Source("pleiades", "Pleiades", "https://pleiades.stoa.org/", _pleiades),
    "openlibrary": Source("openlibrary", "Open Library", "https://openlibrary.org/", _openlibrary),
    "loc": Source("loc", "Library of Congress", "https://www.loc.gov/", _library_of_congress),
    "viaf": Source("viaf", "VIAF", "https://viaf.org/", _viaf),
    "gutenberg": Source("gutenberg", "Project Gutenberg", "https://www.gutenberg.org/", _gutenberg),
    "perseus": Source("perseus", "Perseus Digital Library", "https://catalog.perseus.org/", _perseus),
}


def _project_uri(record: SourceRecord) -> URIRef:
    key = f"{record.source_key}\0{record.record_url or record.external_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return URIRef(SOURCE_NS[digest])


def records_to_graph(records: list[SourceRecord], query: str) -> Graph:
    graph = Graph()
    graph.bind("ex", EX)
    graph.bind("dcterms", DCTERMS)
    graph.bind("prov", PROV)
    graph.bind("rdfs", RDFS)
    graph.bind("schema", SCHEMA)
    graph.bind("wgs84", WGS84)
    retrieved_at = Literal(datetime.now(timezone.utc).isoformat(), datatype=XSD.dateTime)
    for record in records:
        if not _is_http_url(record.record_url) or not _is_http_url(record.source_home):
            raise SourceError(f"Invalid source URL for record {record.external_id!r}.")
        subject = _project_uri(record)
        # Source records use PROV and Dublin Core metadata rather than adding
        # provider-specific classes to the philosophy domain ontology.
        graph.add((subject, RDF.type, PROV.Entity))
        graph.add((subject, RDFS.label, Literal(record.title, lang="en")))
        graph.add((subject, DCTERMS.publisher, Literal(record.source_name)))
        graph.add((subject, DCTERMS.identifier, Literal(record.external_id)))
        graph.add((subject, DCTERMS.type, Literal(record.kind)))
        graph.add((subject, DCTERMS.source, URIRef(record.source_home)))
        graph.add((subject, PROV.wasDerivedFrom, URIRef(record.record_url)))
        graph.add((subject, PROV.generatedAtTime, retrieved_at))
        graph.add((subject, SCHEMA.url, URIRef(record.record_url)))
        graph.add((subject, SCHEMA.additionalType, Literal(record.source_key)))
        graph.add((subject, DCTERMS.subject, Literal(record.retrieved_for or query)))
        if record.description:
            graph.add((subject, DCTERMS.description, Literal(record.description)))
        if record.creator:
            graph.add((subject, DCTERMS.creator, Literal(record.creator)))
        if record.date:
            graph.add((subject, DCTERMS.date, Literal(record.date)))
        if _is_http_url(record.license_url):
            graph.add((subject, DCTERMS.license, URIRef(record.license_url)))
        if _is_http_url(record.image_url):
            graph.add((subject, SCHEMA.image, URIRef(record.image_url)))
        if record.latitude:
            graph.add((subject, WGS84.lat, Literal(record.latitude, datatype=XSD.decimal)))
        if record.longitude:
            graph.add((subject, WGS84.long, Literal(record.longitude, datatype=XSD.decimal)))
    return graph


def fetch_sources(
    source_keys: list[str], query: str, limit: int
) -> tuple[dict[str, list[SourceRecord]], dict[str, str]]:
    if not query.strip():
        raise ValueError("Search query must not be empty.")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"Limit must be between 1 and {MAX_LIMIT}.")
    fetched: dict[str, list[SourceRecord]] = {}
    statuses: dict[str, str] = {}
    for key in source_keys:
        source = SOURCES[key]
        try:
            fetched[key] = source.fetch(query.strip(), limit)
            statuses[key] = f"OK ({len(fetched[key])} records)"
        except MissingCredential as exc:
            statuses[key] = f"SKIPPED ({exc})"
        except SourceError as exc:
            statuses[key] = f"FAILED ({exc})"
    return fetched, statuses


def records_from_results(results: dict[str, list[SourceRecord]]) -> list[SourceRecord]:
    return [record for records in results.values() for record in records]
