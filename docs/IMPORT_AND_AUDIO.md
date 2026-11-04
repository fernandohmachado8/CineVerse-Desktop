# HDR10 base import and audio selection

These import/audio controls were introduced in the local Windows 0.9.0 preview and are included in the published 0.10 subtitle preview. Earlier executables, installers and local settings remain usable. Existing CPU/GPU protection, bounded previews, source integrity checks and verified stage recovery remain required. See [subtitle selection and burn-in](SUBTITLES.md) for the 0.10 additions.

## Import a compatible Dolby Vision source

1. Drop or browse for the original local file.
2. If the app identifies a compatible source, read the format explanation and select **Use HDR10 base**. This option starts unchecked for every newly loaded file.
3. Select the audio language, depth, frame rate and output folder.
4. Generate a short preview before deciding to process the full input.

The supported case is HEVC Dolby Vision Profile 8 with base-layer compatibility ID 1, a present base layer, no enhancement layer, and matching 10-bit BT.2020/PQ video signaling. Profile 5, HLG-based Profile 8 variants, dual-layer sources, unknown metadata and inconsistent signaling remain blocked. A supported NVIDIA profile is still required for HDR conversion. This preview does not add HDR processing to CPU, Radeon or Mac profiles.

Preparation uses FFmpeg's `dovi_rpu=strip=1` filter with stream copy. It creates a temporary main-video/audio MP4 inside the private job folder and removes Dolby Vision configuration/RPU metadata. It does not tone-map to SDR or re-encode the base picture. Static HDR metadata, timing/count information and audio integrity are checked before the existing preparation/conversion pipeline continues. The eventual SBS export still re-encodes and scales the picture under the existing output limits.

This is **HDR10 output**. Dolby Vision dynamic metadata and any unsupported Dolby Vision behavior are not retained. The original source is never modified. Files with no verified compatible base are not made compatible by simply deleting metadata.

The whole video/audio copy is prepared even for a short preview, so preflight adds the source file size to the temporary-space budget. Unsupported FFmpeg builds fail with an actionable error. An extra audio codec that cannot be copied into MP4 also stops preparation; this preview does not silently transcode or discard such tracks. No full conversion or background job starts when the checkbox is selected. Known temporary files are removed after successful export; interrupted stages remain available for manual recovery.

## Audio selection

The audio dropdown lists each source audio track with its language, title, codec and channel count when available. It initially chooses the first audio track, matching previous behavior. Select a different language before generating a preview or starting a full job. A source without audio exports silently.

The request stores the absolute source stream index rather than a displayed list position. Selection is checked against a fresh source probe before processing. When HDR10-base remuxing changes stream indices, the selected source track is mapped to its correct audio position in the temporary copy. The selected track is downmixed/re-encoded as AAC stereo during normal preparation; the finalization step retains that prepared audio and verifies its packet hash.

Additional audio tracks and surround/Atmos preservation are outside this preview. The original retains those tracks. Version 0.10 additionally supports [optional text subtitle burn-in](SUBTITLES.md); selectable output subtitle streams remain omitted. The output report identifies the selected source audio and the HDR10-base choice, so an English dub cannot be mistaken for a Japanese track merely because both were present in the input.

## Recovery and verification

The saved request includes both the source mode and the audio choice. Resume retains the saved settings; changing either choice requires a new job. Existing checkpoints keep their previous first-audio/original-source interpretation. Stage recovery continues to reuse only verified completed stages, with no automatic restart after a temperature stop.

Run the source checks from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s thermal -v
npm ci
npm test
npm run format:check
npm run build
npm run tauri -- build --bundles nsis
```

The development build uses a separate `com.cineverse.desktop.importpreview` identity. Release media, model weights, original movies, local engine settings and private test logs do not belong in Git. Do not infer support for untested hardware or a whole movie's visual quality from a short passing preview.

See [measured local validation and its limits](IMPORT_VALIDATION.md).

## References

- [Dolby bitstream profiles and HDR10 compatibility identifiers](https://ott.dolby.com/OnDelKits/Dolby_Vision_Online_Delivery_Kit/v1/Documentation/Specs/Visio_Profiles/help_files/topics/c_dovi_profiles_public.html)
- [FFmpeg Dolby Vision metadata stripping](https://ffmpeg.org/ffmpeg-bitstream-filters.html#dovi_005frpu)
