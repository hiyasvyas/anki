"""Speedrun MCAT AI subsystem.

A self-contained "memory -> performance bridge": a Transfer-Question generator
that takes a NAMED SOURCE and produces new exam-style MCAT questions testing the
same idea in different words (the paraphrase test).

Everything except the live `generate` step is deterministic and runs on cached
JSON artifacts, so `check`, `eval`, `baselines`, `leakage`, and `paraphrase` all
work today with no API key.

See ``README.md`` and ``../ai-note.md`` for the design rationale.
"""

__all__ = ["config"]

__version__ = "0.1.0"
