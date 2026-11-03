import importlib
import pkgutil
import sys

import pytest

import image_to_cash
import main


def _all_modules():
    yield image_to_cash.__name__
    for info in pkgutil.walk_packages(image_to_cash.__path__, prefix="image_to_cash."):
        yield info.name


@pytest.mark.parametrize("name", list(_all_modules()))
def test_module_imports_without_windows(name):
    importlib.import_module(name)


def test_cli_help_exits_cleanly():
    with pytest.raises(SystemExit) as exc:
        main.main(["--help"])
    assert exc.value.code == 0


def test_sample_image_present(sample_image):
    assert sample_image.is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="the UI driver runs on Windows only")
def test_windows_ui_libraries_load():
    import pywinauto
    import winocr
