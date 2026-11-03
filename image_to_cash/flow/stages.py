from __future__ import annotations

from image_to_cash.flow.debtor import select_debtor
from image_to_cash.flow.order import open_order
from image_to_cash.flow.products import add_products
from image_to_cash.flow.runner import Stage

STAGES = [
    Stage("1", "Open the New Order", open_order),
    Stage("2", "Select or create the Debtor", select_debtor),
    Stage("3", "Select or create each Product", add_products),
    Stage("4", "Complete and save the Order", None),
    Stage("5", "Complete and verify the linked Invoice", None),
]
