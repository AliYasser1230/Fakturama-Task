from image_to_cash.errors import ControlNotFound
from image_to_cash.ocr import Box
from image_to_cash.ui.actions import MONTH_ABBR
from image_to_cash.ui.grid_ocr import Grid, GridRow

NEW_ORDER = {"number": "PO000001", "date": "Nov 3, 2026", "cust_ref": "", "price_mode": "Gross", "vat_mode": "With VAT"}
ADDRESS_COLUMNS = ("No.", "First Name", "Name", "Company", "ZIP", "City")
PRODUCT_COLUMNS = ("Item No.", "Name", "Description", "Stock", "Price", "VAT")
ITEM_COLUMNS = ("Pos.", "Qty.", "Item No.", "Picture", "Name", "Description", "VAT", "U.Price")
OPENS = {("order_editor", "select_address"): "select_address", ("order_editor", "select_product"): "select_product"}
NEW_DEBTOR = {"customer_id": "CUST000001", "company": "", "salutation": "---", "first_name": "", "last_name": "",
              "alias": "", "discount": "0%", "net_or_gross": "---"}
ADDRESS_CONTROLS = {"additional_name", "street", "address_specification", "district", "zip", "city", "country",
                    "email", "phone", "mobile", "address_type"}
ROLE_NAMES = {"invoice": "Invoice address", "delivery": "Delivery address"}


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
        self.address_tab = "main"
        self.roles = {}

    def is_open(self, screen, title=None):
        return screen in self.open

    def editor_open(self, screen, title=None):
        return screen in self.open

    def activate(self, screen, title=None, timeout=None):
        return self.wait_open(screen)

    def wait_open(self, screen, timeout=None, title=None):
        if screen not in self.open:
            raise ControlNotFound(screen)
        return screen

    def wait_closed(self, screen, timeout=None, title=None):
        if screen in self.open:
            raise ControlNotFound(f"{screen} still open")

    def _key(self, screen, control):
        if screen == "debtor_editor" and control in ADDRESS_CONTROLS:
            return (screen, f"{self.address_tab}.{control}")
        return (screen, control)

    def exists(self, screen, control, title=None):
        if screen == "address_roles":
            return screen in self.open
        return self._key(screen, control) in self.values or (screen, control) in self.present

    def wait_for(self, screen, control, timeout=None, title=None):
        if not self.exists(screen, control):
            raise ControlNotFound(f"{screen}.{control}")
        return control

    def wait_gone(self, screen, control, timeout=None, title=None):
        if self.exists(screen, control):
            raise ControlNotFound(f"{screen}.{control} still there")

    def read(self, screen, control, title=None):
        return self.values[self._key(screen, control)]

    def _new_address_tab(self, tab):
        self.values.update({("debtor_editor", f"{tab}.{c}"): "" for c in ADDRESS_CONTROLS})
        self.values[("debtor_editor", f"{tab}.country")] = "United States"

    def _done(self, *call):
        self.calls.append(call)
        effect = self.after.get(call[:3])
        if effect:
            effect(self)

    def click(self, screen, control, title=None):
        if (screen, control) == ("main", "new_order"):
            self.open.add("order_editor")
            self.values.update({("order_editor", k): v for k, v in self.new_order.items()})
        elif (screen, control) == ("main", "nav_new_contact"):
            self.open.add("debtor_editor")
            self.values.update({("debtor_editor", k): v for k, v in NEW_DEBTOR.items()})
            self._new_address_tab("main")
        elif (screen, control) == ("debtor_editor", "add_address"):
            self._new_address_tab("additional")
            self.present.add(("debtor_editor", "tab_additional_address"))
            self.address_tab = "additional"
        elif (screen, control) == ("debtor_editor", "address_type_menu"):
            self.open.add("address_roles")
            shown = self.values[self._key("debtor_editor", "address_type")]
            self.roles = {k: name in shown for k, name in ROLE_NAMES.items()}
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
        if screen == "debtor_editor" and control == "discount":
            text = f"{text}%"
        self.values[self._key(screen, control)] = text
        self._done("type", screen, control, text)
        return text

    def set_date(self, screen, control, value, title=None):
        self.values[(screen, control)] = f"{MONTH_ABBR[value.month - 1]} {value.day}, {value.year}"
        self._done("set_date", screen, control, value)
        return self.values[(screen, control)]

    def choose(self, screen, control, option, title=None):
        self.values[self._key(screen, control)] = option
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

    def select_tab(self, screen, control, title=None):
        if screen == "debtor_editor" and control == "tab_main_address":
            self.address_tab = "main"
        elif screen == "debtor_editor" and control == "tab_additional_address":
            if ("debtor_editor", "tab_additional_address") not in self.present:
                raise ControlNotFound("no additional address tab")
            self.address_tab = "additional"
        self._done("select_tab", screen, control)

    def tick(self, screen, control, checked, title=None):
        if screen not in self.open:
            raise ControlNotFound(screen)
        self.roles[control] = checked
        self._done("tick", screen, control, checked)

    def press(self, keys):
        if keys == "{ESC}" and "address_roles" in self.open:
            self.open.discard("address_roles")
            shown = ", ".join(ROLE_NAMES[k] for k in ("invoice", "delivery") if self.roles.get(k))
            self.values[self._key("debtor_editor", "address_type")] = shown
        self._done("press", keys)
