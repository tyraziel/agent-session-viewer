"""Shared formatting helpers."""

import time

ACTIVITY_TIERS = [
    (300, "green", "fiber_manual_record"),
    (600, "yellow", "fiber_manual_record"),
    (1200, "orange", "fiber_manual_record"),
    (float("inf"), "red", "fiber_manual_record"),
]


def get_activity_indicator(mtime: float) -> tuple[str, str] | None:
    """Return (color, icon) if session was active within 20 minutes, else None."""
    elapsed = time.time() - mtime
    if elapsed > 1200:
        return None
    for threshold, color, icon in ACTIVITY_TIERS:
        if elapsed < threshold:
            return color, icon
    return None


def format_duration_ago(mtime: float) -> str:
    elapsed = time.time() - mtime
    if elapsed < 60:
        return "just now"
    if elapsed < 3600:
        mins = int(elapsed // 60)
        return f"{mins}m ago"
    if elapsed < 86400:
        hours = int(elapsed // 3600)
        return f"{hours}h ago"
    days = int(elapsed // 86400)
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"
