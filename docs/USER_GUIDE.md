# First run with automatic setup (0.6 preview)

Install and open **CineVerse Setup Preview**. In Engine settings keep Automatic, choose the engine drive if desired, acknowledge the component downloads and click **Install engine automatically**. All dependency paths are saved after validation. No system Python or Git is needed. Enable CPU sensing before conversion; if PawnIO is missing, open the original signed driver installer from the protection panel and handle its normal Windows approval. See [automatic setup](AUTOMATIC_SETUP.md).

# CineVerse Desktop 0.4

Windows desktop converter with integrated CPU/GPU temperature supervision and bounded local engine discovery for this configured NVIDIA PC: source HDR10 preservation, preferred depth 1.5 with neural gap filling and optional true 60 FPS interpolation, NVENC export, preview, and recovery of completed stages. Earlier reconstruction experiments remain separate from this standalone desktop repository.

## Use

1. Open CineVerse Desktop. The local engine is detected from its portable settings or the known `CineVerse/engine.json` path on a fixed drive. The Engine settings screen offers **Find installed engine** and **Locate engine folder**, an eight-component found/missing checklist, and collapsed **Advanced paths**. Valid custom paths are preserved; missing or stale paths can be repaired from the selected installation. No machine-specific paths are committed.
2. Click **Enable CPU sensor**, approve the read-only helper's Windows administrator prompt, and wait for fresh CPU and GPU readings and **Ready to arm**. This is required again after closing/reopening the app. The default is **CPU + GPU**; GPU-only mode requires an explicit selection and shows that CPU temperature is unmonitored. No conversion starts during setup.
3. Drop/select a local video, or paste its path. HDR10 sources retain BT.2020/PQ and 10-bit HEVC. SDR sources produce H.264 SDR.
4. Depth starts at **1.5**, gap filling at **Neural**, motion at **60 FPS**. Fast (the previous gap-filling method) and adjustable strength remain available. Original FPS remains available. These preferences reflect local VR tests, not a universal comfort setting.
5. Choose a short preview and start position. A three-minute quality-test option is available. **Generate preview** always processes only that window; **Convert full video** processes the whole input independently of preview settings.
6. Check the full-video workspace budget, free space, approximate processing time and output-size range. Estimates vary with footage. Large source videos may require hours.
7. Open the completed file's folder and play it in Bigscreen with normal **SBS**, left eye first.

The app keeps Windows awake while its worker runs, without changing global power settings. Closing the app or cancelling stops the worker tree. Completed stages can be recovered from the output folder on the next launch; an interrupted stage restarts. Keep the app open and the PC powered during conversion. No full-movie job is auto-started on launch or recovery.

Neural gap filling uses the official iw3 `forward_inpaint` method and `light_inpaint_v1` image/video models. Missing pixels contain generated texture, not recovered footage; filled areas can soften or flicker. Short VR comparisons support this preferred preset, not universal full-movie visual reliability. First use may download the official model weights into the configured cache. The preflight uses a slower estimate for neural processing.

## Integrated temperature protection

The UI displays live temperatures and readiness. **Ready to arm** means valid required readings are available; **Monitoring** means the per-conversion supervisor is active. Conversion and Resume are blocked without the required readings. The backend independently checks them again before launching the converter, even if a UI reading was previously valid.

| Sensor | Sustained cutoff | Immediate cutoff |
|---|---|---|
| Hottest available CPU temperature | 95 °C for 10 seconds | 100 °C on a reading |
| CUDA GPU core, bound by UUID | 85 °C for 10 seconds | 90 °C on a reading |

Required readings missing for 30 seconds after arming also stop the conversion. CPU samples older than six seconds are rejected. Polling is approximately every two seconds plus GPU query overhead; this is software supervision, not an instantaneous hardware cutoff. GPU-only mode does not monitor CPU limits. GPU core readings do not measure VRAM or hotspot temperatures. These defaults were tested on the i9-14900KF / RTX 4090 machine; they are not a hardware-safety guarantee.

Only the CPU reader runs elevated, using the separately installed LibreHardwareMonitor library and signed PawnIO driver. The converter and app remain unelevated. The helper is bound to the app's PID and creation time and exits when that instance closes. No execution-policy or Windows security settings are changed. A normal local path is used for PowerShell rather than Tauri's extended Win32 resource path. If a managed PC requires signed scripts, respect that policy and obtain an approved signed helper; the app does not bypass it.

A separate Python supervisor owns the converter's process handle and a Windows job object. It checks limits independently of the renderer, terminates only that converter tree, and closes the tree if the supervisor fails. Thermal stops appear as an app error and are recorded in the private job folder's `protection.jsonl` and `thermal-stop.json`. Existing source/output files remain untouched. Completed stages remain recoverable; the interrupted stage restarts. Resume always requires a manual action and new valid sensor checks. Nothing resumes automatically after a thermal stop.

The standalone watchdog scripts in `thermal/` remain available for legacy jobs; do not also attach them to a conversion already monitored by 0.4.

## Fidelity and compatibility

