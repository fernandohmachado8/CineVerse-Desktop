# CineVerse Desktop — your first 3D preview

An edited walkthrough of the real Windows **0.8.1 preview** interface, using original animated artwork. The engine was already installed on the demonstration PC. Setup and processing are condensed; this is not a speed benchmark.

[Watch the captioned demonstration (MP4)](https://github.com/fernandohmachado8/CineVerse-Desktop/releases/download/v0.8.1-auto-setup-preview/CineVerse-Desktop-Demo-0.8.1.mp4) · [Download the original 2D sample](https://github.com/fernandohmachado8/CineVerse-Desktop/releases/download/v0.8.1-auto-setup-preview/CineVerse-Sample-2D.mp4) · [Download the AI-converted SBS sample for VR](https://github.com/fernandohmachado8/CineVerse-Desktop/releases/download/v0.8.1-auto-setup-preview/CineVerse-Sample-SBS-Depth-1.5.mp4)

The **1:26, 1080p** video is silent and readable without audio. An [optional SRT caption file](https://github.com/fernandohmachado8/CineVerse-Desktop/releases/download/v0.8.1-auto-setup-preview/CineVerse-Desktop-Demo-0.8.1.srt) and [ready-to-use description with chapters](DEMO_DESCRIPTION.md) are available. At **0:44** it shows the original; at **0:54** it shows the AI SBS output; at **1:15** it explains VR playback.

## 1. Install the app and engine

Download the [Windows 0.8.1 installer](https://github.com/fernandohmachado8/CineVerse-Desktop/releases/tag/v0.8.1-auto-setup-preview). The public preview is unsigned. Open **Engine settings**, keep **Automatic**, select an engine drive and acknowledge the dependency downloads. Click **Install engine automatically** and wait for the checks to finish. You do not need to enter Python or model paths.

First setup needs internet and several GB of downloads. Allow **15 GiB free**, or **25 GiB for the experimental AMD route and possible CPU fallback**, plus conversion workspace and output space. Display drivers are separate. Automatic chooses a supported acceleration route or CPU fallback after its checks. Detection alone does not certify performance on every GPU. See the [hardware and setup guide](https://github.com/fernandohmachado8/CineVerse-Desktop/blob/v0.8.1-auto-setup-preview/docs/AUTOMATIC_HARDWARE_SETUP.md).

The [Apple Silicon Mac preview](https://github.com/fernandohmachado8/CineVerse-Desktop/releases/tag/v0.7.0-macos-preview) is a separate **0.7** build for M1 or newer with macOS 14+. Its setup and supported options differ. This video demonstrates Windows.

## 2. Choose a short source and an output folder

Drop your local video onto **Choose your video**, click to browse, or expand **Enter a file path**. For a repeatable first test, use the original sample linked above. Under **Save your film**, select a folder with enough free space. CineVerse writes a new export; it does not replace the source.

## 3. Start with restrained depth

Use **depth 1.5**, **Neural** gap filling and **Original FPS**. These are the settings used for the downloadable SBS sample. Stronger depth can stretch edges and reveal more missing background. Neural filling generates those regions; it can soften detail or flicker.

On the supported NVIDIA route, **Smooth 60 FPS** uses RIFE to synthesize intermediate frames. It takes extra processing and can introduce motion artifacts. Supported HDR10 input has a separate NVIDIA path. The sample here is **SDR at 24 FPS**, with neither HDR nor smoothing enabled.

## 4. Check temperature protection

On Windows, complete the normal driver/helper prompts and click **Enable CPU sensor** when offered. The read-only sensor helper needs Windows administrator approval; the converter itself does not run elevated. Wait for the required CPU and GPU readings and **Ready to arm** before starting. CPU-only processing requires the CPU reading.

The default NVIDIA policy stops at CPU **95 °C for 10 seconds** or **100 °C immediately**, and GPU core **85 °C for 10 seconds** or **90 °C immediately**. Loss of a required sensor for 30 seconds also stops the job. GPU monitoring covers core temperature, not VRAM or hotspot. Software monitoring cannot guarantee hardware safety.

## 5. Generate and inspect a preview

Set **Preview starts at** and **Length**, then click **Generate preview**. Use 10 seconds on a suitable GPU, or start with three seconds on CPU. Watch the current stage, progress, elapsed time and estimates. Estimates can change; use **Cancel conversion** if needed.

Switch between **Original** and **SBS result** after completion. Test faces, thin objects, occlusions, movement and cuts in your own material. This simple animated sample demonstrates the workflow; it does not establish movie-quality performance. Reduce depth if objects stretch or depth feels uncomfortable.

## 6. Watch the SBS result in VR

Click **Open output folder**. Open the exported MP4 in Bigscreen or a compatible local VR player. Select **SBS, left eye first** rather than the reversed-eye mode. Check the aspect ratio: each eye should look normally proportioned. If depth appears inverted, check eye order first.

Two pictures next to each other on a monitor are expected. The headset shows one to each eye to create binocular depth. The product walkthrough itself is a normal 2D presentation; play the **separate SBS sample** to evaluate stereo. The source and sample have no audio by design.

After checking a preview, **Convert full video** processes your selected source. Review storage, cooling and estimated time first. No full movie was processed for this demonstration.

## What this demonstration proves

- Real Windows 0.8.1 application screens, with an already provisioned local engine.
- An actual bounded preview of original animated artwork through the NVIDIA iw3 pipeline, not a hand-made stereo pair presented as AI output.
- A separate original source and full SBS result for comparison. Compatibility margins are part of the export.

It does **not** demonstrate a walkable room, recovered unseen footage, 360° reconstruction, universal hardware support or a whole-movie quality benchmark. AI depth and the synthesized viewpoint can contain errors. The showcase is an edited sequence of real captures and sample playback, not a continuous screen recording.

The actual export is **1920 × 576, 240 frames, 10 seconds**, with 18 black compatibility rows above and below each 960 × 540 eye image. Verification found no removed source pixels, no timestamp-grid error and no decode errors. The decoded source-eye sample mean absolute errors were **0.143–0.164** in 8-bit sample units versus the prepared reference; these small encoding differences are not a perceptual quality score. The original source passed the app's integrity check. This new sample has not been physically evaluated in a headset.

## Credits and reproducibility

CineVerse provides the desktop workflow, setup, job supervision and export checks. Stereo conversion is powered by [iw3 / nunif](https://github.com/nagadomi/nunif), using Depth Anything V2; optional smoothing uses [Practical-RIFE](https://github.com/hzwer/Practical-RIFE). Their own licenses apply. Bigscreen is a separate playback application; no affiliation is implied.

The sample is original analytical geometry rendered by [generate_sample.py](../examples/demo/generate_sample.py), released under this repository's MIT license. No movie frames, book text, music, likenesses or third-party artwork are included. Read the [sample reproduction instructions](../examples/demo/README.md) and the release's `DEMO-PROVENANCE.json` and `DEMO-SHA256SUMS.txt` for exact media records.
