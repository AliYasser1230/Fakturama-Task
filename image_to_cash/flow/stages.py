from __future__ import annotations

from image_to_cash.flow.debtor import select_debtor
from image_to_cash.flow.invoice import complete_invoice
from image_to_cash.flow.order import open_order
from image_to_cash.flow.products import add_products
from image_to_cash.flow.runner import Stage
from image_to_cash.flow.save_order import save_order

STAGES = [
    Stage("1", "Open the New Order", open_order),
    Stage("2", "Select or create the Debtor", select_debtor),
    Stage("3", "Select or create each Product", add_products),
    Stage("4", "Complete and save the Order", save_order),
    Stage("5", "Complete and verify the linked Invoice", complete_invoice),
]
