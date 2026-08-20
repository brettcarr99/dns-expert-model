"""CLI utilities, terminal banner, rich formatting, and diagnostic helpers."""

import sys
from typing import Any, Dict, List, Optional

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None


BANNER = r"""
  ____  _   _ ____    _____                      _   
 |  _ \| \ | / ___|  | ____|_  ___ __   ___ _ __| |_ 
 | | | |  \| \___ \  |  _| \ \/ / '_ \ / _ \ '__| __|
 | |_| | |\  |___) | | |___ >  <| |_) |  __/ |  | |_ 
 |____/|_| \_|____/  |_____/_/\_\ .__/ \___|_|   \__|
                                |_|                  
"""


def print_banner(model_name: str, db_stats: Optional[Dict[str, Any]] = None) -> None:
    if HAS_RICH and console:
        console.print(f"[bold cyan]{BANNER}[/bold cyan]")
        info = f"[bold green]DNS-Expert v1.0.0[/bold green] | Model: [bold yellow]{model_name}[/bold yellow]"
        if db_stats and db_stats.get("total_chunks"):
            total_cnt = db_stats.get("total_chunks", 0)
            size_mb = db_stats.get("size_mb", 0)
            info += f" | Knowledge Base: [bold magenta]{total_cnt}[/bold magenta] chunks ({size_mb}MB)"
        console.print(Panel(info, border_style="cyan"))
        console.print("[dim]Type your question, or [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit.[/dim]\n")
    else:
        print(BANNER)
        print(f"=== DNS-Expert v1.0.0 | Model: {model_name} ===")
        if db_stats and db_stats.get("total_chunks"):
            total_cnt = db_stats.get("total_chunks", 0)
            size_mb = db_stats.get("size_mb", 0)
            print(f"Knowledge Base: {total_cnt} chunks ({size_mb}MB)")
        print("Type your question, or /help for commands, /quit to exit.\n")


def render_markdown(text: str) -> None:
    if HAS_RICH and console:
        md = Markdown(text)
        console.print(md)
    else:
        print(text)


def render_sources(sources: List[Dict[str, Any]]) -> None:
    if not sources:
        return

    if HAS_RICH and console:
        table = Table(title="[bold cyan]Retrieved Knowledge Sources & Citations[/bold cyan]", border_style="dim")
        table.add_column("#", style="bold yellow", width=4)
        table.add_column("Type", style="green", width=12)
        table.add_column("Title / Document", style="white", min_width=30)
        table.add_column("Section / Detail", style="dim", min_width=25)
        table.add_column("RRF Score", style="cyan", justify="right", width=10)

        for idx, src in enumerate(sources, start=1):
            src_type = src.get("source_type", "unknown").upper()
            title = src.get("title", "")
            section = src.get("section", "")
            score = str(src.get("rrf_score", "N/A"))
            table.add_row(str(idx), src_type, title, section, score)

        console.print(table)
    else:
        print("\n=== Retrieved Knowledge Sources ===")
        for idx, src in enumerate(sources, start=1):
            print(f"[{idx}] {src.get('source_type', '').upper()} | {src.get('title')} | Section: {src.get('section')} (Score: {src.get('rrf_score')})")
        print("===================================\n")


def detect_input_type(text: str) -> str:
    lower = text.lower()
    if ";; ->>header<<-" in lower or ";; flags:" in lower or ";; query time:" in lower:
        return "dig_output"
    if "zone " in lower and "{" in lower:
        return "bind_config"
    if "$origin" in lower or "$ttl" in lower or " in soa " in lower:
        return "zone_file"
    return "text"
