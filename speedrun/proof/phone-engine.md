# Phone runtime proof — the shared Rust engine + MCAT scores run on-device

Verifies the Sunday/Friday requirement that the **Rust engine change ships to the
phone** and the companion **shows the three scores with ranges + the give-up
rule** — not a reimplementation, the same `rslib` compiled into
`librsdroid.so`.

## Setup
- Device: Android emulator `Medium_Phone_API_35` (`emulator-5554`, Android 15 / API 35, x86_64).
- App: `com.ichi2.anki.debug` (`AnkiDroid-play-x86_64-debug.apk`, 157 MB) built against
  `Anki-Android-Backend`'s `rsdroid-release.aar` (20.3 MB), whose `anki/` engine is
  **this fork** — `Anki-Android-Backend/anki/rslib/src/stats/{performance,readiness,pace,deck_score,mastery}.rs`
  and `proto/anki/stats.proto`. So the new RPCs are compiled into the on-device `.so`.
- Entry: `am start … com.ichi2.anki.IntentHandler` → `DeckPicker`.

## Runtime evidence (logcat, from the phone)
`DeckPicker.refreshMcatReadiness` calls all five backend RPCs and logged:

```
DeckPicker$refreshMcatReadiness: MCAT-SPEEDRUN McatDeckScore[phone/Rust]
  score=0.63 range=[0.49,0.74] scorable=2917 rated=51 mastered=32 unseen=2866
  perf=0.63 readiness=507 hasScore=false
```

- `[phone/Rust]` — the numbers come from the shared Rust backend on the device.
- `perf=0.63` — `mcat_performance` RPC (new).
- `readiness=507` — `mcat_readiness` RPC (new), on the real 472–528 MCAT scale.
- `range=[0.49,0.74]` — the score ships with a range, not a single number.
- `hasScore=false`, `rated=51` — the **give-up rule** fires: only 51 graded reviews
  (< the 230 floor), so readiness abstains instead of inventing a number.

## Screenshot
`speedrun/proof/phone-scores.png` (DeckPicker three-score panel):
- **Memory 63%**, range 49%–74%.
- **Performance 63%**, "= memory (transfer not yet measured)".
- **Readiness — "No score yet"**: "a score is shown only after 230 graded reviews
  and 50% topic coverage. Missing: only 51 of 230 needed reviews."
- Per-topic mastery table labeled **"Rust engine · mcat_deck_score + mcat_mastery"**.
- Pace Trainer panel (the `mcat_pace` RPC).

## Reproduce
```powershell
$adb="$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb shell am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER `
  -n com.ichi2.anki.debug/com.ichi2.anki.IntentHandler
# then read the score line:
& $adb logcat -d | Select-String "MCAT-SPEEDRUN"
```

## Honesty / notes
- This is the **x86_64 debug** build on an emulator — it proves the engine + scores
  run on the phone. The **signed release APK** for a physical device is the
  remaining packaging step (see `packaging.md`).
- The give-up rule shown here (`hasScore=false`) is the honest behaviour: the phone
  refuses to show a readiness number below the evidence floor.
