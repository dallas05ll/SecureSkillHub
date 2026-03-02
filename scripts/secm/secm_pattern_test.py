#!/usr/bin/env python3
"""
Security Manager — Pattern Regression Test Suite.

Tests scanner regex patterns against known true positives (must match) and
known false positives (must NOT match). Run after any change to
src/scanner/regex_patterns.py or semgrep rules.

Test cases are loaded from data/pattern-test-cases/*.json.

Usage:
    python3 secm_pattern_test.py                     # Run all tests
    python3 secm_pattern_test.py --group injection_patterns  # Test one group
    python3 secm_pattern_test.py --verbose            # Show each test case
    python3 secm_pattern_test.py --pattern py_eval    # Test a single pattern
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_CASES_DIR = PROJECT_ROOT / "data" / "pattern-test-cases"

# Import scanner patterns
sys.path.insert(0, str(PROJECT_ROOT))
from src.scanner.regex_patterns import ALL_PATTERN_GROUPS, PatternEntry


# ---------------------------------------------------------------------------
# Pattern lookup
# ---------------------------------------------------------------------------

def build_pattern_lookup() -> dict[str, PatternEntry]:
    """Build a flat lookup of pattern_name -> PatternEntry across all groups."""
    lookup: dict[str, PatternEntry] = {}
    for group_name, patterns in ALL_PATTERN_GROUPS.items():
        for entry in patterns:
            lookup[entry.name] = entry
    return lookup


PATTERN_LOOKUP = build_pattern_lookup()


def find_pattern(name: str) -> PatternEntry | None:
    """Find a pattern by name, trying exact match and common prefixes."""
    if name in PATTERN_LOOKUP:
        return PATTERN_LOOKUP[name]
    # Try without regex_ prefix
    stripped = name.replace("regex_", "")
    if stripped in PATTERN_LOOKUP:
        return PATTERN_LOOKUP[stripped]
    return None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

class TestResult:
    """Result of a single test case."""

    def __init__(
        self,
        pattern_name: str,
        test_type: str,
        text: str,
        expected_match: bool,
        actual_match: bool,
        reason: str,
    ):
        self.pattern_name = pattern_name
        self.test_type = test_type
        self.text = text
        self.expected_match = expected_match
        self.actual_match = actual_match
        self.reason = reason
        self.passed = expected_match == actual_match

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        expect = "match" if self.expected_match else "no match"
        actual = "matched" if self.actual_match else "no match"
        return f"  [{status}] {self.pattern_name} ({self.test_type}): expected {expect}, got {actual}"


def run_test_case(
    pattern_name: str,
    test_type: str,
    text: str,
    expected_match: bool,
    reason: str,
) -> TestResult:
    """Run a single test case against a pattern."""
    entry = find_pattern(pattern_name)
    if entry is None:
        # Pattern not found — treat as failure
        return TestResult(
            pattern_name=pattern_name,
            test_type=test_type,
            text=text,
            expected_match=expected_match,
            actual_match=not expected_match,  # Force failure
            reason=f"Pattern '{pattern_name}' not found in regex_patterns.py",
        )

    actual_match = bool(entry.pattern.search(text))
    return TestResult(
        pattern_name=pattern_name,
        test_type=test_type,
        text=text,
        expected_match=expected_match,
        actual_match=actual_match,
        reason=reason,
    )


def load_test_file(path: Path) -> list[dict]:
    """Load test cases from a JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("test_cases", [])
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Could not load {path}: {e}", file=sys.stderr)
        return []


def run_tests(
    group_filter: str | None = None,
    pattern_filter: str | None = None,
    verbose: bool = False,
) -> tuple[int, int, list[TestResult]]:
    """Run all pattern tests.

    Returns: (total_tests, passed_tests, failed_results)
    """
    total = 0
    passed = 0
    failed: list[TestResult] = []

    test_files = sorted(TEST_CASES_DIR.glob("*.json"))
    if not test_files:
        print(f"WARNING: No test case files found in {TEST_CASES_DIR}", file=sys.stderr)
        return 0, 0, []

    # Map test file names to pattern groups for filtering
    file_group_map = {
        "injection_patterns.json": "injection_patterns",
        "obfuscation.json": "obfuscation",
        "dangerous_calls.json": "dangerous_calls",
    }

    for test_file in test_files:
        file_group = file_group_map.get(test_file.name, test_file.stem)

        if group_filter and file_group != group_filter:
            continue

        test_cases = load_test_file(test_file)
        if verbose:
            print(f"\n  Loading: {test_file.name} ({len(test_cases)} patterns)")

        for tc in test_cases:
            pattern_name = tc.get("pattern_name", "")
            if not pattern_name:
                continue

            if pattern_filter and pattern_name != pattern_filter:
                continue

            # True positives (must match)
            for tp in tc.get("true_positives", []):
                text = tp.get("text", "")
                reason = tp.get("reason", "")
                result = run_test_case(pattern_name, "true_positive", text, True, reason)
                total += 1
                if result.passed:
                    passed += 1
                    if verbose:
                        print(f"    {result}")
                else:
                    failed.append(result)
                    if verbose:
                        print(f"    {result}")
                        print(f"      Reason: {reason}")
                        print(f"      Text: {text[:100]}")

            # False positives (must NOT match)
            for fp in tc.get("false_positives", []):
                text = fp.get("text", "")
                reason = fp.get("reason", "")
                result = run_test_case(pattern_name, "false_positive", text, False, reason)
                total += 1
                if result.passed:
                    passed += 1
                    if verbose:
                        print(f"    {result}")
                else:
                    failed.append(result)
                    if verbose:
                        print(f"    {result}")
                        print(f"      Reason: {reason}")
                        print(f"      Text: {text[:100]}")

    return total, passed, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SecM Pattern Regression Test Suite — test scanner patterns against known cases"
    )
    parser.add_argument(
        "--group",
        type=str,
        help="Test only patterns from a specific group (e.g., injection_patterns, obfuscation, dangerous_calls)",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        help="Test only a specific pattern by name (e.g., py_eval, markdown_injection)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show each test case result",
    )
    parser.add_argument(
        "--list-patterns",
        action="store_true",
        help="List all available patterns and exit",
    )
    args = parser.parse_args()

    if args.list_patterns:
        print("Available patterns by group:")
        for group_name, patterns in sorted(ALL_PATTERN_GROUPS.items()):
            print(f"\n  {group_name}:")
            for entry in patterns:
                print(f"    - {entry.name}")
        return

    print()
    print("=" * 60)
    print("  SecM Pattern Regression Test Suite")
    print("=" * 60)

    if args.group:
        print(f"  Filter: group={args.group}")
    if args.pattern:
        print(f"  Filter: pattern={args.pattern}")

    total, passed, failed = run_tests(
        group_filter=args.group,
        pattern_filter=args.pattern,
        verbose=args.verbose,
    )

    print()
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {len(failed)} FAILED")
    else:
        print()

    if failed:
        print()
        print("  FAILURES:")
        print(f"  {'-' * 56}")
        for result in failed:
            print(f"    {result}")
            print(f"      Reason: {result.reason}")
            print(f"      Text: {result.text[:80]}")
            print()

    print("=" * 60)

    if not failed and total > 0:
        print("  All tests passed!")
    elif total == 0:
        print("  No tests found.")
        sys.exit(1)
    else:
        print(f"  {len(failed)} test(s) failed.")
        sys.exit(1)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
