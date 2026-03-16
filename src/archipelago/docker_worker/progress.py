"""Progress checkpoint parsing from progress.jsonl files."""

import json
import logging
from pathlib import Path

from archipelago.docker_worker.models import (
    CommitEvidence,
    PatchInfo,
    ProgressEvent,
    ResumePoint,
)

logger = logging.getLogger(__name__)


def parse_progress(workspace_path: Path) -> list[ProgressEvent]:
    """Parse progress.jsonl from the workspace into ProgressEvent objects.

    Returns events sorted chronologically by timestamp.
    Skips malformed lines with a warning.
    """
    progress_file = workspace_path / "progress.jsonl"
    if not progress_file.exists():
        return []

    events = []
    for line_num, line in enumerate(progress_file.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            events.append(ProgressEvent(**data))
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Skipping malformed progress line %d: %s", line_num, e)

    return sorted(events, key=lambda e: e.timestamp)


def get_resume_point(events: list[ProgressEvent]) -> ResumePoint | None:
    """Determine where to resume from a list of progress events.

    Returns None if all work is complete.
    Returns the ResumePoint for the last incomplete boundary.
    """
    if not events:
        return None

    # Track completed commits
    completed_commits: set[tuple[str, str]] = set()
    last_event = None

    for event in events:
        if event.type == "commit_green":
            completed_commits.add((event.pr_id, event.commit_id))
        last_event = event

    if last_event is None:
        return None

    # If the last event is pr_completed and there are no subsequent events, all done
    if last_event.type == "pr_completed":
        return None

    # If the last event is commit_green, check if it's the final one
    if last_event.type == "commit_green":
        # All commits completed so far — might be more to do but we can't tell
        # from the events alone. Return None to indicate no known incomplete work.
        return None

    # Last event is commit_started or blocked — resume there
    return ResumePoint(
        pr_id=last_event.pr_id,
        commit_id=last_event.commit_id,
        status=last_event.type,
    )


def transform_progress_events(
    events: list[ProgressEvent],
) -> tuple[list[PatchInfo], list[CommitEvidence]]:
    """Transform parsed progress events into patch metadata and commit evidence.

    Filters events by type:
    - pr_completed → PatchInfo
    - commit_green → CommitEvidence
    """
    patches: list[PatchInfo] = []
    evidence: list[CommitEvidence] = []

    for event in events:
        if event.type == "pr_completed":
            patches.append(
                PatchInfo(
                    pr_id=event.pr_id,
                    branch_name=event.commit_id,
                    files_changed=event.files_changed,
                    diff_summary=event.notes,
                )
            )
        elif event.type == "commit_green":
            evidence.append(
                CommitEvidence(
                    commit_id=event.commit_id,
                    pr_id=event.pr_id,
                    test_commands_run=[r.command for r in event.tests_run],
                    test_output=event.notes,
                    tests_passed=sum(1 for r in event.tests_run if r.exit_code == 0),
                    tests_failed=sum(1 for r in event.tests_run if r.exit_code != 0),
                    all_green=all(r.exit_code == 0 for r in event.tests_run),
                )
            )

    return patches, evidence
