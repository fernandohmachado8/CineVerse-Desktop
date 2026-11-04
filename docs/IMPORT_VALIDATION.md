# Import preview validation — 2026-11-04

Scope: the unreleased Windows 0.9.0 import/audio preview, based on the working 0.8.1 release. Existing installed versions and their settings remain separate. These checks do not certify an entire movie's visual quality or every hardware configuration.

## Automated checks

| Check | Measured result |
|---|---|
| Python source tests | 105 passed, including 12 new import/audio tests |
| Windows thermal guard tests | 14 passed |
| React interface tests | 40 passed, including import consent, chosen audio, recovery and out-of-order source probes |
| Rust tests | 10 passed |
| TypeScript and production Vite build | Passed |
| Prettier and whitespace checks | Passed |
| Separate current-user Windows installer | Exit code 0; all 26 bundled source resources matched the tested source |
| Installed worker probe and plan | Compatible HDR10 base and Japanese track identified without starting a conversion |

The thermal tests stop disposable process trees using simulated readings; hardware was not deliberately heated to trigger a cutoff. Existing protection remains independent of the interface renderer. Resume coverage includes the exact saved HDR mode/audio request and compatibility with earlier saved-job defaults.

The installed executable matched the compiled binary after Tauri's documented NSIS bundle-marker replacement. SHA-256 checks of the working 0.8.1 and earlier 0.4 installed executables remained unchanged. The preview uses a separate application identity and private settings.

## Actual protected GPU preview

A privately supplied HEVC Dolby Vision Profile 8 source with compatibility ID 1 and five audio tracks was used locally. The input, clips, local settings and logs are excluded from the repository and installer.

- Request: a two-second preview, depth 1.5, neural gap filling, original frame rate, explicit HDR10-base mode, Japanese source audio at absolute stream index 5.
- Output: 48 decoded frames at approximately 23.976 FPS, 10-bit HDR10 SBS, AAC stereo with Japanese language and the chosen track's title retained.
- The temporary base copy retained the source video packet count/timing and static HDR metadata, and had no detected Dolby Vision configuration or first-frame RPU metadata.
- The original input's full SHA-256 remained unchanged after processing. The final pipeline also passed its frame/timing, source-eye detail, compatibility-margin, HDR and prepared-audio checks.
- Both required sensors stayed available. In the final repetition, sampled peaks were CPU 97 °C and GPU core 63.21 °C. The CPU reading did not meet the configured sustained 95 °C/10-second cutoff or immediate 100 °C cutoff; no thermal stop was reported. A release build was compiling concurrently, so these readings are not an isolated conversion benchmark.
- The bounded test completed in 47.84 seconds including full-input remuxing and validation. This does not estimate whole-movie conversion speed.
- No full-video conversion was started for this feature validation.

An earlier repetition also passed before a track-title mux metadata correction. The final repetition verifies the corrected output metadata. No new headset comfort test, perceptual-quality score, physical AMD/Mac test, clean-machine installation certification or signed/notarized release is claimed.

## Reproduce

Run the checks listed in [Import and audio](IMPORT_AND_AUDIO.md). For the GPU test, use a local video you are authorized to process, enable live CPU/GPU protection, select **Use HDR10 base**, choose the intended audio track, and generate a bounded preview. Compare the output report's `sourceImport`, `selectedAudio`, `sourceCheckPassed`, `preparedAudioPreserved` and `outputTimeline` fields. A matching input format is required; an incompatible Dolby Vision file must remain blocked.
