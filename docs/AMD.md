# Intel/AMD CPU compatibility and experimental Radeon integration

This branch provides a separate **CineVerse Hardware Preview** for Windows x64. Existing Windows and Mac releases remain unchanged. No AMD computer was available during development: **AMD CPU inference, Radeon inference and physical AMD temperature readings have not been verified**. Simulated device/sensor tests are explicitly separate from real hardware results.

## Profiles

| Hardware / profile | Behavior | Verification status |
|---|---|---|
| Supported Intel or AMD x64 CPU | Automatic setup can install private CPU-only PyTorch; software H.264, neural stereo, SDR/original FPS, 1280 pixels per eye maximum | Real CPU conversion tested on Intel; AMD CPU testing still needed |
| AMD CPU with NVIDIA GPU | NVIDIA profile uses CUDA/NVENC when available; CPU vendor does not select the GPU engine | NVIDIA regression tested on Intel/RTX 4090; AMD CPU/NVIDIA combination untested |
| Radeon GPU with ordinary CPU engine | CPU compatibility; the Radeon is not used or monitored | Safe default; not advertised as Radeon acceleration |
| Explicit AMD ROCm profile | Opt-in developer experiment on Windows 11, separately prepared official ROCm Python; AI inference requests device 0; software decode/H.264 encoding | Integration and safety fixtures tested; **no real AMD GPU execution** |
| Other/older GPUs or unsupported ROCm configurations | CPU compatibility, when CPU/Python/OS and required CPU sensors are supported | Not a promise of every old CPU, GPU or driver working |

The preferred stereo preset remains **depth 1.5 + neural gap filling**. CPU and experimental Radeon profiles reject HDR and 60 FPS smoothing before conversion. They do not silently tone-map HDR or duplicate frames. RIFE, AMF and Radeon HDR encoding are not integrated. Windows host processing is bounded to two logical CPUs with library thread limits and lower priority; GPU inference, where selected, is separate from that host limit. No Radeon completion-time estimate is borrowed from the RTX 4090.

## Easy setup for AMD PCs

Install the separate Hardware Preview, open Engine settings, and leave the installation package on **Automatic** or choose **CPU compatibility**. On a Radeon-only PC the NVIDIA encoder probe cannot select NVIDIA processing, so setup uses the CPU package. End users do not need to configure Python/model paths for this CPU route. The private default engine root is `CineVerse/Engines/0.7-hardware` under local application data; the existing `0.6` root remains separate.

CPU temperatures are read through the existing narrowly elevated LibreHardwareMonitor/PawnIO helper, which supports multiple CPU families. This application's reader does not restrict CPUs to Intel. Valid readings are nevertheless required: a missing/unsupported sensor blocks conversion rather than claiming protection. Modern Ryzen hardware needs testing by an AMD owner before support can be certified.

Selecting **AMD Radeon** in Processing is not an automatic ROCm installer. With CPU-only Python it reports that ROCm is unavailable and offers CPU compatibility. Automatic selection never mistakes a ROCm `torch.cuda.is_available()` result for NVIDIA CUDA or attempts NVENC/NVIDIA SMI on that device.

## Radeon hardware testers: prepare a separate engine

AMD's exact GPU, operating-system, driver and framework combinations vary by ROCm release. Use the current official [compatibility selector](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) and [PyTorch installation guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html) for **your exact Windows hardware**. Older Radeon/Ryzen documentation covers releases only through 7.2.1; do not treat that old list as the current support matrix. Sharing a GPU architecture does not establish support for every model.

1. First provision a working CineVerse CPU engine. Keep it intact.
2. Prepare a **separate Windows x64 Python 3.12 environment** using AMD's official ROCm/PyTorch instructions and supported driver. Retain the official licenses. Do not install ROCm wheels into CineVerse's working CPU/NVIDIA environment.
3. Install the application dependencies from `requirements/engine-win-py312.txt` in that separate environment, then run `python -m pip check`. This snapshot does not install Torch itself. Compatibility of a different ROCm/Torch release with the pinned iw3 engine is not certified; version/import/model failures must be reported, not bypassed.
4. With the **ROCm environment's Python**, run the linking helper from this repository. It checks the requested backend/software encoder and writes only a new engine manifest. It references existing FFmpeg, sensor, code and model assets, removes stale NVIDIA/sensor bindings, and never starts a conversion:

