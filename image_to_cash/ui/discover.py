from __future__ import annotations

import json
import platform
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Screen:
    key: str
    instructions: str
    countdown: int = 0
    focus: bool = True


SCREENS: list[Screen] = [
    Screen("main", "Close all editors and dialogs so only Fakturama's main window shows "
                   "(toolbar, left Data / New panels)."),
    Screen("data_menu", "After you press Enter you have 5 seconds: click the 'Data' menu in "
                        "Fakturama's menu bar and leave it open.", countdown=5, focus=False),
    Screen("order_editor", "Click 'Order' in the top toolbar. Leave the New Order editor open "
                           "(do not save)."),
    Screen("select_address", "In the New Order editor, click the UPPER contact icon beside "
                             "'Addresses' (not the green +). Leave 'Select the address' open."),
    Screen("select_product", "Click Cancel in 'Select the address'. Then click the UPPER product "
                             "icon beside the Items table (not the green +). Leave 'Select a "
                             "product' open."),
    Screen("debtor_main_address", "Click Cancel. In the left 'New' panel click 'New Contact'. "
                                  "Leave the editor showing Addresses > Main address."),
    Screen("debtor_misc", "In the New Debtor editor, open the 'Miscellaneous' tab."),
    Screen("debtor_payment", "Open the 'Payment' tab."),
    Screen("payment_editor", "In the left 'Data' panel click 'terms of payment', then click the "
                             "green + at the upper-right of that list. Leave the new payment "
                             "editor open (do not save)."),
    Screen("vat_editor", "In the left 'Data' panel click 'VATs', then click the green +. Leave "
                         "the new VAT editor open (do not save)."),
    Screen("product_editor", "In the left 'New' panel click 'New product'. Leave the editor "
                             "open (do not save)."),
    Screen("documents", "In the left 'Data' panel click 'Documents'."),
    Screen("invoice_editor", "Click 'Invoice' in the top toolbar. Leave the New Invoice editor "
                             "open (do not save)."),
]

PATTERNS = (
    "Invoke", "Value", "Toggle", "ExpandCollapse", "Selection", "SelectionItem",
    "RangeValue", "Grid", "Table", "Text", "Scroll", "Window", "LegacyIAccessible",
)

MAX_DEPTH = 60
MAX_ELEMENTS_PER_WINDOW = 6000


def safe_name(text: str, limit: int = 40) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("_")
    return (name or "untitled")[:limit]


def _short(value: Any, limit: int = 80) -> str:
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_node(node: dict[str, Any]) -> str:
    parts = [node.get("control_type") or "?"]
    parts.append(f"name={_short(node.get('name', ''))!r}")
    for key in ("automation_id", "class_name"):
        if node.get(key):
            parts.append(f"{key.split('_')[0]}={node[key]!r}")
    rect = node.get("rect")
    if rect:
        parts.append("rect=({},{},{},{})".format(*rect))
    flags = [f for f in ("enabled", "visible") if not node.get(f, True)]
    if flags:
        parts.append("NOT " + "/".join(flags))
    if node.get("patterns"):
        parts.append("patterns=" + ",".join(node["patterns"]))
    for key in ("value", "toggle", "expand", "labeled_by", "legacy_role", "legacy_value", "help"):
        if node.get(key) not in (None, ""):
            parts.append(f"{key}={_short(node[key])!r}")
    return "  ".join(parts)


def format_tree(node: dict[str, Any], depth: int = 0) -> list[str]:
    lines = ["  " * depth + format_node(node)]
    for child in node.get("children", []):
        lines += format_tree(child, depth + 1)
    if node.get("truncated"):
        lines.append("  " * (depth + 1) + f"... {node['truncated']}")
    return lines


def _describe(info) -> dict[str, Any]:
    from pywinauto.uia_defines import NoPatternInterfaceError, get_elem_interface

    def safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    rect = safe(lambda: info.rectangle)
    node: dict[str, Any] = {
        "control_type": safe(lambda: info.control_type),
        "name": safe(lambda: info.name, ""),
        "automation_id": safe(lambda: info.automation_id, ""),
        "class_name": safe(lambda: info.class_name, ""),
        "rect": [rect.left, rect.top, rect.right, rect.bottom] if rect else None,
        "enabled": safe(lambda: info.enabled, True),
        "visible": safe(lambda: info.visible, True),
        "framework": safe(lambda: info.framework_id, ""),
    }
    element = info.element
    node["help"] = safe(lambda: element.CurrentHelpText, "")
    node["labeled_by"] = safe(lambda: element.CurrentLabeledBy.CurrentName if element.CurrentLabeledBy else "", "")

    patterns = []
    for name in PATTERNS:
        try:
            iface = get_elem_interface(element, name)
        except (NoPatternInterfaceError, KeyError):
            continue
        patterns.append(name)
        if name == "Value":
            node["value"] = safe(lambda: iface.CurrentValue, "")
            node["read_only"] = safe(lambda: bool(iface.CurrentIsReadOnly))
        elif name == "Toggle":
            node["toggle"] = safe(lambda: int(iface.CurrentToggleState))
        elif name == "ExpandCollapse":
            node["expand"] = safe(lambda: int(iface.CurrentExpandCollapseState))
        elif name == "LegacyIAccessible":
            node["legacy_role"] = safe(lambda: int(iface.CurrentRole))
            node["legacy_value"] = safe(lambda: iface.CurrentValue, "")
            node["legacy_name"] = safe(lambda: iface.CurrentName, "")
    node["patterns"] = patterns
    return node


