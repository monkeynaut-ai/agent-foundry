"""Command-line entry point for the eval harness.

Usage::

    python -m agent_foundry.evals.cli <path-to-suite.py>
        --artifacts-dir <path> --workspace-volume <name>
        --base-image-tag <name>
        [--invocations <N>] [--max-concurrency <N>] [--out-dir <path>]

The CLI is a thin wrapper over :func:`agent_foundry.evals.runner.run_suite`.
It loads the suite module, builds a task that invokes the agent via
``run_primitive_plan``, executes the suite, persists the report to
``<out-dir>/<run_id>/report.json``, and prints a console summary.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

from agent_foundry.evals.models import EvalSuite
from agent_foundry.evals.persistence import write_report
from agent_foundry.evals.runner import build_run_primitive_plan_task, run_suite


class SuiteLoadError(RuntimeError):
    """Raised when a suite module cannot be loaded or doesn't export ``suite``."""


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
        description="Run an agent eval suite and write a structured report.",
    )
    parser.add_argument(
        "suite_path",
        type=Path,
        help="Path to a Python module exporting a 'suite' symbol of type EvalSuite.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        required=True,
        help="Artifacts directory passed to run_primitive_plan (lifecycle events, agent outputs).",
    )
    parser.add_argument(
        "--workspace-volume",
        required=True,
        help="Docker workspace volume name for agent containers.",
    )
    parser.add_argument(
        "--base-image-tag",
        required=True,
        help="Docker base image tag for agent containers.",
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


async def _run(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite_path)

    # Apply the invocations override by replacing the suite field. Use
    # model_copy so validation runs.
    if args.invocations is not None:
        suite = suite.model_copy(update={"invocations_per_case": args.invocations})

    task = build_run_primitive_plan_task(
        suite.agent,
        artifacts_dir=args.artifacts_dir,
        workspace_volume=args.workspace_volume,
        base_image_tag=args.base_image_tag,
    )
    result = await run_suite(suite, task=task, max_concurrency=args.max_concurrency)

    # Render then persist.
    result.report.print(include_input=True, include_output=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
