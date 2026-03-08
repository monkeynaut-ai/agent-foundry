#!/bin/bash
# Session Start Protocol: surface work-status.md top 5 items into Claude's context.
# Output is added to Claude's context automatically by the SessionStart hook.

WORK_STATUS="${CLAUDE_PROJECT_DIR}/work-status.md"

if [[ ! -f "$WORK_STATUS" ]]; then
  exit 0
fi

python3 - "$WORK_STATUS" <<'EOF'
import re, sys

with open(sys.argv[1]) as f:
    content = f.read()

in_progress_match = re.search(r'## In Progress\n(.*?)## Backlog', content, re.DOTALL)
backlog_match = re.search(r'## Backlog\n(.*?)## Completed', content, re.DOTALL)

in_progress_items = []
backlog_items = []

if in_progress_match:
    in_progress_items = re.findall(r'^#### (.+)', in_progress_match.group(1), re.MULTILINE)

if backlog_match:
    backlog_items = re.findall(r'^#### (.+)', backlog_match.group(1), re.MULTILINE)

items = [("In Progress", i) for i in in_progress_items] + [("Backlog", i) for i in backlog_items]
top5 = items[:5]

print("=== SESSION START: Work Status ===")
print("Follow the Session Start Protocol: present the items below, then ask 'What do you want to work on?'\n")

for status, title in top5:
    print(f"[{status}] {title}")

if not top5:
    print("(no items in work-status.md)")
EOF
