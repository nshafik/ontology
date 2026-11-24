"""Fetch a bounded sample from selected APIs and save it as RDF/Turtle.

    python3 app/ingest_sources.py --source sep openlibrary viaf --query "Plato" --limit 2
    python3 app/ingest_sources.py --source pleiades --query "Athens" --append
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import Graph

from sources import SOURCES, _project_uri, fetch_sources, records_from_results, records_to_graph

ROOT = Path(__file__).resolve().parent.parent
# Kept out of philosophy_complete.ttl: provider records are metadata for
# curation, not reviewed philosophical claims.
DEFAULT_OUTPUT = ROOT / "data" / "imported_sources.ttl"


def ingest(
    source_keys: list[str],
    query: str,
    limit: int,
    output: Path,
    append: bool = False,
) -> tuple[int, dict[str, str]]:
    fetched, statuses = fetch_sources(source_keys, query, limit)
    records = records_from_results(fetched)
    graph = Graph()
    if append and output.exists():
        graph.parse(output, format="turtle")
    additions = records_to_graph(records, query)
    if append:
        for record in records:
            graph.remove((_project_uri(record), None, None))
    for triple in additions:
        graph.add(triple)

    output.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(output), format="turtle", encoding="utf-8")
    return len(records), statuses


def main() -> int:
    from ask import load_dotenv
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        nargs="+",
        default=["all"],
        choices=["all", *SOURCES.keys()],
        help="one or more source keys, or 'all' (default: all)",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="search term sent to the selected source APIs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="maximum records per source (1-25; default: 3)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Turtle output file (default: data/imported_sources.ttl)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="merge into an existing output file instead of replacing it",
    )
    args = parser.parse_args()
    source_keys = list(SOURCES) if "all" in args.source else args.source
    try:
        record_count, statuses = ingest(
            source_keys,
            args.query,
            args.limit,
            args.output,
            append=args.append,
        )
    except ValueError as exc:
        parser.error(str(exc))
    for key, status in statuses.items():
        print(f"{key}: {status}")
    print(f"Saved {record_count} fetched record(s) to {args.output}")
    return 1 if any(status.startswith("FAILED") for status in statuses.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
