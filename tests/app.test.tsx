// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, it, expect, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
  act,
} from "@testing-library/react";
const mock = vi.hoisted(() => ({
  invoke: vi.fn(),
  handler: null as any,
  setupHandler: null as any,
  drop: null as any,
  open: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({
  invoke: mock.invoke,
  isTauri: () => true,
  convertFileSrc: (p: string) => p,
}));
vi.mock("@tauri-apps/api/event", () => ({
  listen: (_name: string, cb: any) => {
    if (_name === "conversion") mock.handler = cb;
    else if (_name === "engine-setup") mock.setupHandler = cb;
    return Promise.resolve(() => {});
  },
}));
vi.mock("@tauri-apps/api/webview", () => ({
  getCurrentWebview: () => ({
    onDragDropEvent: (cb: any) => {
      mock.drop = cb;
      return Promise.resolve(() => {});
    },
  }),
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: mock.open }));
vi.mock("react-dom/client", () => ({
  createRoot: () => ({ render: () => {} }),
}));
import { App } from "../src/main";
const settings = {
  python: "/engine/python",
  iw3Repo: "/engine/iw3",
  ffmpeg: "/engine/ffmpeg",
  ffprobe: "/engine/ffprobe",
  cache: "/cache",
  rifeRepo: "/rife",
  rifeModel: "/models",
  outputDir: "/exports",
  cpuDriverInstaller: "/engine/downloads/PawnIO_setup.exe",
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
async function setup(
  hdr = false,
  enoughSpace = true,
  restore = false,
  cpuReady = true,
  backend = "cuda",
  checkDelay = 0,
  captureDrop?: (callback: any) => void,
  platform = "windows",
  gpuReady = true,
  sensorDriverInstalled = true,
  mediaOverrides: Record<string, unknown> = {},
  savedJobs: Record<string, unknown>[] = [],
) {
  let driverInstalled = sensorDriverInstalled;
  mock.invoke.mockImplementation(async (name: string, args: any) => {
    if (name === "hardware_info")
      return {
        state: "detected",
        architecture: "x64",
        cpuSensorDriverInstalled: driverInstalled,
        cpu: { name: "AMD Ryzen test CPU", manufacturer: "AuthenticAMD" },
        gpus: [
          { name: "AMD Radeon RX 7900 XTX", driverVersion: "32.0.23027.2005" },
        ],
      };
    if (name === "open_cpu_driver") {
      driverInstalled = true;
      return;
    }
    if (name === "setup_info")
      return { defaultRoot: "/engine-managed", platform };
    if (name === "load_settings")
      return restore ? { ...settings, lastVideo: "/test/video.mp4" } : settings;
    if (name === "check_engine") {
      if (checkDelay)
        await new Promise((resolve) => setTimeout(resolve, checkDelay));
      return {
        ready: true,
        gpu: "Test GPU",
        backend,
        gpuBinding:
          backend === "rocm"
            ? {
                name: "AMD Radeon RX 7900 XTX",
                deviceCount: 1,
                hardwareType: "GpuAmd",
              }
            : undefined,
        platform,
        supportsHDR: backend === "cuda",
        supports60: backend === "cuda",
        maxWidth: backend === "cuda" ? 1920 : 1280,
        rifeReady: true,
        gpuUuid: "GPU-test",
      };
    }
    if (name === "thermal_status" && platform === "macos")
      return {
        ready: cpuReady,
        cpu: {
          state: cpuReady ? "ready" : "unavailable",
          label: cpuReady ? "Nominal" : undefined,
        },
        gpu: { state: "not_separate" },
      };
    if (name === "thermal_status")
      return {
        ready: cpuReady && (backend !== "rocm" || gpuReady),
        cpu: {
          state: cpuReady ? "ready" : "unavailable",
          c: cpuReady ? 60 : undefined,
          message: cpuReady ? undefined : "CPU sensor missing",
        },
        gpu: {
          state: gpuReady ? "ready" : "unavailable",
          c: gpuReady ? 50 : undefined,
          message: gpuReady ? undefined : "Radeon sensor missing",
        },
      };
    if (name === "enable_cpu_sensor")
      return { cpuSensorFile: "/sensor/cpu-sample.json" };
    if (name === "find_engine")
      return {
        settings,
        components: [{ key: "python", label: "CUDA Python", found: true }],
      };
    if (name === "probe_media")
      return {
        path: args.path || "/test/video.mp4",
        width: 1920,
        height: 804,
        fps: 23.976,
        duration: 180,
        hdr,
        hasAudio: true,
        ...mediaOverrides,
      };
    if (name === "list_jobs") return savedJobs;
    if (name === "plan_conversion") {
      if (backend === "cpu" && args.request.fpsMode !== "original")
        throw Error("CPU startup planned unsupported FPS");
      return {
        spaceBudgetBytes: 4e9,
        freeBytes: 40e9,
        enoughSpace,
        estimatedSecondsLow: 480,
        estimatedSecondsHigh: 720,
        outputEstimateBytesLow: 3e8,
        outputEstimateBytesHigh: 8e8,
      };
    }
    if (name === "start_job") return "job-1";
  });
  render(<App />);
  captureDrop?.(mock.drop);
  await screen.findByText("Test GPU");
  if (!restore)
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/video.mp4"] } }),
    );
  await screen.findByText("video.mp4");
  if (!mediaOverrides.dolbyVision)
    await screen.findByLabelText("Full movie estimate", {}, { timeout: 3000 });
  await waitFor(() =>
    expect(
      screen.getByLabelText("Temperature protection").textContent,
    ).toContain(
      !cpuReady
        ? "CPU sensor missing"
        : backend === "rocm" && !gpuReady
          ? "Radeon sensor missing"
          : "Ready to arm",
    ),
  );
}
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
describe("Desktop conversion flow", () => {
  const subtitleTracks = [
    {
      index: 7,
      language: "eng",
      title: "Full dialogue",
      codec: "subrip",
      default: true,
      forced: false,
      supported: true,
    },
    {
      index: 12,
      language: "por",
      title: "Português",
      codec: "ass",
      default: false,
      forced: false,
      supported: true,
    },
    {
      index: 16,
      language: "eng",
      title: "Bitmap signs",
      codec: "hdmv_pgs_subtitle",
      default: false,
      forced: true,
      supported: false,
    },
  ];
  async function setupSubtitles(
    tracks = subtitleTracks,
    saved: Record<string, unknown>[] = [],
  ) {
    await setup(
      false,
      true,
      false,
      true,
      "cuda",
      0,
      undefined,
      "windows",
      true,
      true,
      { subtitleTracks: tracks },
      saved,
    );
  }
  it("keeps subtitles off unless burning is explicitly selected", async () => {
    await setupSubtitles();
    expect(screen.getByText("Off").getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByLabelText("Subtitle language / track")).toBeNull();
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            subtitleMode: "off",
            subtitleSource: "embedded",
            subtitleTrackIndex: null,
            subtitlePath: null,
            preview: true,
          }),
        }),
      ),
    );
  });
  it("sends a selected embedded subtitle language by absolute index for previews and full jobs", async () => {
    await setupSubtitles();
    fireEvent.click(screen.getByText("Burn into both eyes"));
    expect(
      screen.getByLabelText("Subtitle language / track").textContent,
    ).toContain("English");
    expect(
      screen.getByLabelText("Subtitle language / track").textContent,
    ).toContain("Portuguese");
    expect(screen.getByText(/permanently rendered/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Subtitle language / track"), {
      target: { value: "12" },
    });
    await screen.findByLabelText("Full movie estimate");
    expect(mock.invoke).toHaveBeenCalledWith(
      "plan_conversion",
      expect.objectContaining({
        request: expect.objectContaining({
          subtitleMode: "burn",
          subtitleSource: "embedded",
          subtitleTrackIndex: 12,
        }),
      }),
    );
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            subtitleMode: "burn",
            subtitleSource: "embedded",
            subtitleTrackIndex: 12,
            subtitlePath: null,
            preview: true,
          }),
        }),
      ),
    );
    expect(
      (screen.getByLabelText("Subtitle language / track") as HTMLSelectElement)
        .disabled,
    ).toBe(true);
    await act(async () => mock.handler({ payload: { type: "cancelled" } }));
    await screen.findByLabelText("Full movie estimate");
    fireEvent.click(screen.getByText("Convert full video"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            subtitleTrackIndex: 12,
            subtitleMode: "burn",
            preview: false,
          }),
        }),
      ),
    );
  });
  it("accepts an external ASS file through the picker and blocks invalid external formats", async () => {
    await setupSubtitles();
    fireEvent.click(screen.getByText("Burn into both eyes"));
    fireEvent.change(screen.getByLabelText("Subtitle source"), {
      target: { value: "external" },
    });
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("External subtitle file"), {
      target: { value: "/subtitles/captions.exe" },
    });
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    mock.open.mockResolvedValueOnce("/subtitles/Português.ass");
    fireEvent.click(screen.getByText("Browse subtitles"));
    await waitFor(() =>
      expect(
        (screen.getByLabelText("External subtitle file") as HTMLInputElement)
          .value,
      ).toBe("/subtitles/Português.ass"),
    );
    await screen.findByLabelText("Full movie estimate");
    expect(mock.open).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: [{ name: "Text subtitles", extensions: ["srt", "ass"] }],
      }),
    );
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            subtitleMode: "burn",
            subtitleSource: "external",
            subtitleTrackIndex: null,
            subtitlePath: "/subtitles/Português.ass",
          }),
        }),
      ),
    );
  });
  it("blocks bitmap-only subtitles without claiming OCR and allows captions to be turned off", async () => {
    await setupSubtitles([subtitleTracks[2]]);
    fireEvent.click(screen.getByText("Burn into both eyes"));
    expect(
      (
        screen.getByRole("option", {
          name: /Bitmap signs/,
        }) as HTMLOptionElement
      ).disabled,
    ).toBe(true);
    expect(screen.getByText(/Bitmap subtitles require OCR/)).toBeTruthy();
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.queryByLabelText("Full movie estimate")).toBeNull();
    fireEvent.click(screen.getByText("Off"));
    await screen.findByLabelText("Full movie estimate");
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(false);
  });
  it("resets subtitle burn consent and external paths when the video changes", async () => {
    await setupSubtitles();
    fireEvent.click(screen.getByText("Burn into both eyes"));
    fireEvent.change(screen.getByLabelText("Subtitle source"), {
      target: { value: "external" },
    });
    fireEvent.change(screen.getByLabelText("External subtitle file"), {
      target: { value: "/subtitles/first.srt" },
    });
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/another.mp4"] } }),
    );
    await screen.findByText("another.mp4");
    expect(screen.getByText("Off").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByText("Burn into both eyes"));
    expect(
      (screen.getByLabelText("Subtitle source") as HTMLSelectElement).value,
    ).toBe("embedded");
    expect(
      (screen.getByLabelText("Subtitle language / track") as HTMLSelectElement)
        .value,
    ).toBe("7");
    fireEvent.change(screen.getByLabelText("Subtitle source"), {
      target: { value: "external" },
    });
    expect(
      (screen.getByLabelText("External subtitle file") as HTMLInputElement)
        .value,
    ).toBe("");
  });
  it("ignores an external subtitle picker result after a different video is loaded", async () => {
    await setupSubtitles();
    const picker = deferred<string>();
    mock.open.mockReturnValueOnce(picker.promise);
    fireEvent.click(screen.getByText("Burn into both eyes"));
    fireEvent.change(screen.getByLabelText("Subtitle source"), {
      target: { value: "external" },
    });
    fireEvent.click(screen.getByText("Browse subtitles"));
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/new.mp4"] } }),
    );
    await screen.findByText("new.mp4");
    await act(async () => picker.resolve("/subtitles/old.srt"));
    expect(screen.getByText("Off").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByText("Burn into both eyes"));
    fireEvent.change(screen.getByLabelText("Subtitle source"), {
      target: { value: "external" },
    });
    expect(
      (screen.getByLabelText("External subtitle file") as HTMLInputElement)
        .value,
    ).toBe("");
  });
  it.each(["cancel", "error"] as const)(
    "releases a stale subtitle picker when a pending resume ends by %s",
    async (outcome) => {
      const savedRequest = {
        source: "/test/resumable.mp4",
        outputDir: "/exports",
        fpsMode: "original",
        preview: true,
      };
      await setupSubtitles(subtitleTracks, [
        {
          path: "/exports/.cineverse-jobs/resumable/job.json",
          source: savedRequest.source,
          request: savedRequest,
          completedStages: [],
          running: false,
          status: "interrupted",
          log: "/exports/resumable.log",
        },
      ]);
      const picker = deferred<string>();
      const resumeProbe = deferred<Record<string, unknown>>();
      const previous = mock.invoke.getMockImplementation()!;
      mock.invoke.mockImplementation(async (name: string, args: any) => {
        if (name === "probe_media" && args.path === savedRequest.source)
          return resumeProbe.promise;
        return previous(name, args);
      });
      mock.open.mockReturnValueOnce(picker.promise);
      fireEvent.click(screen.getByText("Burn into both eyes"));
      fireEvent.change(screen.getByLabelText("Subtitle source"), {
        target: { value: "external" },
      });
      fireEvent.change(screen.getByLabelText("External subtitle file"), {
        target: { value: "/subtitles/current.srt" },
      });
      fireEvent.click(screen.getByText("Browse subtitles"));
      expect((screen.getByText("Off") as HTMLButtonElement).disabled).toBe(
        true,
      );
      fireEvent.click(await screen.findByLabelText("Resume resumable.mp4"));
      if (outcome === "cancel") {
        fireEvent.click(await screen.findByText("Cancel conversion"));
        await act(async () =>
          resumeProbe.resolve({
            path: savedRequest.source,
            width: 1920,
            height: 1080,
            fps: 24,
            duration: 180,
            hdr: false,
            hasAudio: true,
            subtitleTracks,
          }),
        );
      } else {
        await act(async () =>
          resumeProbe.reject(new Error("Resume probe failed")),
        );
        expect(await screen.findByText(/Resume probe failed/)).toBeTruthy();
      }
      await act(async () => picker.resolve("/subtitles/stale.srt"));
      expect((screen.getByText("Off") as HTMLButtonElement).disabled).toBe(
        false,
      );
      expect(
        (screen.getByLabelText("External subtitle file") as HTMLInputElement)
          .value,
      ).toBe("/subtitles/current.srt");
      await screen.findByLabelText("Full movie estimate");
      expect(
        (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
      ).toBe(false);
      expect(
        mock.invoke.mock.calls.some(
          ([name]) => name === "start_job" || name === "cancel_job",
        ),
      ).toBe(false);
    },
  );
  it("restores exact saved subtitle settings when resuming", async () => {
    const savedRequest = {
      source: "/test/captioned.mp4",
      outputDir: "/exports",
      strength: 1.5,
      stereoMethod: "forward_inpaint",
      fpsMode: "original",
      preview: true,
      previewSeconds: 3,
      subtitleMode: "burn",
      subtitleSource: "embedded",
      subtitleTrackIndex: 12,
      subtitlePath: null,
    };
    await setupSubtitles(subtitleTracks, [
      {
        path: "/exports/.cineverse-jobs/captions/job.json",
        source: savedRequest.source,
        request: savedRequest,
        completedStages: ["Creating stereo depth"],
        running: false,
        status: "interrupted",
        log: "/exports/captions.log",
      },
    ]);
    fireEvent.click(await screen.findByLabelText("Resume captioned.mp4"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: {
            ...savedRequest,
            resumeJob: "/exports/.cineverse-jobs/captions/job.json",
          },
        }),
      ),
    );
    expect(
      screen.getByText("Burn into both eyes").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      (screen.getByLabelText("Subtitle language / track") as HTMLSelectElement)
        .value,
    ).toBe("12");
  });
  it("refuses a saved subtitle stream that is missing or unsupported", async () => {
    const savedRequest = {
      source: "/test/captioned.mp4",
      outputDir: "/exports",
      fpsMode: "original",
      preview: true,
      subtitleMode: "burn",
      subtitleSource: "embedded",
      subtitleTrackIndex: 16,
    };
    await setupSubtitles(subtitleTracks, [
      {
        path: "/exports/.cineverse-jobs/captions/job.json",
        source: savedRequest.source,
        request: savedRequest,
        completedStages: [],
        running: false,
        status: "interrupted",
        log: "/exports/captions.log",
      },
    ]);
    fireEvent.click(await screen.findByLabelText("Resume captioned.mp4"));
    expect(
      await screen.findByText(/saved subtitle track is no longer available/),
    ).toBeTruthy();
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });
  const audioTracks = [
    {
      index: 1,
      language: "eng",
      title: "English dub",
      codec: "eac3",
      channels: 6,
      default: true,
    },
    {
      index: 5,
      language: "jpn",
      title: "Original",
      codec: "eac3",
      channels: 6,
      default: false,
    },
  ];
  const compatibleImport = {
    dolbyVision: true,
    dolbyVisionProfile: 8,
    hdr10BaseCompatible: true,
    audioTracks,
  };
  const compatibleMedia = (path: string) => ({
    path,
    width: 1920,
    height: 1080,
    fps: 24,
    duration: 180,
    hdr: true,
    hasAudio: true,
    ...compatibleImport,
  });
  async function setupCompatibleImport() {
    await setup(
      true,
      true,
      false,
      true,
      "cuda",
      0,
      undefined,
      "windows",
      true,
      true,
      compatibleImport,
    );
  }

  it("requires explicit HDR10-base consent and labels Dolby Vision accurately", async () => {
    await setupCompatibleImport();
    expect(
      screen.getByText("Dolby Vision profile 8 detected", { exact: false }),
    ).toBeTruthy();
    expect(screen.queryByText(/HDR10 is preserved/)).toBeNull();
    expect(
      (screen.getByLabelText("Use HDR10 base") as HTMLInputElement).checked,
    ).toBe(false);
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      mock.invoke.mock.calls.some(
        ([name]) => name === "plan_conversion" || name === "start_job",
      ),
    ).toBe(false);
    fireEvent.click(screen.getByLabelText("Use HDR10 base"));
    await screen.findByLabelText("Full movie estimate");
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(screen.getByText(/removes Dolby Vision metadata/)).toBeTruthy();
    expect(mock.invoke).toHaveBeenCalledWith(
      "plan_conversion",
      expect.objectContaining({
        request: expect.objectContaining({
          sourceMode: "hdr10-base",
          audioTrackIndex: 1,
        }),
      }),
    );
    fireEvent.click(screen.getByLabelText("Use HDR10 base"));
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.queryByLabelText("Full movie estimate")).toBeNull();
  });

  it("sends the selected Japanese absolute stream index in preview and full jobs", async () => {
    await setupCompatibleImport();
    fireEvent.click(screen.getByLabelText("Use HDR10 base"));
    fireEvent.change(screen.getByLabelText("Audio track"), {
      target: { value: "5" },
    });
    await screen.findByLabelText("Full movie estimate");
    expect(
      (screen.getByLabelText("Audio track") as HTMLSelectElement).value,
    ).toBe("5");
    expect(screen.getByLabelText("Audio track").textContent).toContain(
      "Japanese",
    );
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            sourceMode: "hdr10-base",
            audioTrackIndex: 5,
            preview: true,
          }),
        }),
      ),
    );
    expect(
      (screen.getByLabelText("Audio track") as HTMLSelectElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByLabelText("Use HDR10 base") as HTMLInputElement).disabled,
    ).toBe(true);
    await act(async () => mock.handler({ payload: { type: "cancelled" } }));
    await screen.findByLabelText("Full movie estimate");
    fireEvent.click(screen.getByText("Convert full video"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            sourceMode: "hdr10-base",
            audioTrackIndex: 5,
            preview: false,
          }),
        }),
      ),
    );
  });

  it("resets HDR consent and audio selection when another source is loaded", async () => {
    await setupCompatibleImport();
    fireEvent.click(screen.getByLabelText("Use HDR10 base"));
    fireEvent.change(screen.getByLabelText("Audio track"), {
      target: { value: "5" },
    });
    await screen.findByLabelText("Full movie estimate");
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/another.mp4"] } }),
    );
    await screen.findByText("another.mp4");
    expect(
      (screen.getByLabelText("Use HDR10 base") as HTMLInputElement).checked,
    ).toBe(false);
    expect(
      (screen.getByLabelText("Audio track") as HTMLSelectElement).value,
    ).toBe("1");
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.queryByLabelText("Full movie estimate")).toBeNull();
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });

  it("blocks unsupported Dolby Vision profiles without offering HDR10 preparation", async () => {
    await setup(
      true,
      true,
      false,
      true,
      "cuda",
      0,
      undefined,
      "windows",
      true,
      true,
      {
        ...compatibleImport,
        dolbyVisionProfile: 5,
        hdr10BaseCompatible: false,
      },
    );
    expect(screen.getByText(/no verified HDR10-compatible/)).toBeTruthy();
    expect(screen.queryByLabelText("Use HDR10 base")).toBeNull();
    expect(screen.queryByText(/HDR10 is preserved/)).toBeNull();
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByText("Convert full video") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      mock.invoke.mock.calls.some(
        ([name]) => name === "plan_conversion" || name === "start_job",
      ),
    ).toBe(false);
  });

  it("ignores an older probe resolving after a newer source and its HDR consent", async () => {
    await setupCompatibleImport();
    const first = deferred<ReturnType<typeof compatibleMedia>>();
    const second = deferred<ReturnType<typeof compatibleMedia>>();
    const previous = mock.invoke.getMockImplementation()!;
    mock.invoke.mockImplementation(async (name: string, args: any) => {
      if (name === "probe_media" && args.path === "/test/first.mp4")
        return first.promise;
      if (name === "probe_media" && args.path === "/test/second.mp4")
        return second.promise;
      return previous(name, args);
    });
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/first.mp4"] } }),
    );
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/second.mp4"] } }),
    );
    await act(async () => second.resolve(compatibleMedia("/test/second.mp4")));
    await screen.findByText("second.mp4");
    fireEvent.click(screen.getByLabelText("Use HDR10 base"));
    fireEvent.change(screen.getByLabelText("Audio track"), {
      target: { value: "5" },
    });
    await screen.findByLabelText("Full movie estimate");
    await act(async () =>
      first.resolve({
        ...compatibleMedia("/test/first.mp4"),
        audioTracks: [{ ...audioTracks[0], index: 11 }],
      }),
    );
    expect(screen.queryByText("first.mp4")).toBeNull();
    expect(screen.getByText("second.mp4")).toBeTruthy();
    expect(
      (screen.getByLabelText("Video file path") as HTMLInputElement).value,
    ).toBe("/test/second.mp4");
    expect(
      (screen.getByLabelText("Use HDR10 base") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByLabelText("Audio track") as HTMLSelectElement).value,
    ).toBe("5");
    expect(
      mock.invoke.mock.calls.some(
        ([name, args]) =>
          name === "save_settings" &&
          args.settings.lastVideo === "/test/first.mp4",
      ),
    ).toBe(false);
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            source: "/test/second.mp4",
            sourceMode: "hdr10-base",
            audioTrackIndex: 5,
          }),
        }),
      ),
    );
  });

  it("ignores stale probe errors and keeps the latest pending import blocked", async () => {
    await setupCompatibleImport();
    const first = deferred<ReturnType<typeof compatibleMedia>>();
    const second = deferred<ReturnType<typeof compatibleMedia>>();
    const previous = mock.invoke.getMockImplementation()!;
    mock.invoke.mockImplementation(async (name: string, args: any) => {
      if (name === "probe_media" && args.path === "/test/first.mp4")
        return first.promise;
      if (name === "probe_media" && args.path === "/test/second.mp4")
        return second.promise;
      return previous(name, args);
    });
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/first.mp4"] } }),
    );
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/second.mp4"] } }),
    );
    await act(async () => first.reject(new Error("Old probe failed")));
    expect(screen.queryByText(/Old probe failed/)).toBeNull();
    expect(screen.getByText("Reading video…")).toBeTruthy();
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    await act(async () => second.resolve(compatibleMedia("/test/second.mp4")));
    await screen.findByText("second.mp4");
    expect(
      (screen.getByLabelText("Use HDR10 base") as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("orders last-video settings writes so an in-flight old save cannot overwrite the latest import", async () => {
    await setupCompatibleImport();
    const oldSave = deferred<void>();
    const newSave = deferred<void>();
    const writes: string[] = [];
    const previous = mock.invoke.getMockImplementation()!;
    mock.invoke.mockImplementation(async (name: string, args: any) => {
      if (
        name === "save_settings" &&
        args.settings.lastVideo === "/test/first.mp4"
      ) {
        writes.push(args.settings.lastVideo);
        return oldSave.promise;
      }
      if (
        name === "save_settings" &&
        args.settings.lastVideo === "/test/second.mp4"
      ) {
        writes.push(args.settings.lastVideo);
        return newSave.promise;
      }
      return previous(name, args);
    });
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/first.mp4"] } }),
    );
    await screen.findByText("Reading video…");
    await waitFor(() => expect(writes).toEqual(["/test/first.mp4"]));
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/second.mp4"] } }),
    );
    expect(writes).toEqual(["/test/first.mp4"]);
    await act(async () => oldSave.resolve());
    await waitFor(() =>
      expect(writes).toEqual(["/test/first.mp4", "/test/second.mp4"]),
    );
    expect(screen.getByText("Reading video…")).toBeTruthy();
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    await act(async () => newSave.resolve());
    await screen.findByText("second.mp4");
    expect(screen.queryByText("first.mp4")).toBeNull();
  });

  it("keeps legacy files usable and makes no-audio inputs explicit", async () => {
    await setup(
      false,
      true,
      false,
      true,
      "cuda",
      0,
      undefined,
      "windows",
      true,
      true,
      { hasAudio: false, audioTracks: [] },
    );
    expect(screen.getByText("This video has no audio track.")).toBeTruthy();
    expect(screen.queryByLabelText("Audio track")).toBeNull();
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            sourceMode: "original",
            audioTrackIndex: null,
          }),
        }),
      ),
    );
  });

  it("resumes with the exact saved HDR and audio settings and reflects those controls", async () => {
    const savedRequest = {
      source: "/test/saved.mp4",
      outputDir: "/exports",
      strength: 1.25,
      stereoMethod: "forward_inpaint",
      fpsMode: "original",
      preview: false,
      sourceMode: "hdr10-base",
      audioTrackIndex: 5,
    };
    await setup(
      true,
      true,
      false,
      true,
      "cuda",
      0,
      undefined,
      "windows",
      true,
      true,
      compatibleImport,
      [
        {
          path: "/exports/.cineverse-jobs/old/job.json",
          source: savedRequest.source,
          request: savedRequest,
          completedStages: ["Preparing HDR10 base"],
          running: false,
          status: "interrupted",
          log: "/exports/job.log",
        },
      ],
    );
    const oldProbe = deferred<ReturnType<typeof compatibleMedia>>();
    const previous = mock.invoke.getMockImplementation()!;
    mock.invoke.mockImplementation(async (name: string, args: any) => {
      if (name === "probe_media" && args.path === "/test/late.mp4")
        return oldProbe.promise;
      return previous(name, args);
    });
    await act(async () =>
      mock.drop({ payload: { type: "drop", paths: ["/test/late.mp4"] } }),
    );
    fireEvent.click(await screen.findByLabelText("Resume saved.mp4"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: {
            ...savedRequest,
            resumeJob: "/exports/.cineverse-jobs/old/job.json",
          },
        }),
      ),
    );
    expect(
      (screen.getByLabelText("Use HDR10 base") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByLabelText("Audio track") as HTMLSelectElement).value,
    ).toBe("5");
    expect(screen.getByText("saved.mp4")).toBeTruthy();
    expect(screen.getByText("Original FPS").getAttribute("aria-pressed")).toBe(
      "true",
    );
    await act(async () => oldProbe.resolve(compatibleMedia("/test/late.mp4")));
    expect(screen.queryByText("late.mp4")).toBeNull();
    expect(screen.getByText("saved.mp4")).toBeTruthy();
    expect(
      mock.invoke.mock.calls.some(
        ([name, args]) =>
          name === "save_settings" &&
          args.settings.lastVideo === "/test/late.mp4",
      ),
    ).toBe(false);
  });

  it("cancels a pending resume probe without later starting its job", async () => {
    const savedRequest = {
      source: "/test/saved.mp4",
      outputDir: "/exports",
      strength: 1.5,
      stereoMethod: "forward_inpaint",
      fpsMode: "original",
      preview: false,
      sourceMode: "hdr10-base",
      audioTrackIndex: 5,
    };
    await setup(
      true,
      true,
      false,
      true,
      "cuda",
      0,
      undefined,
      "windows",
      true,
      true,
      compatibleImport,
      [
        {
          path: "/exports/.cineverse-jobs/old/job.json",
          source: savedRequest.source,
          request: savedRequest,
          completedStages: ["Preparing HDR10 base"],
          running: false,
          status: "interrupted",
          log: "/exports/job.log",
        },
      ],
    );
    const savedProbe = deferred<ReturnType<typeof compatibleMedia>>();
    const previous = mock.invoke.getMockImplementation()!;
    mock.invoke.mockImplementation(async (name: string, args: any) => {
      if (name === "probe_media" && args.path === savedRequest.source)
        return savedProbe.promise;
      return previous(name, args);
    });
    fireEvent.click(await screen.findByLabelText("Resume saved.mp4"));
    fireEvent.click(await screen.findByText("Cancel conversion"));
    expect(await screen.findByText("Conversion cancelled")).toBeTruthy();
    await act(async () =>
      savedProbe.resolve(compatibleMedia(savedRequest.source)),
    );
    expect(
      mock.invoke.mock.calls.some(
        ([name]) => name === "start_job" || name === "cancel_job",
      ),
    ).toBe(false);
    expect(screen.queryByText("saved.mp4")).toBeNull();
    expect(screen.getByText("video.mp4")).toBeTruthy();
  });

  it("shows detected hardware and keeps setup on automatic without starting conversion", async () => {
    await setup();
    fireEvent.click(screen.getByLabelText("Engine settings"));
    expect(screen.getByLabelText("Detected hardware").textContent).toContain(
      "AMD Ryzen test CPU",
    );
    expect(screen.getByLabelText("Detected hardware").textContent).toContain(
      "AMD Radeon RX 7900 XTX",
    );
    expect(screen.getByLabelText("Detected hardware").textContent).toContain(
      "32.0.23027.2005",
    );
    expect(
      (screen.getByLabelText("Processing package") as HTMLSelectElement).value,
    ).toBe("auto");
    expect(
      screen
        .getAllByRole("option")
        .some((o) => (o as HTMLOptionElement).value === "rocm"),
    ).toBe(true);
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });
  it("guides a missing sensor driver into the signed installer then the temperature helper", async () => {
    await setup(
      false,
      true,
      false,
      false,
      "cpu",
      0,
      undefined,
      "windows",
      true,
      false,
    );
    fireEvent.click(screen.getByText("Enable CPU sensor"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("open_cpu_driver", {
        settings: expect.objectContaining({
          cpuDriverInstaller: "/engine/downloads/PawnIO_setup.exe",
        }),
      }),
    );
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "enable_cpu_sensor",
        expect.anything(),
      ),
    );
    const commands = mock.invoke.mock.calls.map(([name]) => name);
    expect(commands.indexOf("open_cpu_driver")).toBeLessThan(
      commands.indexOf("enable_cpu_sensor"),
    );
    expect(commands.filter((name) => name === "enable_cpu_sensor").length).toBe(
      1,
    );
    expect(commands.includes("start_job")).toBe(false);
  });
  it("keeps the Radeon requirements visible and blocks conversion when its runtime check fails", async () => {
    await setup(false, true, false, true, "cpu");
    const previous = mock.invoke.getMockImplementation()!;
    mock.invoke.mockImplementation(async (name: string, args: any) => {
      if (name === "check_engine" && args.settings.backend === "rocm")
        throw Error("AMD ROCm is unavailable in this Python engine.");
      return previous(name, args);
    });
    fireEvent.change(screen.getByLabelText("Processing backend"), {
      target: { value: "rocm" },
    });
    await screen.findByText(/AMD ROCm is unavailable/);
    expect(
      screen.getByText(
        /Automatic setup can install the pinned supported Radeon runtime/,
      ),
    ).toBeTruthy();
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });
  it("keeps experimental Radeon on original FPS with mandatory CPU/GPU protection", async () => {
    await setup(false, true, false, true, "rocm");
    expect(screen.queryByLabelText("Required temperature sensors")).toBeNull();
    expect(
      (screen.getByText("Smooth 60 FPS").closest("button") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      screen.getByText(
        /Automatic setup can install the pinned supported Radeon runtime/,
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          settings: expect.objectContaining({
            resolvedBackend: "rocm",
            gpuBinding: {
              name: "AMD Radeon RX 7900 XTX",
              deviceCount: 1,
              hardwareType: "GpuAmd",
            },
          }),
          request: expect.objectContaining({
            fpsMode: "original",
            preview: true,
          }),
        }),
      ),
    );
  });
  it("allows re-enabling Radeon sensors even when CPU readings already work", async () => {
    await setup(
      false,
      true,
      false,
      true,
      "rocm",
      0,
      undefined,
      "windows",
      false,
    );
    // The renderer must honor the worker's combined ready flag.
    await act(async () =>
      mock.handler({
        payload: {
          type: "thermal",
          ready: false,
          cpu: { state: "ready", c: 60 },
          gpu: { state: "unavailable", message: "Radeon sensor missing" },
        },
      }),
    );
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByText("Enable CPU and Radeon sensors"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("enable_cpu_sensor", {
        settings: expect.objectContaining({ resolvedBackend: "rocm" }),
      }),
    );
  });
  it("clears previous engine executable paths when a different engine folder is explicitly selected", async () => {
    await setup();
    mock.open.mockResolvedValueOnce("/other-engine");
    fireEvent.click(screen.getByLabelText("Engine settings"));
    fireEvent.click(screen.getByText("Locate engine folder"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("find_engine", {
        root: "/other-engine",
        settings: expect.objectContaining({
          python: "",
          iw3Repo: "",
          backend: undefined,
        }),
      }),
    );
  });
  it("offers Mac setup without NVIDIA or Windows sensor controls", async () => {
    await setup(false, true, false, true, "cpu", 0, undefined, "macos");
    const protection = screen.getByLabelText("Temperature protection");
    expect(protection.textContent).toContain("Nominal");
    expect(protection.textContent).not.toContain("°C");
    expect(screen.queryByText("Enable CPU sensor")).toBeNull();
    expect(screen.queryByLabelText("Required temperature sensors")).toBeNull();
    fireEvent.click(screen.getByLabelText("Engine settings"));
    expect(
      screen
        .getAllByRole("option")
        .some((o) => (o as HTMLOptionElement).value === "cuda"),
    ).toBe(false);
    expect(screen.queryByRole("option", { name: /NVIDIA CUDA/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Processing package"), {
      target: { value: "mps" },
    });
    fireEvent.click(
      screen.getByLabelText(/Download the engine and model files/),
    );
    fireEvent.click(screen.getByText("Install engine automatically"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("install_engine", {
        profile: "mps",
        root: "/engine-managed",
      }),
    );
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });
  it("rejects unsupported HDR on Mac without offering NVIDIA as a solution", async () => {
    await setup(true, true, false, true, "cpu", 0, undefined, "macos");
    expect(
      screen.getByText(/This Mac preview supports SDR input only/),
    ).toBeTruthy();
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
  it("keeps current engine paths when an early native drop subscription fires", async () => {
    let earlyDrop: any;
    await setup(false, true, false, true, "cuda", 0, (callback) => {
      earlyDrop = callback;
    });
    await act(async () =>
      earlyDrop({ payload: { type: "drop", paths: ["/test/other.mp4"] } }),
    );
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("save_settings", {
        settings: expect.objectContaining({
          lastVideo: "/test/other.mp4",
          python: "/engine/python",
          outputDir: "/exports",
        }),
      }),
    );
  });

  it("requires download consent and a destination before installing dependencies", async () => {
    await setup();
    fireEvent.click(screen.getByLabelText("Engine settings"));
    expect(
      (screen.getByText("Install engine automatically") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(
      screen.getByLabelText(/Download the engine and model files/),
    );
    fireEvent.click(screen.getByText("Install engine automatically"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("install_engine", {
        profile: "auto",
        root: "/engine-managed",
      }),
    );
    expect(
      (screen.getByLabelText("Close settings") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByText("Cancel engine setup"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("cancel_engine_setup"),
    );
    await act(async () =>
      mock.setupHandler({
        payload: {
          type: "cancelled",
          message: "Setup cancelled; downloads retained",
        },
      }),
    );
    expect(
      screen.getByLabelText("Engine setup progress").textContent,
    ).toContain("downloads retained");
    expect(
      (screen.getByText("Install engine automatically") as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
  it("adopts verified installation settings without starting conversion", async () => {
    await setup();
    fireEvent.click(screen.getByLabelText("Engine settings"));
    await act(async () =>
      mock.setupHandler({
        payload: {
          type: "complete",
          config: { ...settings, python: "/managed/python" },
          warnings: [],
        },
      }),
    );
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("check_engine", {
        settings: expect.objectContaining({ python: "/managed/python" }),
      }),
    );
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });
  it("shows setup failures and allows retry", async () => {
    await setup();
    fireEvent.click(screen.getByLabelText("Engine settings"));
    fireEvent.click(
      screen.getByLabelText(/Download the engine and model files/),
    );
    fireEvent.click(screen.getByText("Install engine automatically"));
    await act(async () =>
      mock.setupHandler({
        payload: { type: "error", message: "Download hash mismatch" },
      }),
    );
    expect(
      screen.getByLabelText("Engine setup progress").textContent,
    ).toContain("hash mismatch");
    expect(
      (screen.getByText("Install engine automatically") as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("waits for CPU capability detection before planning a restored video", async () => {
    await setup(false, true, true, true, "cpu", 500);
    expect(
      screen.queryByText("CPU startup planned unsupported FPS"),
    ).toBeNull();
    const plans = mock.invoke.mock.calls.filter(
      ([name]) => name === "plan_conversion",
    );
    expect(plans.length).toBeGreaterThan(0);
    expect(
      plans.every(
        ([, args]) =>
          args.settings.resolvedBackend === "cpu" &&
          args.request.fpsMode === "original",
      ),
    ).toBe(true);
  });
  it("uses original FPS and required CPU sensing in CPU compatibility mode", async () => {
    await setup(false, true, false, true, "cpu");
    expect(
      (screen.getByText("Smooth 60 FPS").closest("button") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByLabelText("Required temperature sensors")).toBeNull();
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          settings: expect.objectContaining({ resolvedBackend: "cpu" }),
          request: expect.objectContaining({
            fpsMode: "original",
            preview: true,
            strength: 1.5,
          }),
        }),
      ),
    );
  });
  it("blocks HDR in CPU mode without starting a conversion", async () => {
    await setup(true, true, false, true, "cpu");
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(mock.invoke.mock.calls.some(([name]) => name === "start_job")).toBe(
      false,
    );
  });
  it("blocks CPU conversion when CPU sensing is unavailable", async () => {
    await setup(false, true, false, false, "cpu");
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.queryByLabelText("Required temperature sensors")).toBeNull();
  });
  it("blocks preview and full conversion without required CPU readings", async () => {
    await setup(false, true, false, false);
    expect(
      (screen.getByText("Generate preview") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (
        screen
          .getByText("Convert full video")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(mock.invoke.mock.calls.some((c) => c[0] === "start_job")).toBe(
      false,
    );
    fireEvent.click(screen.getByText("Enable CPU sensor"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "enable_cpu_sensor",
        expect.anything(),
      ),
    );
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("save_settings", {
        settings: expect.objectContaining({
          cpuSensorFile: "/sensor/cpu-sample.json",
        }),
      }),
    );
  });
  it("warns explicitly when GPU-only protection is selected", async () => {
    await setup();
    fireEvent.change(screen.getByLabelText("Required temperature sensors"), {
      target: { value: "gpu" },
    });
    expect(
      screen.getByText("CPU temperature is not protected in GPU-only mode."),
    ).toBeTruthy();
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("save_settings", {
        settings: expect.objectContaining({ thermalMode: "gpu" }),
      }),
    );
  });
  it("keeps thermal readings separate from conversion progress", async () => {
    await setup();
    fireEvent.click(screen.getByText("Generate preview"));
    await act(async () =>
      mock.handler({
        payload: {
          type: "progress",
          stage: "Preparing HDR10 video",
          percent: 20,
        },
      }),
    );
    await act(async () =>
      mock.handler({
        payload: {
          type: "thermal",
          state: "active",
          ready: true,
          cpu: { state: "ready", c: 72 },
          gpu: { state: "ready", c: 61 },
        },
      }),
    );
    expect(screen.getByText("Preparing HDR10 video")).toBeTruthy();
    expect(screen.getByText("Monitoring")).toBeTruthy();
    expect(screen.getByText("72 °C")).toBeTruthy();
  });
  it("finds the engine without starting a conversion and hides advanced paths", async () => {
    await setup();
    fireEvent.click(screen.getByLabelText("Engine settings"));
    expect(
      (document.querySelector(".advanced-settings") as HTMLDetailsElement).open,
    ).toBe(false);
    fireEvent.click(screen.getByText("Find installed engine"));
    await screen.findByText("✓ CUDA Python — found");
    expect(mock.invoke).toHaveBeenCalledWith(
      "find_engine",
      expect.objectContaining({ root: null }),
    );
    expect(mock.invoke.mock.calls.some((c) => c[0] === "start_job")).toBe(
      false,
    );
  });

  it("sends the preferred depth 1.5, neural gap filling and 60 FPS preview request", async () => {
    await setup();
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            strength: 1.5,
            stereoMethod: "forward_inpaint",
            fpsMode: "60",
            preview: true,
            previewSeconds: 10,
          }),
        }),
      ),
    );
  });
  it("can explicitly select the previous fast method and reset the full preferred preset", async () => {
    await setup();
    fireEvent.change(screen.getByLabelText("Gap filling"), {
      target: { value: "row_flow_v3" },
    });
    fireEvent.change(screen.getByLabelText("Depth strength"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByText("Generate preview"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({
            strength: 3,
            stereoMethod: "row_flow_v3",
          }),
        }),
      ),
    );
    await act(async () => mock.handler({ payload: { type: "cancelled" } }));
    fireEvent.click(screen.getByText("1.5 · Your preset"));
    expect(
      (screen.getByLabelText("Depth strength") as HTMLInputElement).value,
    ).toBe("1.5");
    expect(
      (screen.getByLabelText("Gap filling") as HTMLSelectElement).value,
    ).toBe("forward_inpaint");
  });
  it("keeps the full-video action separate from the preview window", async () => {
    await setup();
    fireEvent.click(screen.getByText("Smooth 60 FPS"));
    fireEvent.click(screen.getByText("Convert full video"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith(
        "start_job",
        expect.objectContaining({
          request: expect.objectContaining({ fpsMode: "60", preview: false }),
        }),
      ),
    );
  });
  it("disables duplicate submission and exposes cancellation while working", async () => {
    await setup();
    fireEvent.click(screen.getByText("Generate preview"));
    await screen.findByText("Cancel conversion");
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByText("Cancel conversion"));
    await waitFor(() => expect(mock.invoke).toHaveBeenCalledWith("cancel_job"));
    await act(async () =>
      mock.handler({ payload: { type: "cancelled", message: "Cancelled" } }),
    );
    await screen.findByText("Conversion cancelled");
  });
  it("shows errors and permits another attempt", async () => {
    await setup();
    fireEvent.click(screen.getByText("Generate preview"));
    await act(async () =>
      mock.handler({
        payload: { type: "error", message: "GPU memory exhausted" },
      }),
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "GPU memory exhausted",
    );
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });
  it("reveals the verified output and enables SBS playback", async () => {
    await setup();
    fireEvent.click(screen.getByText("Generate preview"));
    await act(async () =>
      mock.handler({
        payload: {
          type: "complete",
          output: "/exports/result.mp4",
          fps: 60,
          frames: 600,
        },
      }),
    );
    fireEvent.click(screen.getByText("Open output folder"));
    await waitFor(() =>
      expect(mock.invoke).toHaveBeenCalledWith("open_folder", {
        path: "/exports/result.mp4",
      }),
    );
    expect(document.querySelector("video")?.getAttribute("src")).toBe(
      "/exports/result.mp4",
    );
  });
  it("permits HDR previews and identifies HDR preservation", async () => {
    await setup(true);
    expect(screen.getByText(/HDR10 is preserved/)).toBeTruthy();
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });
  it("blocks a full movie with insufficient space while permitting a short preview", async () => {
    await setup(false, false);
    expect(
      (
        screen
          .getByText("Convert full video")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen
          .getByText("Generate preview")
          .closest("button") as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });
  it("does not make an unsupported player codec a conversion error", async () => {
    await setup();
    fireEvent.error(document.querySelector("video")!);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/Conversion remains available/)).toBeTruthy();
  });
  it("restores the selected movie without starting a conversion", async () => {
    await setup(false, true, true);
    expect(mock.invoke).toHaveBeenCalledWith(
      "probe_media",
      expect.objectContaining({ path: "/test/video.mp4" }),
    );
    expect(mock.invoke.mock.calls.some((c) => c[0] === "start_job")).toBe(
      false,
    );
  });
});
