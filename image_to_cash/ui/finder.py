"""
Find controls by meaning, never by fixed coordinates.

1. UIA name + control type inside a scope (main window, editor tab, dialog).
2. Label-relative: the editable control next to a label such as "Cust.Ref.".
3. OCR fallback: find the label text in a window screenshot.
"""
