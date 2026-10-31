# Architecture

The interface, native process host, thermal supervisor and conversion stages have separate responsibilities.

```mermaid
flowchart TD
    UI[React + TypeScript] --> IPC[Tauri Rust commands]
    IPC --> CHECK[Discovery, GPU checks and media probe]
    IPC --> SUP[Independent Python thermal supervisor]
    CPU[Elevated read-only CPU sensor] --> SUP
    GPU[NVIDIA GPU core / UUID] --> SUP
    SUP --> JOB[Windows job object / converter tree]
    JOB --> PREP[FFmpeg preparation]
    PREP --> CUT[Scene analysis via iw3 / TransNetV2]
    CUT --> RIFE[Optional RIFE 4.25 interpolation]
    RIFE --> DEPTH[iw3 depth, stereo and gap filling]
    CUT --> DEPTH
    DEPTH --> HDR[HDR metadata, margins and audio]
    HDR --> VERIFY[Decode and verify every output frame]
    VERIFY --> SBS[Unique full-SBS MP4 and report]
    JOB <--> STATE[Atomic checkpoints and stage hashes]
    SUP --> EVENTS[NDJSON progress / thermal events]
    EVENTS --> IPC
    IPC --> UI
```

## Important boundaries

- The frontend disables actions without required readings; the supervisor independently checks again before inference.
- Only CPU sensing requests administrator access. Readers bind to the exact parent PID/creation time and end with that instance. Conversion stays unelevated.
- A Windows job object owns each converter tree. Cutoffs, lost readings and supervisor failures terminate that tree. Resume is manual.
- A saved sensor path does not prove protection after reopening the app. Fresh permission/readings are required for each session.
- Recovery checks source identity, settings, pipeline version and stage hashes. Interrupted stages restart; existing finished outputs are never overwritten.
- Previews have explicit start/duration. Full conversion is a separate user action.

## Tradeoffs

HDR interpolation keeps PQ RGB in FP32 before 10-bit output. This avoids an SDR round trip but does not make RIFE HDR-trained. Timing is normalized to average input frame rate; footage is not bit-identical. Full movies use complete source hashes; previews explicitly use sampled hashes for responsiveness.

Scene-cut guards cannot guarantee perfect detection. Neural gap filling may reduce stretching but can invent soft detail and costs processing time. The 1.5 preset reflects local VR comparisons, not a general comfort study.

Separately licensed engines provide inference; CineVerse coordinates their execution and verifies results. Clean-machine deployment and wider GPU compatibility remain follow-up work.
