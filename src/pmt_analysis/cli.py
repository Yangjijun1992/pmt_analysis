import argparse

from pmt_analysis.config import DEFAULT_OUTPUT_DIR, DEFAULT_TPC_DATA_ROOT
from pmt_analysis.pipeline import analyze_runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmt-analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze PMT runs")
    analyze_parser.add_argument(
        "--run-id",
        nargs="+",
        type=str,
        required=True,
        help="One or more 5-digit run IDs (e.g. 00292 00295)",
    )
    analyze_parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to store outputs (default: output)",
    )
    analyze_parser.add_argument(
        "--data-root",
        default=DEFAULT_TPC_DATA_ROOT,
        help="Root directory for TPC data (default: /mnt/data/TPC)",
    )
    analyze_parser.add_argument(
        "--save-plots",
        action="store_true",
        default=True,
        help="Generate and save validation plots (default: enabled)",
    )
    analyze_parser.add_argument(
        "--no-plots",
        action="store_true",
        default=False,
        help="Disable validation plot generation",
    )
    analyze_parser.add_argument(
        "--print-summary",
        action="store_true",
        default=False,
        help="Print a concise summary table after analysis",
    )
    analyze_parser.add_argument(
        "--write-db",
        action="store_true",
        default=False,
        help="Write analysis results to database (default: off)",
    )

    return parser


def _print_summary_table(results: list) -> None:
    """Print a compact summary table of analysis results.

    Placeholder: currently prints run IDs only.
    A full implementation would accept AnalysisBundle objects.
    """
    print()
    print("Summary table is not yet implemented (pending full bundle integration).")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyze":
        save_plots = args.save_plots and not args.no_plots
        raise SystemExit(
            analyze_runs(
                run_ids=args.run_id,
                output_dir=args.output_dir,
                data_root=args.data_root,
                save_plots=save_plots,
                write_db=args.write_db,
            )
        )

    parser.error(f"Unsupported command: {args.command}")
