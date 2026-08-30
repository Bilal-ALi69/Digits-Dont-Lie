"""
Fraud Analysis & Verification Backend — CLI Mode.

Usage:
    python -m app.main                             # run built-in demo data
    python -m app.main --image path/to/photo       # OCR an image then analyse
    python -m app.main --numbers "123,456,.."      # analyse your own numbers
    python -m app.main --value "4532015112830366"   # analyse a single value
    python -m app.main --file path/to/data.csv     # analyse a file
    python -m app.main --interactive               # guided prompt loop
    uvicorn app.api.server:app                     # launch API server
"""

from __future__ import annotations

import argparse
import sys

from app.models import AnalysisResponse

# ---------------------------------------------------------------------------
# Demo datasets
# ---------------------------------------------------------------------------

DEMO_NUMBERS = [
    123, 145, 112, 189, 104, 135, 176, 158, 119, 143,
    167, 121, 198, 105, 131,
    210, 245, 223, 267, 289, 204, 231, 256, 278,
    312, 345, 334, 367, 389, 305,
    421, 456, 478, 490, 435,
    512, 534, 567, 589,
    612, 645, 678,
    723, 756, 789,
    834, 867, 891,
    912, 945,
    -42, 0.55, 0,
]

NON_BENFORD_NUMBERS: list[float] = [
    110, 120, 130, 140, 150, 160, 170, 180, 190,
    112, 122, 132, 142, 152, 162, 172, 182, 192,
    118, 128, 138, 148, 158, 168, 178, 188, 198,
]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_response(resp: AnalysisResponse) -> None:
    """Print an AnalysisResponse in a readable CLI format."""
    print()
    print("=" * 62)
    if resp.input_classification:
        print(f" INPUT: {resp.input_classification.type} "
              f"(confidence: {resp.input_classification.confidence:.0%})")
    print(f" STATUS: {resp.overall_status.value}")
    print("=" * 62)

    if resp.extracted_data:
        print()
        print(" Extracted Data:")
        for k, v in resp.extracted_data.items():
            print(f"   {k}: {v}")

    if resp.statistical_analysis:
        benford_raw = resp.statistical_analysis.get("benford")
        if isinstance(benford_raw, dict):
            _print_benford_table(benford_raw)

    if resp.checks:
        print()
        print(" Checks:")
        for c in resp.checks:
            icon = {"passed": "OK", "failed": "!!", "warning": "~~", "not_applicable": "--"}.get(
                c.status.value, "??"
            )
            print(f"   [{icon}] {c.check}: {c.message}")

    if resp.risk_assessment:
        r = resp.risk_assessment
        print()
        print(f" Risk: {r.risk_score}/100 ({r.level})  |  Confidence: {r.confidence}/100")

    if resp.limitations:
        print()
        print(" Limitations:")
        for lim in resp.limitations:
            print(f"   - {lim}")

    if resp.recommendation:
        print()
        print(f" Recommendation: {resp.recommendation}")

    print()


def _print_benford_table(benford: dict[str, object]) -> None:
    obs_raw = benford.get("observed_frequencies")
    exp_raw = benford.get("expected_frequencies")
    obs: dict[str, float] = obs_raw if isinstance(obs_raw, dict) else {}
    exp: dict[str, float] = exp_raw if isinstance(exp_raw, dict) else {}
    if not obs or not exp:
        return
    print()
    print(f" Benford Analysis  (chi-square: {benford.get('chi_square', '?')}, "
          f"p-value: {benford.get('p_value', '?')})")
    print(f" Applicability: {benford.get('applicability', '?')}")
    print("-" * 62)
    print(f" {'Digit':<6}{'Expected %':>11}{'Observed %':>12}")
    print("-" * 62)
    for d in range(1, 10):
        ds = str(d)
        e = exp.get(ds, 0.0)
        o = obs.get(ds, 0.0)
        print(f" {d:<6}{e:>11.2f}{o:>12.2f}")
    print("-" * 62)


# ---------------------------------------------------------------------------
# Core analysis runners (using new orchestrator)
# ---------------------------------------------------------------------------

