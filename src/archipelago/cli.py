"""Archipelago pipeline CLI."""

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from archipelago.runner import run_archipelago, run_dev_test


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the Archipelago pipeline")
    parser.add_argument("-f", "--file", required=True, help="Path to YAML input file")
    args = parser.parse_args(argv)

    input_path = Path(args.file)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        data = yaml.safe_load(input_path.read_text())
    except yaml.YAMLError as e:
        print(f"Error: invalid YAML: {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("Error: YAML must be a mapping", file=sys.stderr)
        return 1

    if "dev_test_input" in data:
        result = run_dev_test(data["dev_test_input"])
        print(yaml.dump(result, default_flow_style=False))
        return 0

    if "product_brief_input" not in data:
        print(
            "Error: YAML must contain 'product_brief_input' or 'dev_test_input' key",
            file=sys.stderr,
        )
        return 1

    result = run_archipelago(data["product_brief_input"])
    print(yaml.dump(result, default_flow_style=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
