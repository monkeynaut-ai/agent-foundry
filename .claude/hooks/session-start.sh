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

items = []  # list of (number, category, title)

# Parse In Progress section
in_progress_match = re.search(r'## In Progress\n(.*?)## Backlog', content, re.DOTALL)
if in_progress_match:
    for title in re.findall(r'^#### (.+)', in_progress_match.group(1), re.MULTILINE):
        m = re.match(r'^(\d+)\.\s+(.+)', title)
        if m:
            items.append((m.group(1), "In Progress", m.group(2)))
        else:
            items.append(("", "In Progress", title))

# Parse Backlog section, tracking ### subsection headings as categories
backlog_match = re.search(r'## Backlog\n(.*?)## Completed', content, re.DOTALL)
if backlog_match:
    current_category = "Backlog"
    for line in backlog_match.group(1).splitlines():
        sub = re.match(r'^### (.+)', line)
        if sub:
            # Normalize em-dash to hyphen for display
            current_category = sub.group(1).replace('—', '-').strip()
        item = re.match(r'^#### (.+)', line)
        if item:
            title = item.group(1)
            m = re.match(r'^(\d+)\.\s+(.+)', title)
            if m:
                items.append((m.group(1), current_category, m.group(2)))
            else:
                items.append(("", current_category, title))

top5 = items[:5]

print("=== SESSION START: Work Status ===")
print("Follow the Session Start Protocol: present the items below, then ask 'What do you want to work on?'\n")

if top5:
    num_w = max(len(n) for n, _, _ in top5)
    num_w = max(num_w, 1)
    cat_w = max(len(c) for _, c, _ in top5)
    cat_w = max(cat_w, len("Category"))
    item_w = max(len(i) for _, _, i in top5)
    item_w = max(item_w, len("Item"))

    header = f"{'#':<{num_w}}  {'Category':<{cat_w}}  Item"
    sep    = f"{'-'*num_w}  {'-'*cat_w}  {'-'*item_w}"
    print(header)
    print(sep)
    for num, cat, title in top5:
        print(f"{num:<{num_w}}  {cat:<{cat_w}}  {title}")
else:
    print("(no items in work-status.md)")
EOF
