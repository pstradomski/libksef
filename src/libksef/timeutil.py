import datetime


def parse_timestamp(timestamp_text: str) -> datetime.datetime:
    """Convert timestamp from string to datetime.

    WARNING: loses precision.
    """
    timestamp_text = timestamp_text.removesuffix("+00:00")
    if (micros_len := len(timestamp_text.split(".")[-1])) > 6:
        to_strip = micros_len - 6
        timestamp_text = timestamp_text[:-to_strip]
    return datetime.datetime.strptime(
        timestamp_text + "+0000", "%Y-%m-%dT%H:%M:%S.%f%z"
    ).astimezone(datetime.timezone.utc)


def write_timestamp(timestamp: datetime.datetime) -> str:
    """Writes timestamp back in the format KSEF expects."""
    return timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
