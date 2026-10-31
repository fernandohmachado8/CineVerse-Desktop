import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { invoke, convertFileSrc, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open } from "@tauri-apps/plugin-dialog";
import {
  Aperture,
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clapperboard,
  Cpu,
  FolderOpen,
  Film,
  LoaderCircle,
  Play,
  Settings2,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import "./style.css";

type Settings = {
  managedBackend?: string;
  runtimeProbePassed?: boolean;
  setupTorchVersion?: string;
  setupGpuName?: string;
  python: string;
  iw3Repo: string;
  ffmpeg: string;
  ffprobe: string;
  cache: string;
  rifeRepo: string;
  rifeModel: string;
  outputDir: string;
  lastVideo?: string;
  sensorLibrary?: string;
  cpuSensorFile?: string;
  cpuDriverInstaller?: string;
  thermalMode?: "required" | "gpu" | "macos";
  backend?: "auto" | "cuda" | "cpu" | "mps" | "rocm";
};
type Media = {
  path: string;
  width: number;
  height: number;
  fps: number;
  duration: number;
  hdr: boolean;
  hasAudio: boolean;
};
type Plan = {
  spaceBudgetBytes: number;
  freeBytes: number;
  enoughSpace: boolean;
  estimatedSecondsLow: number | null;
  estimatedSecondsHigh: number | null;
  outputEstimateBytesLow: number;
  outputEstimateBytesHigh: number;
};
type SavedJob = {
  path: string;
  source: string;
  request: Record<string, unknown>;
  completedStages: string[];
  running: boolean;
  status: string;
  log: string;
};
type Engine = {
  ready: boolean;
  gpu: string;
  rifeReady: boolean;
  neuralReady?: boolean;
  gpuUuid?: string;
  backend?: "cuda" | "cpu" | "mps" | "rocm";
  gpuBinding?: { name: string; deviceCount: number; hardwareType: string };
  platform?: string;
  supportsHDR?: boolean;
  supports60?: boolean;
  maxWidth?: number;
  codec?: string;
  note?: string;
};
type Thermal = {
  ready: boolean;
  state?: string;
  reason?: string;
  cpu: {
    state: string;
    c?: number;
    message?: string;
    label?: string;
    thermalState?: number;
  };
  gpu: { state: string; c?: number; message?: string };
};
type Component = {
  key: string;
  label: string;
  found: boolean;
  optional?: boolean;
};
type SetupEvent = {
  type: string;
  stage?: string;
  message?: string;
  percent?: number | null;
  config?: Settings;
  warnings?: string[];
};
type HardwareInventory = {
  state: string;
  architecture?: string;
  cpu?: { name: string; manufacturer: string };
  gpus: { name: string; driverVersion?: string }[];
  message?: string;
  cpuSensorDriverInstalled?: boolean;
};
type StereoMethod = "forward_inpaint" | "row_flow_v3";
type Progress = {
  type: string;
  stage?: string;
  percent?: number | null;
  eta?: number | null;
  message?: string;
  output?: string;
  report?: string;
  log?: string;
  fps?: number;
  frames?: number;
};
const empty: Settings = {
  python: "",
  iw3Repo: "",
  ffmpeg: "",
  ffprobe: "",
  cache: "",
  rifeRepo: "",
  rifeModel: "",
  outputDir: "",
};
export const duration = (s: number) =>
  s >= 3600
    ? `${Math.floor(s / 3600)}:${Math.floor((s / 60) % 60)
        .toString()
        .padStart(2, "0")}:${Math.floor(s % 60)
        .toString()
        .padStart(2, "0")}`
    : `${Math.floor(s / 60)}:${Math.floor(s % 60)
        .toString()
        .padStart(2, "0")}`;
const basename = (p: string) => p.split(/[\\/]/).pop() || p;

export function App() {
  const [settings, setSettings] = useState<Settings>(empty),
    [settingsOpen, setSettingsOpen] = useState(false);
  const [engine, setEngine] = useState<Engine | null>(null),
    [checking, setChecking] = useState(false);
  const [thermal, setThermal] = useState<Thermal | null>(null),
    [sensorStarting, setSensorStarting] = useState(false);
  const [hostPlatform, setHostPlatform] = useState("windows");
  const isMac = hostPlatform === "macos" || engine?.platform === "macos";
  const [setupRoot, setSetupRoot] = useState("");
  const [setupProfile, setSetupProfile] = useState("auto");
  const [hardwareInventory, setHardwareInventory] =
    useState<HardwareInventory | null>(null);
  const [awaitingSensorDriver, setAwaitingSensorDriver] = useState(false);
  const [protectionSetupNotice, setProtectionSetupNotice] = useState("");
  const [setupConsent, setSetupConsent] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const [setupProgress, setSetupProgress] = useState<SetupEvent | null>(null);
  const [setupLogs, setSetupLogs] = useState<string[]>([]);
  const [setupWarnings, setSetupWarnings] = useState<string[]>([]);
  const [detecting, setDetecting] = useState(false),
    [components, setComponents] = useState<Component[]>([]);
  const [media, setMedia] = useState<Media | null>(null),
    [path, setPath] = useState(""),
    [probing, setProbing] = useState(false);
  const [strength, setStrength] = useState(1.5),
    [stereoMethod, setStereoMethod] = useState<StereoMethod>("forward_inpaint"),
    [fpsMode, setFpsMode] = useState("60");
  const [plan, setPlan] = useState<Plan | null>(null),
    [savedJobs, setSavedJobs] = useState<SavedJob[]>([]),
    [playerError, setPlayerError] = useState(false);
  const [start, setStart] = useState(0),
    [length, setLength] = useState(10);
  const [busy, setBusy] = useState(false),
    [cancelling, setCancelling] = useState(false),
    [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null),
    [error, setError] = useState(""),
    [result, setResult] = useState<Progress | null>(null);
  const [view, setView] = useState("original"),
    [history, setHistory] = useState<Progress[]>([]);
  const [startedAt, setStartedAt] = useState(0),
    [now, setNow] = useState(Date.now());
  const native = isTauri(),
    videoRef = useRef<HTMLVideoElement>(null);
  const setFailure = (e: unknown) => setError(String(e));
  async function check(s: Settings) {
    setChecking(true);
    setEngine(null);
    try {
      const info = await invoke<Engine>("check_engine", { settings: s });
      setEngine(info);
      setThermal(null);
      if (info.supports60 === false || !info.rifeReady) setFpsMode("original");
      return true;
    } catch (e) {
      setFailure(e);
      return false;
    } finally {
      setChecking(false);
    }
  }
  async function loadVideo(p: string, s = settings) {
    if (busy) return;
    setPath(p);
    setError("");
    setPlayerError(false);
    setProbing(true);
    setResult(null);
    setView("original");
    setMedia(null);
    setStart(0);
    try {
      setMedia(await invoke("probe_media", { settings: s, path: p }));
      if (s.lastVideo !== p) {
        const recent = { ...s, lastVideo: p };
        setSettings(recent);
        await invoke("save_settings", { settings: recent });
      }
    } catch (e) {
      setFailure(e);
    } finally {
      setProbing(false);
    }
  }
  useEffect(() => {
    if (!native) return;
    void invoke<{ defaultRoot: string; platform?: string }>("setup_info")
      .then((info) => {
        if (info?.defaultRoot) setSetupRoot(info.defaultRoot);
        if (info?.platform) setHostPlatform(info.platform);
      })
      .catch(() => {});
    void invoke<HardwareInventory>("hardware_info")
      .then((info) => setHardwareInventory(info || null))
      .catch(() =>
        setHardwareInventory({
          state: "unavailable",
          gpus: [],
          message:
            "Hardware information unavailable; Automatic setup will check again.",
        }),
      );
    const sub = listen<SetupEvent>("engine-setup", ({ payload: p }) => {
      if (p.type === "log") {
        setSetupLogs((lines) => [...lines.slice(-39), p.message || ""]);
        return;
      }
      setSetupProgress(p);
      if (["error", "cancelled", "complete"].includes(p.type))
        setSetupBusy(false);
      if (p.type === "complete" && p.config) {
        setSettings(p.config);
        setSetupWarnings(p.warnings || []);
        setError("");
        setThermal(null);
        void check(p.config).then((ok) => {
          if (ok) setSettingsOpen(false);
        });
      }
    });
    return () => {
      void sub.then((unlisten) => unlisten());
    };
  }, []);
  async function chooseSetupLocation() {
    try {
      const folder = await open({
        directory: true,
        multiple: false,
        title: "Choose a drive or parent folder for the AI engine",
      });
      if (typeof folder === "string")
        setSetupRoot(
          folder.replace(/[\\/]$/, "") +
            (isMac
              ? "/CineVerse-Mac-Engine-0.7"
              : "/CineVerse-Automatic-Engine-0.8"),
        );
    } catch (e) {
      setFailure(e);
    }
  }
  async function installEngine() {
    setSetupBusy(true);
    setSetupLogs([]);
    setSetupWarnings([]);
    setSetupProgress({
      type: "progress",
      stage: "Starting setup",
      message: "Preparing a private engine installation",
    });
    try {
      await invoke("install_engine", {
        profile: setupProfile,
        root: setupRoot,
      });
    } catch (e) {
      setSetupBusy(false);
      setSetupProgress({ type: "error", message: String(e) });
    }
  }
  async function cancelSetup() {
    try {
      await invoke("cancel_engine_setup");
      setSetupProgress({
        type: "progress",
        stage: "Cancelling setup",
        message: "Waiting for owned installers to stop",
      });
    } catch (e) {
      setFailure(e);
    }
  }
  async function openDriver() {
    try {
      await invoke("open_cpu_driver", { settings });
    } catch (e) {
      setFailure(e);
    }
  }
  useEffect(() => {
    if (!native) return;
    invoke<Settings>("load_settings")
      .then((s) => {
        setSettings(s);
        if (s.python) {
          void check(s).then((ok) => {
            if (!ok) setSettingsOpen(true);
          });
          if (s.lastVideo) void loadVideo(s.lastVideo, s);
        } else setSettingsOpen(true);
      })
      .catch(setFailure);
    const sub = listen<Progress>("conversion", ({ payload: p }) => {
      if (p.type === "thermal") {
        setThermal(p as unknown as Thermal);
        return;
      }
      setProgress(p);
      if (["complete", "error", "cancelled"].includes(p.type)) {
        setBusy(false);
        setCancelling(false);
      }
      if (p.type === "complete") {
        setResult(p);
        setView("sbs");
        setHistory((h) => [p, ...h].slice(0, 4));
      }
      if (p.type === "error") setError(p.message || "Conversion failed");
    });
    return () => {
      void sub.then((unlisten) => unlisten());
    };
  }, []);
  // Native event subscriptions can settle after a settings update. Keep one
  // subscription and read the latest handler instead of capturing old paths.
  const nativeDrop = useRef<(event: any) => void>(() => {});
  nativeDrop.current = (event) => {
    setDragging(
      event.payload.type === "over" || event.payload.type === "enter",
    );
    if (event.payload.type === "drop" && !busy && !setupBusy) {
      const file = event.payload.paths[0];
      if (file) void loadVideo(file);
    }
  };
  useEffect(() => {
    if (!native) return;
    const sub = getCurrentWebview().onDragDropEvent((event) =>
      nativeDrop.current(event),
    );
    return () => {
      void sub.then((unlisten) => unlisten());
    };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!native || !settings.outputDir || busy) return;
    invoke<SavedJob[]>("list_jobs", { settings })
      .then((j) => setSavedJobs(j || []))
      .catch(setFailure);
  }, [settings.outputDir, busy]);
  useEffect(() => {
    if (!media || !settings.outputDir || busy || !engine?.ready) return;
    let current = true;
    setPlan(null);
    const timer = setTimeout(() => {
      invoke<Plan>("plan_conversion", {
        settings: { ...settings, resolvedBackend: engine?.backend },
        request: {
          source: media.path,
          outputDir: settings.outputDir,
          strength,
          stereoMethod,
          fpsMode,
          preview: false,
        },
      })
        .then((p) => {
          if (current) setPlan(p);
        })
        .catch((e) => {
          if (current) setFailure(e);
        });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [
    media?.path,
    settings.outputDir,
    strength,
    stereoMethod,
    fpsMode,
    engine?.backend,
    engine?.ready,
    busy,
  ]);
  useEffect(() => {
    if (!native || !engine?.ready || busy) return;
    let active = true;
    async function poll() {
      try {
        const t = await invoke<Thermal>("thermal_status", {
          settings: {
            ...settings,
            gpuUuid: engine!.gpuUuid,
            gpuBinding: engine!.gpuBinding,
            resolvedBackend: engine!.backend,
          },
        });
        if (active) setThermal(t);
      } catch (e) {
        if (active) setThermal(null);
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [
    engine?.gpuUuid,
    engine?.gpuBinding?.name,
    engine?.backend,
    settings.cpuSensorFile,
    settings.thermalMode,
    busy,
  ]);
  async function enableSensor() {
    setSensorStarting(true);
    setError("");
    try {
      const result = await invoke<{ cpuSensorFile: string }>(
        "enable_cpu_sensor",
        { settings: { ...settings, resolvedBackend: engine?.backend } },
      );
      const s = { ...settings, ...result };
      setSettings(s);
      await invoke("save_settings", { settings: s });
    } catch (e) {
      setFailure(e);
    } finally {
      setSensorStarting(false);
    }
  }
  async function setupProtection() {
    if (
      !isMac &&
      hardwareInventory?.cpuSensorDriverInstalled === false &&
      settings.cpuDriverInstaller
    ) {
      try {
        await invoke("open_cpu_driver", { settings });
        setProtectionSetupNotice(
          "Complete the signed PawnIO installer and Windows approval. CineVerse will then request approval for its read-only temperature helper. No paths need to be configured.",
        );
        setAwaitingSensorDriver(true);
      } catch (e) {
        setFailure(e);
      }
    } else await enableSensor();
  }
  useEffect(() => {
    if (!awaitingSensorDriver) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const began = Date.now();
    async function pollDriver() {
      try {
        const info = await invoke<HardwareInventory>("hardware_info");
        if (!active) return;
        if (info?.cpuSensorDriverInstalled) {
          setHardwareInventory(info);
          setAwaitingSensorDriver(false);
          setProtectionSetupNotice(
            "Driver detected. Approve the read-only sensor helper when Windows asks.",
          );
          await enableSensor();
          return;
        }
      } catch {}
      if (!active) return;
      if (Date.now() - began > 300000) {
        setAwaitingSensorDriver(false);
        setProtectionSetupNotice(
          "Driver setup has not finished. Complete its installer, then enable protection again.",
        );
        return;
      }
      timer = setTimeout(() => void pollDriver(), 3000);
    }
    void pollDriver();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [awaitingSensorDriver, settings.python, engine?.backend]);
  async function detect(s = settings, root: string | null = null) {
    setDetecting(true);
    setError("");
    try {
      const result = await invoke<{
        settings: Settings;
        components: Component[];
      }>("find_engine", { settings: s, root });
      setSettings(result.settings);
      setComponents(result.components);
      await invoke("save_settings", { settings: result.settings });
      await check(result.settings);
    } catch (e) {
      setFailure(e);
    } finally {
      setDetecting(false);
    }
  }
  async function locateEngine() {
    try {
      const root = await open({
        directory: true,
        multiple: false,
        title: "Select your CineVerse engine folder",
      });
      if (typeof root === "string")
        await detect(
          {
            ...settings,
            python: "",
            iw3Repo: "",
            ffmpeg: "",
            ffprobe: "",
            cache: "",
            rifeRepo: "",
            rifeModel: "",
            sensorLibrary: "",
            cpuDriverInstaller: "",
            cpuSensorFile: undefined,
            backend: undefined,
            thermalMode: undefined,
            managedBackend: undefined,
            runtimeProbePassed: undefined,
            setupTorchVersion: undefined,
            setupGpuName: undefined,
          },
          root,
        );
    } catch (e) {
      setFailure(e);
    }
  }
  async function protectionMode(value: "required" | "gpu") {
    const s = { ...settings, thermalMode: value };
    setSettings(s);
    setThermal(null);
    try {
      await invoke("save_settings", { settings: s });
    } catch (e) {
      setFailure(e);
    }
  }
  async function changeBackend(
    value: "auto" | "cuda" | "cpu" | "mps" | "rocm",
  ) {
    const next = { ...settings, backend: value };
    setSettings(next);
    setThermal(null);
    setError("");
    try {
      await invoke("save_settings", { settings: next });
      await check(next);
    } catch (e) {
      setFailure(e);
    }
  }
  async function browseVideo() {
    try {
      const selected = await open({
        multiple: false,
        filters: [
          {
            name: "Videos",
            extensions: ["mp4", "mkv", "mov", "webm", "avi", "m4v"],
          },
        ],
      });
      if (typeof selected === "string") await loadVideo(selected);
    } catch (e) {
      setFailure(e);
    }
  }
  async function folder() {
    try {
      const p = await open({
        directory: true,
        multiple: false,
        defaultPath: settings.outputDir || undefined,
      });
      if (typeof p === "string") {
        const s = { ...settings, outputDir: p };
        setSettings(s);
        await invoke("save_settings", { settings: s });
      }
    } catch (e) {
      setFailure(e);
    }
  }
  async function launch(preview: boolean) {
    if (!media) return;
    setError("");
    setBusy(true);
    setCancelling(false);
    setProgress({
      type: "progress",
      stage: "Starting conversion",
      percent: null,
    });
    setStartedAt(Date.now());
    setNow(Date.now());
    try {
      await invoke("start_job", {
        settings: {
          ...settings,
          gpuUuid: engine?.gpuUuid,
          gpuBinding: engine?.gpuBinding,
          resolvedBackend: engine?.backend,
        },
        request: {
          source: media.path,
          outputDir: settings.outputDir,
          strength,
          stereoMethod,
          fpsMode,
          preview,
          previewStart: start,
          previewSeconds: length,
        },
      });
    } catch (e) {
      setBusy(false);
      setFailure(e);
    }
  }
  async function resume(job: SavedJob) {
    setError("");
    setBusy(true);
    setCancelling(false);
    setProgress({
      type: "progress",
      stage: "Recovering saved conversion",
      percent: null,
    });
    setStartedAt(Date.now());
    setNow(Date.now());
    try {
      await invoke("start_job", {
        settings: {
          ...settings,
          gpuUuid: engine?.gpuUuid,
          gpuBinding: engine?.gpuBinding,
          resolvedBackend: engine?.backend,
        },
        request: { ...job.request, resumeJob: job.path },
      });
    } catch (e) {
      setBusy(false);
      setFailure(e);
    }
  }
  async function cancel() {
    setCancelling(true);
    try {
      await invoke("cancel_job");
    } catch (e) {
      setCancelling(false);
      setFailure(e);
    }
  }
  async function reveal(p: string) {
    try {
      await invoke("open_folder", { path: p });
    } catch (e) {
      setFailure(e);
    }
  }
  async function save() {
    setError("");
    try {
      await invoke("save_settings", { settings });
      if (await check(settings)) setSettingsOpen(false);
    } catch (e) {
      setFailure(e);
    }
  }
  const protectionReady = !!thermal?.ready;
  const ready =
    protectionReady &&
    native &&
    !!engine?.ready &&
    !!media &&
    !!settings.outputDir &&
    !busy &&
    !setupBusy &&
    !probing &&
    (fpsMode !== "60" || (engine.rifeReady && engine.supports60 !== false)) &&
    (!media.hdr || engine.supportsHDR !== false) &&
    (stereoMethod !== "forward_inpaint" || engine.neuralReady !== false);
  const fullReady = ready && !!plan?.enoughSpace;
  const playerPath = view === "sbs" ? result?.output : media?.path;
  const stage = progress?.stage || progress?.message || "Ready when you are";
  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="brand-icon">
            <Aperture size={25} />
          </span>
          <strong>
            CineVerse<span>DESKTOP</span>
          </strong>
        </div>
        <div className="header-right">
          <span className="local">
            <i /> Local processing
          </span>
          <button
            className="icon-button"
            title="Engine settings"
            aria-label="Engine settings"
            disabled={busy}
            onClick={() => setSettingsOpen(true)}
          >
            <Settings2 size={19} />
          </button>
        </div>
      </header>
      <main>
        <div className="intro">
          <div>
            <div className="eyebrow">YOUR FILMS. ANOTHER DIMENSION.</div>
            <h1>Bring depth to movie night.</h1>
            <p>Turn a 2D video into a stereo film, ready for your headset.</p>
          </div>
          <span className="version">PREVIEW · 0.8.1</span>
        </div>
        {!native && (
          <div className="notice">
            Interface preview only. Open CineVerse Desktop to choose local files
            and run local conversions.
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            <CircleHelp size={19} />
            <div>
              <strong>Something needs attention</strong>
              <p>{error}</p>
            </div>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={18} />
            </button>
          </div>
        )}
        <section className="processing-profile" aria-label="Processing profile">
          <label htmlFor="processing-backend">Processing</label>
          <select
            id="processing-backend"
            aria-label="Processing backend"
            value={settings.backend || "auto"}
            disabled={!native || busy || checking || setupBusy}
            onChange={(e) =>
              void changeBackend(
                e.target.value as "auto" | "cuda" | "cpu" | "mps" | "rocm",
              )
            }
          >
            <option value="auto">Automatic · detect this PC</option>
            {isMac ? (
              <option value="mps">Apple MPS · experimental</option>
            ) : (
              <>
                <option value="cuda">NVIDIA CUDA · HDR + 60 FPS</option>
                <option value="rocm">
                  AMD Radeon · experimental ROCm engine
                </option>
              </>
            )}
            <option value="cpu">CPU compatibility · SDR / original FPS</option>
          </select>
          <p className="hint">
            {isMac
              ? "Mac preview: SDR / original FPS, software H.264 and Apple system thermal-state supervision. MPS is opt-in and experimental."
              : settings.backend === "rocm" || engine?.backend === "rocm"
                ? "Automatic setup can install the pinned supported Radeon runtime. AMD inference remains experimental and requires matching CPU/Radeon sensors. Software H.264, SDR/original FPS only; unsupported hardware uses CPU compatibility."
                : engine?.backend === "cpu"
                  ? "CPU mode works with supported Intel and AMD x64 processors. It uses software H.264, up to 1280 pixels per eye, original FPS and CPU temperature protection. Work is limited to two logical CPU cores and can be much slower than a GPU."
                  : "NVIDIA mode retains HDR10, optional RIFE smoothing and GPU encoding when supported."}
          </p>
          {engine?.note && <p className="warning">{engine.note}</p>}
          {media?.hdr && engine?.supportsHDR === false && (
            <p className="warning">
              {isMac
                ? "This Mac preview supports SDR input only; HDR preservation is not implemented."
                : "CPU compatibility supports SDR input only. Choose an SDR source or NVIDIA mode; HDR is not converted to SDR automatically."}
            </p>
          )}
        </section>
        {setupWarnings.length > 0 && (
          <div className="notice">
            {setupWarnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
        )}
        <div className="workspace">
          <section className="setup">
            <div className="section-heading">
              <span className="step">01</span>
              <h2>Choose your video</h2>
            </div>
            <button
              className={`dropzone ${dragging ? "dragging" : ""} ${media ? "selected" : ""}`}
              onClick={browseVideo}
              disabled={busy || !native}
            >
              {probing ? (
                <LoaderCircle className="spin" size={27} />
              ) : media ? (
                <Film size={27} />
              ) : (
                <Upload size={27} />
              )}
              <strong>
                {probing
                  ? "Reading video…"
                  : media
                    ? basename(media.path)
                    : "Drop a video here"}
              </strong>
              <span>
                {media
                  ? `${media.width} × ${media.height} · ${media.fps.toFixed(3)} FPS · ${duration(media.duration)}`
                  : "or click to browse your files"}
              </span>
              {!media && <small>MP4, MKV, MOV and more</small>}
            </button>
            <details className="path-entry">
              <summary>Enter a file path</summary>
              <div>
                <input
                  aria-label="Video file path"
                  placeholder="Paste a local video path"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  disabled={busy}
                />
                <button
                  disabled={!native || busy || !path}
                  onClick={() => loadVideo(path)}
                >
                  Load
                </button>
              </div>
            </details>
            {media && (
              <p className="source-format">
                {media.hdr
                  ? engine?.supportsHDR === false
                    ? "HDR10 requires NVIDIA mode"
                    : "HDR10 is preserved · 10-bit HEVC"
                  : "SDR source · H.264 export"}{" "}
                · {engine?.codec || "NVIDIA NVENC"}
              </p>
            )}
            <div className="section-heading">
              <span className="step">02</span>
              <h2>Make it yours</h2>
            </div>
            <div className="depth-label">
              <label htmlFor="depth">Depth strength</label>
              <output>{strength.toFixed(1)}</output>
            </div>
            <input
              id="depth"
              aria-label="Depth strength"
              className="range"
              type="range"
              min="0"
              max="5"
              step="0.25"
              value={strength}
              disabled={busy}
              onChange={(e) => setStrength(Number(e.target.value))}
            />
            <div className="range-labels">
              <span>Subtle</span>
              <button
                disabled={busy}
                onClick={() => {
                  setStrength(1.5);
                  setStereoMethod("forward_inpaint");
                }}
              >
                1.5 · Your preset
              </button>
              <span>Strong</span>
            </div>
            <label className="field-label" htmlFor="gap-filling">
              Gap filling
            </label>
            <select
              id="gap-filling"
              aria-label="Gap filling"
              value={stereoMethod}
              disabled={busy}
              onChange={(e) => setStereoMethod(e.target.value as StereoMethod)}
            >
              <option value="forward_inpaint">Neural · your default</option>
              <option value="row_flow_v3">Fast · previous method</option>
            </select>
            <p className="hint">
              {stereoMethod === "forward_inpaint"
                ? "Generates texture for missing areas. Slower; filled details may soften or flicker."
                : "Faster processing; stretched edges can be more visible."}
            </p>
            {stereoMethod === "forward_inpaint" &&
              engine?.neuralReady === false && (
                <p className="warning">
                  This engine needs a newer iw3 checkout for neural gap filling.
                  Fast remains available.
                </p>
              )}
            <label className="field-label">Motion</label>
            <div className="segmented">
              <button
                aria-pressed={fpsMode === "original"}
                className={fpsMode === "original" ? "active" : ""}
                disabled={busy}
                onClick={() => setFpsMode("original")}
              >
                Original FPS
              </button>
              <button
                aria-pressed={fpsMode === "60"}
                className={fpsMode === "60" ? "active" : ""}
                disabled={busy || engine?.supports60 === false}
                onClick={() => setFpsMode("60")}
              >
                Smooth 60 FPS
              </button>
            </div>
            <p className="hint">
              {fpsMode === "60"
                ? "RIFE creates intermediate frames. Scene-cut guards reduce blending; motion artifacts can still occur."
                : "Keep the source frame rate and the original motion cadence."}
            </p>
            {fpsMode === "60" && engine && !engine.rifeReady && (
              <p className="warning">
                Set up RIFE in Engine settings to enable 60 FPS.
              </p>
            )}
            <div className="section-heading">
              <span className="step">03</span>
              <h2>Save your film</h2>
            </div>
            <button
              className="folder"
              onClick={folder}
              disabled={busy || !native}
            >
              <FolderOpen size={19} />
              <span title={settings.outputDir}>
                {settings.outputDir || "Choose an output folder"}
              </span>
              <ChevronRight size={17} />
            </button>
            <div className="output-spec">
              <span>FULL SBS</span>
              <span>Compatibility margins</span>
              <span>MP4 · AAC stereo</span>
            </div>
            <p className="hint">
              Up to {engine?.maxWidth || 1920} pixels per eye. First audio
              track; subtitles omitted.
            </p>
            <p className="safety">
              <ShieldCheck size={15} /> Your original file stays untouched.
            </p>
            {plan && (
              <div className="preflight" aria-label="Full movie estimate">
                <strong>Full-video estimate</strong>
                <p>
                  Allow {(plan.spaceBudgetBytes / 1024 ** 3).toFixed(0)} GB of
                  temporary space · {(plan.freeBytes / 1024 ** 3).toFixed(0)} GB
                  free
                </p>
                <p>
                  {plan.estimatedSecondsLow != null &&
                  plan.estimatedSecondsHigh != null ? (
                    <>
                      About {duration(plan.estimatedSecondsLow)}–
                      {duration(plan.estimatedSecondsHigh)} processing time
                    </>
                  ) : (
                    "Run a short preview to measure this CPU. Whole-video processing time is not yet estimated."
                  )}
                </p>
                <p>
                  Estimated export{" "}
                  {(plan.outputEstimateBytesLow / 1e9).toFixed(1)}–
                  {(plan.outputEstimateBytesHigh / 1e9).toFixed(1)} GB. Actual
                  time and size vary.
                </p>
                {!plan.enoughSpace && (
                  <p className="warning">
                    Choose a drive with more space. Short previews remain
                    available.
                  </p>
                )}
              </div>
            )}
          </section>
          <section className="preview-section">
            <div className="preview-heading">
              <h2>Screening room</h2>
              <div className="view-switch">
                <button
                  className={view === "original" ? "active" : ""}
                  onClick={() => setView("original")}
                >
                  Original
                </button>
                <button
                  disabled={!result}
                  className={view === "sbs" ? "active" : ""}
                  onClick={() => setView("sbs")}
                >
                  SBS result
                </button>
              </div>
            </div>
            <div className="screen">
              {playerPath ? (
                <video
                  ref={videoRef}
                  key={playerPath}
                  controls
                  preload="metadata"
                  src={convertFileSrc(playerPath)}
                  onLoadedData={() => setPlayerError(false)}
                  onError={() => setPlayerError(true)}
                />
              ) : (
                <div className="screen-empty">
                  <div className="film-mark">
                    <Clapperboard size={47} />
                  </div>
                  <h3>A little depth. A different experience.</h3>
                  <p>Choose a video to start your first preview.</p>
                </div>
              )}
              <div className="screen-caption">
                <span>
                  {view === "sbs" ? "SIDE-BY-SIDE PREVIEW" : "ORIGINAL FOOTAGE"}
                </span>
                <span>
                  {view === "sbs" ? "Use SBS in your VR player" : "2D source"}
                </span>
              </div>
            </div>
            {playerError && (
              <p className="hint">
                This embedded player cannot preview the codec. Conversion
                remains available; review the exported file in Bigscreen.
              </p>
            )}
            <div className="preview-controls">
              <div>
                <label htmlFor="preview-start">Preview starts at</label>
                <div className="number-input">
                  <input
                    id="preview-start"
                    type="number"
                    min="0"
                    max={media ? Math.max(0, media.duration - 0.1) : 0}
                    step="1"
                    value={start}
                    disabled={busy}
                    onChange={(e) => setStart(Number(e.target.value))}
                  />
                  <span>sec</span>
                </div>
              </div>
              <div>
                <label htmlFor="preview-duration">Length</label>
                <select
                  id="preview-duration"
                  value={length}
                  disabled={busy}
                  onChange={(e) => setLength(Number(e.target.value))}
                >
                  <option value="3">3 seconds</option>
                  <option value="10">10 seconds</option>
                  <option value="20">20 seconds</option>
                  <option value="180">3-minute quality test</option>
                </select>
              </div>
              <button
                className="preview-button"
                disabled={!ready}
                onClick={() => launch(true)}
              >
                <Play size={16} /> Generate preview
              </button>
            </div>
            <section
              className="protection-panel"
              aria-label="Temperature protection"
            >
              <div className="protection-heading">
                <ShieldCheck size={18} />
                <h2>Temperature protection</h2>
                <strong>
                  {busy && thermal?.state === "active"
                    ? "Monitoring"
                    : protectionReady
                      ? "Ready to arm"
                      : busy && thermal?.state === "stopping"
                        ? "Stopping"
                        : "Not ready"}
                </strong>
              </div>
              <div className="temperatures">
                <span>
                  {isMac ? "System thermal state" : "CPU"}{" "}
                  <b>
                    {isMac
                      ? thermal?.cpu?.label || "Unavailable"
                      : thermal?.cpu?.c != null
                        ? `${thermal.cpu.c.toFixed(0)} °C`
                        : "Unavailable"}
                  </b>
                </span>
                <span>
                  {isMac ? "Monitoring" : "GPU core"}{" "}
                  <b>
                    {isMac
                      ? "Apple system state"
                      : thermal?.gpu?.c != null
                        ? `${thermal.gpu.c.toFixed(0)} °C`
                        : engine?.backend === "cpu"
                          ? "Not used"
                          : "Unavailable"}
                  </b>
                </span>
              </div>
              {isMac ? (
                <p className="hint">
                  macOS thermal pressure is a system state, not a Celsius
                  reading or separate CPU/GPU sensor.
                </p>
              ) : engine?.backend === "rocm" ? (
                <p className="hint">
                  Both CPU and Radeon GPU Core readings are required. Only one
                  visible ROCm GPU and one matching sensor adapter are accepted.
                  Ambiguous devices block conversion.
                </p>
              ) : engine?.backend === "cpu" ? (
                <p className="hint">
                  CPU protection is required. The GPU is not used or monitored
                  in this profile.
                </p>
              ) : (
                <>
                  <label className="field-label" htmlFor="thermal-mode">
                    Required sensors
                  </label>
                  <select
                    id="thermal-mode"
                    aria-label="Required temperature sensors"
                    disabled={busy}
                    value={settings.thermalMode || "required"}
                    onChange={(e) =>
                      void protectionMode(e.target.value as "required" | "gpu")
                    }
                  >
                    <option value="required">CPU + GPU · recommended</option>
                    <option value="gpu">GPU only · CPU unmonitored</option>
                  </select>
                </>
              )}
              {!isMac &&
                engine?.backend !== "cpu" &&
                engine?.backend !== "rocm" &&
                settings.thermalMode === "gpu" && (
                  <p className="warning">
                    CPU temperature is not protected in GPU-only mode.
                  </p>
                )}
              <p className="hint">
                {isMac
                  ? "Stops immediately at Critical, after 10 seconds at Serious, or after 30 seconds without valid system readings. No automatic restart. These are thermal states, not temperatures."
                  : "CPU: stop at 95 °C for 10 seconds or 100 °C immediately. GPU core: 85 °C for 10 seconds or 90 °C immediately. A required sensor missing for 30 seconds also stops the job. No automatic restart."}
              </p>
              {!isMac &&
                !busy &&
                (thermal?.cpu?.state !== "ready" ||
                  (engine?.backend === "rocm" &&
                    thermal?.gpu?.state !== "ready")) && (
                  <>
                    <button
                      disabled={
                        sensorStarting ||
                        awaitingSensorDriver ||
                        !native ||
                        !settings.python
                      }
                      onClick={() => void setupProtection()}
                    >
                      {awaitingSensorDriver
                        ? "Waiting for driver setup…"
                        : sensorStarting
                          ? "Requesting permission…"
                          : engine?.backend === "rocm"
                            ? "Enable CPU and Radeon sensors"
                            : "Enable CPU sensor"}
                    </button>
                    <p className="hint">
                      Approve Windows administrator access for the read-only
                      sensor helper. Only the sensor runs elevated; it exits
                      when this app closes.
                    </p>
                    {settings.cpuDriverInstaller && (
                      <p className="hint">
                        If PawnIO is missing,{" "}
                        <button onClick={() => void openDriver()}>
                          Open signed CPU driver installer
                        </button>
                        . Complete its Windows approval and setup, then enable
                        the CPU sensor.
                      </p>
                    )}
                  </>
                )}
              {protectionSetupNotice && (
                <p className="hint" role="status">
                  {protectionSetupNotice}
                </p>
              )}
              {!protectionReady && !busy && (
                <p className="warning">
                  Conversion is blocked until required readings are available
                  and below the immediate cutoffs.{" "}
                  {(settings.thermalMode === "gpu" &&
                  engine?.backend !== "cpu" &&
                  engine?.backend !== "rocm"
                    ? thermal?.gpu?.message
                    : thermal?.cpu?.message || thermal?.gpu?.message) ||
                    "Check the engine and enable the CPU sensor."}
                </p>
              )}
              <p className="hint">
                {isMac
                  ? "Apple thermal-state supervision does not guarantee hardware safety or establish VR comfort."
                  : engine?.backend === "cpu"
                    ? "CPU sensing requires supported package/core sensors. Software protection cannot guarantee hardware safety."
                    : "Checks GPU core temperature, not VRAM or hotspot. Software protection cannot guarantee hardware safety."}
              </p>
            </section>
            <div className="job-panel" aria-live="polite">
              <div className="job-title">
                <span className={`status-dot ${busy ? "working" : ""}`} />
                <strong>
                  {busy
                    ? stage
                    : progress?.type === "complete"
                      ? "Your stereo video is ready"
                      : progress?.type === "cancelled"
                        ? "Conversion cancelled"
                        : checking
                          ? "Checking your GPU…"
                          : engine
                            ? protectionReady
                              ? "Ready to convert"
                              : "Waiting for temperature protection"
                            : "Set up your processing engine"}
                </strong>
                {busy && (
                  <span>
                    {progress?.percent == null
                      ? "Working…"
                      : `${Math.round(progress.percent)}%`}
                  </span>
                )}
              </div>
              {busy ? (
                <>
                  <div
                    className={`progress-track ${progress?.percent == null ? "indeterminate" : ""}`}
                  >
                    <div
                      style={{
                        width:
                          progress?.percent == null
                            ? "35%"
                            : `${progress.percent}%`,
                      }}
                    />
                  </div>
                  <div className="job-meta">
                    <span>Elapsed {duration((now - startedAt) / 1000)}</span>
                    <span>
                      {progress?.eta != null && progress.eta > 0
                        ? `About ${duration(progress.eta)} left in this pass`
                        : "Estimating this stage…"}
                    </span>
                  </div>
                </>
              ) : (
                <p>
                  {result
                    ? `${result.frames} frames checked · ${result.fps?.toFixed(3)} FPS · Open the file in Bigscreen using SBS.`
                    : "Try a short preview first. Adjust the depth before converting the full video."}
                </p>
              )}
              <div className="job-actions">
                {busy ? (
                  <button
                    className="cancel"
                    disabled={cancelling}
                    onClick={cancel}
                  >
                    {cancelling ? "Stopping…" : "Cancel conversion"}
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={!fullReady}
                    onClick={() => launch(false)}
                  >
                    Convert full video <ArrowRight size={17} />
                  </button>
                )}
                {result?.output && !busy && (
                  <button
                    className="secondary"
                    onClick={() => reveal(result.output!)}
                  >
                    <FolderOpen size={17} /> Open output folder
                  </button>
                )}
              </div>
              <p className="hint">
                Keeps this PC awake while converting. Closing the app stops the
                job; completed stages can be recovered.
              </p>
            </div>
            <div className="playback-note">
              <span className="note-icon">
                <Film size={19} />
              </span>
              <p>
                <strong>Made for your VR cinema</strong>
                <br />
                Open the exported MP4 in Bigscreen and select <b>SBS</b>, with
                left eye first. This creates screen depth, not a walkable 360°
                scene.
              </p>
            </div>
          </section>
        </div>
        {savedJobs.length > 0 && !busy && (
          <section className="history recovery">
            <h2>Recover an interrupted conversion</h2>
            <p className="hint">
              Completed stages are reused with their saved depth and gap
              filling. The interrupted stage restarts.
            </p>
            {savedJobs.map((job) => (
              <div key={job.path} className="recovery-row">
                <span>
                  {basename(job.source)} · {job.completedStages.length} stages
                  saved · depth {String(job.request.strength)} ·{" "}
                  {job.request.stereoMethod === "forward_inpaint"
                    ? "neural"
                    : "previous fast method"}
                </span>
                <button
                  disabled={job.running || !engine || !protectionReady}
                  onClick={() => resume(job)}
                  aria-label={`Resume ${basename(job.source)}`}
                >
                  {job.running ? "Running" : "Resume"}
                </button>
                <button onClick={() => reveal(job.log)}>Logs</button>
              </div>
            ))}
          </section>
        )}
        {history.length > 0 && (
          <section className="history">
            <h2>This session</h2>
            {history.map((item) => (
              <button key={item.output} onClick={() => reveal(item.output!)}>
                <Check size={17} />
                <span>{basename(item.output!)}</span>
                <FolderOpen size={17} />
              </button>
            ))}
          </section>
        )}
        <footer>
          <span>
            <Cpu size={14} />
            {checking
              ? "Checking engine…"
              : engine?.gpu || "Engine not configured"}
          </span>
          <span>
            {engine?.supports60 === false
              ? "Powered by iw3"
              : "Powered by iw3 + RIFE"}{" "}
            <i>·</i> No cloud upload
          </span>
        </footer>
      </main>
      {settingsOpen && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Engine settings"
          >
            <div className="modal-heading">
              <div>
                <div className="eyebrow">LOCAL PROCESSING</div>
                <h2>Engine settings</h2>
              </div>
              <button
                aria-label="Close settings"
                disabled={setupBusy}
                onClick={() => setSettingsOpen(false)}
              >
                <X size={20} />
              </button>
            </div>
            <p>
              Detect your CPU and GPUs and install the AI engine automatically.
              CineVerse downloads a private Python runtime, video tools and
              model files, checks them and saves all paths for you. Setup never
              starts a movie conversion.
            </p>
            <section
              className="automatic-setup"
              aria-label="Automatic engine setup"
            >
              {!isMac && (
                <div className="notice" aria-label="Detected hardware">
                  <strong>Detected hardware</strong>
                  <p>
                    {hardwareInventory?.cpu?.name ||
                      (hardwareInventory
                        ? "CPU information unavailable"
                        : "Detecting CPU and graphics…")}
                  </p>
                  {hardwareInventory?.gpus?.map((gpu, index) => (
                    <p key={index}>
                      {gpu.name}
                      {gpu.driverVersion
                        ? ` · driver ${gpu.driverVersion}`
                        : ""}
                    </p>
                  ))}
                  {hardwareInventory?.message && (
                    <p>{hardwareInventory.message}</p>
                  )}
                  <p>
                    Automatic checks the installed driver and runtime. Supported
                    AMD cards use an experimental pinned recipe; other systems
                    receive CPU compatibility. No dependency paths are needed.
                  </p>
                </div>
              )}
              <label className="field-label" htmlFor="setup-profile">
                Processing package
              </label>
              <select
                id="setup-profile"
                value={setupProfile}
                disabled={setupBusy}
                onChange={(e) => setSetupProfile(e.target.value)}
              >
                <option value="auto">Automatic · recommended</option>
                <option value="cpu">
                  CPU compatibility · no NVIDIA required
                </option>
                {isMac ? (
                  <option value="mps">Apple MPS · experimental</option>
                ) : (
                  <>
                    <option value="cuda">
                      NVIDIA · HDR and optional 60 FPS
                    </option>
                    <option value="rocm">
                      AMD Radeon · supported recipe · experimental
                    </option>
                  </>
                )}
              </select>
              <p className="hint">
                Several GB of downloads; allow at least {isMac ? "8" : "15"} GiB
                free{isMac ? "" : " (25 GiB for AMD and fallback)"}. You do not
                need to install Python, Git or configure dependency paths.
              </p>
              <p className="engine-location">
                <b>Engine location</b>
                <span>{setupRoot || "Finding the default location…"}</span>
              </p>
              <button
                disabled={!native || setupBusy}
                onClick={() => void chooseSetupLocation()}
              >
                Choose engine drive or folder
              </button>
              <label className="setup-consent">
                <input
                  type="checkbox"
                  checked={setupConsent}
                  disabled={setupBusy}
                  onChange={(e) => setSetupConsent(e.target.checked)}
                />
                Download the engine and model files. Each component keeps its
                original license.
              </label>
              <details>
                <summary>Included components and driver approval</summary>
                <p className="hint">
                  Private CPython (PSF and bundled notices), PyTorch, iw3 (MIT),
                  Depth Anything V2 Small (Apache-2.0), FFmpeg (GPL build),
                  {isMac
                    ? "Mac uses Apple's built-in system thermal state. No PawnIO, Homebrew, kernel driver or administrator sensor helper is installed. Original notices are retained in the engine files. This development build is not Developer ID notarized."
                    : "LibreHardwareMonitor (MPL-2.0), and optional RIFE. Original notices are retained in the engine files. NVIDIA drivers are not installed or changed. CPU sensing uses the signed PawnIO driver: Windows approval and its interactive installer remain your choice."}
                </p>
              </details>
              <button
                className="primary"
                disabled={
                  !native ||
                  setupBusy ||
                  busy ||
                  checking ||
                  !setupRoot ||
                  !setupConsent
                }
                onClick={() => void installEngine()}
              >
                {setupBusy
                  ? "Installing engine…"
                  : "Install engine automatically"}
              </button>
              {setupProgress && (
                <div
                  className="setup-progress"
                  role="status"
                  aria-label="Engine setup progress"
                >
                  <strong>{setupProgress.stage || setupProgress.type}</strong>
                  <p>{setupProgress.message}</p>
                  {(setupBusy || setupProgress.percent != null) && (
                    <progress
                      aria-label="Engine setup stage"
                      value={setupProgress.percent ?? undefined}
                      max="100"
                    />
                  )}
                </div>
              )}
              {setupBusy && (
                <button onClick={() => void cancelSetup()}>
                  Cancel engine setup
                </button>
              )}
              {setupLogs.length > 0 && (
                <details>
                  <summary>Setup details</summary>
                  <pre>{setupLogs.join("\n")}</pre>
                </details>
              )}
            </section>
            <div className="setup-actions">
              <button
                disabled={detecting || checking || !native || setupBusy}
                onClick={() => void detect()}
              >
                {detecting ? "Finding engine…" : "Find installed engine"}
              </button>
              <button
                disabled={detecting || checking || !native || setupBusy}
                onClick={locateEngine}
              >
                Locate engine folder
              </button>
            </div>
            {engine && (
              <p className="setup-success">
                <Check size={16} /> Engine checked · {engine.gpu}
              </p>
            )}
            {error && (
              <p className="warning" role="status">
                {error}
              </p>
            )}
            {components.length > 0 && (
              <ul className="component-list">
                {components.map((c) => (
                  <li key={c.key}>
                    {c.found ? "✓" : "○"} {c.label} —{" "}
                    {c.found
                      ? "found"
                      : c.optional
                        ? "optional · 60 FPS only"
                        : "missing"}
                  </li>
                ))}
              </ul>
            )}
            <p className="hint">
              Already have an engine? Find or locate it above. Advanced paths
              remain available for custom installations.
            </p>
            <details className="advanced-settings">
              <summary>Advanced paths</summary>
              {(
                [
                  "python",
                  "iw3Repo",
                  "ffmpeg",
                  "ffprobe",
                  "cache",
                  "rifeRepo",
                  "rifeModel",
                  "sensorLibrary",
                ] as const
              ).map((key) => (
                <label className="setting" key={key}>
                  <span>
                    {
                      {
                        python: "AI Python executable",
                        iw3Repo: "nunif / iw3 repository folder",
                        ffmpeg: "FFmpeg executable",
                        ffprobe: "FFprobe executable",
                        cache: "Model cache folder",
                        rifeRepo: "Practical-RIFE folder (60 FPS)",
                        rifeModel: "RIFE 4.25 train_log folder (60 FPS)",
                        sensorLibrary:
                          "LibreHardwareMonitor folder (CPU sensor)",
                      }[key]
                    }
                  </span>
                  <input
                    value={settings[key] || ""}
                    onChange={(e) =>
                      setSettings({ ...settings, [key]: e.target.value })
                    }
                  />
                </label>
              ))}
            </details>
            <p className="hint">
              Model files and GPU dependencies are separate from the desktop
              installer. Their original licenses apply.
            </p>
            <button
              className="primary"
              disabled={checking || !native || setupBusy}
              onClick={save}
            >
              {checking ? (
                <LoaderCircle className="spin" size={17} />
              ) : (
                <Check size={17} />
              )}{" "}
              Save and check engine
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
