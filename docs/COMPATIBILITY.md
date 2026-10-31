# Windows compatibility preview (0.5)

This experimental build extends CineVerse to Windows x64 PCs without NVIDIA. It is isolated from the working 0.4 application by a separate executable name, application identifier, settings directory and installation folder. The `main` branch remains the 0.4 baseline while the preview is evaluated.

| Profile | Processing | Output | Current limits |
|---|---|---|---|
| Automatic | Probe CUDA and NVENC, otherwise choose CPU before conversion | Matches the selected profile | The selected backend is shown; no mid-job fallback |
| NVIDIA | CUDA depth/filling, NVENC | SDR H.264 or supported HDR10 HEVC; optional RIFE 60 FPS | Existing NVIDIA drivers, models and working thermal sensors required |
| CPU compatibility | CPU-only PyTorch, software decode/encode | SDR H.264, original frame rate, full SBS; at most 1280 pixels per eye | HDR and smoothing rejected explicitly; substantially slower; no GPU acceleration |

An AMD or Intel graphics card is not used by the CPU profile. This does not establish native AMD/Intel GPU acceleration. macOS, Linux, Windows ARM, unsupported instruction sets and low-memory machines are not certified.

## Setup

Install Windows x64 Python 3.12 and Git, then inspect the CPU plan:

```powershell
py -3.12 scripts/setup_engine.py --profile cpu --root "D:/CineVerse-CPU" --download-models
```

Execute it in a **new** engine folder:

```powershell
py -3.12 scripts/setup_engine.py --profile cpu --root "D:/CineVerse-CPU" --install --download-models
py -3.12 scripts/setup_engine.py --root "D:/CineVerse-CPU" --check
```

This selects official `torch==2.11.0+cpu` and `torchvision==0.26.0+cpu`, the pinned iw3/depth code, six checked model downloads, FFmpeg and the sensor library. It omits RIFE code/weights. No CUDA runtime or NVIDIA driver is required for CPU inference. The existing package snapshot still includes some optional packages; this is a compatibility preview, not a minimized installer. Allow 15 GiB for setup and additional output space.

Use **Locate engine folder**, select the new folder and select **CPU compatibility**. The signed PawnIO driver must still be installed interactively, and the read-only CPU helper needs administrator approval. Not all machines expose a supported CPU sensor. If readings are unavailable, CPU conversion is blocked rather than silently running unprotected.

Original app paths and saved movies are not replaced. Dependencies remain separate downloads with upstream licenses, as documented in [dependency setup](DEPENDENCIES.md). Planning or installation never starts conversion.

## Load and safety

CPU conversion is restricted to **two logical processors**, inherited by FFmpeg and iw3 child processes, with below-normal process priority. PyTorch uses two intra-op threads, one inter-op thread, batch size one and synchronous video inference. These limits trade speed for a bounded CPU workload; they cannot guarantee a temperature or universal compatibility.

CPU sensing is mandatory even if an old configuration selected GPU-only protection. CPU limits remain 95 C for ten seconds or 100 C immediately, with a 30-second sensor-loss cutoff. The CPU profile neither uses nor queries the GPU. Cancellation and supervisor failure terminate only the owned conversion process tree. GPU mode retains its existing CPU/GPU protection rules.

A first CPU test hit the immediate temperature cutoff and stopped. That exposed the need to constrain the whole process tree: library thread counts alone did not bound codec/helper pools. The revised two-processor profile is tested separately; see [validation](VALIDATION.md). Protection must stay enabled.

## Reproduce a bounded test

Generate an original synthetic video, then use a three-second preview in the app. Or run the same supervised worker with the engine's Python:

```powershell
python examples/generate_fixture.py --assets "D:/CineVerse-QA/assets" --video "D:/CineVerse-QA/synthetic.mp4" --ffmpeg "PATH_TO_FFMPEG"
& "D:/CineVerse-CPU/environments/desktop-v05-cpu/Scripts/python.exe" examples/run_smoke.py --engine "D:/CineVerse-CPU/engine.json" --video "D:/CineVerse-QA/synthetic.mp4" --output "D:/CineVerse-QA/cpu-result" --backend cpu --seconds 3
```

The helper has no full-movie option. It launches the normal temperature supervisor, saves NDJSON events and a result summary, and leaves conversion reports beside the output. Do not bypass protection by invoking the internal `convert` mode.

The source eye is compared with the prepared reference; encoding/resizing still change pixels. The generated right eye and neural gap filling are invented estimates, not recovered unseen footage. Original timing and prepared audio are verified. Short synthetic tests do not establish whole-movie quality or VR comfort.

## Preview status

A three-second 640x360/24 FPS synthetic preview passed in **160.531 seconds on CPU**; the NVIDIA regression took **17.360 seconds**. Both preserved 72 frames, prepared audio and source integrity. The CPU run had 77 valid thermal samples at 62-93 C. Only the tested Windows machine provides current hardware evidence. A CPU-only wheel environment proves that the test does not depend on CUDA; it does not prove good performance on a typical laptop. Unknown CPU processing time is shown honestly until progress is available. Do not extrapolate the NVIDIA ETA to a CPU movie conversion. Try a short preview before committing substantial time.

Exact input used for the recorded benchmark (the fixture generator above supplies a different, original scene):

```powershell
& "PATH_TO_FFMPEG" -v error -n -f lavfi -i "testsrc2=size=640x360:rate=24:duration=3" -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=3" -c:v libx264 -threads 2 -crf 16 -pix_fmt yuv420p -c:a aac -shortest "D:/CineVerse-QA/source-synthetic.mp4"
```

Then use this file with `examples/run_smoke.py` and a CPU-profile engine. The benchmark is for pipeline verification and does not establish depth accuracy on movies.
