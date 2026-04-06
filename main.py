#!/usr/bin/env python3
"""
Python TUI Agent — Entry point.

Usage:
    python main.py                     # Interactive TUI mode
    python main.py -p "your prompt"   # Headless (single turn, no TUI)
    python main.py --version
    python main.py --setup             # Open setup dialog immediately
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as `python main.py` from the project root
sys.path.insert(0, str(Path(__file__).parent))

VERSION = "0.1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pty-agent",
        description="Python TUI Agent — AI coding assistant in your terminal",
    )
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Print version and exit",
    )
    parser.add_argument(
        "-p", "--print",
        metavar="PROMPT",
        nargs="?",
        const="__stdin__",
        help="Headless mode: run a single prompt and print the result (no TUI). "
             "Omit PROMPT to read from stdin.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Open the setup dialog on startup (TUI mode only)",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Override the model (e.g. claude-3-5-sonnet-20241022)",
    )
    parser.add_argument(
        "--base-url",
        metavar="URL",
        help="Override the API base URL",
    )
    parser.add_argument(
        "--cwd",
        metavar="DIR",
        help="Set working directory (default: current directory)",
    )
    return parser.parse_args()


# ── Headless mode ─────────────────────────────────────────────────────────────

async def run_headless(prompt: str, args: argparse.Namespace) -> None:
    """Run a single query without TUI, print result to stdout."""
    from agent.config import load_config
    from agent.messages import UserMessage
    from agent.query_engine import QueryEngine

    cfg = load_config()
    if args.model:
        cfg.model = args.model
    if args.base_url:
        cfg.base_url = args.base_url

    if not cfg.is_configured():
        print("Error: No API key configured. Set ANTHROPIC_API_KEY or run with --setup.", file=sys.stderr)
        sys.exit(1)

    engine = QueryEngine(cfg)
    messages = [UserMessage(content=prompt)]

    system = (
        "You are a helpful AI assistant. Answer concisely and accurately."
    )

    def on_text(chunk: str) -> None:
        print(chunk, end="", flush=True)

    def on_tool_use(name: str, tool_id: str, tool_input: dict) -> None:
        print(f"\n[Tool: {name}]\n", flush=True)

    def on_tool_result(tool_id: str, result: str, is_error: bool) -> None:
        prefix = "[Error] " if is_error else "[Result] "
        print(f"{prefix}{result[:500]}\n", flush=True)

    await engine.stream_query(
        messages=messages,
        system_prompt=system,
        on_text=on_text,
        on_tool_use=on_tool_use,
        on_tool_result=on_tool_result,
        confirm_fn=None,  # Auto-approve in headless mode
    )
    print()  # Final newline


# ── TUI mode ──────────────────────────────────────────────────────────────────

def run_tui(args: argparse.Namespace) -> None:
    """Launch the full Textual TUI."""
    import os
    from agent.config import load_config
    from tui.app import AgentApp

    cfg = load_config()
    if args.model:
        cfg.model = args.model
    if args.base_url:
        cfg.base_url = args.base_url
    if args.cwd:
        target = Path(args.cwd).resolve()
        if not target.is_dir():
            print(f"Error: --cwd path does not exist: {target}", file=sys.stderr)
            sys.exit(1)
        os.chdir(target)
        cfg.cwd = str(target)
    else:
        cfg.cwd = str(Path.cwd())

    app = AgentApp(config=cfg)

    # If --setup flag, open setup dialog on first render
    if args.setup or not cfg.is_configured():
        original_on_mount = app.on_mount

        def patched_on_mount() -> None:
            original_on_mount()
            app.call_after_refresh(app.action_open_setup)

        app.on_mount = patched_on_mount

    app.run()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.version:
        from tui.app import WXJ_LOGO
        print(WXJ_LOGO)
        print(f"WXJ AI Coding Assistant  v{VERSION}")
        return

    if args.print is not None:
        # Headless mode
        if args.print == "__stdin__":
            if sys.stdin.isatty():
                print("Usage: python main.py -p 'your prompt'  or  echo 'prompt' | python main.py -p", file=sys.stderr)
                sys.exit(1)
            prompt = sys.stdin.read().strip()
        else:
            prompt = args.print

        if not prompt:
            print("Error: Empty prompt.", file=sys.stderr)
            sys.exit(1)

        asyncio.run(run_headless(prompt, args))
        return

    # Interactive TUI
    run_tui(args)


if __name__ == "__main__":
    main()
