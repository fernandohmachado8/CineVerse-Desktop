# Video title

CineVerse Desktop — Turn a 2D Video into VR-Ready 3D | Demo & Quick Start

# Description

Choose a local video, adjust stereo depth, generate a short preview and export a side-by-side MP4 for your VR cinema.

This captioned walkthrough shows CineVerse Desktop's Windows 0.8.1 public preview with original animated sample footage. Start at depth 1.5 with neural gap filling, check temperature protection and compare the result in Bigscreen using SBS, left eye first. Conversion runs locally; source files stay untouched.

- [Download Windows or the separate Apple Silicon Mac preview](https://github.com/fernandohmachado8/CineVerse-Desktop#cineverse-desktop)
- [Step-by-step tutorial and sample downloads](https://github.com/fernandohmachado8/CineVerse-Desktop/blob/main/docs/DEMO_TUTORIAL.md)
- [Source code, hardware support and limitations](https://github.com/fernandohmachado8/CineVerse-Desktop)

Shown: real app captures and an actual NVIDIA conversion of an original 10-second SDR/24 FPS sample at depth 1.5. The engine was installed beforehand. The walkthrough is edited and processing is condensed; it is not a speed benchmark. Optional NVIDIA HDR10 and 60 FPS features are not used in this sample. Windows and Mac previews have different capabilities.

AI can introduce edge, occlusion and motion artifacts. This produces stereo screen depth, not a walkable 360° scene. A flat video cannot show the binocular effect: download the separate SBS sample and use a compatible headset/player.

Powered by iw3 / nunif, Depth Anything V2 and optional Practical-RIFE. CineVerse's contribution is desktop and systems integration, not a newly trained stereo model. Bigscreen is a separate playback app. No affiliation with these projects is implied. Original sample artwork and application code: MIT; third-party licenses apply. No copyrighted movie footage or music is included.

## Chapters

```text
00:00 CineVerse Desktop
00:06 Install the engine
00:16 Choose a video
00:25 Depth and motion
00:35 Protection and preview
00:44 Original 2D source
00:54 Actual AI SBS output
01:06 Open the export
01:15 Watch in VR
```

# Optional portfolio post

I built CineVerse Desktop, an open-source desktop workflow for converting local 2D videos into SBS 3D for VR playback.

The project combines React/TypeScript, Tauri/Rust and Python/PyTorch with automatic dependency setup, hardware detection, supervised conversion jobs, temperature checks and export verification. Stereo conversion uses iw3; optional frame interpolation uses RIFE.

Here's a short demo and tutorial using original sample artwork. It's a public preview, with clear hardware and quality limits. I'd welcome reproducible bug reports and feedback from other PCs.

[Demo, downloads and source](https://github.com/fernandohmachado8/CineVerse-Desktop)

This is suggested copy for the project owner to publish; no social post is sent automatically.
