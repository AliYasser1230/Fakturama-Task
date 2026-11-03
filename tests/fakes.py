from image_to_cash.errors import ControlNotFound
from image_to_cash.ocr import Box
from image_to_cash.ui.actions import MONTH_ABBR
from image_to_cash.ui.grid_ocr import Grid, GridRow

NEW_ORDER = {"number": "PO000001", "date": "Nov 3, 2026", "cust_ref": "", "price_mode": "Gross", "vat_mode": "With VAT"}
ADDRESS_COLUMNS = ("No.", "First Name", "Name", "Company", "ZIP", "City")
PRODUCT_COLUMNS = ("Item No.", "Name", "Description", "Stock", "Price", "VAT")
ITEM_COLUMNS = ("Pos.", "Qty.", "Item No.", "Picture", "Name", "Description", "VAT", "U.Price")
OPENS = {("order_editor", "select_address"): "select_address", ("order_editor", "select_product"): "select_product"}


def grid(columns, *rows):
    grid_rows = tuple(GridRow(dict(zip(columns, values)), Box(10, 30 + 20 * i, 400, 12)) for i, values in enumerate(rows))
    return Grid(tuple(columns), Box(10, 5, 400, 12), grid_rows)


class FakeApp:
    def __init__(self, *, open_screens=(), new_order=None, after=None, tables=None, on_ok=None, present=()):
        self.open = set(open_screens)
        self.values = {}
        self.calls = []
        self.new_order = {**NEW_ORDER, **(new_order or {})}
        self.after = after or {}
        self.tables = dict(tables or {})
        self.on_ok = on_ok or {}
        self.present = set(present)

    def is_open(self, screen, title=None):
        return screen in self.open

    def wait_open(self, screen, timeout=None, title=None):
        if screen not in self.open:
            raise ControlNotFound(screen)
        return screen

    def wait_closed(self, screen, timeout=None, title=None):
        if screen in self.open:
            raise ControlNotFound(f"{screen} still open")

    def exists(self, screen, control, title=None):
        return (screen, control) in self.values or (screen, control) in self.present

    def read(self, screen, control, title=None):
        return self.values[(screen, control)]

    def _done(self, *call):
        self.calls.append(call)
        effect = self.after.get(call[:3])
        if effect:
            effect(self)

    def click(self, screen, control, title=None):
        if (screen, control) == ("main", "new_order"):
            self.open.add("order_editor")
            self.values.update({("order_editor", k): v for k, v in self.new_order.items()})
        elif (screen, control) in OPENS:
            self.open.add(OPENS[(screen, control)])
        elif control in ("ok", "cancel"):
            self.open.discard(screen)
            if control == "ok":
                for key, value in self.on_ok.get(screen, {}).items():
                    if isinstance(value, Grid):
                        self.tables[key] = value
                    else:
                        self.values[key] = value
        self._done("click", screen, control)

    def type(self, screen, control, text, *, check=None, commit="{TAB}", title=None):
        self.values[(screen, control)] = text
        self._done("type", screen, control, text)
        return text

    def set_date(self, screen, control, value, title=None):
        self.values[(screen, control)] = f"{MONTH_ABBR[value.month - 1]} {value.day}, {value.year}"
        self._done("set_date", screen, control, value)
        return self.values[(screen, control)]

    def choose(self, screen, control, option, title=None):
        self.values[(screen, control)] = option
        self._done("choose", screen, control, option)
        return option

    def read_table(self, screen, control, title=None):
        table = self.tables.get((screen, control))
        if callable(table):
            return table(self.values.get((screen, "search"), ""))
        if table is None:
            raise ControlNotFound(f"no table {screen}.{control}")
        return table

    def read_table_stable(self, screen, control, title=None, timeout=None):
        return self.read_table(screen, control, title)

    def click_row(self, row, *, double=False):
        self.calls.append(("click_row", dict(row.cells), double))
