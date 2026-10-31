# Automatic engine setup (0.6 preview)

Install the Windows app, open **Engine settings**, choose **Install engine automatically**, and let setup finish. Normal users do not need Python, Git, a compiler or dependency path configuration. Internet access is required for the first setup.

1. Keep **Automatic** selected, or choose CPU/NVIDIA explicitly.
2. Keep the default engine location, or choose another drive. Allow at least **15 GiB** free, plus space for converted movies. Downloads, pip caches, temporary package files, models and the runtime stay on that chosen drive.
3. Check the download/license acknowledgment and start installation. The app shows stage progress, verified-file download progress and expandable package logs. Large package stages can be indeterminate; no invented completion time is shown.
4. On success the app saves every engine path and checks imports and encoding. Choose a video and run a short preview.
5. Enable CPU sensing before conversion. If PawnIO is missing, choose **Open signed CPU driver installer**, complete its normal Windows approval/installer, then enable sensing. The app never approves UAC or installs a kernel driver silently.

The installer provisions WebView2 when needed. NVIDIA display drivers remain the user's responsibility. Automatic setup tests NVENC before choosing the GPU package; if the installed CUDA runtime cannot initialize, it selects CPU compatibility before conversion. CPU mode supports SDR/original FPS with software H.264; it does not promise fast whole-film processing. NVIDIA mode retains HDR and optional 60 FPS smoothing.

If the official RIFE model cannot be fetched or verified, the core engine remains usable at Original FPS. A visible warning explains that smoothing was not installed. No duplicate-frame or SDR substitute is produced silently.

## What is installed

| Component | Source and handling |
|---|---|
| Private CPython 3.12.16 | Pinned Astral python-build-standalone archive; official release SHA-256; no system Python/PATH/registry installation |
| PyTorch / torchvision | Selected official CPU or CUDA wheel index, exact versions |
| Python packages | Pinned binary wheels; no compiler needed; isolated pip configuration and a private download cache |
| iw3, depth adapter and optional RIFE code | SHA-256-checked archives of exact upstream commits; no Git installation |
| Depth/filling/cut model files | Recorded original URLs and SHA-256 hashes |
| FFmpeg / sensor library | Recorded versioned archives and SHA-256 hashes |
| PawnIO installer | Separate original signed 2.2.0 executable, hash checked before launch; always interactive |

Runtime and asset hashes come from upstream release metadata where available; source ZIP hashes are locally measured at the recorded commits. Python package wheels are version-pinned and fetched over TLS from their package indexes; the project does not currently provide a complete wheel hash lock. Every dependency retains its original license and notices. See [third-party notices](../THIRD_PARTY_NOTICES.md) and [the manifest](../requirements/engine-manifest.json).

The application downloads dependencies after an explicit user action. No movie is uploaded or converted during installation. The core application and engine do not run as administrator; only the optional signed driver installer and read-only CPU sensor helper request their necessary approval.

## Retry, cancellation and existing installations

A managed-folder marker binds the private runtime. Setup refuses a foreign nonempty folder or another runtime version. Transient asset downloads retry up to three times with checksums still required. Verified downloads, completed source installs and completed package stages are reused on retry; incomplete downloads/stages restart. It does not delete movie files or replace the existing 0.4/0.5 installations.

Only one setup can use a managed folder at a time. Conversion and installation cannot run concurrently in one app. Closing the app or cancelling setup stops the owned installer process tree; a Windows job object also cleans up descendants if the host exits. CPU/GPU conversion temperature protection remains independent and mandatory according to the selected profile.

The new executable, identifier and installer are **CineVerse Setup Preview**, separate from the preserved baseline. No full-movie conversion is part of testing this feature.

## Reproduce the packaged bootstrap

The installer contains the same setup resources used by the app. Its setup-only CLI is intended for QA; normal users use the button:

```powershell
& "PATH_TO_INSTALLED_APP/cineverse-setup-preview.exe" --setup-engine "D:/CineVerse-QA/Engine" cpu
```

Use a new empty engine folder. This provisions its private runtime, invokes the pinned installer and checks the engine without starting conversion. A successful run leaves `engine.json`, `setup-result.json` and a private `setup.log` in that folder. The app's first-run flow additionally saves that configuration automatically.

For developer source checks:

```powershell
npm ci
npm test
npm run build
python -m unittest discover -s tests -v
python -m unittest discover -s thermal -v
cargo test --manifest-path src-tauri/Cargo.toml --locked
npm run tauri -- build --bundles nsis
```

Building requires the normal Tauri developer tools; installing the resulting app does not. The manifest's dependency installer can also be invoked manually with Python 3.12; it now uses verified source archives instead of Git.

## Validation scope

See [validation](VALIDATION.md) for measured installation and preview results. The native first-run flow saved and selected a freshly provisioned CPU engine after recovery tests. A fresh private engine on the development workstation is different from a clean Windows VM or a broad laptop certification. The workstation already has WebView2, an NVIDIA driver, compiler tools and an approved PawnIO driver; bootstrap testing must not be presented as proof that those absent-system cases have all been exercised.
