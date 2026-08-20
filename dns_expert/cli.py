"""Interactive CLI and Command Runner for DNS-Expert."""

import argparse
import os
import select
import sys
from typing import Any, Dict, List, Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

from dns_expert.config import CHAT_MODEL, DB_PATH, DEFAULT_DATA_DIR, SUPPORTED_VENDORS
from dns_expert.knowledge.db import KnowledgeDB
from dns_expert.knowledge.search import HybridSearchEngine
from dns_expert.ollama_client import OllamaClient, OllamaError
from dns_expert.prompt import build_rag_prompt
from dns_expert.utils import (
    HAS_RICH,
    console,
    detect_input_type,
    print_banner,
    render_markdown,
    render_sources,
)


class DNSExpertCLI:
    def __init__(self, model: Optional[str] = None, db_path: Optional[str] = None):
        self.db = KnowledgeDB(db_path=db_path)
        self.client = OllamaClient(model=model or CHAT_MODEL)
        self.search_engine = HybridSearchEngine(db=self.db, ollama_client=self.client)
        self.history: List[Dict[str, str]] = []
        self.last_sources: List[Dict[str, Any]] = []
        self.active_vendor: Optional[str] = None
        self.active_source_type: Optional[str] = None

        if not self.client.check_health():
            print(f"[!] Warning: Unable to connect to Ollama at {self.client.host}.")
            print("    Make sure Ollama is running (ollama serve or Ollama desktop app).\n")

    def run_repl(self) -> None:
        best_model = self.client.get_best_available_model()
        db_stats = self.db.get_stats()
        print_banner(best_model, db_stats)

        session = None
        if HAS_PROMPT_TOOLKIT:
            history_file = DEFAULT_DATA_DIR / "history.txt"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            session = PromptSession(
                history=FileHistory(str(history_file)),
                auto_suggest=AutoSuggestFromHistory(),
            )

        while True:
            try:
                prompt_prefix = "dns-expert"
                if self.active_vendor:
                    prompt_prefix += f"[{self.active_vendor}]"
                elif self.active_source_type:
                    prompt_prefix += f"[{self.active_source_type}]"
                prompt_str = f"{prompt_prefix}> "

                if session:
                    user_input = session.prompt(prompt_str).strip()
                else:
                    user_input = input(prompt_str).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if not self._handle_slash_command(user_input):
                        break
                    continue

                self.query(user_input)

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break

    def query(
        self,
        user_query: str,
        diagnostic_input: Optional[str] = None,
        source_type: Optional[str] = None,
        vendor: Optional[str] = None,
        show_citations: bool = False,
    ) -> None:
        src_type = source_type or self.active_source_type
        vend = vendor or self.active_vendor

        if HAS_RICH and console:
            console.print(f"\n[dim]Searching DNS knowledge base...[/dim]")

        # 1. Retrieve relevant chunks
        try:
            chunks = self.search_engine.search(
                query=user_query,
                top_k=6,
                source_type=src_type,
                vendor=vend,
            )
            self.last_sources = chunks
        except Exception:
            chunks = []
            self.last_sources = []

        # 2. Assemble RAG prompt
        messages = build_rag_prompt(
            user_query=user_query,
            retrieved_chunks=chunks,
            conversation_history=self.history,
            diagnostic_context=diagnostic_input,
        )

        # 3. Stream model response
        if HAS_RICH and console:
            console.print(f"[bold green]DNS-Expert:[/bold green]")
        else:
            print("\nDNS-Expert:")

        response_chunks = []
        try:
            for token in self.client.chat_stream(messages):
                sys.stdout.write(token)
                sys.stdout.flush()
                response_chunks.append(token)
            print("\n")
        except OllamaError as e:
            print(f"\n[Error communicating with Ollama: {e}]\n")
            return

        full_response = "".join(response_chunks)

        # Update conversation history
        self.history.append({"role": "user", "content": user_query})
        self.history.append({"role": "assistant", "content": full_response})

        if show_citations and self.last_sources:
            render_sources(self.last_sources)

    def _handle_slash_command(self, cmd_line: str) -> bool:
        parts = cmd_line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ["/quit", "/exit", "/q"]:
            print("Goodbye!")
            return False

        elif cmd in ["/help", "/h", "/?"]:
            self._print_help()

        elif cmd == "/clear":
            self.history.clear()
            print("[+] Conversation history cleared.")

        elif cmd == "/sources":
            if self.last_sources:
                render_sources(self.last_sources)
            else:
                print("[!] No sources available from last query.")

        elif cmd == "/stats":
            stats = self.db.get_stats()
            print(f"\n=== Knowledge Base Statistics ===")
            print(f"Database: {stats['db_path']} ({stats['size_mb']} MB)")
            print(f"Total Chunks: {stats['total_chunks']}")
            print(f"With Embeddings: {stats['chunks_with_embeddings']}")
            print(f"Source Breakdown: {stats['by_source']}")
            print(f"Vendor Breakdown: {stats['by_vendor']}")
            print("=================================\n")

        elif cmd == "/vendor":
            if not args:
                print(f"Active vendor filter: {self.active_vendor or 'None'}")
                print(f"Supported vendors: {', '.join(SUPPORTED_VENDORS)}")
                print("Usage: /vendor <name> or /vendor all")
            else:
                vend = args[0].lower()
                if vend in ["all", "none", "clear", "reset"]:
                    self.active_vendor = None
                    self.active_source_type = None
                    print("[+] Reset vendor and source filters to ALL.")
                elif vend in SUPPORTED_VENDORS:
                    self.active_vendor = vend
                    self.active_source_type = "vendor_doc"
                    print(f"[+] Knowledge retrieval restricted to: {vend.upper()}")
                else:
                    print(f"[!] Unknown vendor '{vend}'. Options: {', '.join(SUPPORTED_VENDORS)}")

        elif cmd == "/rfc":
            if not args:
                print("Usage: /rfc <number> (e.g. /rfc 1035, /rfc 8484)")
            else:
                rfc_num = args[0].replace("rfc", "").strip()
                self.query(
                    f"Explain RFC {rfc_num} and summarize its key protocol specifications and requirements.",
                    source_type="rfc",
                    show_citations=True,
                )

        elif cmd == "/model":
            if not args:
                installed = self.client.list_models()
                print(f"Current Model: {self.client.model}")
                print(f"Available in Ollama: {', '.join(installed)}")
                print("Usage: /model <model_name>")
            else:
                new_model = args[0]
                self.client.model = new_model
                print(f"[+] Active model switched to: {new_model}")

        else:
            print(f"[!] Unknown command: {cmd}. Type /help for available commands.")

        return True

    def _print_help(self) -> None:
        help_text = """
[bold cyan]DNS-Expert Commands & Shortcuts:[/bold cyan]
  [bold yellow]/rfc <num>[/bold yellow]         Query specific RFC (e.g. /rfc 8484, /rfc 1035)
  [bold yellow]/vendor <name>[/bold yellow]     Restrict search to vendor (bind9, unbound, powerdns, etc.)
  [bold yellow]/vendor all[/bold yellow]        Clear vendor restrictions
  [bold yellow]/sources[/bold yellow]           Show citations and retrieved sources for last response
  [bold yellow]/model <name>[/bold yellow]      Switch active Ollama model
  [bold yellow]/stats[/bold yellow]             Show indexed chunks and database statistics
  [bold yellow]/clear[/bold yellow]             Reset conversation history
  [bold yellow]/help[/bold yellow]              Show this help menu
  [bold yellow]/quit[/bold yellow]              Exit DNS-Expert
"""
        if HAS_RICH and console:
            console.print(help_text)
        else:
            print(help_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="DNS-Expert: Local AI Assistant for DNS Engineers")
    parser.add_argument("subcommand", nargs="?", choices=["chat", "ask", "debug", "rfc", "stats"], default="chat", help="Subcommand to run")
    parser.add_argument("query_text", nargs="*", help="Query text or RFC number")
    parser.add_argument("--model", "-m", type=str, default=None, help="Ollama model name to use")
    parser.add_argument("--db", type=str, default=None, help="Path to knowledge database")
    parser.add_argument("--vendor", "-v", type=str, default=None, help="Filter search by vendor")
    parser.add_argument("--citations", "-c", action="store_true", help="Display retrieved source citations")

    args = parser.parse_args()
    cli = DNSExpertCLI(model=args.model, db_path=args.db)

    piped_input = None
    if not sys.stdin.isatty():
        try:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                piped_input = sys.stdin.read().strip()
        except Exception:
            pass

    if args.subcommand == "chat" and not piped_input:
        cli.run_repl()

    elif args.subcommand == "ask" or (args.subcommand == "chat" and piped_input):
        q = " ".join(args.query_text) if args.query_text else "Analyze and explain the provided input."
        cli.query(user_query=q, diagnostic_input=piped_input, vendor=args.vendor, show_citations=args.citations)

    elif args.subcommand == "debug":
        if not piped_input and not sys.stdin.isatty():
            try:
                piped_input = sys.stdin.read().strip()
            except Exception:
                pass
        q = " ".join(args.query_text) if args.query_text else "Diagnose this DNS diagnostic output / configuration for root causes or errors."
        cli.query(user_query=q, diagnostic_input=piped_input, vendor=args.vendor, show_citations=True)

    elif args.subcommand == "rfc":
        if not args.query_text:
            print("Error: Specify RFC number, e.g. dns-expert rfc 8484")
            sys.exit(1)
        rfc_num = args.query_text[0].replace("rfc", "").strip()
        cli.query(f"Explain RFC {rfc_num} and summarize its key protocol specifications.", source_type="rfc", show_citations=True)

    elif args.subcommand == "stats":
        stats = cli.db.get_stats()
        print(f"Database: {stats['db_path']} ({stats['size_mb']} MB)")
        print(f"Total Chunks: {stats['total_chunks']}")
        print(f"With Vectors: {stats['chunks_with_embeddings']}")
        print(f"By Source: {stats['by_source']}")
        print(f"By Vendor: {stats['by_vendor']}")


if __name__ == "__main__":
    main()
