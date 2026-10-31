# Third-party notices

MIT covers the original application. It does not relicense upstream engines, models, codecs, drivers or media. Those dependencies are fetched separately. Preserve exact-version license/notice files when distributing a binary or engine bundle.

| Component | Official reference | Scope |
|---|---|---|
| iw3 / nunif | [MIT](https://github.com/nagadomi/nunif/blob/master/LICENSE); copy in `licenses/nunif-MIT.txt` | Stereo engine, not authored by CineVerse |
| Practical-RIFE | [MIT code and linked-model declaration](https://github.com/hzwer/Practical-RIFE#trained-model); code notice in `licenses/Practical-RIFE-MIT.txt` | Separately downloaded code and official 4.25 model |
| Depth Anything V2 Small | [Apache-2.0 model card](https://huggingface.co/depth-anything/Depth-Anything-V2-Small) | Small only; larger checkpoints have different terms |
| Depth Anything iw3 adapter / DINOv2 | [Adapter](https://github.com/nagadomi/Depth-Anything_iw3), [DINOv2](https://github.com/facebookresearch/dinov2) | Preserve bundled code notices and exact model terms |
| iw3 filling/depth AA and TransNetV2 | [Pinned iw3 source](https://github.com/nagadomi/nunif/tree/0d3d92c8f4396da564c44524b6390ee5c76b9668/iw3), [TransNetV2](https://github.com/soCzech/TransNetV2) | Individual upstream checkpoints/notices; no general relicensing by this app |
| Private CPython / standalone packaging | [Python PSF license](https://docs.python.org/3/license.html), [Astral standalone builds](https://github.com/astral-sh/python-build-standalone) | Runtime extracted with its bundled notices; not a new Python implementation |
| Native setup HTTP/archive/hash libraries | [reqwest](https://github.com/seanmonstar/reqwest), [tar](https://github.com/alexcrichton/tar-rs), flate2 and sha2; Cargo lockfile | Original upstream licenses remain applicable |
| PyTorch / torchvision | [PyTorch](https://github.com/pytorch/pytorch/blob/main/LICENSE), [torchvision](https://github.com/pytorch/vision/blob/main/LICENSE) | BSD-style licenses plus bundled notices, including CUDA wheel components |
| FFmpeg / Gyan build | [Builds/source](https://www.gyan.dev/ffmpeg/builds/), [GPLv3](https://github.com/FFmpeg/FFmpeg/blob/master/COPYING.GPLv3) | Selected build enables GPL/version3; separately launched executable |
| Mac FFmpeg / FFprobe arm64 build | [ffmpeg-static 6.1.1 release](https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1) | Separately downloaded executables; exact binary LICENSE and README retained alongside tools; not relicensed as MIT |
| LibreHardwareMonitor | [MPL-2.0](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/master/LICENSE) | Separate library; bundled components keep their notices |
| PawnIO | [Upstream driver](https://github.com/namazso/PawnIO) | Separate signed driver and installer terms; never silently installed |
| Tauri / official plugins | [MIT or Apache-2.0](https://github.com/tauri-apps/tauri) | Rust/JavaScript runtime and plugins |
| React | [MIT](https://github.com/facebook/react/blob/main/LICENSE) | UI runtime |
| Lucide | [ISC and inherited notices](https://github.com/lucide-icons/lucide/blob/main/LICENSE) | Icons |
| Other Python/npm/Cargo packages | `requirements/`, `package-lock.json`, `src-tauri/Cargo.lock` | Each package retains its own license |

The app icon, overview graphic and synthetic fixture generator are original project assets under the application MIT license. The fixture uses analytical test geometry: it is neither recovered film content nor a claimed AI conversion. No films, book extracts, actor imagery, credentials, personal paths or pretrained weights are published here.

Exact-version notices take precedence over this summary. The repository does not promise legal clearance for every possible engine/model combination or commercial distribution.
