# Subtitle preview validation — 2026-11-04

Scope: separate Windows 0.10.0 preview, based on the working 0.9 import/audio preview. No full-video conversion was requested or started for these checks. Original inputs, subtitle files, movies, private engine settings and logs are excluded from the source repository and installer.

## Automated checks

- 120 Python tests, including 15 subtitle tests: passed in the configured engine environment.
- 50 React interface tests, including subtitle selection, consent, source resets, recovery and stale file-picker callbacks: passed.
- 14 Windows thermal guard tests: passed.
- 10 Rust tests: passed.
- TypeScript, production Vite build, Prettier and whitespace checks: passed.
- Separate current-user installer: exit code 0; all 27 packaged resources matched the tested source, and the installed binary matched the compiled NSIS payload.
- Installed worker probe and planning: embedded Portuguese, external SRT and subtitle-off plans passed without starting conversion; accented track titles were retained correctly.

Installed executable hashes for 0.9, 0.8.1 and 0.4 remained unchanged. The new preview uses a separate application identity and private settings.

The numeric post-burn picture test requires NumPy/PyAV and skips in a stdlib-only test environment. It ran and passed locally. Thermal cutoff tests use simulated readings and disposable processes; the machine was not deliberately heated. These results do not establish support on untested physical AMD/Mac hardware.

## Short protected GPU tests

All cases used depth 1.5, neural filling, explicit subtitle burn-in and required live CPU/GPU monitoring on the RTX 4090 workstation.

| Case | Selected captions | Duration | Verified output |
|---|---|---|---|
| Original synthetic SDR fixture | Embedded Portuguese text track | 3 seconds | 72 frames, 24 FPS |
| Original synthetic SDR fixture | External UTF-8 SRT | 3 seconds | 72 frames, 24 FPS |
| Privately supplied compatible Dolby Vision source | Embedded English text, Japanese audio, HDR10 base | 3 seconds | 72 frames, approximately 23.976 FPS, Main10 HDR10 |
| Original synthetic SDR fixture with RIFE smoothing | External SRT | 3 seconds | 180 frames, 60 FPS |

Each test intentionally began during an already-active cue. Normalized captions retained that cue at preview time zero. For the synthetic fixtures, a later gap between cues was also checked: no caption was rendered during the gap. Source checksums remained unchanged. The HDR case retained Japanese audio and passed static HDR, timing, geometry, black-margin and prepared-audio verification.

A separately rendered caption mask was compared with both output eyes at a cue-active sample. All expected full-coverage glyph pixels matched the intended subtitle luminance within the test's encoding tolerance in both eyes: 174 mask pixels for Portuguese, 166 for external SRT, and 3,606 for the HDR sample. This checks presence and matching placement at a sample, not every glyph throughout a film or headset comfort.

Sampled upper-picture normalized luma error against the uncaptioned stereo image was below 0.00003 in all four cases. Required sensors remained available; sampled peaks across these previews were CPU 81 °C and GPU core 74.84 °C. No thermal stop was reported. These short runs are not an overnight-load certification.

## Renderer and timing regressions

Tiny original analytic fixtures verified that per-eye crop/subtitles/hstack retains native `yuv420p10le` without an 8-bit intermediate. The untouched upper region remained exact before encoding, and both caption halves matched. A real one-frame NVENC encode verified that explicit filter-frame `setparams` preserves BT.2020/PQ tags after hstack.

HDR gray RGB 148 produced caption fill near 201.5 nits in PQ code space. ASS inline white bypassed a simple force-style override, so this preview removes style/color/drawing overrides before rendering. Nonzero video timestamps and boundary-straddling cues were verified using full text extraction with `-copyts`, followed by overlap clipping; input seeking during extraction was rejected because it produced negative ASS timestamps.

Unicode track titles are decoded explicitly as UTF-8. A tested source title containing accented characters was initially misread under Windows' legacy code page; the probe now retains the correct title, with a regression test covering Portuguese and Japanese text.

## Limits and reproduction

See [Subtitles](SUBTITLES.md) for commands and format limits. No new VR headset comfort test, long-film visual certification, complex ASS style fidelity, font-attachment handling, bitmap OCR, selectable output subtitle streams, clean-machine installation certification or code signing is claimed. Source-eye fidelity is measured before the intentional text overlay; sampled post-burn checks do not establish full-frame perceptual equivalence.
