"""Shared text-processing helpers."""


def split_addresses(value: str) -> list[str]:
    """Split a comma-separated address string into a trimmed list."""
    return [v.strip() for v in value.split(",") if v.strip()]
