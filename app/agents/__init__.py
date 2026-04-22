"""Translator router — returns the run() coroutine for the requested kind."""

from . import ollama, plain, strands


def get_translator(kind: str):
    if kind == "plain":
        return plain.run
    if kind == "strands":
        return strands.run
    if kind == "ollama":
        return ollama.run
    raise ValueError(f"Unknown translator: {kind!r}. Use 'plain', 'strands', or 'ollama'.")
