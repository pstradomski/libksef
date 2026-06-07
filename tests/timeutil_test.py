import datetime
from libksef.timeutil import parse_timestamp, write_timestamp


def test_parse_timestamp_basic():
    ts = "2023-10-27T10:00:00.123456"
    dt = parse_timestamp(ts)
    assert dt == datetime.datetime(
        2023, 10, 27, 10, 0, 0, 123456, tzinfo=datetime.timezone.utc
    )


def test_parse_timestamp_with_offset():
    ts = "2023-10-27T10:00:00.123456+00:00"
    dt = parse_timestamp(ts)
    assert dt == datetime.datetime(
        2023, 10, 27, 10, 0, 0, 123456, tzinfo=datetime.timezone.utc
    )


def test_parse_timestamp_extra_precision():
    # KSEF sometimes returns more than 6 digits for microseconds
    ts = "2023-10-27T10:00:00.123456789+00:00"
    dt = parse_timestamp(ts)
    assert dt == datetime.datetime(
        2023, 10, 27, 10, 0, 0, 123456, tzinfo=datetime.timezone.utc
    )


def test_write_timestamp():
    dt = datetime.datetime(2023, 10, 27, 10, 0, 0, 123456, tzinfo=datetime.timezone.utc)
    ts = write_timestamp(dt)
    assert ts == "2023-10-27T10:00:00.123456+00:00"


def test_roundtrip():
    ts_original = "2023-10-27T10:00:00.123456+00:00"
    dt = parse_timestamp(ts_original)
    ts_new = write_timestamp(dt)
    assert ts_original == ts_new