```powershell
python scripts/link_rocm_engine.py --base-engine "D:/CineVerse-CPU/engine.json" --root "D:/CineVerse-Radeon-Experiment"
```

5. In Hardware Preview, choose **Locate engine folder** and select the newly linked folder. Explicit folder selection replaces the previous engine's executable paths; automatic discovery still preserves valid custom paths. Enable **CPU and Radeon sensors**, handle the normal Windows approval, and wait for both readings. Choosing a different engine does not start a job.
6. Use a synthetic input and a three-second preview first. Keep the output separate from real movies. The bounded CLI helper uses the same thermal supervisor:

```powershell
python examples/run_smoke.py --engine "D:/CineVerse-Radeon-Experiment/engine.json" --video "D:/QA/synthetic.mp4" --output "D:/QA/Radeon-preview" --backend rocm --seconds 3
```

Run this helper with the linked ROCm Python. It generates no full movie and cannot run if protection fails to arm. Inspect the private report, conversion log and `protection.jsonl`; provide sanitized hardware/runtime details if reporting a problem. Do not publish your film frames, private filenames or settings as test evidence.

The CPU/NVIDIA lockfiles, model sources and hashes remain pinned. An AMD runtime has **not** been bundled, downloaded, hash-pinned or validated by this release; the separately prepared official runtime keeps its own terms. No ZLUDA bridge, unofficial wheel repository, DirectML substitution, driver downgrade or security-policy change is used. PyTorch's [HIP semantics](https://docs.pytorch.org/docs/stable/notes/hip.html) intentionally reuse the CUDA namespace; that does not make NVIDIA codecs usable on Radeon.

## Radeon temperature binding

The read-only Windows helper optionally enables LibreHardwareMonitor's AMD GPU reader. Its [pinned AMD implementation](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/v0.9.6/LibreHardwareMonitorLib/Hardware/Gpu/AmdGpu.cs) reports a `GpuAmd` adapter, `/gpu-amd/...` identifier and distinct **GPU Core** and **GPU Hot Spot** sensors.

The experiment requires exactly one visible ROCm device and one observed AMD adapter. Their full normalized model names must match; only capitalization, punctuation, optional AMD prefix and trademark markers are normalized. This is **single-device name matching, not PCI/UUID identification**. Multiple adapters, different model names, missing core readings, stale/future timestamps or invalid values block protection. A hotspot/memory reading cannot substitute for core temperature. A name-format mismatch must be investigated; do not rename devices or edit sensor JSON to bypass binding.

Both CPU and Radeon core readings are mandatory even if old settings requested GPU-only protection. CPU stops at 95 C for 10 seconds or 100 C immediately; GPU core at 85 C for 10 seconds or 90 C immediately. Missing valid required readings for 30 seconds stops the job. These are inherited conservative experimental limits, not AMD thermal specifications. The process supervisor terminates only the owned conversion tree. Actual AMD sensor mapping, sustained load and shutdown behavior still need physical-hardware validation; software monitoring cannot guarantee hardware safety or monitor all hotspot/VRAM risks.

## Development checks and remaining gate

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s thermal -v
npm test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml --locked
npm run tauri -- build --config src-tauri/tauri.hardware.conf.json --bundles nsis
```

The automated Radeon tests simulate HIP discovery, encoder selection, unsupported runtime/OS, ambiguous GPUs, fresh/stale sensor samples, wrong models, missing core temperatures and thermal cutoffs. They do **not** execute Radeon kernels or measure an AMD CPU. An AMD owner must still pass actual depth/neural-filling inference, source/timing/audio checks, physical sensor matching, short VR playback and sustained-load tests before Radeon acceleration is promoted beyond an experimental community-testing path. Automatic setup continues to favor the tested CPU route for other users.
