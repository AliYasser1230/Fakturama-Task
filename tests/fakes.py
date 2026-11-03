from contextlib import contextmanager
from decimal import Decimal

from image_to_cash.errors import ControlNotFound
from image_to_cash.numbers import money, parse_amount
from image_to_cash.ocr import Box
from image_to_cash.ui.actions import MONTH_ABBR
from image_to_cash.ui.grid_ocr import Grid, GridRow, OcrWord

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
PAYMENT_COLUMNS = ("Standard", "Name", "Description", "Discount", "Disc. Days", "Net Days")
NEW_PAYMENT = {"name": "", "description": "", "account": "", "payment_code": "Mutually defined ", "cash_discount": "0%",
               "discount_days": "0", "net_days": "0", "text_unpaid": "", "text_deposit": "", "text_paid": "",
               "standard": "Cash"}
MENU_ITEMS = {("data_menu", "payments"): "payments_list", ("data_menu", "vats"): "vats_list",
              ("data_menu", "documents"): "documents_list"}
DOCUMENT_COLUMNS = ("Document", "Date", "Name", "Cust.Ref.", "State", "Total", "Printed")
VAT_COLUMNS = ("Standard", "Name", "Description", "Value")
NEW_VAT = {"name": "", "description": "", "vat_code": "S (Standard rate)", "value": "0%", "standard": "Tax-free"}
NEW_PRODUCT = {"item_number": "", "name": "", "category": "", "gtin": "", "supplier_code": "", "description": "",
               "price_gross": "$0.00", "cost_price_net": "$0.00", "vat": "Free of Tax", "stock": "0.00"}


def grid(columns, *rows):
    grid_rows = tuple(GridRow(dict(zip(columns, values)), Box(10, 30 + 20 * i, 400, 12)) for i, values in enumerate(rows))
    return Grid(tuple(columns), Box(10, 5, 400, 12), grid_rows)


