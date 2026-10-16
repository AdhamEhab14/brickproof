"""A broken link: the host's bytes stop reaching the device part-way through."""
from brickproof import runner
from brickproof.engine.session import RenodeSession


def test_link_points_cover_the_first_byte_the_last_and_between():
    assert runner.link_points(100, 3) == [1, 25, 50, 75, 99]
    assert runner.link_points(5, 8) == [1, 2, 3, 4]          # no more points than bytes
    assert runner.link_points(1, 8) == [] and runner.link_points(0, 8) == []


def wire():
    """A session whose UART writes are recorded instead of sent to Renode."""
    s = RenodeSession.__new__(RenodeSession)
    s.uart_name, s.uart_sent, s.link_budget, s.virtual_time = "usart2", 0, None, 0.0
    s.delivered = bytearray()
    s.cmd_batch = lambda lines: s.delivered.extend(
        int(line.split()[-1]) for line in lines if "WriteChar" in line)
    s._run_cmd = lambda seconds: "run"
    s._pull = lambda seconds: None
    return s


def test_with_a_budget_only_that_many_bytes_get_through():
    s = wire()
    s.link_budget = 5
    s.uart_write(b"abc")
    s.uart_write(b"defgh")                      # only "de" fits
    s.uart_write(b"ijk")                        # the cable is out: nothing
    assert bytes(s.delivered) == b"abcde"
    assert s.uart_sent == 11 and s.link_budget == 0
    s.link_budget = None                        # back in
    s.uart_write(b"xy")
    assert bytes(s.delivered) == b"abcdexy"
