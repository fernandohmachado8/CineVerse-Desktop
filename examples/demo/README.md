# Original public demonstration sample

This generator renders original analytical artwork: shaded spheres, a perspective grid and simple wall panels. It uses no movie, book, downloaded art or learned model. The generated **2D source is not AI reconstruction or AI stereo output**.

With Python, NumPy, Pillow and FFmpeg available:

```powershell
python -m pip install numpy Pillow
python examples/demo/generate_sample.py --output ./demo-source.mp4 --ffmpeg ffmpeg
```

The default source is 10 seconds, 960 × 540, 24 FPS, H.264, SDR, without audio. Existing output files are preserved. The Windows Segoe UI font is used if present; other systems use Pillow's default font, so rendering can differ.

For the published demonstration, the source was **actually converted separately** in the Windows 0.8.1 app with depth **1.5**, **Neural**, **Original FPS**, **10-second preview** and CPU + GPU thermal supervision on an RTX 4090. The app's installed engine paths were provisioned beforehand. Follow the [tutorial](../../docs/DEMO_TUTORIAL.md) to reproduce the workflow using the published source or your own generated file. Model/runtime versions and media hashes are in the release's `DEMO-PROVENANCE.json`; expect numerical differences across runtimes/hardware.

This is a functional demonstration rather than a reconstruction, quality ranking or processing-speed benchmark. Compare the 2D original and separate SBS export in a compatible headset/player. Credits and limitations are in the tutorial. The artwork and generator are MIT licensed; dependencies retain their own licenses.

## Re-editing the walkthrough

`render_walkthrough.py` creates the captioned 86-second presentation from real 0.8.1 app captures, the 2D source and its actual AI export. It does not simulate the UI. Capture your own matching 1222 × 892 app screens before using it: `01-source.jpg` (source loaded, top), `02-controls.jpg` (controls, scrolled), `03-ready.jpg` (live sensors), `04-started.jpg` (real preview started), `06-complete.jpg` (completed preview) and `08-setup-private.jpg` (settings top). The compositor's fixed crops reflect these states and exclude the settings path. Do not publish uncropped private screenshots. Adjust the crop definitions for another layout or display scale, then visually review every chapter.

```powershell
python examples/demo/render_walkthrough.py --captures ./captures --source ./demo-source.mp4 --sbs ./actual-ai-export.mp4 --output-dir ./presentation --ffmpeg ffmpeg
```

The renderer expects the 10-second, 240-frame samples, uses Windows Segoe UI fonts, preserves sample playback timing on its 30 FPS presentation timeline, and refuses to overwrite an existing demo. It creates an MP4, optional SRT and poster. The published SRT summarizes each chapter; the presentation's visible instructional text is already in the picture. There is no narration or music. Full app screenshots remain private; public release assets include the reviewed edited video and original/SBS samples, not raw settings or logs.

## Developer edition

`render_developer_demo.py` creates the separate **2:58 technical walkthrough**, with architecture/pipeline diagrams, recorded request fields, supervision and recovery explanations, actual sample playback and measured verification. Its diagrams are explanatory graphics, not simulated app screenshots or invented model outputs. The original 1:26 quick start remains available.

Use the published original/SBS samples and download `DEVELOPER-DEMO-EVIDENCE.json` from the 0.8.1 release. It contains the sanitized recorded request, completed-stage hashes and verification fields. The renderer checks the sample byte hashes against it before rendering. It never starts inference. Use your own matching app captures as described above; only `08-setup-private.jpg` and `03-ready.jpg` are required for this edition. Review the setup crop so private paths remain excluded. Windows Segoe UI and Consolas fonts are expected; `--font-dir` can select another folder with these filenames.

```powershell
python examples/demo/render_developer_demo.py --captures ./captures --source ./CineVerse-Sample-2D.mp4 --sbs ./CineVerse-Sample-SBS-Depth-1.5.mp4 --evidence ./DEVELOPER-DEMO-EVIDENCE.json --output-dir ./developer-presentation --ffmpeg ffmpeg
```

Outputs include the 1080p/30 FPS MP4, poster, SRT, chapter-review images and a rendering validation record. Text boxes are checked for overflow. Review images are local QA outputs; only the reviewed presentation, poster, description, sanitized evidence, provenance and checksums are release assets. No private settings or full application captures are published. See [technical notes](../../docs/DEVELOPER_DEMO.md) and [description with chapters](../../docs/DEVELOPER_DEMO_DESCRIPTION.md).