def _walk(info, depth: int, budget: list[int]) -> dict[str, Any]:
    node = _describe(info)
    budget[0] -= 1
    if depth >= MAX_DEPTH:
        node["truncated"] = "max depth reached"
        return node
    try:
        children = info.children()
    except Exception as exc:
        node["truncated"] = f"children not readable: {exc}"
        return node
    node["children"] = []
    for child in children:
        if budget[0] <= 0:
            node["truncated"] = "element budget reached"
            break
        node["children"].append(_walk(child, depth + 1, budget))
    return node


_CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow"}


def pick_fakturama_window(windows: list[tuple[str, str, Any]]) -> Any:
    candidates = [
        (title, cls, w) for title, cls, w in windows
        if "fakturama" in (title or "").lower() and cls not in _CONSOLE_CLASSES
    ]
    swt = [w for _, cls, w in candidates if (cls or "").startswith("SWT_Window")]
    if swt:
        return swt[0]
    return candidates[0][2] if candidates else None


def _find_fakturama():
    import os

    from pywinauto import Desktop

    own_pid = os.getpid()
    windows = [
        (w.window_text(), w.element_info.class_name, w)
        for w in Desktop(backend="uia").windows(visible_only=True)
        if w.process_id() != own_pid
    ]
    return pick_fakturama_window(windows)


def _environment(main) -> dict[str, Any]:
    import ctypes

    import pywinauto

    env: dict[str, Any] = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "windows": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "pywinauto": getattr(pywinauto, "__version__", "?"),
        "fakturama_title": main.window_text(),
        "fakturama_pid": main.process_id(),
    }
    try:
        env["system_dpi"] = ctypes.windll.user32.GetDpiForSystem()
        env["screen"] = [ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)]
    except Exception:
        pass
    return env


def _capture(screen: Screen, index: int, out_dir: Path, pid: int, ocr_lang: str | None) -> list[str]:
    from pywinauto import Desktop

    folder = out_dir / f"{index:02d}_{screen.key}"
    folder.mkdir(parents=True, exist_ok=True)
    windows = Desktop(backend="uia").windows(process=pid, visible_only=True)
    written = []
    for k, win in enumerate(windows, start=1):
        title = win.window_text() or win.element_info.class_name or "window"
        stem = folder / f"{k}_{safe_name(title)}"

        if screen.focus:
            try:
                win.set_focus()
                time.sleep(0.3)
            except Exception:
                pass

        tree = _walk(win.element_info, 0, [MAX_ELEMENTS_PER_WINDOW])
        stem.with_suffix(".tree.json").write_text(json.dumps(tree, indent=1, ensure_ascii=False), encoding="utf-8")
        header = [f"# screen: {screen.key}", f"# window: {title!r}", f"# window rect: {tree.get('rect')}", ""]
        stem.with_suffix(".tree.txt").write_text("\n".join(header + format_tree(tree)) + "\n", encoding="utf-8")
        written.append(stem.name)

        image = None
        try:
            image = win.capture_as_image()
            if image is not None:
                image.save(stem.with_suffix(".png"))
        except Exception as exc:
            stem.with_suffix(".png.error.txt").write_text(str(exc), encoding="utf-8")

        if image is not None and ocr_lang:
            try:
                from image_to_cash.ocr import run_ocr

                result = run_ocr(image, lang=ocr_lang, scale=2.0)
                ocr = {
                    "engine": result.engine,
                    "note": "boxes are relative to the window screenshot",
                    "lines": [
                        {"text": l.text, "box": [round(l.box.left), round(l.box.top), round(l.box.width), round(l.box.height)],
                         "words": [{"text": w.text, "box": [round(w.box.left), round(w.box.top), round(w.box.width), round(w.box.height)]}
                                   for w in l.words]}
                        for l in result.lines
                    ],
                }
                stem.with_suffix(".ocr.json").write_text(json.dumps(ocr, indent=1, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:
                stem.with_suffix(".ocr.error.txt").write_text(str(exc), encoding="utf-8")
    return written


def run_discovery(out_root: Path, *, only: list[str] | None = None, ocr_lang: str | None = "en") -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Discovery needs Windows: UI Automation is a Windows API.")

    screens = [s for s in SCREENS if not only or s.key in only]
    unknown = set(only or []) - {s.key for s in SCREENS}
    if unknown:
        raise ValueError(f"unknown screen(s): {', '.join(sorted(unknown))}")

    main = _find_fakturama()
    if main is None:
        raise RuntimeError("Fakturama's main window was not found. Start Fakturama first.")
    pid = main.process_id()

    out_dir = out_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "environment.json").write_text(json.dumps(_environment(main), indent=2), encoding="utf-8")
    print(f"Fakturama found: {main.window_text()!r} (pid {pid}). Recording to {out_dir}\n")

    for index, screen in enumerate(SCREENS):
        if screen not in screens:
            continue
        print(f"[{index:02d}] {screen.key}\n     {screen.instructions}")
        try:
            answer = input("     Enter = record, s = skip, q = quit: ").strip().lower()
        except EOFError:
            answer = "q"
        if answer == "q":
            break
        if answer == "s":
            continue
        if screen.countdown:
            for remaining in range(screen.countdown, 0, -1):
                print(f"     recording in {remaining}...", end="\r", flush=True)
                time.sleep(1)
            print()
        started = time.time()
        written = _capture(screen, index, out_dir, pid, ocr_lang)
        print(f"     recorded {len(written)} window(s) in {time.time() - started:.1f}s\n")

    print("Done. Close the editors you opened in Fakturama and answer 'No' when asked to save.")
    archive = shutil.make_archive(str(out_dir), "zip", root_dir=out_dir)
    return Path(archive)
