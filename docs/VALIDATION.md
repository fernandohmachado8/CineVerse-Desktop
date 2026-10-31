# Validation — 31 October 2026

This standalone repository extracts the desktop converter from the larger CineVerse workspace. The existing application, source repository and movie exports were left intact. Evidence below separates source checks, native hardware runs and untested deployment claims.

## Local checks

| Check | Evidence |
|---|---|
| Desktop Python tests | 37 passed, including Windows disposable-process stop/cleanup tests |
| Distribution helper tests | 6 passed: pinned assets, side-effect-free plan, traversal/symlink refusal, good archive extraction, bad hash refusal and cached hash reuse |
| React tests | 14 passed for preview/full separation, presets, cancellation/errors, sensor gating, helper activation and setup |
| Legacy thermal tests | 14 passed on Windows; disposable targets only |
| Dependency installation | `npm ci` succeeds with no reported vulnerabilities; formatting checks pass; Python snapshot wheel availability checked with pip dry-run, not a fresh full-engine install |
| Engine plan/check | Plan emits pins without installing; existing configured RTX 4090 engine passes CUDA/neural/RIFE and synthetic NVENC checks |
| TypeScript/Vite | Production build checked locally |
| Windows binary | Standalone Rust MSVC/NSIS 0.4.0 build passed locally; installed original app was not replaced |
| Publication | Git-index audit rejects private paths/tokens, unregistered binary assets, weights and local settings |

**71 tests total** in the standalone local suite: 43 Python tests, 14 React tests and 14 Windows legacy watchdog tests. Linux CI skips the three Windows-only process tests; the Windows job runs them. CI does not have the test machine's CUDA GPU or CPU sensor.

## Measured native behavior

Before extraction, desktop 0.4 was tested on Windows with an i9-14900KF, RTX 4090, CUDA PyTorch 2.11.0+cu128, iw3 and RIFE 4.25. These are historical local measurements of the code being extracted, not GPU work performed by GitHub Actions.

- A three-second HDR10/60 FPS window completed through the packaged worker in 47.97 seconds: 181 frames, 3840×832, first PTS 0, last PTS 3.0 and zero frame-grid error. Fractional-rate preparation accounts for the small duration extension. HDR10 metadata, prepared audio, sampled source integrity, source-eye samples and 14-row compatibility margins passed.
- Its 22 active thermal samples were all available: CPU 72–85 °C and GPU core 39.71–62.53 °C.
- A second three-second preview was launched through native app controls. The UI moved from Ready to arm → Monitoring → Your stereo video is ready. The saved request confirmed preview mode, duration 3, depth 1.5, neural filling and 60 FPS. All 20 active samples were ready: CPU 73–86 °C, GPU core 39.88–60.36 °C. Output had 181 verified frames.
- Native engine discovery found eight components with Advanced paths collapsed. CPU-helper activation and startup without readings were exercised. Closing the app ended its bound CPU reader.
- Two startup faults were fixed: extended Win32 resource paths were normalized for normal PowerShell signing semantics, and helper-launch IPC pipe inheritance was suppressed so the app can receive startup completion. No execution-policy/security setting was changed.

The source and output of those private film tests are not included. No film imagery or source filenames are used as portfolio assets. The original wider workspace had 31 additional reconstruction tests, but those are **not counted** as tests of this standalone repository.

## Reproduce without copyrighted footage

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s thermal -v
npm ci
npm test
npm run build

# Optional: Pillow is needed only to generate original synthetic assets.
python -m pip install -r requirements/test.txt
python examples/generate_fixture.py --video "PATH_OUTSIDE_REPO/synthetic.mp4" --ffmpeg "PATH_TO_FFMPEG"
```

Configure the Windows engine, enable CPU sensing and wait for Ready to arm. Select the generated local video, choose a three-second preview and Generate preview. Inspect the final report and private job's `protection.jsonl`. Do not call the internal `convert` child mode directly or start a full movie as a test.

![Original analytical SBS fixture](assets/synthetic-preview.gif)

This is a directly rendered analytical stereo fixture, **not an AI conversion result**. Its source generator and asset hashes are committed. It is suitable as a deterministic input and illustration; it does not establish real-world depth accuracy.

## Limits and remaining work

A new clean Windows machine, unattended overnight operation, other CPU/GPU models, whole-film neural visual quality, VR comfort and every scene cut have not been certified. The dependency helper's safeguards and existing-engine check are tested; a complete fresh dependency install is not claimed. Native inference tests are distinct from CPU-only CI. Temperature cutoffs are simulated in disposable-process tests; hardware is not deliberately overheated. Software polling cannot guarantee hardware safety or monitor GPU VRAM/hotspot temperatures.

The project is an experimental portfolio application with measured capabilities and explicit limits, not a production certification or a new model-research claim.
