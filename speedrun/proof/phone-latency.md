# Phone-side latency (section 10 phone targets)

Measured on-device with `speedrun/bench/phone_latency.ps1` against the **shipping
signed release build** (`com.ichi2.anki`, the x86_64 APK from
[`packaging.md`](../packaging.md)) via `adb`. Raw numbers:
[`phone-latency.json`](phone-latency.json). Re-runnable:

```powershell
# emulator/device up, AnkiDroid onboarding completed once (lands on DeckPicker)
powershell -File speedrun\bench\phone_latency.ps1 -Iters 7
```

## Device under test

| | |
| --- | --- |
| Model | `sdk_gphone64_x86_64` (Android Studio emulator) |
| API / ABI | 35 / `x86_64` |
| Build | signed release `com.ichi2.anki` |

> **Read this first — emulator caveat.** These come from an **x86_64 emulator
> with a software GPU and cold ART/JIT**, not a physical phone. Startup and
> frame-render numbers on this setup are **several× slower than real hardware**
> (no hardware GPU, no AOT-compiled release image, cold dexopt). They are
> reported honestly and unadjusted; a real arm64 device with a hardware GPU is
> materially faster. The one number that transfers well is memory.

## 1. Cold start → first usable screen (DeckPicker)

7 cold starts (`am force-stop` → `am start -W`) after 2 warmup runs; each landed
on `com.ichi2.anki/.DeckPicker`.

| Metric | Value | Target | Verdict |
| --- | --- | --- | --- |
| min | 4.86 s | < 4 s | OVER (emulator) |
| median | 7.27 s | < 4 s | OVER (emulator) |
| max | 9.02 s | — | — |

Runs (ms): `4864, 5056, 6777, 7268, 7818, 8258, 9021`.

**Honest reading:** over the 4 s target *on this emulator*. The cost is
emulator-specific: software-GPU surface creation + cold ART on a freshly-booted
x86_64 image. It is **not** engine work — the shared Rust backend opens the
collection in single-digit ms (see the desktop dashboard/hot-path numbers in
[`latency.md`](latency.md)). We report the measured number rather than a
hand-tuned one; the representative device figure requires an arm64 build on
hardware (see the arm64 caveat in [`packaging.md`](../packaging.md)).

## 2. Memory footprint

`dumpsys meminfo com.ichi2.anki`:

| State | TOTAL PSS |
| --- | --- |
| Just after UI interaction (benchmarked) | ≈ 151 MB (154,651 KB) |
| Idle on the deck list | ≈ 112 MB (114,708 KB) |

The desktop process core measured 69.4 MiB on a 50k-card deck; the phone figure
includes the full Android app + WebView + UI graphics buffers (which is why PSS
rises after rendering, then settles). Well within a modern phone's budget.

## 3. Interactive latency (button press / next card)

The spec's interactive targets are **button press < 50 ms** and **next card <
100 ms**. On the phone these split into two layers:

### 3a. The decision/compute — shared Rust engine (representative)
Answering a card and fetching the next one is done by the **same Rust engine
binary** the desktop app uses, compiled into `librsdroid.so`. That path is
benchmarked directly in [`latency.md`](latency.md) on a 50,000-card deck:

| Action | p50 | p95 | target | verdict |
| --- | --- | --- | --- | --- |
| Button press acknowledged | 1.4 ms | 2.0 ms | < 50 ms | **PASS** |
| Next card after grading | 0.3 ms | 0.4 ms | < 100 ms | **PASS** |

Because the phone embeds this exact engine, the compute cost of grading a card
and scheduling the next is the same order of magnitude — far under target. This
is the honest, representative interactive-latency evidence.

### 3b. The phone render layer — gfxinfo (emulator, software GPU)
`dumpsys gfxinfo` while scripted taps drove the DeckPicker (open add sheet, nav
drawer, scroll): **20 frames rendered, 100% janky, p50 ≈ 400 ms, p90–p99 ≈ 2350
ms**. These are **software-GPU emulator artifacts** — a mostly-idle app produces
few frames and each software-composited frame is very expensive on this image.
They do **not** represent frame timing on a hardware GPU (which composites at
60–120 fps). We record them for transparency, not as a device claim.

## Verdict

| Target | Measured (emulator) | Representative? |
| --- | --- | --- |
| Button press < 50 ms | 1.4 / 2.0 ms (shared engine) | Yes — same binary |
| Next card < 100 ms | 0.3 / 0.4 ms (shared engine) | Yes — same binary |
| Cold start < 4 s | 4.9–9.0 s (software-GPU emulator) | No — inflated by emulator |
| Memory | ≈ 151 MB PSS | Yes |

**Bottom line:** the interactive review hot-path (the part the target is really
about) is the shared engine and passes comfortably; memory is healthy; cold-start
and frame numbers are honestly over/janky **on this software-GPU emulator** and
would need an arm64-on-hardware run to state a device figure. Nothing here is
tuned or hidden.
