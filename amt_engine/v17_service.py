"""Railway-safe V1.7 service entry point.

Default mode is inert. Database writes require the explicit run subcommand
and a supplied session-envelope file. All target and PostgreSQL identity checks
remain in the underlying V1.7 writer.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from amt_engine.v17_writer import persist_session, validate_target_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "idle",
        help="Remain inert until Railway stops the service (the default)",
    )
    run_parser = subparsers.add_parser(
        "run",
        help="Manually execute one validated V1.7 session envelope",
    )
    run_parser.add_argument(
        "--input",
        required=True,
        help="Path to a reviewed JSON session-envelope file",
    )
    return parser


def idle() -> int:
    """Block without opening a database connection or performing writes."""
    print("V1.7 runner idle; no database connection opened.", flush=True)
    while True:
        signal.pause()


def run_once(input_path: str) -> int:
    env = dict(os.environ)
    validate_target_environment(env)
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    with psycopg.connect(
        env["DATABASE_URL"],
        sslmode="require",
        row_factory=dict_row,
    ) as conn:
        result = persist_session(conn, payload, test_mode=False)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "idle"):
        return idle()
    if args.command == "run":
        return run_once(args.input)
    parser.error("Unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
