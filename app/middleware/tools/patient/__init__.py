"""Patient-facing tools. Dropped-file auto-discovery: importing this package
registers every `@tool` function via decorator side effects."""

from . import labs, notes  # noqa: F401 — import side effects register the @tool
