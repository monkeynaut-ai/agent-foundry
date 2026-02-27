"""CLI entrypoint for the Decision Support demo."""

import argparse
import json
import sys

from agent_foundry.demo.runner import run_demo


def main():
    parser = argparse.ArgumentParser(description="Decision Support Demo")
    parser.add_argument("question", help="The question to analyze")
    parser.add_argument("--domain", default="general", help="Domain context (default: general)")
    parser.add_argument("--constraints", nargs="*", default=[], help="Optional constraints")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output raw JSON")
    args = parser.parse_args()

    result = run_demo(args.question, domain=args.domain, constraints=args.constraints)

    if args.json_output:
        print(json.dumps(result, indent=2))
        return

    rec = result.get("recommendation", {})
    print(f"\nQuestion: {result.get('question')}")
    print(f"Domain:   {result.get('domain')}")
    print()
    print(f"Recommendation: {rec.get('recommendation', 'N/A')}")
    print()
    print("Evidence:")
    for e in result.get("retrieved_evidence", []):
        print(f"  [{e['id']}] {e['text']}")
    print()
    print(f"Assumptions: {', '.join(rec.get('assumptions', []))}")
    unc = rec.get("uncertainty", {})
    print(f"Confidence:  {unc.get('confidence', 'N/A')}")
    print(f"Rationale:   {unc.get('rationale', 'N/A')}")
    print()
    print("Gate Results:")
    for gate in ("schema_valid", "citations_valid", "uncertainty_valid", "evidence_valid"):
        status = "PASS" if result.get(gate) else "FAIL"
        print(f"  {gate}: {status}")

    if result.get("gate_failure"):
        print(f"\n  Gate failure: {result['gate_failure']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
