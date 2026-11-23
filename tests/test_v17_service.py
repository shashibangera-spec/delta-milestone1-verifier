from __future__ import annotations

from amt_engine.v17_service import build_parser


def test_default_service_command_is_inert_idle():
    args = build_parser().parse_args([])
    assert args.command is None


def test_explicit_idle_command_is_available():
    args = build_parser().parse_args(["idle"])
    assert args.command == "idle"


def test_manual_run_requires_an_input_file():
    args = build_parser().parse_args(["run", "--input", "/run/input/session.json"])
    assert args.command == "run"
    assert args.input == "/run/input/session.json"
