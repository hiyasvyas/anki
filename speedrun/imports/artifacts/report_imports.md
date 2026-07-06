# Corrupt-deck / broken-image import test (section 10 adversarial)

**Claim:** handed a corrupt collection, a corrupt/missing deck, or a deck with broken images, the app degrades gracefully -- it never crashes and never silently corrupts data.

Run against the **real shared Anki engine** (the Rust backend the desktop app and the phone build embed). Re-runnable.

**Overall: PASS**

| Scenario | Result | Verdict |
| --- | --- | :--: |
| corrupt_collection_file | refused to open (raised `DBError`), not usable=True | PASS |
| corrupt_apkg_import | import raised `SyncError`; live notes 5→5, integrity ok=True | PASS |
| missing_apkg_import | import raised `BackendIOError`; live notes 3→3, integrity ok=True | PASS |
| deck_with_broken_images | missing reported=['definitely_missing.png'], card rendered=True, kept broken `<img>`=True, integrity ok=True | PASS |
| valid_apkg_import (control) | exported 4 notes, import ok=True, dst notes 0→4, integrity ok=True | PASS |

## What each scenario shows

- **Corrupt collection file** -- the engine refuses to open a non-SQLite file (clean exception), so a damaged profile can't crash the app or masquerade as usable.
- **Corrupt / truncated .apkg** -- the import raises a clean error and the collection it was imported into is byte-for-byte unchanged (same note count, integrity `ok`): a bad import is rejected as a transaction, not half-applied.
- **Missing .apkg** -- import raises a clean error rather than crashing.
- **Deck with broken images** -- `media.check()` lists the missing file, the card still renders with the `<img>` in place (the UI shows a broken-image placeholder), and the collection stays healthy.
- **Valid .apkg (control)** -- a genuine exported package still imports and adds its notes, proving the importer is discriminating, not a blanket reject.

## Reproduce

```powershell
$env:PYTHONPATH = "$PWD\out\pylib"
out\pyenv\Scripts\python.exe -m speedrun.imports.deck_resilience
```
