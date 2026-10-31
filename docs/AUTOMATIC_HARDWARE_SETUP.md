# Automatic hardware setup — Windows 0.8 preview

**Use 0.8.1 or newer.** Final installed-app testing found that Tauri's verbatim resource paths (`\\?\...`) made Windows PowerShell 5 reject the inventory script under the normal signing policy. Version 0.8.1 supplies the equivalent ordinary path to inventory and setup without changing execution policy. The original 0.8.0 release remains preserved but is superseded by this correction.

Install **CineVerse Automatic Setup Preview**, open Engine settings and keep **Automatic** selected. Choose an engine drive, accept the dependency-download acknowledgment and click **Install engine automatically**. Setup detects the CPU architecture, GPU models and installed driver versions using read-only Windows inventory. It installs private Python, the selected PyTorch runtime, video tools, pinned engine code and models, then saves every path. Users need neither Python nor Git nor a compiler.

The Windows installer installs the app and WebView2 when needed. First-run setup downloads the larger engine after consent; this is an online installer, not an offline bundle. Detection is local. No movie is uploaded, and installation never starts a conversion.

| Detected Windows hardware | Automatic choice | Conversion limits |
|---|---|---|
| Healthy NVIDIA adapter with working Main10 NVENC | CUDA package, followed by live runtime/import/encoder checks | Existing HDR10 and optional RIFE 60 FPS features |
| One allowlisted Radeon, Windows 11 desktop, eligible installed driver | Pinned official AMD ROCm package; live checks must pass | Experimental inference; software H.264, SDR, original FPS, up to 1280 pixels per eye |
| Intel/AMD x64 CPU without an eligible accelerated route | Private CPU-only PyTorch | Software H.264, SDR, original FPS, up to 1280 pixels per eye; slower |
| Unsupported AMD model, old/missing driver, multiple AMD adapters or failed GPU startup | Automatic CPU installation with the reason shown | CPU limits apply; no claim of GPU acceleration |
| Known Windows ARM / non-x64 processor | Setup stops with an architecture error | This Windows build is x64 only |

