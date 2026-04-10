"""``jarvis knowledge`` — inspect and search the local knowledge store."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("knowledge")
def knowledge() -> None:
    """Inspect and search the local knowledge store."""


@knowledge.command("list")
@click.option("--source", "-s", default=None, help="Filter by source.")
@click.option("--limit", "-n", default=20, show_default=True, help="Max rows to show.")
def list_cmd(source: str | None, limit: int) -> None:
    """List what's stored in the knowledge base, grouped by source."""
    from openjarvis.connectors.store import KnowledgeStore

    store = KnowledgeStore()
    conn = store._conn

    if source:
        rows = conn.execute(
            """
            SELECT source, doc_type, title, content, url, timestamp
            FROM knowledge_chunks
            WHERE source = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (source, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT source, doc_type, title, content, url, timestamp
            FROM knowledge_chunks
            ORDER BY source, timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        msg = "No chunks found" + (f" for source='{source}'" if source else "") + "."
        console.print(f"[yellow]{msg}[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("Source", style="green", no_wrap=True, min_width=12)
    table.add_column("Type", style="dim", no_wrap=True, min_width=8)
    table.add_column("Title", no_wrap=True, max_width=48)
    table.add_column("Content (preview)", no_wrap=True, max_width=40)
    table.add_column("URL", style="dim cyan", no_wrap=True, max_width=45)

    for row in rows:
        title = (row["title"] or "")[:48]
        content_preview = (row["content"] or "")[:40]
        url = row["url"] or ""
        table.add_row(row["source"], row["doc_type"], title, content_preview, url)

    console.print(table)
    console.print(f"\n[dim]{len(rows)} chunk(s) shown[/dim]")


@knowledge.command("sources")
def sources_cmd() -> None:
    """Show a summary of all sources and how many chunks each has."""
    from openjarvis.connectors.store import KnowledgeStore

    store = KnowledgeStore()
    rows = store._conn.execute(
        """
        SELECT source, doc_type, COUNT(*) as chunks, MAX(timestamp) as last_sync
        FROM knowledge_chunks
        GROUP BY source, doc_type
        ORDER BY chunks DESC
        """
    ).fetchall()

    if not rows:
        console.print("[yellow]Knowledge base is empty.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("Source", style="green", no_wrap=True, min_width=14)
    table.add_column("Type", style="dim", no_wrap=True, min_width=10)
    table.add_column("Chunks", justify="right", no_wrap=True)
    table.add_column("Last Synced", style="dim", no_wrap=True)

    for row in rows:
        table.add_row(
            row["source"], row["doc_type"], str(row["chunks"]), row["last_sync"] or "—"
        )

    console.print(table)


@knowledge.command("chat")
@click.option("--model", "-m", default=None, help="Model override.")
def chat_cmd(model: str | None) -> None:
    """Interactive deep-research chat against the local knowledge store."""
    from openjarvis.agents.deep_research import DeepResearchAgent
    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.core.config import load_config
    from openjarvis.engine import get_engine
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    config = load_config()
    resolved = get_engine(config, None)
    if resolved is None:
        console.print("[red]No inference engine available. Is Ollama running?[/red]")
        return

    engine_name, engine = resolved
    model_name = model or config.intelligence.default_model or ""
    console.print(f"[dim]Engine: {engine_name}  Model: {model_name}[/dim]\n")

    store = KnowledgeStore()
    rows = store._conn.execute(
        "SELECT source, COUNT(*) as n FROM knowledge_chunks GROUP BY source"
    ).fetchall()
    if not rows:
        console.print(
            "[yellow]Knowledge base is empty. Sync a connector first.[/yellow]"
        )
        return

    parts = [f"{r['source']} ({r['n']})" for r in rows]
    console.print(f"[green]Knowledge base:[/green] {', '.join(parts)}")
    console.print("Type your question. [bold]/quit[/bold] to exit.\n")

    retriever = TwoStageRetriever(store)
    tools = [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=model_name),
        ThinkTool(),
    ]

    agent = DeepResearchAgent(
        engine=engine, model=model_name, tools=tools, interactive=True
    )

    while True:
        try:
            query = console.input("[bold blue]knowledge>[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query:
            continue
        if query in ("/quit", "/exit", "quit", "exit"):
            break
        agent.run(query)


@knowledge.command("search")
@click.argument("query")
@click.option("--source", "-s", default=None, help="Filter by source.")
@click.option("--top-k", "-k", default=10, show_default=True, help="Number of results.")
def search_cmd(query: str, source: str | None, top_k: int) -> None:
    """Search the knowledge base with a BM25 keyword query."""
    from openjarvis.connectors.store import KnowledgeStore

    store = KnowledgeStore()
    results = store.retrieve(query, top_k=top_k, source=source)

    if not results:
        console.print(f"[yellow]No results for '{query}'.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        title = r.metadata.get("title", "")
        url = r.metadata.get("url", "")
        console.print(
            f"\n[bold cyan]Result {i}[/bold cyan] "
            f"[dim](score={r.score:.2f}, source={r.source})[/dim]"
        )
        if title:
            console.print(f"  [bold]{title}[/bold]")
        console.print(f"  {r.content}")
        if url:
            console.print(f"  [dim cyan]{url}[/dim cyan]")
