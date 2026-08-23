"""csebridge — keep Google Custom Search JSON API code alive after Jan 1 2027."""

from .api import CseError, search

__version__ = "1.0.0"

__all__ = ["CseError", "search", "__version__"]
