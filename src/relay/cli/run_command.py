"""`relay run PACKET`: the interactive steering loop on one work packet, recorded in the
repository's run store."""

import argparse
from pathlib import Path

from relay.domain import PacketError, load_work_packet
from relay.drift.git import GitError
from relay.loop.agent import OpenCodeAgent
from relay.loop.publish import GitHubPublisher, PublishError, issue_title
from relay.loop.record import RunLog, developer_identity, store_path
from relay.loop.steer import AgentSettings, Console, run_packet
from relay.loop.workspace import WorkspaceError
from relay.runtime.opencode import OpenCodeClient, OpenCodeError
from relay.store.runs import RunStore, StoreError

DEFAULT_OPENCODE = "http://127.0.0.1:4096"


def provider_and_model(text: str) -> tuple[str, str]:
    provider, _, model = text.partition("/")
    if not provider or not model:
        raise argparse.ArgumentTypeError("use PROVIDER/MODEL, e.g. anthropic/claude-sonnet-5-5")
    return provider, model


def add_run_arguments(run: argparse.ArgumentParser) -> None:
    run.add_argument("packet", type=Path, help="work packet YAML")
    run.add_argument("--repo", type=Path, default=Path("."), help="repository (default: .)")
    run.add_argument("--model", type=provider_and_model, required=True, help="PROVIDER/MODEL")
    run.add_argument("--agent", help="OpenCode agent (default: the packet's role)")
    run.add_argument("--opencode", default=DEFAULT_OPENCODE, help="OpenCode server URL")


def run_command(args: argparse.Namespace) -> tuple[str, int]:
    console = Console(ask=input, show=print)
    try:
        path = store_path(args.repo)
    except GitError as error:
        return f"relay run stopped: {error}", 2
    try:
        message = steer_packet(args, console, path)
    except (
        PacketError,
        WorkspaceError,
        OpenCodeError,
        PublishError,
        GitError,
        StoreError,
    ) as error:
        return f"relay run stopped: {error}\nRun store: {path}", 2
    except KeyboardInterrupt:
        pending = "Interrupted; the run stays pending and the next relay run offers cleanup."
        return f"\n{pending}\nRun store: {path}", 130
    return f"{message}\nRun store: {path}", 0


def steer_packet(args: argparse.Namespace, console: Console, path: Path) -> str:
    packet = load_work_packet(args.packet)
    provider, model = args.model
    settings = AgentSettings(args.agent or packet.role, provider, model)
    developer = developer_identity(args.repo)
    store = RunStore(path)
    client = OpenCodeClient(args.opencode)
    try:
        result = run_packet(
            args.repo,
            packet,
            settings,
            OpenCodeAgent(client, console.show),
            GitHubPublisher(),
            console,
            lambda number: issue_title(args.repo, number),
            RunLog(store, developer),
        )
    finally:
        client.close()
        store.close()
    outcome = result.records[-1].outcome if result.records else "no attempt"
    return f"Packet {result.branch}: {outcome} after {len(result.records)} attempt(s)."