class FakeApp:
    def __init__(self, *, open_screens=(), new_order=None, after=None, tables=None, on_ok=None, present=(),
                 payment_options=("Pay Cash",)):
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
        self.payment_options = list(payment_options)
        self.saved = []
        self.last_row = None
        self.auto_select = {}
        self.tables.setdefault(("payments_list", "table"), grid(PAYMENT_COLUMNS, ("", "Cash", "Pay Cash", "0%", "0", "0")))
        self.tables.setdefault(("select_product", "table"), grid(PRODUCT_COLUMNS))
        self.tables.setdefault(("vats_list", "table"), grid(VAT_COLUMNS, ("", "Tax-free", "Free of Tax", "0.00 %")))
        self.tables.setdefault(("documents_list", "table"), grid(DOCUMENT_COLUMNS))
        self.vat_options = ["Free of Tax"]
        self.vat_codes = {}
        self.line_data = []
        self.documents = []

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
            self.values.update({("order_editor", "discount"): "0%", ("order_editor", "shipping"): "Free of shipping costs",
                                ("order_editor", "shipping_amount"): "$0.00"})
            self._totals()
        elif (screen, control) == ("order_editor", "create_invoice"):
            self.open.add("invoice_editor")
            o = lambda key: self.values.get(("order_editor", key), "")
            self.values.update({("invoice_editor", k): o(k) for k in
                                ("cust_ref", "address", "delivery_address", "price_mode", "vat_mode", "subtotal",
                                 "vat_total", "total")})
            self.values.update({("invoice_editor", "number"): "INV000001", ("invoice_editor", "date"): "Nov 3, 2026",
                                ("invoice_editor", "service_date"): "Nov 3, 2026",
                                ("invoice_editor", "order_date"): o("date"), ("invoice_editor", "paid"): False,
                                ("invoice_editor", "payment"): self.values.get(("debtor_editor", "payment"), "Pay Cash")})
            self.tables[("invoice_editor", "items")] = self.tables[("order_editor", "items")]
            for tab in ("tab_invoice_address", "tab_delivery_address"):
                if ("order_editor", tab) in self.present:
                    self.present.add(("invoice_editor", tab))
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
        elif (screen, control) == ("main", "menu_data"):
            self.open.add("data_menu")
        elif (screen, control) in MENU_ITEMS:
            self.open.discard(screen)
            self.open.add(MENU_ITEMS[(screen, control)])
        elif (screen, control) == ("vats_list", "create"):
            self.open.add("vat_editor")
            self.values.update({("vat_editor", k): v for k, v in NEW_VAT.items()})
        elif (screen, control) == ("main", "nav_new_product"):
            self.open.add("product_editor")
            self.values.update({("product_editor", k): v for k, v in NEW_PRODUCT.items()})
        elif (screen, control) == ("payments_list", "create"):
            self.open.add("payment_editor")
            self.values.update({("payment_editor", k): v for k, v in NEW_PAYMENT.items()})
        elif (screen, control) in OPENS:
            self.open.add(OPENS[(screen, control)])
        elif control in ("ok", "cancel"):
            self.open.discard(screen)
            if control == "ok" and screen == "select_address" and screen not in self.on_ok:
                self._fill_order_addresses()
            if control == "ok" and screen == "select_product" and screen not in self.on_ok and self.last_row:
                row = self.last_row
                rate = Decimal(row["VAT"].split()[1].rstrip("%")) if row["VAT"].startswith("VAT ") else Decimal("0")
                self.line_data.append({"sku": row["Item No."], "qty": Decimal("1"), "disc": Decimal("0"), "vat": rate,
                                       "unit": money(parse_amount(row["Price"]) / (1 + rate / 100)),
                                       "name": row["Name"], "vat_name": row["VAT"]})
                self._totals()
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
        if (screen, control) == ("invoice_editor", "paid_value"):
            text = f"${text}"
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

    def read_table(self, screen, control, title=None, required=None):
        table = self.tables.get((screen, control))
        if callable(table):
            return table(self.values.get((screen, "search"), ""))
        if table is None:
            raise ControlNotFound(f"no table {screen}.{control}")
        return table

    def table_rows(self, screen, control, title=None):
        rows = [[OcrWord("Qty.", Box(40, 0, 30, 10)), OcrWord("Item No.", Box(100, 0, 50, 10))]]
        for n, line in enumerate(self.line_data, 1):
            rows.append([OcrWord(f"{line['qty']:.2f}", Box(40, 20 * n, 30, 10)),
                         OcrWord(line["sku"], Box(100, 20 * n, 60, 10))])
        return rows

    @contextmanager
    def revealed(self, screen, control, title=None):
        self._done("reveal", screen, control)
        yield

    def read_cell(self, screen, control, row, column, title=None):
        return row.cells.get(column, "")

    def read_table_stable(self, screen, control, title=None, timeout=None):
        return self.read_table(screen, control, title)

    def search_table(self, screen, text, timeout=None):
        self.values[(screen, "search")] = text
        self.calls.append(("search", screen, text))
        auto = self.auto_select.get(screen)
        if auto is not None:
            self.last_row = auto
            self.click(screen, "ok")
            return None
        return self.read_table(screen, "table")

    def click_row(self, row, *, double=False):
        self.last_row = dict(row.cells)
        self.calls.append(("click_row", dict(row.cells), double))
        if double and "Value" in row.cells:
            self.open.add("vat_editor")
            name = row.cells["Name"]
            self.values.update({("vat_editor", "name"): name, ("vat_editor", "description"): row.cells["Description"],
                                ("vat_editor", "vat_code"): self.vat_codes.get(name, "S (Standard rate)"),
                                ("vat_editor", "value"): row.cells["Value"]})

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
        if (screen, control) == ("invoice_editor", "paid"):
            self.values[(screen, "paid")] = checked
            if checked:
                self.values[(screen, "paid_date")] = "Nov 3, 2026"
                self.values[(screen, "paid_value")] = self.values[(screen, "total")]
            self._done("tick", screen, control, checked)
            return
        self.roles[control] = checked
        self._done("tick", screen, control, checked)

    def press(self, keys):
        if keys == "{ESC}" and "address_roles" in self.open:
            self.open.discard("address_roles")
            shown = ", ".join(ROLE_NAMES[k] for k in ("invoice", "delivery") if self.roles.get(k))
            self.values[self._key("debtor_editor", "address_type")] = shown
        self._done("press", keys)

    def check_no_dialog(self, doing):
        dialog = self.after.get(("dialog", doing))
        if dialog:
            from image_to_cash.errors import ManualReviewRequired
            raise ManualReviewRequired(f"Fakturama showed {dialog[0]!r} while {doing}: {dialog[1]}")

    def click_when(self, screen, control, title=None, timeout=None):
        self.click(screen, control, title)

    def is_ticked(self, screen, control, title=None):
        return bool(self.values.get((screen, control)))

    def options(self, screen, control, title=None):
        if (screen, control) == ("debtor_editor", "payment"):
            return list(self.payment_options)
        if (screen, control) == ("product_editor", "vat"):
            return list(self.vat_options)
        if (screen, control) == ("invoice_editor", "payment"):
            return ["Pay Cash"] + [o for o in self.payment_options if o != "Pay Cash"]
        return []

    def close_editor(self, screen, timeout=None, title=None):
        self.open.discard(screen)
        self._done("close_editor", screen, title)

    def save(self, screen, title=None, *, saved_title=None, timeout=None):
        if screen in ("order_editor", "invoice_editor"):
            v = lambda key: self.values[(screen, key)]
            state = "paid" if screen == "invoice_editor" and self.values.get((screen, "paid")) else "open"
            self.documents.append((v("number"), v("date"), "Northstar Office GmbH", v("cust_ref"), state, v("total"), ""))
            self.tables[("documents_list", "table")] = grid(DOCUMENT_COLUMNS, *self.documents)
            self.saved.append((screen, v("number")))
            self._done("save", screen, v("number"))
            return v("number")
        if screen == "payment_editor":
            self.payment_options.append(self.values[("payment_editor", "description")])
        elif screen == "vat_editor":
            v = lambda key: self.values[("vat_editor", key)]
            rows = self.tables[("vats_list", "table")].rows
            self.tables[("vats_list", "table")] = grid(VAT_COLUMNS, *[tuple(r.cells.values()) for r in rows],
                                                       ("", v("name"), v("description"), f"{v('value').rstrip('%')}.00 %"))
            self.vat_codes[v("name")] = v("vat_code")
            self.vat_options.append(v("description"))
        elif screen == "product_editor":
            v = lambda key: self.values[("product_editor", key)]
            rows = [tuple(r.cells.values()) for r in self.tables[("select_product", "table")].rows]
            rows.append((v("item_number"), v("name"), v("description"), "0", v("price_gross"), v("vat")))
            self.tables[("select_product", "table")] = grid(PRODUCT_COLUMNS, *rows)
            saved_title = saved_title or v("name")
        elif screen == "debtor_editor":
            v = lambda key: self.values[("debtor_editor", key)]
            row = (v("customer_id"), v("first_name"), v("last_name"), v("company"), v("main.zip"), v("main.city"))
            self.tables[("select_address", "table")] = grid(ADDRESS_COLUMNS, row)
            saved_title = saved_title or v("company")
        self.saved.append((screen, saved_title))
        if screen in ("payment_editor", "debtor_editor", "vat_editor", "product_editor"):
            self.open.discard(screen)
        self._done("save", screen, saved_title)
        return saved_title

    def _fill_order_addresses(self):
        v = lambda key: self.values.get(("debtor_editor", key), "")
        invoice = [v("company"), f"{v('first_name')} {v('last_name')}", v("main.street"),
                   f"{v('main.zip')} {v('main.city')}", v("main.country")]
        self.values[("order_editor", "address")] = "\n".join(invoice)
        self.present.add(("order_editor", "tab_invoice_address"))
        if v("additional.street"):
            delivery = [v("company"), v("additional.additional_name"), v("additional.street"),
                        f"{v('additional.zip')} {v('additional.city')}", v("additional.country")]
            self.values[("order_editor", "delivery_address")] = "\n".join(delivery)
            self.present.add(("order_editor", "tab_delivery_address"))


    def _totals(self):
        net = sum((money(l["qty"] * l["unit"] * (1 - l["disc"] / 100)) for l in self.line_data), Decimal("0"))
        vat = sum((money(money(l["qty"] * l["unit"] * (1 - l["disc"] / 100)) * l["vat"] / 100) for l in self.line_data),
                  Decimal("0"))
        self.tables[("order_editor", "items")] = grid(ITEM_COLUMNS, *[
            (str(n), f"{l['qty']:.2f}", l["sku"], "", l["name"], "", l["vat_name"], f"${l['unit']:.2f}")
            for n, l in enumerate(self.line_data, 1)])
        self.values[("order_editor", "subtotal")] = f"${net:.2f}"
        self.values[("order_editor", "vat_total")] = f"${vat:.2f}"
        self.values[("order_editor", "total")] = f"${net + vat:.2f}"

    def set_line_cell(self, screen, control, key, column, text, *, check, left_of_key=False):
        line = next((l for l in self.line_data if l["sku"] == key), None)
        if line is None:
            raise ControlNotFound(f"no line {key}")
        field = {"Qty.": "qty", "U.Price": "unit", "Discount": "disc"}[column]
        line[field] = Decimal(text)
        self._totals()
        self._done("set_line_cell", key, column, text)
        if not check(text):
            from image_to_cash.errors import VerificationFailed
            raise VerificationFailed(f"{column} of {key} shows {text!r}")
        return text
