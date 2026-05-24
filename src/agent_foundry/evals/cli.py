"""Command-line entry point for the eval harness.

Usage::

    python -m agent_foundry.evals.cli <path-to-suite.py>
        [--invocations <N>] [--max-concurrency <N>] [--out-dir <path>]
        [--artifacts-dir <path>] [--workspace-volume <name>]
        [--base-image-tag <name>]

Loads the suite module, picks the appropriate task builder for the
target kind, dispatches to a :class:`Runner`, persists the report to
``<out-dir>/<run_id>/report.json``, and prints a console summary.

Target-specific arg requirements:

- ``AgentTarget`` — ``--artifacts-dir``, ``--workspace-volume``, and
  ``--base-image-tag`` are required (the agent runs in a container via
  ``run_primitive_plan``).
- ``AICallTarget`` — those three are not used; ``invoke_ai_call`` runs
  in-process without container infrastructure.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

from agent_foundry.evals.agent_foundry_tasks import (
    build_invoke_ai_call_task,
    build_run_primitive_plan_task,
)
from agent_foundry.evals.models import (
    AgentTarget,
    AICallTarget,
    EvalSuite,
    RunResult,
    Task,
)
from agent_foundry.evals.persistence import write_report
from agent_foundry.evals.runner_loader import load_runner


class SuiteLoadError(RuntimeError):
    """Raised when a suite module cannot be loaded or doesn't export ``suite``."""


class MissingTargetArgsError(RuntimeError):
    """Raised when a suite's target requires CLI args that weren't supplied."""


def load_suite(path: Path) -> EvalSuite:
    """Import the Python module at ``path`` and return its ``suite`` symbol.

    Raises :class:`SuiteLoadError` with an explanatory message if the
    file is missing, fails to import, doesn't export ``suite``, or
    exports a ``suite`` of the wrong type.
    """
    if not path.is_file():
        raise SuiteLoadError(f"Suite file not found: {path}")

    spec = importlib.util.spec_from_file_location("_eval_suite_module", path)
    if spec is None or spec.loader is None:
        raise SuiteLoadError(f"Could not load suite module from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    suite = getattr(module, "suite", None)
    if suite is None:
        raise SuiteLoadError(f"Suite module {path} must export a 'suite' symbol of type EvalSuite")
    if not isinstance(suite, EvalSuite):
        raise SuiteLoadError(
            f"'suite' symbol in {path} must be an EvalSuite instance, got {type(suite).__name__}"
        )
    return suite


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments. Exposed for testability."""
    parser = argparse.ArgumentParser(
        prog="agent_foundry.evals.cli",
        description="Run an eval suite and write a structured report.",
    )
    parser.add_argument(
        "suite_path",
        type=Path,
        help="Path to a Python module exporting a 'suite' symbol of type EvalSuite.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Artifacts directory for AgentTarget runs (required for agent suites).",
    )
    parser.add_argument(
        "--workspace-volume",
        default=None,
        help="Docker workspace volume name for AgentTarget runs (required for agent suites).",
    )
    parser.add_argument(
        "--base-image-tag",
        default=None,
        help="Docker base image tag for AgentTarget runs (required for agent suites).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("evals/runs"),
        help="Where to write report.json (default: evals/runs).",
    )
    parser.add_argument(
        "--invocations",
        type=int,
        default=None,
        help="Override suite.invocations_per_case for this run.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Max concurrent (case, invocation) pairs (default: 1).",
    )
    return parser.parse_args(argv)


def build_task_for_suite(suite: EvalSuite, args: argparse.Namespace) -> Task:
    """Build the appropriate :class:`Task` for ``suite.target``.

    Raises :class:`MissingTargetArgsError` if an ``AgentTarget`` suite
    is missing one of the container-related CLI args.
    """
    target = suite.target
    if isinstance(target, AgentTarget):
        missing = [
            flag
            for flag, value in (
                ("--artifacts-dir", args.artifacts_dir),
                ("--workspace-volume", args.workspace_volume),
                ("--base-image-tag", args.base_image_tag),
            )
            if value is None
        ]
        if missing:
            raise MissingTargetArgsError(f"AgentTarget suite requires {', '.join(missing)}")
        return build_run_primitive_plan_task(
            target.agent,
            artifacts_dir=args.artifacts_dir,
            workspace_volume=args.workspace_volume,
            base_image_tag=args.base_image_tag,
        )
    if isinstance(target, AICallTarget):
        return build_invoke_ai_call_task(target.ai_call)
    raise AssertionError(f"Unhandled target kind: {type(target).__name__}")


def render_summary(result: RunResult) -> str:
    """Render a compact text summary of a run for the CLI."""
    passes = 0
    fails = 0
    for case in result.report.cases:
        if case.assertions and all(a.value for a in case.assertions):
            passes += 1
        else:
            fails += 1
    total_cases = len(result.report.cases)
    duration = (result.ended_at - result.started_at).total_seconds()
    lines = [
        f"Run: {result.run_id}",
        f"Suite: {result.suite_name}",
        f"Cases: {total_cases} ({passes} passed, {fails} failed/unscored, "
        f"{len(result.report.failures)} errored)",
        f"Duration: {duration:.2f}s",
    ]
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite_path)

    # Apply the invocations override by replacing the suite field. Use
    # model_copy so validation runs.
    if args.invocations is not None:
        suite = suite.model_copy(update={"invocations_per_case": args.invocations})

    task = build_task_for_suite(suite, args)
    runner = load_runner()
    result = await runner.run(suite, task=task, max_concurrency=args.max_concurrency)

    print(render_summary(result))
    report_path = write_report(result, args.out_dir)
    print(f"\nReport written to: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except SuiteLoadError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except MissingTargetArgsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
