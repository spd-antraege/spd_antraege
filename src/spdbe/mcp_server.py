"""Phase 5: MCP Server — the intelligence interface for Claude Code."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ---------------------------------------------------------------------------
# TTL cache — plain dict with timestamps, no external deps
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl_seconds: int, fn):
    """Return cached result if fresh, otherwise call fn() and cache."""
    now = time.monotonic()
    if key in _cache:
        cached_at, value = _cache[key]
        if now - cached_at < ttl_seconds:
            return value
    value = fn()
    _cache[key] = (now, value)
    return value


# Lazy imports to avoid loading everything at startup
_search = None
_federated = None
_driver = None


def _get_search():
    """Legacy: single-state HybridSearch for backwards compat."""
    global _search
    if _search is None:
        from spdbe.search import HybridSearch
        _search = HybridSearch(
            Path(os.environ.get("PIS_PARQUET", "/opt/pis/data/derived/antraege.parquet")),
            Path(os.environ.get("PIS_LANCE_DIR", "/opt/pis/data/vectors/documents")),
        )
        _search.build()
    return _search


def _get_federated():
    """Multi-state FederatedSearch. Falls back to legacy if no state dirs exist."""
    global _federated
    if _federated is None:
        from spdbe.search import FederatedSearch
        data_dir = Path(os.environ.get("PIS_DATA_DIR", "/opt/pis/data"))
        _federated = FederatedSearch(data_dir)
    return _federated


def _get_driver():
    global _driver
    if _driver is None:
        from spdbe.graph import get_driver
        _driver = get_driver()
    return _driver


def _graph_query(cypher: str, params: dict | None = None) -> list[dict]:
    driver = _get_driver()
    with driver.session() as s:
        result = s.run(cypher, **(params or {}))
        return [dict(record) for record in result]


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

app = Server("pis")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # Corpus & Search
        Tool(
            name="corpus_search",
            description="Search SPD Antragskorpus. Default: Berlin only. Set landesverband to search other states or 'all'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "landesverband": {"type": ["string", "array"], "default": "berlin", "description": "State(s) to search: 'berlin' (default), 'all', or ['berlin','bayern',...]"},
                    "top_k": {"type": "integer", "default": 10},
                    "year_min": {"type": "integer", "description": "Filter: minimum year"},
                    "year_max": {"type": "integer", "description": "Filter: maximum year"},
                    "submitter_type": {"type": "string", "description": "Filter: KDV|AG|FA|Abteilung|Landesvorstand"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="available_states",
            description="List available Landesverbände with document counts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="document_detail",
            description="Get full intelligence record for a single document by doc_id or kuerzel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document ID (SHA1) or kuerzel like 'Antrag 150/I/2022'"},
                },
                "required": ["doc_id"],
            },
        ),
        # Knowledge Graph
        Tool(
            name="graph_query",
            description="Execute a Cypher query against the Neo4j knowledge graph. Use for complex multi-hop queries about actors, topics, demands, and their relationships.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cypher": {"type": "string", "description": "Cypher query"},
                    "params": {"type": "object", "description": "Query parameters"},
                },
                "required": ["cypher"],
            },
        ),
        Tool(
            name="topic_map",
            description="Get overview of a topic or domain: connected topics, key actors, key documents, demand count.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Topic ID from taxonomy (e.g. 'mietenpolitik'). Omit for full taxonomy overview."},
                },
            },
        ),
        Tool(
            name="actor_profile",
            description="Get full profile of an actor: topics of interest, submission history, success rate, allies.",
            inputSchema={
                "type": "object",
                "properties": {
                    "actor_name": {"type": "string", "description": "Actor name (e.g. 'KDV Neukölln', 'Jusos Berlin')"},
                },
                "required": ["actor_name"],
            },
        ),
        # Strategy
        Tool(
            name="beschlusslage",
            description="Get all accepted Anträge on a topic with their demands. The authoritative 'what has already been decided' answer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Topic ID (e.g. 'mietenpolitik', 'digitale_souveraenitaet')"},
                },
                "required": ["topic_id"],
            },
        ),
        Tool(
            name="coalition_finder",
            description="Find likely allies and opponents for a topic based on historical submission patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Topic ID"},
                },
                "required": ["topic_id"],
            },
        ),
        Tool(
            name="red_line_check",
            description="Check if demands violate any of the 9 red lines (no Palantir, no biometric surveillance, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "demands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of demand texts to check",
                    },
                },
                "required": ["demands"],
            },
        ),
        Tool(
            name="failure_analysis",
            description="Analyze why Anträge failed on a topic. Returns demand count patterns, framing analysis, commission patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Topic ID"},
                },
                "required": ["topic_id"],
            },
        ),
        Tool(
            name="domain_landscape",
            description="Get full landscape of a political domain: all topics, top actors, success rates, trends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain_id": {"type": "string", "description": "Domain ID (e.g. 'digitalisierung', 'wohnen_stadtentwicklung')"},
                },
                "required": ["domain_id"],
            },
        ),
        # External Intelligence
        Tool(
            name="rss_digest",
            description="Get recent RSS signals, filtered by topic. Shows what's happening in the political news landscape.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string", "description": "Filter by topic ID (optional)"},
                    "hours": {"type": "integer", "default": 24, "description": "Look back N hours"},
                },
            },
        ),
        Tool(
            name="seo_landscape",
            description="Get SEO/search volume data for a keyword. Shows what people are actually searching for.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Keyword to check (e.g. 'Mietpreisbremse Berlin')"},
                },
                "required": ["keyword"],
            },
        ),
        # People
        Tool(
            name="person_lookup",
            description="Look up a person in SPD Berlin — role, organization, documents they're connected to.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Person name (or partial name for search)"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="people_by_org",
            description="List all known people in an organization (KDV, AG, Fraktion, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization": {"type": "string", "description": "Organization name (e.g. 'KDV Neukölln', 'SPD-Fraktion AGH')"},
                },
                "required": ["organization"],
            },
        ),
        # System
        Tool(
            name="graph_stats",
            description="Get node and edge counts from the knowledge graph.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        result = _handle_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


def _handle_tool(name: str, args: dict) -> dict | list:
    if name == "corpus_search":
        return _tool_corpus_search(args)
    elif name == "available_states":
        return _tool_available_states(args)
    elif name == "document_detail":
        return _tool_document_detail(args)
    elif name == "graph_query":
        return _tool_graph_query(args)
    elif name == "topic_map":
        return _tool_topic_map(args)
    elif name == "actor_profile":
        return _tool_actor_profile(args)
    elif name == "beschlusslage":
        return _tool_beschlusslage(args)
    elif name == "coalition_finder":
        return _tool_coalition_finder(args)
    elif name == "red_line_check":
        return _tool_red_line_check(args)
    elif name == "failure_analysis":
        return _tool_failure_analysis(args)
    elif name == "domain_landscape":
        return _tool_domain_landscape(args)
    elif name == "rss_digest":
        return _tool_rss_digest(args)
    elif name == "seo_landscape":
        return _tool_seo_landscape(args)
    elif name == "person_lookup":
        return _tool_person_lookup(args)
    elif name == "people_by_org":
        return _tool_people_by_org(args)
    elif name == "graph_stats":
        return _tool_graph_stats(args)
    else:
        return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_corpus_search(args: dict) -> list[dict]:
    states = args.get("landesverband", "berlin")
    top_k = args.get("top_k", 10)
    cache_key = f"corpus_search:{args.get('query')}:{states}:{top_k}:{args.get('year_min')}:{args.get('year_max')}:{args.get('submitter_type')}"

    def _do():
        es_host = os.environ.get("ES_HOST", "http://localhost:9200")
        es_index = os.environ.get("ES_INDEX", "spd-motions")

        # Normalize landesverband — "all" means no filter
        lv = None
        if isinstance(states, str) and states != "all":
            lv = states
        elif isinstance(states, list):
            lv = states[0] if len(states) == 1 else None

        try:
            from spdbe.haystack.pipelines.search import run_search
            return run_search(
                query=args["query"],
                es_host=es_host,
                index_name=es_index,
                top_k=top_k,
                landesverband=lv,
                year_min=args.get("year_min"),
                year_max=args.get("year_max"),
                submitter_type=args.get("submitter_type"),
                mode="hybrid",
            )
        except Exception:
            # Fall back to legacy search if Haystack/ES unavailable
            fs = _get_federated()
            filters = {}
            if args.get("year_min"):
                filters["year_min"] = args["year_min"]
            if args.get("year_max"):
                filters["year_max"] = args["year_max"]
            if args.get("submitter_type"):
                filters["submitter_type"] = args["submitter_type"]
            return fs.search(
                args["query"],
                states=states,
                top_k=top_k,
                filters=filters or None,
                mode="bm25",
            )

    return _cached(cache_key, 300, _do)


def _tool_available_states(args: dict) -> list[dict]:
    cache_key = "available_states"

    def _do():
        fs = _get_federated()
        return fs.state_info()

    return _cached(cache_key, 1800, _do)


def _tool_document_detail(args: dict) -> dict:
    doc_id = args["doc_id"]
    # Try by kuerzel first
    if doc_id.startswith("Antrag"):
        results = _graph_query(
            "MATCH (d:Document {kuerzel: $k}) RETURN d", params={"k": doc_id}
        )
    else:
        results = _graph_query(
            "MATCH (d:Document {doc_id: $id}) RETURN d", params={"id": doc_id}
        )

    if not results:
        return {"error": f"Document not found: {doc_id}"}

    doc = dict(results[0]["d"])

    # Get intelligence record
    intel_dir = Path(os.environ.get("PIS_INTELLIGENCE_DIR", "/opt/pis/data/intelligence"))
    year_str = str(doc.get("year", "UNKNOWN"))
    intel_path = intel_dir / year_str / f"{doc.get('doc_id', '')}.json"
    if intel_path.exists():
        doc["intelligence"] = json.loads(intel_path.read_text())

    # Get topics
    topics = _graph_query(
        "MATCH (d:Document {doc_id: $id})-[r:ABOUT]->(t:Topic) RETURN t.id AS topic, t.label_de AS label, r.rank AS rank",
        params={"id": doc.get("doc_id", doc_id)},
    )
    doc["topics"] = topics

    # Get demands
    demands = _graph_query(
        "MATCH (d:Document {doc_id: $id})-[:CONTAINS]->(dem:Demand) RETURN dem.text AS text, dem.type AS type, dem.strength AS strength",
        params={"id": doc.get("doc_id", doc_id)},
    )
    doc["demands"] = demands

    return doc


def _tool_graph_query(args: dict) -> list[dict]:
    return _graph_query(args["cypher"], args.get("params"))


def _tool_topic_map(args: dict) -> dict:
    topic_id = args.get("topic_id")
    cache_key = f"topic_map:{topic_id}"

    def _do():
        if not topic_id:
            # Full taxonomy overview
            domains = _graph_query("""
                MATCH (dm:Domain)<-[:BELONGS_TO]-(t:Topic)
                OPTIONAL MATCH (t)<-[:ABOUT]-(d:Document)
                WITH dm, t, count(d) AS doc_count
                RETURN dm.id AS domain, dm.label_de AS label,
                       collect({topic: t.id, label: t.label_de, docs: doc_count}) AS topics
                ORDER BY dm.label_de
            """)
            return {"domains": domains}

        # Single topic detail
        topic = _graph_query("""
            MATCH (t:Topic {id: $tid})
            OPTIONAL MATCH (t)<-[:ABOUT]-(d:Document)
            WITH t, count(d) AS total_docs,
                 sum(CASE WHEN d.status IN ['Annahme', 'Annahme mit Änderungen'] THEN 1 ELSE 0 END) AS accepted
            OPTIONAL MATCH (t)<-[:ABOUT]-(d2:Document)-[:SUBMITTED_BY]->(a:Actor)
            WITH t, total_docs, accepted, a, count(d2) AS actor_docs
            ORDER BY actor_docs DESC
            WITH t, total_docs, accepted, collect({name: a.name, type: a.type, docs: actor_docs})[..10] AS top_actors
            RETURN t.id AS topic, t.label_de AS label, total_docs, accepted, top_actors
        """, params={"tid": topic_id})

        return topic[0] if topic else {"error": f"Topic not found: {topic_id}"}

    return _cached(cache_key, 900, _do)


def _tool_actor_profile(args: dict) -> dict:
    from spdbe.graph import CYPHER_TEMPLATES
    results = _graph_query(CYPHER_TEMPLATES["actor_profile"], {"actor_name": args["actor_name"]})
    if not results:
        return {"error": f"Actor not found: {args['actor_name']}"}
    return results[0]


def _tool_beschlusslage(args: dict) -> list[dict]:
    cache_key = f"beschlusslage:{args['topic_id']}"

    def _do():
        from spdbe.graph import CYPHER_TEMPLATES
        return _graph_query(CYPHER_TEMPLATES["beschlusslage"], {"topic_id": args["topic_id"]})

    return _cached(cache_key, 900, _do)


def _tool_coalition_finder(args: dict) -> dict:
    topic_id = args["topic_id"]

    # Actors who submitted successfully on this topic
    allies = _graph_query("""
        MATCH (t:Topic {id: $tid})<-[:ABOUT]-(d:Document)-[:SUBMITTED_BY]->(a:Actor)
        WHERE d.status IN ['Annahme', 'Annahme mit Änderungen']
        WITH a, count(d) AS wins, collect(d.kuerzel) AS antraege
        ORDER BY wins DESC
        RETURN a.name AS actor, a.type AS type, wins, antraege[..3] AS sample_antraege
        LIMIT 15
    """, params={"tid": topic_id})

    # Actors who submitted but failed
    opponents = _graph_query("""
        MATCH (t:Topic {id: $tid})<-[:ABOUT]-(d:Document)-[:SUBMITTED_BY]->(a:Actor)
        WHERE d.status IN ['Ablehnung', 'Rücküberweisung']
        WITH a, count(d) AS losses
        ORDER BY losses DESC
        RETURN a.name AS actor, a.type AS type, losses
        LIMIT 10
    """, params={"tid": topic_id})

    return {"likely_allies": allies, "potential_opponents": opponents}


def _tool_red_line_check(args: dict) -> list[dict]:
    red_lines = _graph_query("MATCH (r:RedLine) RETURN r.id AS id, r.description AS description")
    results = []
    for demand in args["demands"]:
        demand_lower = demand.lower()
        status = "clear"
        matched_lines = []
        for rl in red_lines:
            desc = (rl.get("description") or "").lower()
            # Simple keyword matching for red line proximity
            keywords = desc.split()
            if any(kw in demand_lower for kw in keywords if len(kw) > 4):
                status = "warning"
                matched_lines.append(rl["description"])
            # Hard violations
            for trigger in ["palantir", "predictive policing", "chatkontrolle",
                          "vorratsdatenspeicherung", "biometrisch", "gesichtserkennung"]:
                if trigger in demand_lower and trigger in desc:
                    status = "violation"
                    if rl["description"] not in matched_lines:
                        matched_lines.append(rl["description"])

        results.append({
            "demand": demand,
            "status": status,
            "matched_red_lines": matched_lines,
        })
    return results


def _tool_failure_analysis(args: dict) -> dict:
    topic_id = args["topic_id"]

    # Failed Anträge
    failed = _graph_query("""
        MATCH (t:Topic {id: $tid})<-[:ABOUT]-(d:Document)
        WHERE d.status IN ['Ablehnung', 'Rücküberweisung']
        OPTIONAL MATCH (d)-[:CONTAINS]->(dem:Demand)
        WITH d, count(dem) AS demand_count, collect(dem.text)[..3] AS sample_demands
        RETURN d.kuerzel AS kuerzel, d.year AS year, d.status AS status,
               d.strategy_framing AS framing, d.style_persuasion AS persuasion,
               demand_count, sample_demands
        ORDER BY d.year DESC
    """, params={"tid": topic_id})

    # Successful Anträge stats
    success_stats = _graph_query("""
        MATCH (t:Topic {id: $tid})<-[:ABOUT]-(d:Document)
        WHERE d.status IN ['Annahme', 'Annahme mit Änderungen']
        OPTIONAL MATCH (d)-[:CONTAINS]->(dem:Demand)
        WITH d, count(dem) AS demand_count
        RETURN avg(demand_count) AS avg_demands_success,
               collect(d.strategy_framing) AS framings,
               collect(d.style_persuasion) AS persuasions
    """, params={"tid": topic_id})

    failure_stats = _graph_query("""
        MATCH (t:Topic {id: $tid})<-[:ABOUT]-(d:Document)
        WHERE d.status IN ['Ablehnung', 'Rücküberweisung']
        OPTIONAL MATCH (d)-[:CONTAINS]->(dem:Demand)
        WITH d, count(dem) AS demand_count
        RETURN avg(demand_count) AS avg_demands_failure
    """, params={"tid": topic_id})

    # Count framings
    from collections import Counter
    succ = success_stats[0] if success_stats else {}
    framing_counts = Counter(f for f in succ.get("framings", []) if f)

    return {
        "failed_antraege": failed,
        "aggregate_patterns": {
            "avg_demands_success": succ.get("avg_demands_success"),
            "avg_demands_failure": failure_stats[0].get("avg_demands_failure") if failure_stats else None,
            "successful_framings": [{"framing": f, "count": c} for f, c in framing_counts.most_common(5)],
        },
    }


def _tool_domain_landscape(args: dict) -> dict:
    from spdbe.graph import CYPHER_TEMPLATES
    results = _graph_query(CYPHER_TEMPLATES["domain_landscape"], {"domain_id": args["domain_id"]})

    # Also get topic overview
    topics = _graph_query("""
        MATCH (dm:Domain {id: $did})<-[:BELONGS_TO]-(t:Topic)
        OPTIONAL MATCH (t)<-[:ABOUT]-(d:Document)
        WITH t, count(d) AS docs
        RETURN t.id AS topic, t.label_de AS label, docs
        ORDER BY docs DESC
    """, params={"did": args["domain_id"]})

    return {"topics": topics, "top_actors": results}


def _tool_rss_digest(args: dict) -> list[dict]:
    topic_id = args.get("topic_id")
    hours = args.get("hours", 24)

    if topic_id:
        # Get signals linked to this topic from Neo4j
        return _graph_query("""
            MATCH (es:ExternalSignal)-[:RELATES_TO]->(t:Topic {id: $tid})
            RETURN es.title AS title, es.source AS source, es.url AS url,
                   es.relevance_score AS relevance, es.fetched_at AS fetched
            ORDER BY es.fetched_at DESC
            LIMIT 20
        """, params={"tid": topic_id})
    else:
        # Get all recent signals
        return _graph_query("""
            MATCH (es:ExternalSignal)
            OPTIONAL MATCH (es)-[:RELATES_TO]->(t:Topic)
            RETURN es.title AS title, es.source AS source, es.url AS url,
                   es.relevance_score AS relevance, es.fetched_at AS fetched,
                   collect(t.id) AS topics
            ORDER BY es.fetched_at DESC
            LIMIT 20
        """)


def _tool_seo_landscape(args: dict) -> dict:
    try:
        from spdbe.external.dataforseo import get_keyword_data, get_related_keywords
        keyword = args["keyword"]
        data = get_keyword_data(keyword)
        related = get_related_keywords(keyword, limit=10)
        return {"keyword": keyword, "data": data, "related": related}
    except Exception as e:
        return {"error": str(e)}


def _tool_person_lookup(args: dict) -> dict:
    name = args["name"]
    # Try exact match first, then fuzzy
    results = _graph_query("""
        MATCH (p:Person)
        WHERE p.name = $name OR p.name CONTAINS $name
        OPTIONAL MATCH (p)-[:MEMBER_OF]->(a:Actor)
        OPTIONAL MATCH (p)-[:MENTIONED_IN]->(d:Document)
        WITH p, collect(DISTINCT a.name) AS orgs, count(DISTINCT d) AS doc_mentions
        RETURN p.name AS name, p.role AS role, p.source AS source,
               orgs, doc_mentions
        LIMIT 10
    """, params={"name": name})

    if not results:
        return {"error": f"Person not found: {name}"}
    return results


def _tool_people_by_org(args: dict) -> list[dict]:
    org = args["organization"]
    return _graph_query("""
        MATCH (p:Person)-[:MEMBER_OF]->(a:Actor)
        WHERE a.name CONTAINS $org
        RETURN p.name AS name, p.role AS role, p.source AS source, a.name AS organization
        ORDER BY p.role, p.name
    """, params={"org": org})


def _tool_graph_stats(args: dict) -> dict:
    def _do():
        stats = {}
        for label in ["Document", "Topic", "Domain", "Actor", "Person", "Demand", "Event", "RedLine"]:
            result = _graph_query(f"MATCH (n:{label}) RETURN count(n) AS n")
            stats[label] = result[0]["n"] if result else 0

        for rel in ["ABOUT", "SUBMITTED_BY", "ADDRESSED_TO", "CONTAINS",
                    "INTERESTED_IN", "ALLIES_WITH", "CONTINUES", "CONTRADICTS",
                    "STRENGTHENS", "MEMBER_OF", "MENTIONED_IN"]:
            result = _graph_query(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n")
            stats[f"edge_{rel}"] = result[0]["n"] if result else 0

        return stats

    return _cached("graph_stats", 1800, _do)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    if "--ping" in sys.argv:
        print("pong")
        sys.exit(0)

    import asyncio
    asyncio.run(main())
