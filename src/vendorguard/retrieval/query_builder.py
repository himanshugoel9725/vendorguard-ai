"""Turn a control into a search query: its title, requirement and keywords."""

from vendorguard.models.control import Control


def build_query(control: Control) -> str:
    """Title, requirement and every keyword, so both wording and exact terms can match."""
    return f"{control.title}. {control.requirement} {' '.join(control.keywords)}"


__all__ = ["build_query"]
