from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from image_to_cash.errors import ControlNotFound
from image_to_cash.ui.locators import Locator, Locators, Scope

GRID_FILLER = {"ScrollBar", "Thumb"}
CELL_EDITORS = {"Edit", "ComboBox"}
MIN_GRID_HEIGHT = 60


class Node(Protocol):
    @property
    def control_type(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def visible(self) -> bool: ...

    @property
    def rect(self) -> tuple[int, int, int, int] | None: ...

    def children(self) -> list["Node"]: ...


@dataclass
class DictNode:
    data: dict[str, Any]
    _children: list["DictNode"] | None = field(default=None, repr=False)

    @property
    def control_type(self) -> str:
        return self.data.get("control_type") or ""

    @property
    def name(self) -> str:
        return self.data.get("name") or ""

    @property
    def visible(self) -> bool:
        return self.data.get("visible", True)

    @property
    def rect(self) -> tuple[int, int, int, int] | None:
        r = self.data.get("rect")
        return tuple(r) if r else None

    @property
    def value(self) -> str | None:
        return self.data.get("value")

    def children(self) -> list["DictNode"]:
        if self._children is None:
            self._children = [DictNode(c) for c in self.data.get("children", [])]
        return self._children


def preorder(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children()))


def is_grid(node: Node) -> bool:
    if node.control_type != "Pane" or not node.visible:
        return False
    r = node.rect
    if not r or r[3] - r[1] < MIN_GRID_HEIGHT:
        return False
    kids = node.children()
    editors = [c for c in kids if c.control_type in CELL_EDITORS]
    return len(editors) <= 1 and all(c.control_type in GRID_FILLER or c in editors for c in kids)


def matches(node: Node, control_type: str, name: str | None = None, name_re: str | None = None) -> bool:
    if control_type == "Grid":
        if not is_grid(node):
            return False
    elif node.control_type != control_type or not node.visible:
        return False
    if name is not None and node.name != name:
        return False
    if name_re is not None and not re.fullmatch(name_re, node.name):
        return False
    return True


def _is_label(node: Node, anchor_type: str) -> bool:
    return node.control_type == anchor_type and bool(node.name) and node.visible


def candidates(root: Node, loc: Locator) -> list[Node]:
    base = root
    if loc.within is not None:
        containers = [n for n in preorder(root) if matches(n, loc.within.type, loc.within.name)]
        if len(containers) != 1:
            raise ControlNotFound(f"{loc.describe()}: found {len(containers)} {loc.within.type} {loc.within.name!r}")
        base = containers[0]

    nodes = list(preorder(base))[1:]
    if loc.after is not None:
        anchors = [i for i, n in enumerate(nodes)
                   if n.control_type == loc.after.type and n.name == loc.after.name and n.visible]
        if len(anchors) != 1:
            raise ControlNotFound(f"{loc.describe()}: found {len(anchors)} {loc.after.type} {loc.after.name!r}")
        following = []
        for n in nodes[anchors[0] + 1:]:
            if _is_label(n, loc.after.type):
                break
            following.append(n)
        nodes = following
    return [n for n in nodes if matches(n, loc.type, loc.name, loc.name_re)]


def resolve(root: Node, loc: Locator) -> Node:
    found = candidates(root, loc)
    index = loc.index if loc.index is not None else (1 if loc.after is not None else None)
    if index is not None:
        if len(found) < index:
            raise ControlNotFound(f"{loc.describe()}: {len(found)} match(es), wanted number {index}")
        return found[index - 1]
    if len(found) != 1:
        hint = "; narrow it with name, after, within or index" if found else ""
        raise ControlNotFound(f"{loc.describe()}: {len(found)} matches{hint}")
    return found[0]


CONTAINERS = {"Window", "Tab"}


def _search(root: Node, keep: Any) -> list[Node]:
    found, stack = [], [root]
    while stack:
        current = stack.pop()
        if current is not root and keep(current):
            found.append(current)
        if current is root or current.control_type not in CONTAINERS:
            stack.extend(reversed(current.children()))
    return found


def scope_root(main: Node, scope: Scope) -> Node:
    if scope.window == "main":
        return main
    if scope.dialog is not None:
        found = _search(main, lambda n: n.control_type == "Window" and n.visible and n.name == scope.dialog)
    elif scope.menu is not None:
        found = _search(main, lambda n: n.control_type == "Menu" and n.visible and n.name == scope.menu)
    else:
        found = _search(main, lambda n: n.control_type == "Tab" and n.visible and bool(re.fullmatch(scope.tab, n.name)))
    if len(found) != 1:
        raise ControlNotFound(f"{scope.describe()}: found {len(found)}")
    return found[0]


def locate(main: Node, locators: Locators, screen: str, control: str, scope: Scope | None = None) -> Node:
    spec = locators.screen(screen)
    root = scope_root(main, scope or spec.scope)
    try:
        return resolve(root, locators.control(screen, control))
    except ControlNotFound as exc:
        raise ControlNotFound(f"{screen}.{control}: {exc}") from None


class UiaNode:
    def __init__(self, info: Any):
        self.info = info
        self._cache: dict[str, Any] = {}

    def _get(self, key: str, read: Any, default: Any) -> Any:
        if key not in self._cache:
            try:
                self._cache[key] = read()
            except Exception:
                self._cache[key] = default
        return self._cache[key]

    @property
    def control_type(self) -> str:
        return self._get("control_type", lambda: self.info.control_type or "", "")

    @property
    def name(self) -> str:
        return self._get("name", lambda: self.info.name or "", "")

    @property
    def visible(self) -> bool:
        return self._get("visible", lambda: bool(self.info.visible), False)

    @property
    def enabled(self) -> bool:
        return self._get("enabled", lambda: bool(self.info.enabled), False)

    @property
    def rect(self) -> tuple[int, int, int, int] | None:
        def read():
            r = self.info.rectangle
            return (r.left, r.top, r.right, r.bottom)
        return self._get("rect", read, None)

    @property
    def value(self) -> str | None:
        def read():
            from pywinauto.uia_defines import get_elem_interface
            return get_elem_interface(self.info.element, "Value").CurrentValue
        return self._get("value", read, None)

    def children(self) -> list["UiaNode"]:
        return self._get("children", lambda: [UiaNode(c) for c in self.info.children()], [])

    def wrapper(self) -> Any:
        from pywinauto.controls.uiawrapper import UIAWrapper
        return UIAWrapper(self.info)

    def __repr__(self) -> str:
        return f"<{self.control_type} {self.name!r} {self.rect}>"
