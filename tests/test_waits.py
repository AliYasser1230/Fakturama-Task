import pytest

from image_to_cash.errors import ControlNotFound, WaitTimeout
from image_to_cash.ui.waits import is_transient, wait_stable, wait_until


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class COMError(Exception):
    pass


def test_returns_the_first_truthy_result():
    clock = FakeClock()
    answers = iter([None, "", "ready"])
    assert wait_until(lambda: next(answers), timeout=5, what="x", clock=clock, sleep=clock.sleep) == "ready"
    assert clock.now == pytest.approx(0.4)


def test_retries_transient_ui_errors():
    clock = FakeClock()
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ControlNotFound("not yet")
        if len(calls) == 2:
            raise COMError("element gone")
        return "found"

    assert wait_until(flaky, timeout=5, what="x", clock=clock, sleep=clock.sleep) == "found"


def test_other_errors_are_raised_at_once():
    clock = FakeClock()

    def bug():
        raise TypeError("a real bug")

    with pytest.raises(TypeError):
        wait_until(bug, timeout=5, what="x", clock=clock, sleep=clock.sleep)
    assert clock.now == 0


def test_timeout_names_what_and_the_last_error():
    clock = FakeClock()

    def missing():
        raise ControlNotFound("order_editor.cust_ref: 0 matches")

    with pytest.raises(WaitTimeout, match=r"waited 2s for the order editor; last error: order_editor.cust_ref"):
        wait_until(missing, timeout=2, what="the order editor", clock=clock, sleep=clock.sleep)


def test_is_transient():
    assert is_transient(ControlNotFound("x")) and is_transient(COMError())
    assert not is_transient(ValueError())


def test_wait_stable_returns_once_the_value_stops_changing():
    clock = FakeClock()
    values = iter(["$0.00", "$297.50", "$345.10", "$345.10", "$345.10", "$345.10", "$345.10"])
    result = wait_stable(lambda: next(values), timeout=10, what="total", settle=0.6, clock=clock, sleep=clock.sleep)
    assert result == "$345.10"


def test_wait_stable_times_out_if_it_keeps_changing():
    clock = FakeClock()
    counter = iter(range(1000))
    with pytest.raises(WaitTimeout, match="to stop changing"):
        wait_stable(lambda: next(counter), timeout=3, what="total", clock=clock, sleep=clock.sleep)
