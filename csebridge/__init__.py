"""csebridge — keep Google Custom Search JSON API code alive after Jan 1 2027."""

from .api import CseError, search

__version__ = "0.2.0"

__all__ = ["CseError", "search", "__version__"]
