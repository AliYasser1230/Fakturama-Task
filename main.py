from __future__ import annotations

import argparse
import sys


def _api_error_message(exc: Exception) -> str | None:
    try:
        import anthropic
    except ImportError:
        return None
    if isinstance(exc, TypeError) and "authentication method" in str(exc):
        return ("No Claude API key found. Put ANTHROPIC_API_KEY in .env (see .env.example), "
                "or try without a key: --raw samples/order_WEB-2026-0714-A17.raw.json")
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude API key missing or invalid. Put ANTHROPIC_API_KEY in .env (see .env.example)."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "This API key may not use the extraction model. Check EXTRACTION_MODEL and the key's workspace."
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude API rate limit reached; try again in a minute."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Claude API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Claude API (network)."
    if isinstance(exc, anthropic.AnthropicError):
        return f"Claude API client error: {exc}. Is ANTHROPIC_API_KEY set in .env?"
    return None


def _load_order(args: argparse.Namespace, settings):
    from image_to_cash.errors import ExtractionRejected
    from image_to_cash.extract.pipeline import extract_order, load_raw_json

    try:
        raw = load_raw_json(args.raw) if args.raw else None
        result = extract_order(args.image, settings=settings, raw=raw)
        info = {"source": result.source, "image": str(args.image), "ocr_engine": result.ocr_engine,
                "issues": [i.to_dict() for i in result.issues]}
        return result.order, result.issues, info
    except ExtractionRejected as exc:
        for issue in exc.issues:
            print(f"  {issue}", file=sys.stderr)
        print("REJECTED: fix the image or the data above; Fakturama was not touched.", file=sys.stderr)
        return None, [], {}
    except Exception as exc:
        message = _api_error_message(exc)
        if message is None:
            raise
        print(message, file=sys.stderr)
        return None, [], {}


def cmd_run(args: argparse.Namespace) -> int:
    from image_to_cash.errors import FlowStopped
    from image_to_cash.flow.runner import RunContext, RunResult, Stage, format_run, run_flow
    from image_to_cash.flow.stages import STAGES
    from image_to_cash.report.run_report import RunReport
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama

    if sys.platform != "win32":
        print("run needs Windows with Fakturama (UI Automation is a Windows API).", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    order, issues, extraction = _load_order(args, settings)
    if order is None:
        return 1
    for issue in issues:
        print(f"  {issue}", file=sys.stderr)
    print(f"Order {order.external_reference}: {len(order.items)} item(s), "
          f"gross {order.totals.gross} {order.currency}, {order.payment.method.value} {order.payment.paid_status}",
          flush=True)

    report = RunReport(settings.runs_dir, order, extraction=extraction)
    try:
        app = Fakturama.connect(settings)
    except FlowStopped as exc:
        result = RunResult([], Stage("0", "Connect to Fakturama", None), "stopped", str(exc))
        folder = report.finish(result)
        print(exc, file=sys.stderr)
        print(f"Report: {folder / 'report.md'}", file=sys.stderr)
        return 1
    report.capture_fn = app.screenshot
    app.bring_to_front()
    app.maximize()
    report.capture("start")
    result = run_flow(RunContext(order=order, app=app, settings=settings), STAGES, after_stage=report.after_stage)
    folder = report.finish(result, fakturama={"title": app.title, "pid": app.pid}, open_editors=app.editor_tab_names())
    print("\n".join(format_run(result)), flush=True)
    print(f"\nReport: {folder / 'report.md'}", flush=True)
    if not result.ok and result.kind != "not built yet":
        if result.trace:
            print(result.trace, file=sys.stderr)
        print(f"STOPPED for manual review ({result.kind}): see {folder / 'manual_review.json'}. "
              f"Fakturama was left as it is.", file=sys.stderr)
        return 1
    if result.ok and not result.not_built:
        print("Completed.")
        return 0
    print("Stopped where the flow is not built yet; Fakturama was left as it is (unsaved editors stay open).")
    return 3
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Fakturama Image-to-Cash: order image -> saved Order + linked, paid Invoice.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="Run the full Order -> Invoice flow (Windows only).")
    p.add_argument("image", help="Path to the order image.")
    p.add_argument("--raw", help="Use a saved raw transcription instead of calling Claude (no API key needed).")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
