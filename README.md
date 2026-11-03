# Fakturama Image-to-Cash Automation

Turns one order image into a saved, verified **Order** and a linked, paid **Invoice** in
[Fakturama](https://www.fakturama.info/download/). It drives Fakturama's own UI with
Microsoft UI Automation, uses OCR for controls UIA cannot see, and uses Claude to read the
image. It never uses fixed screen coordinates.

> **Status:** work in progress. See [Progress](#progress) below.

## How it works

```
order image ─► extract (Claude → JSON, OCR cross-check, normalize, arithmetic checks)
                  │  validated order (nothing touches Fakturama before this passes)
                  ▼
           flow: 1 open Order → 2 Debtor → 3 Products → 4 save Order → 5 linked Invoice
                  │  each stage ends with a verification gate
                  ▼
           ui driver (locators.yaml: UIA first, label-relative, OCR fallback)  ◄──► Fakturama
                  │
                  ▼
           run report (JSON log, screenshots, manual-review stop)
```

## Project layout

```
.
├── main.py                       CLI: extract | discover | run
├── config/
│   └── locators.yaml             every UI control declared once (UIA / label / OCR)
├── image_to_cash/
│   ├── settings.py               model, timeouts, paths (from .env)
│   ├── errors.py                 ExtractionRejected, ManualReviewRequired, ...
│   ├── numbers.py                exact Decimal money / percentage parsing and rounding
│   ├── ocr.py                    Windows OCR / Apple Vision / Tesseract, words + boxes
│   ├── extract/                  image → validated order (no Fakturama access)
│   │   ├── schema.py             pydantic models of the order
│   │   ├── llm_extractor.py      Claude vision → structured output
│   │   ├── crosscheck.py         critical values must also appear in OCR text
│   │   ├── normalize.py          dates, amounts, percentages, payment method, names
│   │   ├── validate.py           line, net, VAT and gross arithmetic; required fields
│   │   └── pipeline.py           runs the steps above; also loads a saved JSON
│   ├── ui/                       Fakturama driver (Windows; pywinauto imported lazily)
│   │   ├── app.py                connect to / start Fakturama
│   │   ├── locators.py           loads config/locators.yaml
│   │   ├── finder.py             find by name+type, by label, or by OCR
│   │   ├── actions.py            click / set / select / toggle, each read back
│   │   ├── waits.py              wait for state, not time
│   │   ├── grid_ocr.py           reads custom-drawn tables via OCR
│   │   └── discover.py           dumps the UIA tree to build locators.yaml
│   ├── flow/                     the spec's Order-first flow, one module per stage
│   │   ├── stage1_open_order.py  spec 1.3–1.8
│   │   ├── stage2_debtor.py      spec 2.1–2.13
│   │   ├── payment_method.py     spec 2.10.x
│   │   ├── stage3_products.py    spec 3.1–3.17
│   │   ├── vat.py                spec 3.4–3.6
│   │   ├── stage4_save_order.py  spec 4.1–4.7
│   │   ├── stage5_invoice.py     spec 5.1–5.7
│   │   ├── documents.py          Data > Documents checks (4.5, 5.5)
│   │   ├── matching.py           exact-match rules (pure functions)
│   │   ├── context.py            state shared across stages
│   │   └── runner.py             runs stages 1–5, stops at the first failed gate
│   └── report/
│       └── run_report.py         runs/<timestamp>/report.json, screenshots, manual_review.json
├── scripts/
│   └── windows_setup.ps1         one-command Windows setup + guided discovery
├── samples/                      the supplied order image, its hand-checked transcription
│                                 (*.raw.json) and the expected validated order (*.expected.json)
├── tests/                        unit tests (run on any OS)
│   ├── fixtures/uia/             slim copies of the recorded Fakturama control trees
│   └── live/                     live UI tests against a running Fakturama (opt-in)
└── docs/screenshots/             annotated screenshots of a run
```

## Development setup

The extraction and the unit tests run on any OS. The Fakturama automation needs
**Windows 10/11** with Fakturama installed.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip install -r requirements.txt
cp .env.example .env                            # then add your ANTHROPIC_API_KEY
.venv/bin/python -m pytest
```

## Windows setup (to run against Fakturama)

1. **Windows 10 or 11**, on a PC or in a VM. On an Apple-silicon Mac, use
   [UTM](https://mac.getutm.app) (free) or Parallels with Windows 11 on ARM. Set the
   Windows display language to English, because the OCR uses English.
2. **Fakturama.** Download the Windows version from
   <https://www.fakturama.info/download/>, install it, start it once and finish the first-start
   dialog. A new, empty workspace is best for testing. Keep Fakturama's language English:
   the spec and `config/locators.yaml` use the English labels.
3. **Get this project** onto Windows, e.g. to `C:\Fakturama-Task`. Either use GitHub's
   *Code > Download ZIP* and unzip it, or clone it with GitHub Desktop or git.
4. **Run the setup script** in PowerShell from the project folder:

   ```powershell
   cd C:\Fakturama-Task
   powershell -ExecutionPolicy Bypass -File scripts\windows_setup.ps1
   ```

   It installs Python 3.11 x64 with winget if it is missing, creates `.venv`, installs
   `requirements.txt` and runs the tests, including Windows OCR on the sample image. If
   Microsoft's Visual C++ Redistributable (x64) is missing, it installs that too: pywinauto
   needs it, and a new Windows may not have it. Then it waits for Fakturama and starts the
   guided discovery (below). Use `-SkipDiscovery` to stop after the tests.

   The same steps by hand:

   ```powershell
   py -3.11 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   .venv\Scripts\python -m pytest
   ```

   Use the **x64** Python 3.11 **on ARM Windows too**: some dependencies (e.g. PyYAML) have
   no ARM64 builds, and Windows runs x64 Python transparently. If the OCR test reports a
   missing language, run this in an administrator PowerShell:
   `Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"`. If importing
   pywinauto fails with `DLL load failed while importing win32ui`, install the
   [Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe).

## Discovering Fakturama's controls (Windows)

`locators.yaml` is built from what UI Automation really exposes, not from guesses. With
Fakturama running:

```powershell
.venv\Scripts\python main.py discover            # guided: one prompt per screen
.venv\Scripts\python main.py discover --list     # what each screen needs open
.venv\Scripts\python main.py discover --only order_editor select_address   # redo some
```

Each prompt says what to open in Fakturama; press Enter to record it. Keep the PowerShell
window next to Fakturama rather than on top of it. The tool is read-only: it brings
Fakturama's windows to the front but never clicks or types. For every window it writes the
control tree (`.tree.txt` / `.tree.json`), a screenshot (`.png`) and the OCR of that
screenshot (`.ocr.json`). At the end it prints the path of a `.zip` with everything.

To check `config/locators.yaml` against the Fakturama that is running now (read-only; it
lists every control it finds on the screens that are open):

```powershell
.venv\Scripts\python main.py probe
.venv\Scripts\python main.py probe --screen order_editor
```

## Live UI tests (Windows)

`tests/live/` drives the real Fakturama and is skipped unless `FAKTURAMA_LIVE=1` is set.
Start Fakturama with no editor open, then:

```powershell
$env:FAKTURAMA_LIVE = "1"; .venv\Scripts\python -m pytest tests/live -v
```

The tests:

- open a New Order, set Cust.Ref., Date and the Net price mode (each read back), open and
  cancel Select the address, close the order **without saving**, and check that the next
  New Order still gets the same number;
- open Data > VATs, read the list with OCR, find the `Tax-free` row, open it by
  double-click and read Name, VAT code and Value from its editor;
- read the column headers of Data > Documents and of the Select the address table.

Nothing is saved.

## Extracting the order data

```bash
# Claude reads the image (needs ANTHROPIC_API_KEY in .env)
python main.py extract samples/order_WEB-2026-0714-A17.png --out order.json --save-raw order.raw.json

# Same checks without an API key, using a saved transcription
python main.py extract samples/order_WEB-2026-0714-A17.png --raw samples/order_WEB-2026-0714-A17.raw.json
```

The validated order goes to stdout (or `--out`); warnings and a one-line summary go to
stderr. Exit code `0` = accepted, `1` = rejected (every problem is listed, and Fakturama is
never touched). The four steps:

| Step | Module | What it does |
|---|---|---|
| A | `llm_extractor.py` | Claude transcribes the image into a fixed schema (structured output). It copies values verbatim and never calculates. |
| B | `crosscheck.py` | Every critical value (reference, dates, SKUs, prices, totals, ZIPs, ...) must also appear in the OCR text, which catches invented values. Percentages allow for Windows OCR reading `%` as `96` or `0/0`. A discount or VAT rate OCR misses entirely is only a warning when OCR found the amounts that fix it, so step D's arithmetic proves it. |
| C | `normalize.py` | Converts to typed values: ISO dates, `Decimal` amounts, known payment methods, first/last name. Ambiguous input (`03/04/2026`, `1,234`, a three-part name) is an error, not a guess. |
| D | `validate.py` | Line totals, net, VAT and gross arithmetic; PAID needs a payment date; the currency must match Fakturama's. |

OCR engine by OS: Windows built-in OCR (Windows), Apple Vision (macOS, for development),
Tesseract if installed.

## Changes from the design doc

- **No `temperature: 0`.** Current Claude models reject the sampling parameters. Repeatable
  output comes from the strict output schema, verbatim-only instructions and the B–D checks.
- **Apple Vision OCR on macOS**, in addition to Windows OCR and Tesseract, so the
  extraction and the OCR cross-check can be developed and tested without Windows.
- **Two schema layers**: a verbatim `Raw*` layer (what Claude returns and OCR is compared
  against) and a typed `OrderData` layer (what the Fakturama flow uses).

## Fakturama 2.2.0 notes (found while building the UI driver)

- The contact's payment method is on the **Miscellaneous** tab; 2.2.0 has no separate
  Payment tab (task step 2.10).
- In **Net** price mode the order's "Total Gross" field becomes "Total Net".
- Fakturama shows amounts with `$` and dates as `Jul 14, 2026` (as in the task's own
  screenshots). Amounts are compared as numbers; the order currency (EUR) is checked against
  `EXPECTED_CURRENCY`, not against Fakturama's display.
- The Date field is a segmented date editor: typing `Jul 14, 2026` only changes the day.
  It is set by typing month, day and year as digits, then read back.
- Closing a changed editor opens a **Save Parts** list with a tick box, not a Yes/No
  question. To discard, the tool unticks the row with Space, confirms through the list
  control that nothing is ticked, then presses OK. Any other dialog is cancelled and the
  run stops for manual review.
- Payment-code names end with a space (`'Credit transfer '`); names are compared with
  surrounding spaces ignored.
- The lists (products, contacts, VATs, documents) are drawn by Fakturama itself, so UI
  Automation sees no rows. They are read with OCR: the table area (found through UIA) is
  captured, read at 2x, words are grouped into rows and put under the column whose header
  starts at or before them. In a selected row the white column lines read as `I`/`|`;
  those tokens are dropped. A row is clicked at the position OCR found for it, and every
  selection is confirmed by its effect (the editor or the address it fills in).
- The list tabs (VATs, Documents, ...) do not support UI Automation's Select; the tool
  clicks them instead and checks that they became selected.
- An existing record opens in an editor tab named after it (e.g. `Tax-free`). The
  standard VAT cannot be deleted (its delete button stays disabled).

## Progress

| # | Step | Status |
|---|---|---|
| 1 | Repo structure, dependencies, sample image | done |
| 2 | Extraction: schema, Claude call, OCR cross-check, normalize, validate | done (Claude call tested with a fake client; first live call needs an API key) |
| 3 | UIA discovery on Windows | done: all 13 screens recorded from Fakturama 2.2.0 on Windows 11 |
| 4 | UI helpers and `locators.yaml` | done: locators and finder, connect and waits, actions with read-back, table OCR; 5 live tests pass. Editing item-line cells moves to step 6 (needs a product line) |
| 5 | Stage 1: open New Order | — |
| 6 | Stages 2–3: select existing Debtor and Products, fill item lines | — |
| 7 | Stages 4–5: save Order, linked Invoice, paid status, verification | — |
| 8 | Create missing Debtor, Payment Method, VAT, Product | — |
| 9 | Run report and manual-review stops | — |
| 10 | README, screenshots / recording, written answers | — |
