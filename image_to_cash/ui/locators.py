from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


def _check_regex(pattern: str, what: str) -> None:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{what} is not a valid regular expression: {exc}") from None


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: str = "Text"


class Container(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    name: str


class Locator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    name: str | None = None
    name_re: str | None = None
    after: Anchor | None = None
    within: Container | None = None
    index: int | None = Field(default=None, ge=1)
    columns: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "Locator":
        if self.name is not None and self.name_re is not None:
            raise ValueError("use either name or name_re, not both")
        if self.name_re is not None:
            _check_regex(self.name_re, "name_re")
        if self.columns and self.type != "Grid":
            raise ValueError("columns are only allowed for type Grid")
        return self

    def describe(self) -> str:
        parts = [self.type]
        if self.name is not None:
            parts.append(repr(self.name))
        if self.name_re is not None:
            parts.append(f"/{self.name_re}/")
        if self.index is not None:
            parts.append(f"#{self.index}")
        if self.after is not None:
            parts.append(f"after {self.after.type} {self.after.name!r}")
        if self.within is not None:
            parts.append(f"in {self.within.type} {self.within.name!r}")
        return " ".join(parts)


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window: Literal["main"] | None = None
    dialog: str | None = None
    tab: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "Scope":
        if sum(v is not None for v in (self.window, self.dialog, self.tab)) != 1:
            raise ValueError("scope needs exactly one of: window, dialog, tab")
        if self.tab is not None:
            _check_regex(self.tab, "tab")
        return self

    def describe(self) -> str:
        if self.window:
            return "main window"
        if self.dialog:
            return f"dialog {self.dialog!r}"
        return f"tab /{self.tab}/"


class Screen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Scope
    controls: dict[str, Locator]


class Locators:
    def __init__(self, screens: dict[str, Screen]):
        self.screens = screens

    def screen(self, name: str) -> Screen:
        try:
            return self.screens[name]
        except KeyError:
            raise KeyError(f"no screen {name!r} in locators (have: {', '.join(sorted(self.screens))})") from None

    def control(self, screen: str, control: str) -> Locator:
        controls = self.screen(screen).controls
        try:
            return controls[control]
        except KeyError:
            raise KeyError(f"no control {control!r} on screen {screen!r} (have: {', '.join(sorted(controls))})") from None


def load_locators(path: str | Path) -> Locators:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of screens")
    screens = {}
    for name, spec in data.items():
        try:
            screens[name] = Screen.model_validate(spec)
        except ValidationError as exc:
            raise ValueError(f"{path}: screen {name!r} is invalid:\n{exc}") from None
    return Locators(screens)
