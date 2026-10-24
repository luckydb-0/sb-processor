from pathlib import Path

from sb_processor.cli import build_parser


def test_review_command_accepts_existing_staged_run():
    args = build_parser().parse_args(["review", "--run", "staging/run_1", "--vault", "vault"])
    assert args.command == "review"
    assert args.run == Path("staging/run_1")


def test_process_can_opt_into_full_pipeline():
    args = build_parser().parse_args(["process", "--workflow", "university", "--source", "s.pdf",
                                      "--vault", "vault", "--with-agent-b"])
    assert args.with_agent_b is True
