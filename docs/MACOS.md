# Apple Silicon Mac preview

The `feature/macos-preview` branch adds CineVerse Mac Preview **0.7** as a separate application (`com.cineverse.desktop.macos`). The published Windows releases and their engine directories remain separate. This is an experimental port, not a claim that all Mac models or whole movies have been validated.

## Supported scope

| Item | First Mac preview |
|---|---|
| Hardware | Native Apple Silicon arm64; M1 and newer |
| Operating system | macOS 14 or later; Intel and Rosetta setup refused |
| Default processing | CPU, software H.264, SDR input, original frame rate |
| Optional GPU | Apple MPS, explicitly selected and experimental; unsupported operations may fall back to CPU |
| Stereo | Full left/right SBS; default depth 1.5 and neural gap filling |
| Resolution | At most 1280 pixels per eye; depth inference resolution 392 |
| HDR / 60 FPS | Not implemented on Mac; rejected before conversion rather than silently changing the requested format |
| Thermal supervision | Apple's system thermal state, not Celsius or individual CPU/GPU temperatures |
| Distribution | Ad-hoc development signing; **not Developer ID signed or notarized** |

The MPS backend is supported by [PyTorch on Apple Silicon](https://developer.apple.com/metal/pytorch/) and the pinned iw3 engine. Availability alone does not establish this adapter's speed, numerical quality, memory use or stability. Automatic mode intentionally selects CPU on Mac until physical-Mac inference has been tested.

## Setup and use

1. Use the Apple Silicon app build. An installed copy belongs in a writable user application location; the engine is kept outside the app bundle.
2. Open **Engine settings**, leave **Automatic** selected and choose the engine's destination if desired. Allow at least **8 GiB free for setup**, plus substantially more temporary/output space for videos.
3. Review the component notices and select the download consent checkbox. **Install engine automatically** downloads a private Python 3.12 runtime, native arm64 wheels, pinned engine code, FFmpeg/FFprobe and verified model weights. It saves paths automatically. End users do not need Python, Git, Homebrew, PawnIO or an administrator sensor helper.
4. Drop an authorized **SDR** video, choose the output folder and generate a short preview. Check the SBS result in your VR player before considering a longer conversion.
5. MPS is an explicit experimental processing option. If unavailable, the app reports the error; choose CPU. A per-operation CPU fallback is enabled for supported MPS runs and is not a promise of GPU speed.

The default engine is under `~/Library/Application Support/CineVerse/Engines/0.7-macos`. A selected destination is also supported. Temporary files, packages, model files and settings stay outside the application bundle. Model/engine notices remain in their respective directories. Setup, relaunch and recovery never start conversion automatically.

## System thermal supervision and cancellation

The worker reads Foundation `ProcessInfo.thermalState` using the built-in JavaScript bridge in `/usr/bin/osascript`. Nominal and Fair can arm protection. Serious or Critical cannot start a conversion. During processing, Critical stops immediately, Serious for 10 seconds stops the job, and missing valid readings for 30 seconds stops it. Polling is approximately every two seconds plus the sensor-read timeout. There is no automatic restart.

The monitor runs outside the converter. Each converter has a private Unix process group; cancellation and thermal stops verify the process identity before terminating that group. A parent-exit watcher stops descendants if their supervising parent disappears. macOS uses lower process priority and library thread limits; it does **not** enforce the Windows two-core affinity policy. A `caffeinate` assertion is held during app-driven conversions.

System thermal pressure is not a component temperature measurement and cannot guarantee hardware safety. No overheating is induced in validation. The preview does not install kernel drivers or change Gatekeeper, quarantine, SIP or macOS security settings.

## Build and reproduce on a Mac

Developer prerequisites: native arm64 macOS 14+, Xcode command-line tools, Rust, Node.js 22 and Python 3.12 for source tests. The app's end-user bootstrap does not depend on that developer Python.

```sh
npm ci
python3.12 -m unittest discover -s tests -v
npm test
npm run format:check
npm run build
cargo test --manifest-path src-tauri/Cargo.toml --locked
npm run tauri -- build --config src-tauri/tauri.macos.conf.json --bundles app,dmg
```

The `.app` and `.dmg` are produced under `src-tauri/target/release/bundle`. Run the same bounded packaged-bootstrap test as CI:

```sh
APP="$PWD/src-tauri/target/release/bundle/macos/CineVerse Mac Preview.app"
ENGINE="$HOME/CineVerse-Mac-QA"
codesign --verify --deep --strict "$APP"
PATH=/usr/bin:/bin:/usr/sbin:/sbin "$APP/Contents/MacOS/cineverse-setup-preview" --setup-engine "$ENGINE" cpu
"$ENGINE/environments/desktop-v07-macos/bin/python3" examples/ci_macos.py "$ENGINE" "$APP/Contents/Resources"
codesign --verify --deep --strict "$APP"
```

Use a new QA engine directory for the synthetic fixture generator. It refuses to overwrite its source fixture. The helper generates a three-second, **three-frame, 1 FPS** color test pattern with audio, runs the packaged CPU worker with real models and live system thermal-state readings, and checks frame count/timestamps, source preservation and prepared audio. It also terminates a disposable process tree while preserving another process and refusing a stale identity. This small fixture validates integration; it is not a movie-quality or throughput benchmark. Private videos/logs stay in the engine directory. The sanitized summary is written to `macos-smoke-summary.json`.

## Distribution and remaining validation

The [macOS workflow](../.github/workflows/macos.yml) builds and tests on a hosted Apple Silicon runner. Native app launch, dialogs, folder access, external SBS playback, MPS inference, sleep/wake and long-job behavior still need testing on a physical Mac. A hosted CPU smoke test cannot establish VR comfort or visual quality.

This development build is ad-hoc signed. `codesign --verify` establishes bundle integrity, **not** Apple notarization or Gatekeeper acceptance. A smooth public download needs a Developer ID signing identity, the appropriate hardened-runtime configuration and Apple notarization; follow [Tauri's macOS signing guide](https://v2.tauri.app/distribute/sign/macos/). No signing account or credentials are included. Do not bypass macOS security to treat this preview as a notarized release.

FFmpeg 6.1.1 arm64 executables and their license/README are downloaded from the pinned [ffmpeg-static release](https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1), separately from the app. SHA-256 hashes and upstream references are in `requirements/engine-manifest.json`. Python dependencies have their own Mac snapshot. See [third-party notices](../THIRD_PARTY_NOTICES.md); the application's MIT license does not relicense these components.
