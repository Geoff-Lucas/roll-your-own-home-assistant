import threading

import pytest

from app.sync import locks


def test_a_busy_account_times_out_instead_of_waiting_forever():
    with locks.account_lock(101):
        with pytest.raises(locks.AccountBusy):
            with locks.account_lock(101, timeout=0.05):
                pass


def test_accounts_do_not_block_each_other():
    with locks.account_lock(102):
        with locks.account_lock(103, timeout=0.05):  # a different account: no wait
            pass


def test_the_lock_is_released_even_when_the_work_fails():
    with pytest.raises(ValueError):
        with locks.account_lock(104):
            raise ValueError("server said no")

    with locks.account_lock(104, timeout=0.05):  # free again
        pass


def test_a_waiter_gets_its_turn_once_the_holder_finishes():
    order = []

    def holder():
        with locks.account_lock(105):
            order.append("sync")

    with locks.account_lock(105):
        thread = threading.Thread(target=holder)
        thread.start()
        order.append("edit")
    thread.join(timeout=5)

    assert order == ["edit", "sync"]
