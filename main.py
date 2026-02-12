import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import config as app_config
from agents.registry import AgentRegistry
from chief.orchestrator import ChiefOfStaff
from documents.ingestion import chunk_text, content_hash, load_text_file
from documents.store import DocumentStore
from memory.store import MemoryStore

console = Console()


def create_chief() -> ChiefOfStaff:
    app_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    app_config.AGENT_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    memory_store = MemoryStore(app_config.MEMORY_DB_PATH)
    document_store = DocumentStore(persist_dir=app_config.CHROMA_PERSIST_DIR)
    agent_registry = AgentRegistry(app_config.AGENT_CONFIGS_DIR)

    return ChiefOfStaff(
        memory_store=memory_store,
        document_store=document_store,
        agent_registry=agent_registry,
    )


async def run_command(command: str, chief: ChiefOfStaff) -> str:
    if command == "agents":
        agents = chief.agent_registry.list_agents()
        if not agents:
            return "No expert agents configured yet. They'll be created on demand."
        lines = ["Available expert agents:"]
        for a in agents:
            lines.append(f"  - {a.name}: {a.description}")
        return "\n".join(lines)

    elif command == "memory":
        categories = ["personal", "preference", "work", "relationship"]
        lines = ["Stored facts:"]
        total = 0
        for cat in categories:
            facts = chief.memory_store.get_facts_by_category(cat)
            if facts:
                lines.append(f"\n  [{cat}]")
                for f in facts:
                    lines.append(f"    {f.key}: {f.value}")
                    total += 1
        if total == 0:
            return "No facts stored yet. I'll learn about you as we chat."
        return "\n".join(lines)

    elif command == "clear":
        chief.conversation_history.clear()
        return "Conversation cleared. Memory persists."

    elif command.startswith("ingest "):
        path = Path(command[7:].strip())
        if not path.exists():
            return f"Path not found: {path}"
        return ingest_path(path, chief.document_store)

    return None


def ingest_path(path: Path, document_store: DocumentStore) -> str:
    supported = {".txt", ".md", ".py", ".json", ".yaml", ".yml"}
    files = []

    if path.is_file():
        files = [path]
    elif path.is_dir():
        for ext in supported:
            files.extend(path.glob(f"**/*{ext}"))

    if not files:
        return f"No supported files found at {path}"

    total_chunks = 0
    for file in files:
        text = load_text_file(file)
        chunks = chunk_text(text)
        file_hash = content_hash(text)

        texts = []
        metadatas = []
        ids = []
        for i, chunk in enumerate(chunks):
            texts.append(chunk)
            metadatas.append({"source": str(file.name), "chunk_index": i})
            ids.append(f"{file_hash}_{i}")

        document_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        total_chunks += len(chunks)

    return f"Ingested {len(files)} file(s), {total_chunks} chunks."


async def chat_loop():
    console.print(Panel(
        Text("Chief of Staff ready. Type your request.\n"
             "Commands: agents | memory | clear | ingest <path> | quit",
             style="bold"),
        title="Chief of Staff",
        border_style="blue",
    ))

    chief = create_chief()

    while True:
        try:
            user_input = console.input("[bold green]> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            console.print("Goodbye!")
            break

        # Check for built-in commands
        cmd_result = await run_command(user_input.lower(), chief)
        if cmd_result is not None:
            console.print(cmd_result)
            continue

        # Send to Chief of Staff
        with console.status("[bold blue]Chief of Staff is thinking...[/]"):
            try:
                response = await chief.process(user_input)
                console.print(f"\n[bold blue]Chief of Staff:[/] {response}\n")
            except Exception as e:
                console.print(f"\n[bold red]Error:[/] {e}\n")


def cli_entry():
    asyncio.run(chat_loop())


if __name__ == "__main__":
    cli_entry()
