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


def cmd_extract(args: argparse.Namespace) -> int:
    import json

    from image_to_cash.errors import ExtractionRejected
    from image_to_cash.extract.pipeline import extract_order, load_raw_json
    from image_to_cash.settings import Settings

    settings = Settings.from_env()
    raw = load_raw_json(args.raw) if args.raw else None
    try:
        result = extract_order(args.image, settings=settings, raw=raw, ocr_check=not args.no_ocr_check)
    except ExtractionRejected as exc:
        for issue in exc.issues:
            print(f"  {issue}", file=sys.stderr)
        print("REJECTED: fix the image or the data above; Fakturama was not touched.", file=sys.stderr)
        return 1
    except Exception as exc:
        message = _api_error_message(exc)
        if message is None:
            raise
        print(message, file=sys.stderr)
        return 1

    if args.save_raw:
        with open(args.save_raw, "w", encoding="utf-8") as f:
            f.write(result.raw.model_dump_json(indent=2))
    order_json = result.order.model_dump_json(indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(order_json + "\n")
    else:
        print(order_json)

    for issue in result.issues:
        print(f"  {issue}", file=sys.stderr)
    o = result.order
    print(
        f"OK: {o.external_reference}, {len(o.items)} item(s), net {o.totals.net} / VAT {o.totals.vat} / "
        f"gross {o.totals.gross} {o.currency}  [source: {result.source}, OCR: {result.ocr_engine or 'skipped'}]",
        file=sys.stderr,
    )
    if result.llm_usage:
        print(f"    tokens: {json.dumps(result.llm_usage)}", file=sys.stderr)
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from pathlib import Path

    from image_to_cash.settings import Settings
    from image_to_cash.ui.discover import SCREENS, run_discovery

    if args.list:
        for i, screen in enumerate(SCREENS):
            print(f"{i:02d} {screen.key:22s} {screen.instructions}")
        return 0
    if sys.platform != "win32":
        print("discover needs Windows (UI Automation is a Windows API). See README: Windows setup.",
              file=sys.stderr)
        return 2

    settings = Settings.from_env()
    try:
        archive = run_discovery(Path(args.out_dir), only=args.only,
                                ocr_lang=None if args.no_ocr else settings.ocr_language)
    except (RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"\nSend this file: {archive}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    import time

    from image_to_cash.errors import FlowStopped
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama, format_probe

    if sys.platform != "win32":
        print("probe needs Windows (UI Automation is a Windows API).", file=sys.stderr)
        return 2
    try:
        app = Fakturama.connect(Settings.from_env())
    except FlowStopped as exc:
        print(exc, file=sys.stderr)
        return 1
    started = time.monotonic()
    results = app.probe(args.screen)
    print(f"Fakturama: {app.title!r} (pid {app.pid})")
    print("\n".join(format_probe(results)) or "No screen from locators.yaml is open.")
    found = sum(r.found for r in results)
    print(f"\n{found}/{len(results)} controls found on the open screens in {time.monotonic() - started:.1f}s")
    return 0


def _load_order(args: argparse.Namespace, settings):
    from image_to_cash.errors import ExtractionRejected
    from image_to_cash.extract.pipeline import extract_order, load_order_json, load_raw_json

    try:
        if args.from_json:
            return load_order_json(args.from_json, settings=settings), []
        raw = load_raw_json(args.raw) if args.raw else None
        result = extract_order(args.image, settings=settings, raw=raw)
        return result.order, result.issues
    except ExtractionRejected as exc:
        for issue in exc.issues:
            print(f"  {issue}", file=sys.stderr)
        print("REJECTED: fix the image or the data above; Fakturama was not touched.", file=sys.stderr)
        return None, []
    except Exception as exc:
        message = _api_error_message(exc)
        if message is None:
            raise
        print(message, file=sys.stderr)
        return None, []


def cmd_run(args: argparse.Namespace) -> int:
    from image_to_cash.errors import FlowStopped
    from image_to_cash.flow.runner import RunContext, format_run, run_flow
    from image_to_cash.flow.stages import STAGES
    from image_to_cash.settings import Settings
    from image_to_cash.ui.app import Fakturama

    if sys.platform != "win32":
        print("run needs Windows with Fakturama (UI Automation is a Windows API).", file=sys.stderr)
        return 2
    if args.raw and not args.image:
        print("--raw needs the order image too (it is checked against the image's OCR).", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    order, issues = _load_order(args, settings)
    if order is None:
        return 1
    for issue in issues:
        print(f"  {issue}", file=sys.stderr)
    print(f"Order {order.external_reference}: {len(order.items)} item(s), "
          f"gross {order.totals.gross} {order.currency}, {order.payment.method.value} {order.payment.paid_status}",
          flush=True)

    try:
        app = Fakturama.connect(settings)
    except FlowStopped as exc:
        print(exc, file=sys.stderr)
        return 1
    app.bring_to_front()
    app.maximize()
    result = run_flow(RunContext(order=order, app=app, settings=settings), STAGES)
    print("\n".join(format_run(result)), flush=True)
    if not result.ok:
        print("\nSTOPPED. Fakturama was left as it is, so you can look at it.", file=sys.stderr)
        return 1
    if result.not_built:
        print("\nThe New Order stays open and unsaved in Fakturama.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Fakturama Image-to-Cash: order image -> saved Order + linked, paid Invoice.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="Extract and validate the order data from an image.")
    p.add_argument("image", help="Path to the order image (PNG/JPG).")
    p.add_argument("--out", help="Write the validated JSON here (default: print to stdout).")
    p.add_argument("--raw", help="Use a saved raw transcription instead of calling Claude (no API key needed).")
    p.add_argument("--save-raw", help="Also save Claude's raw transcription here, for re-runs with --raw.")
    p.add_argument("--no-ocr-check", action="store_true", help="Skip the OCR cross-check (not recommended).")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("discover", help="Record Fakturama's UIA control tree, screen by screen (Windows only).")
    p.add_argument("--out-dir", default="runs/discovery", help="Where to write the recordings.")
    p.add_argument("--only", nargs="+", metavar="SCREEN", help="Record only these screens (see --list).")
    p.add_argument("--list", action="store_true", help="List the screens and what to open for each.")
    p.add_argument("--no-ocr", action="store_true", help="Skip OCR of the screenshots (faster).")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("probe", help="Show which locators.yaml controls are found on the open Fakturama screens (Windows, read-only).")
    p.add_argument("--screen", nargs="+", help="Only these screens from locators.yaml.")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("run", help="Run the full Order -> Invoice flow (Windows only).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("image", nargs="?", help="Path to the order image.")
    src.add_argument("--from-json", help="Skip extraction and use a saved order JSON.")
    p.add_argument("--raw", help="Use a saved raw transcription instead of calling Claude (no API key needed).")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
