"""Every publisher returns this, or raises ApiError."""
from dataclasses import dataclass


@dataclass
class PublishResult:
    post_id: str                 # the platform's id for the created post
    detail: str = ""             # human note, e.g. "scheduled for 19:00"
    scheduled: bool = False      # True = the platform will publish it later


class NotSupported(Exception):
    """Raised when a platform genuinely cannot accept this content type."""