The pinned NVIDIA runtime is PyTorch 2.11.0 with CUDA 12.8. Its compiled support starts at **Turing (SM 7.5)**; RTX 20/30/40/50-series are expected candidates, subject to working drivers, NVENC Main10, available memory and the live startup check. Other cards have not been individually hardware-validated by this project. GTX 10-series and older cannot use this runtime and fall back to CPU in Automatic. See [PyTorch's version-specific architecture matrix](https://dev-discuss.pytorch.org/t/dropping-volta-support-from-cuda-12-8-binaries-for-release-2-11/3290) and [NVIDIA's encoder matrix](https://developer.nvidia.com/video-encode-decode-support-matrix). No minimum-memory performance guarantee is established by a tiny startup probe.

AMD CPU branding does not require ROCm. A Ryzen PC with NVIDIA can use CUDA, and a Ryzen PC without a supported GPU can use CPU PyTorch. Intel GPU acceleration, DirectML, AMF encoding and AMD RIFE/HDR are not implemented. The separate [Apple Silicon preview](MACOS.md) keeps its existing CPU/default and opt-in MPS behavior.

## AMD recipe and eligibility

This preview deliberately pins **ROCm 7.2.1, PyTorch 2.9.1+rocm7.2.1 and torchvision 0.24.1+rocm7.2.1 on Python 3.12**. This is a reproducible older recipe, **not the latest ROCm version**. The newer AMD package endpoint could not be retrieved reliably during development, so it was not silently substituted or called verified. The [official 7.2.1 installation instructions](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2.1/docs/install/installrad/windows/install-pytorch.html) and [version-specific support matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2.1/docs/compatibility/compatibilityrad/windows/windows_compatibility.html) define this recipe.

Only these exact normalized names can attempt automatic AMD setup: Radeon RX 9070, RX 9070 XT, RX 9060 XT, RX 7900 XTX, RX 7700, Radeon AI PRO R9700, PRO W7900 and PRO W7900 Dual Slot. Similar names, other products sharing an architecture, integrated graphics and APUs are not inferred to be supported. In particular, RX 7700 XT and RX 7900 XT are not on this recipe's list.

Windows 11 desktop and a reported driver-store version of at least **32.0.23027.2005** are required before attempting it. The minimum corresponds to Adrenalin 26.2.2 for RDNA 3/4 in AMD's [GPUOpen driver version table](https://gpuopen.com/version-table/). A later version is permission to **attempt** the pinned runtime, not a promise of vendor-certified compatibility with every later driver. No display driver is installed, upgraded or downgraded. If the installed driver is ineligible, CPU setup remains available.

Six AMD SDK/Torch artifacts are fetched from the official versioned AMD directory, with SHA-256 values in [the manifest](../requirements/engine-manifest.json). Those hashes were measured from downloaded official HTTPS bytes; they are not misrepresented as publisher-provided signatures. Exact upstream package licenses/notices are retained. Common Python wheels are version-pinned over TLS but do not yet have a complete per-wheel hash lock.

Allow **25 GiB free** for the AMD installation and possible CPU fallback, excluding movies and conversion workspaces; other Windows routes need at least 15 GiB. Downloads, caches, temporary files and virtual environments stay on the selected drive. A new private root `CineVerse/Engines/0.8-auto` preserves previous managed engines. Existing custom working paths remain usable.

## Startup proof and fallback

Before publishing `engine.json`, setup checks package consistency, imports Torch/torchvision and iw3, and runs tiny convolution, resize and integer scatter-reduction operations. AMD must expose exactly one live device whose normalized name and architecture match the detected allowlisted adapter. The worker then checks the selected encoder. These startup operations process no video and do not establish sustained inference performance or VR quality.

In **Automatic**, GPU package/startup failure installs and checks a separate CPU environment. The UI receives a visible fallback warning. A checksum mismatch stops setup instead of accepting the file or disguising the integrity failure as a successful fallback. An explicitly selected GPU package reports its failure; choose Automatic to request fallback. CPU startup failure does not publish a ready engine.

The private engine stores `hardware-detection.json`, `hardware-selection.json`, `runtime-check.json`, `setup-result.json` and setup logs for troubleshooting. They contain local hardware/path information and should not be published unredacted. A managed AMD engine is selected automatically later only while its recorded runtime version and single GPU name still match. Legacy/manual HIP environments remain CPU in Auto until validated by this setup.

## Temperature protection without path configuration

Once setup finishes, click **Enable CPU sensor** or **Enable CPU and Radeon sensors**. If the PawnIO driver is missing, the app opens the hash-checked signed installer, waits for its installation, and then requests the read-only helper. Complete the vendor installer and normal Windows approval prompts. Existing installed PawnIO drivers are detected through the Windows driver service, including DriverStore installations; they are not unnecessarily reinstalled.

These approvals cannot be bypassed by the app. Drivers/security policies are never silently changed. CPU compatibility requires fresh CPU readings; Radeon requires fresh CPU and matching Radeon core readings. Unavailable/ambiguous sensors block conversion. See [sensor binding and cutoff limits](AMD.md#radeon-temperature-binding). Software monitoring does not guarantee hardware safety.

## Reproduce and validation scope

Normal users use the buttons. Developer checks:

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s thermal -v
npm test
npm run format:check
npm run build
cargo test --manifest-path src-tauri/Cargo.toml --locked
npm run tauri -- build --config src-tauri/tauri.auto.conf.json --bundles nsis
```

The packaged executable also has read-only detection and setup-only QA commands, neither of which starts conversion:

```powershell
& "PATH_TO_APP/cineverse-setup-preview.exe" --detect-hardware
& "PATH_TO_APP/cineverse-setup-preview.exe" --setup-engine "D:/CineVerse-QA/New-Engine" auto
```

Validation records distinguish real package installation, simulated inventory and physical GPU execution. **No AMD PC is available to the developer. Radeon inference, AMD CPU operation, actual AMD sensor matching and sustained AMD load remain unverified.** AMD acceleration is an experimental community-testing route, not broad Radeon certification. A successful local startup should be followed by a short protected synthetic preview and playback check. Existing releases remain preserved; no full movie is part of this feature's tests.
