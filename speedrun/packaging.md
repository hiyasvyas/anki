# Packaging & Clean-Device Proof (Sunday: ship both builds)

This covers the Sunday hand-in items **"a packaged desktop installer and a packaged
phone build"** and the hard-limit **"either app does not run on a clean device →
50% max."** Both apps must also **run with AI switched off and still give a score**
(currently trivially true — the score RPCs never call any AI service).

Status legend: [x] done · [~] in progress · [ ] pending.

---

## 1. Desktop installer (Windows)

The fork already ships an installer recipe (Briefcase-based, see `qt/installer/`):

```powershell
# from repo root C:\dev\speedrun\anki
just installer            # -> ninja installer:package -> out/installer/dist/
```

Output: a packaged installer under `out\installer\dist\` that runs on a clean
machine (no dev toolchain required).

- [ ] Build the installer with `just installer` (heavy build — must NOT run while
  the shared-env build is in progress, to avoid cargo/ninja lock contention).
- [ ] Verify the artifact exists in `out\installer\dist\` and record its version +
  SHA-256.
- [ ] **Clean-machine install recording**: on a fresh Windows VM / clean user
  account with no Anki dev tools, run the installer, launch the app, import the
  MCAT deck, review a card, and open the readiness/mastery dashboard. Capture a
  screen recording. Save under `speedrun/proof/desktop-install.<ext>`.
- [ ] **AI-off proof (desktop):** with any AI feature/service disabled or
  offline, confirm the app still launches and the memory/readiness score renders
  (or the honest abstain message shows when below the give-up thresholds).

### Reference machine + reported numbers
State the reference machine (CPU/RAM/OS) alongside the recording so the §10 speed
and memory numbers are interpretable on the same hardware. The latency harness
(`speedrun/bench/latency.py`) already records the reference machine in its
output; current numbers on a 50k-card deck live in `speedrun/proof/latency.md`
(Intel i7-8xxxU class, 8 GB RAM, Windows 11). See that file for p50/p95/worst
per action plus the honest over-target dashboard finding + optimization path.

---

## 2. Phone build — signed release APK (AnkiDroid)

Repo: `C:\dev\speedrun\Anki-Android` (Kotlin UI) consuming `librsdroid.so` built
from this fork's shared Rust engine via `C:\dev\speedrun\Anki-Android-Backend`.

> **Sequencing:** the final signed APK must be built **after** the mobile-UI
> agents land the pace-timer / per-topic-mastery / three-score panels, so the
> shipped build contains the finished companion UI. The signing pipeline below is
> prepared now; the release build itself is the last step.

### Signing pipeline (prepare now, build last)
- [ ] Generate a release keystore (one-time, keep OUT of git):
  ```powershell
  keytool -genkeypair -v -keystore speedrun-release.jks -alias speedrun `
    -keyalg RSA -keysize 4096 -validity 10000
  ```
  Store the keystore + passwords outside the repo (e.g. a local secrets path);
  never commit `.jks` or credentials.
- [ ] Add a `signingConfig` to `AnkiDroid/build.gradle` reading the keystore
  path/passwords from `local.properties` or env vars (NOT hard-coded). Wire the
  `release` (or a `speedrunRelease`) build type to use it.
- [ ] Build the signed APK (x86_64 + arm64 as feasible for a real device):
  ```powershell
  cd C:\dev\speedrun\Anki-Android
  .\gradlew :AnkiDroid:assemblePlayRelease   # or assembleFullRelease
  ```
- [ ] Verify signature: `apksigner verify --verbose <apk>` (or `jarsigner
  -verify`). Record the APK path + SHA-256.
- [ ] **Clean-device install recording**: on a fresh emulator/device (or a device
  with the app uninstalled), `adb install` the signed APK, load the MCAT deck,
  run a review session, and show the three scores / give-up rule. Save under
  `speedrun/proof/phone-install.<ext>`.
- [ ] **AI-off proof (phone):** with the network pulled / AI disabled, confirm the
  companion still reviews and still renders a score (or the abstain message).

---

## 3. Sunday proof checklist (both apps)

- [ ] Desktop installer artifact + clean-machine install recording.
- [ ] Signed phone APK + clean-device install recording.
- [ ] Both apps demonstrably run with AI off and still give a score.
- [ ] Sync-conflict correctness already documented in
  [`sync-test.md`](sync-test.md) (mtime-wins; reviews append-only, none
  lost/doubled).

## Notes / honesty
- The current committed AnkiDroid artifact
  (`speedrun/AnkiDroid-mcat-localbackend-x86_64.apk`) is an **x86_64 debug**
  build for the emulator. The Sunday deliverable requires a **signed release**
  build — tracked above, gated on the mobile-UI work.
- Nothing in the scoring path calls an AI service, so "runs with AI off" is a
  matter of confirming graceful degradation of the (separately-built) AI card
  features, which are owned by the AI workstream.
