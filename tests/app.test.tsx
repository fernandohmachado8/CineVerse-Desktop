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
};
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
) {
  mock.invoke.mockImplementation(async (name: string, args: any) => {
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
        path: "/test/video.mp4",
        width: 1920,
        height: 804,
        fps: 23.976,
        duration: 180,
        hdr,
        hasAudio: true,
      };
    if (name === "list_jobs") return [];
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
      screen.getByText(/Radeon preview requires a separately prepared/),
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
      screen.getByText(/Radeon preview requires a separately prepared/),
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
