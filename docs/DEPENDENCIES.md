# Dependency setup

Application source and dependency manifests are included. Multi-gigabyte runtimes, model weights, codecs, drivers and media stay outside Git. They retain upstream licenses and attribution.

| Layer | Tested source/profile | Installation |
|---|---|---|
| UI | React 19, TypeScript, Vite, Tauri 2 APIs, Lucide | `package-lock.json`, `npm ci` |
| Native | Rust MSVC / Tauri 2 | `src-tauri/Cargo.lock` |
| Build prerequisites | Node 22+, C++ tools/SDK, WebView2 | Official Tauri prerequisites |
| Python | CPython 3.12 x64 | [python.org](https://www.python.org/downloads/windows/) |
| CUDA | PyTorch 2.11.0+cu128 / torchvision 0.26.0+cu128 | Official PyTorch wheel index |
| Python packages | Exact tested environment, including PyAV 19.0.1 | `requirements/engine-win-py312.txt` |
| Stereo | nagadomi/nunif | Exact Git commit in engine manifest |
| Depth adapter | nagadomi/Depth-Anything_iw3 | Exact Git commit in the expected Torch Hub cache |
| Depth | Depth Anything V2 Small | Official Hugging Face file + SHA-256 |
| Filling/cuts | iw3 light image/video inpainting, depth AA, row-flow fallback, TransNetV2 | Official iw3 files + hashes |
| Smoothing | Practical-RIFE / 4.25 model | Pinned code and official model ZIP |
| Codecs | FFmpeg/FFprobe 9.0.2 Gyan essentials | Versioned GPL build ZIP + release digest |
| CPU sensing | LibreHardwareMonitor 0.9.6 | Official ZIP + release digest |
| CPU driver | Signed PawnIO | User-installed separately |
| GPU driver | NVIDIA CUDA/NVENC-capable driver | User-installed separately |

`requirements/engine-manifest.json` records commits, URLs and hashes. Upstream release digests are distinguished from locally measured hashes. Local hashes detect changes; they are not independent signatures. A changed file fails verification rather than silently selecting another version.

## CPU compatibility preview

For Windows without NVIDIA, use `--profile cpu` in the commands below, with a new engine folder. This installs official CPU-only PyTorch/torchvision and omits RIFE downloads. CPU exports are SDR/original FPS only; see [compatibility](COMPATIBILITY.md). An NVIDIA driver is required only for the CUDA profile.

## Commands

```powershell
# Inspect only: no downloads or writes.
py -3.12 scripts/setup_engine.py --root "D:/CineVerse" --download-models

# Install into a NEW folder outside the source tree; allow at least 15 GiB.
py -3.12 scripts/setup_engine.py --root "D:/CineVerse" --install --download-models

# Check an existing engine without processing media.
py -3.12 scripts/setup_engine.py --root "D:/CineVerse" --check
```

Choose any drive with sufficient space. Movie workspaces need additional storage, budgeted separately by the app. The helper refuses to replace an existing engine manifest or a checkout at another revision.

If Google Drive is unavailable, download **4.25**, not lite or another model, from the [upstream list](https://github.com/hzwer/Practical-RIFE#trained-model). Add `--rife-archive "PATH_TO_OFFICIAL_4_25_ZIP"` to the install/download command. Both archive and extracted weights are checked. The tested environment does not use Practical-RIFE's old NumPy constraint; the application imports its required inference code.

The sensor archive includes PawnIO setup. Review its signature and install it interactively from upstream. Do not change Windows security to make it work. In the app select the engine folder, enable the CPU helper and approve its prompt. Managed signing policies must be respected. GPU-only mode explicitly leaves CPU temperature unmonitored.

## Manual configuration

`engine.json` fields: `python`, `iw3Repo`, `ffmpeg`, `ffprobe`, `cache`, `rifeRepo`, `rifeModel`, `sensorLibrary`, `outputDir`, `thermalMode`, `backend` (`auto`, `cuda`, `cpu`). The RIFE directory needs `flownet.pkl` and its Python inference files. `cache` becomes `NUNIF_HOME`; checkpoints are beneath `iw3/pretrained_models/hub/checkpoints`.

The app checks the selected backend and a small synthetic NVENC or software H.264 encode. First-use weights may be downloaded if omitted; `--download-models` prefetches recorded defaults. Inference is local; dependency downloads require network access.

## Distribution and validation

MIT covers the original application, not the entire engine. Keep upstream extracted notices and source references. See [third-party notices](../THIRD_PARTY_NOTICES.md).

A complete clean-machine installation has not been certified. The working workstation already had NVIDIA drivers, compiler tools and PawnIO. Planning, pins, archive traversal/hash safeguards and existing-engine checks are tested independently; this limitation is stated in the README rather than hidden.
