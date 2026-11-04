# Subtitles in the 0.10 preview

This separate development preview preserves the working 0.9 and 0.8.1 applications. No conversion starts when importing media, picking a subtitle language, or selecting burn-in. CPU/GPU supervision is still required for processing.

## Choose subtitles

1. Load the original video and select the intended audio language.
2. In **Subtitles**, explicitly choose **Burn into both eyes**. The default is **Off**, and every newly loaded video resets that choice.
3. Select an embedded text track by language/title, or choose an external `.srt` or `.ass` file.
4. Generate a short preview containing dialogue. Check the language, timing and text size in your player before starting a full video yourself.

The text appears in both halves of a full-SBS export. The same placement in each eye puts captions at the screen plane, rather than making the AI depth estimator warp their letters. Burn-in is permanent; it cannot be disabled or changed in the finished file. Keep a subtitle-free export if you want both options.

## Supported inputs and styling

Embedded text tracks such as SubRip, ASS/SSA, MP4 text and WebVTT are supported where FFmpeg can decode them. External SRT/ASS files are supported. Track labels come from source metadata; missing or incorrect language tags cannot establish the actual spoken/written language. External files do not necessarily carry a language tag.

Bitmap formats such as PGS/VobSub remain unavailable. This preview does not perform OCR or translate captions. It also does not add selectable subtitle tracks to the finished MP4. With **Off**, no subtitle text is rendered.

The first version normalizes text to a consistent bottom-centred style. Complex ASS positioning, overlapping signs, karaoke effects, drawings, inline colors and attached custom fonts are not preserved. Font fallback depends on the installed fonts; check language-specific glyphs in a preview. These limits are particularly relevant for styled anime releases.

## Timing and HDR

Subtitle text is taken from the original input, including when its temporary HDR10 base omits subtitle tracks. Preview timing is adjusted to the selected interval, retaining cues that begin before the preview but remain active at its start. Subtitle selection and external-file identity participate in saved-job validation; changing a subtitle file/settings requires a new job rather than reusing mismatched completed stages.

Text is rendered after stereo generation and optional frame interpolation. The existing Main10 HDR path remains 10-bit BT.2020/PQ. HDR text uses a controlled neutral gray code targeting approximately 200-nit white, with a dark outline, rather than maximum PQ white. Display brightness and perceived contrast still depend on the headset/player. Both eye images receive the same cue and placement.

Burn-in adds an encoding pass and temporary video, so it takes extra time and space. Final checks still verify frame count, timestamps, geometry, audio and HDR metadata. Source-eye fidelity is checked on the stereo image before the intentional caption overlay; it must not be described as an unchanged picture after text has been added. A short passing test does not establish comfort or perfect rendering across a whole film.

## Build and check

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s thermal -v
npm ci
npm test
npm run format:check
npm run build
npm run tauri -- build --bundles nsis
```

The preview has the separate `com.cineverse.desktop.subtitlepreview` identity. It needs the FFmpeg `subtitles` filter/libass; missing capability must produce an actionable error. Original media, external subtitle files, local engine settings and private test clips remain outside the repository and installer.

See [measured validation and its limits](SUBTITLE_VALIDATION.md) and [FFmpeg subtitle rendering](https://ffmpeg.org/ffmpeg-filters.html#subtitles-1).