HDR10 (10-bit BT.2020/PQ) is preserved through floating-point HDR interpolation and Main10 encoding. HLG, Dolby Vision preservation, anamorphic inputs and rates outside 1–60 FPS are rejected. RIFE 4.25 is experimental on HDR PQ imagery; it is not an HDR-specific model. Intermediate motion and the right eye are synthesized. Scene-cut guards reduce blending; missed cuts, hands, hair and occlusions still need visual review.

The video is normalized to the source average frame rate and scaled to at most 1920 pixels per eye. The first audio stream is downmixed to AAC stereo; additional audio tracks and subtitles are omitted. This is not bit-identical source preservation or a walkable 360-degree scene.

Before the final NVENC encode, explicit black compatibility margins align the frame height to 64 rows. The tested 804-row movie image becomes an 832-row frame with 14 black rows above/below; no movie rows are cropped or resized by this padding. The padding is applied before final encoding and avoids a diagnostic re-encode. HDR mastering/display metadata is retained in the elementary HEVC stream, not just the container.

The embedded WebView may not preview MKV/HEVC on every Windows installation. An unsupported embedded preview does not block conversion; Bigscreen remains the viewing target.

## Long jobs and recovery

Each job has a private `.cineverse-jobs/<id>` folder in the selected output directory, containing `job.json`, stage hashes, logs and temporary files. Stages are preparation, scene analysis, interpolation when needed, stereo generation, metadata/audio finalization, and verification. Checkpoints are replaced atomically. Resume checks source identity, settings, pipeline version, completed-stage checksums and a live-process lock. Version 0.2 checkpoints retain their original fast method rather than inheriting the new default. Partial files are deleted only from the known generated names inside that private job folder. Existing finished files are never overwritten.

Recovery is **between stages**, not halfway through a stage. A cancelled multi-hour interpolation may need to restart interpolation, while completed preparation remains reusable. Do not move the source or delete saved job files before resuming. Successful publication removes the known large intermediate videos and retains reports/logs. Cancelled/failed jobs retain their temporary data for recovery.

The full conversion uses a complete source SHA-256 check before/after. To keep previews fast on large source movies, previews use sampled SHA-256 of start/middle/end plus file size and modification time; reports name that method explicitly. Every final output frame is decoded with NVIDIA hardware to verify frame count, dimensions and timestamps. Prepared audio hashes, HDR metadata, source-eye detail samples and black margins are also checked before publishing the unique finished MP4.

Temporary-space budgets are conservative: HDR/60 FPS currently reserves 24 MiB per second of selected footage, including intermediate copies and safety margin. The whole-movie action is disabled when the preflight budget does not fit. A disk-full or GPU failure leaves completed checkpoints recoverable. Final reports distinguish estimates from measured results.

## Local engine and packaging

The app bundles the interface and CineVerse Python adapters. It includes the supervisor and sensor-helper scripts, but uses the separately installed LibreHardwareMonitor/PawnIO sensor runtime, CUDA Python, official iw3, official RIFE 4.25, model cache, FFmpeg and FFprobe on this PC. It is not yet a self-provisioning clean-machine installer. The portable build keeps `portable.json` next to its executable to avoid AppData launch-context differences. Installed builds fall back to the per-user Tauri configuration and known local engine manifests on fixed drives. Settings contain local paths, never service credentials.

The shared engine configuration points to Python, nunif/iw3, FFmpeg/FFprobe, model cache, Practical-RIFE, official RIFE `train_log`, and an output folder. The source movie and models are not included in the repository or interface installer. Original dependencies and weights retain their licenses; see [third-party notices](../THIRD_PARTY_NOTICES.md).

The tested PC now uses an independent CPython/venv and copied dependency snapshot on its external drive; it no longer imports runtime packages from the Codex cache or working folder. The prior experiment environment is retained. The selected movie is remembered locally and re-probed at launch for preflight, but processing always requires an explicit action.

## Build and verify

Use Node.js, Rust MSVC, Windows C++ build tools/SDK and WebView2 (see the root README):

```powershell
npm ci
npm test
python -m unittest discover -s tests -p 'test_*.py' -v
npm run tauri -- build --bundles nsis
```

`worker/worker.py` accepts JSON on stdin (`config`, `request`) and modes `check`, `probe`, `plan`, `jobs`, `discover`, `thermal`, `sensor`, `run`. `sensor` requires the parent app PID. `run` is supervised; `convert` is an internal child command and must not be used to bypass supervision. Job progress is NDJSON; estimates during conversion describe the current pass. All child commands use argument arrays without shell interpolation. Only explicitly selected source/output files enter the asset scope. Single-instance handling prevents accidental duplicate application windows.

See [validation](VALIDATION.md), [dependency setup](DEPENDENCIES.md) and [third-party notices](../THIRD_PARTY_NOTICES.md). The installer is unsigned. A full film requires its own quality review and explicit launch.

## CPU compatibility preview

Choose **CPU compatibility** for Windows without NVIDIA. Use an SDR source and Original FPS; the app blocks HDR and smoothing rather than silently changing the source format. Output is at most 1280 pixels per eye. Enable CPU sensing before previewing. GPU-only protection is not available in this profile. Start with three seconds: CPU inference may take substantially longer than GPU inference. See [setup and limitations](COMPATIBILITY.md).