def run_dataset_analysis(numbers: list[float], label: str = "Dataset") -> None:
    from app.orchestrator import analyze_dataset
    resp = analyze_dataset(numbers, label=label)
    _print_response(resp)


def run_single_value(value: str) -> None:
    from app.orchestrator import analyze_single_value
    resp = analyze_single_value(value)
    _print_response(resp)


def run_image_analysis(image_path: str) -> None:
    from app.orchestrator import analyze_file
    resp = analyze_file(image_path)
    _print_response(resp)


def run_file_analysis(file_path: str) -> None:
    from app.orchestrator import analyze_file
    resp = analyze_file(file_path)
    _print_response(resp)


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def interactive_mode() -> None:
    print()
    print("=" * 62)
    print(" FRAUD ANALYSIS & VERIFICATION BACKEND")
    print("=" * 62)
    print()

    while True:
        print(" Choose input method:")
        print("   1) Enter a single value (amount, card number, date, etc.)")
        print("   2) Enter numbers manually (dataset)")
        print("   3) Scan an image (OCR)")
        print("   4) Analyse a file (CSV/PDF/image)")
        print("   5) Run demo data")
        print("   q) Quit")
        print()

        choice = input(" > ").strip().lower()

        if choice == "q":
            print(" Goodbye!")
            break

        if choice == "1":
            raw = input("\n Enter a single value: ").strip()
            if not raw:
                print(" No input provided.\n")
                continue
            run_single_value(raw)

        elif choice == "2":
            raw = input("\n Enter numbers (comma-separated): ").strip()
            if not raw:
                print(" No input provided.\n")
                continue
            try:
                numbers = [float(x.strip()) for x in raw.split(",")]
            except ValueError:
                print(" Error: could not parse all values as numbers.\n")
                continue
            run_dataset_analysis(numbers, "Manual Input")

        elif choice == "3":
            path = input("\n Enter image path: ").strip()
            if not path:
                print(" No path provided.\n")
                continue
            run_image_analysis(path)

        elif choice == "4":
            path = input("\n Enter file path: ").strip()
            if not path:
                print(" No path provided.\n")
                continue
            run_file_analysis(path)

        elif choice == "5":
            print("\nRunning demo data...")
            run_dataset_analysis(DEMO_NUMBERS, "Demo: Roughly follows Benford's Law")
            run_dataset_analysis(NON_BENFORD_NUMBERS, "Demo: Does NOT follow Benford's Law")

        else:
            print(" Invalid choice.\n")
            continue

        again = input(" Run another test? (y/n): ").strip().lower()
        if again != "y":
            print(" Goodbye!")
            break
        print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fraud Analysis & Verification Backend — CLI Mode"
    )
    parser.add_argument(
        "--image", metavar="PATH",
        help="Path to an image file to OCR and analyse"
    )
    parser.add_argument(
        "--numbers", metavar="STR",
        help='Comma-separated list of numbers to analyse, e.g. "123,456,789"'
    )
    parser.add_argument(
        "--value", metavar="STR",
        help='A single value to analyse, e.g. "4532015112830366" or "$1499.00"'
    )
    parser.add_argument(
        "--file", metavar="PATH",
        help="Path to a file (CSV, XLSX, PDF, image) to analyse"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Launch guided interactive prompt"
    )
    args = parser.parse_args()

    if args.interactive or (
        not args.image and not args.numbers and not args.value and not args.file
    ):
        interactive_mode()
        return

    if args.value:
        run_single_value(args.value)

    if args.image:
        run_image_analysis(args.image)

    if args.file:
        run_file_analysis(args.file)

    if args.numbers:
        try:
            numbers = [float(x.strip()) for x in args.numbers.split(",")]
        except ValueError:
            print("Error: --numbers must be a comma-separated list of values.")
            print('Example:  python -m app.main --numbers "123,45,6.7,-89"')
            sys.exit(1)
        run_dataset_analysis(numbers, "Your Numbers")


if __name__ == "__main__":
    main()
