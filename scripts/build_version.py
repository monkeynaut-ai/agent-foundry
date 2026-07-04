from __future__ import annotations

import re
from datetime import UTC, datetime

BASE_VERSION = "0.10.6"


def format_version(version) -> str:
    """Format SCM-derived versions before the first release tag exists."""
    if version.distance is None:
        main_version = str(version.version)
    else:
        main_version = f"{_next_dev_base(str(version.version))}.dev{version.distance}"

    if version.distance is None or version.node is None:
        local_version = f"+d{_today()}" if version.dirty else ""
    elif version.dirty:
        local_version = f"+{version.node}.d{_today()}"
    else:
        local_version = f"+{version.node}"

    return main_version + local_version


def _next_dev_base(raw_version: str) -> str:
    public_version = raw_version.partition("+")[0]
    if public_version in {"0.0", "0.0.0"}:
        return BASE_VERSION
    if ".dev" in public_version:
        prefix, dev_number = public_version.rsplit(".dev", 1)
        if dev_number == "0":
            return prefix

    match = re.match(r"(.*?)(\d+)$", public_version)
    if match is None:
        return public_version

    prefix, number = match.groups()
    return f"{prefix}{int(number) + 1}"


def _today() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d")
