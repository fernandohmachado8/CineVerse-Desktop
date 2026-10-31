#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod engine_install;
use serde_json::{json, Value};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
};
use tauri::{Emitter, Manager};

struct Active {
    id: String,
    pid: u32,
    cancelled: Arc<AtomicBool>,
}
#[derive(Default)]
struct Jobs(Mutex<Option<Active>>);

fn quiet(cmd: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
}
fn config_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let portable = parent.join("portable.json");
            if portable.is_file() {
                return Ok(portable);
            }
        }
    }
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("settings.json"))
}
#[tauri::command]
fn load_settings(app: tauri::AppHandle) -> Result<Value, String> {
    let path = config_path(&app)?;
    let mut saved: Value = if path.is_file() {
        serde_json::from_slice(&fs::read(&path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?
    } else {
        json!({"python":"","iw3Repo":"","ffmpeg":"","ffprobe":"","cache":"","rifeRepo":"","rifeModel":"","outputDir":""})
    };
    // An elevated CPU reader is bound to one app session, never a saved promise
    // of active protection after reopening the app.
    if let Some(object) = saved.as_object_mut() {
        object.remove("cpuSensorFile");
    }
    if saved["python"].as_str().unwrap_or("").is_empty() {
        let managed = engine_install::default_root(&app)?.join("engine.json");
        if let Ok(data) = fs::read(managed) {
            if let Ok(value) = serde_json::from_slice::<Value>(&data) {
                saved = value;
            }
        }
    }
    Ok(saved)
}
fn engine_roots(root: Option<String>) -> Vec<PathBuf> {
    if let Some(root) = root {
        return vec![PathBuf::from(root)];
    }
    let mut roots = Vec::new();
    #[cfg(windows)]
    for letter in b'C'..=b'Z' {
        let root = format!("{}:\\", letter as char);
        let wide: Vec<u16> = root.encode_utf16().chain(Some(0)).collect();
        if unsafe { GetDriveTypeW(wide.as_ptr()) } != 3 {
            continue;
        }
        let folder = PathBuf::from(root).join("CineVerse");
        if folder.is_dir() {
            roots.push(folder);
        }
    }
    roots
}
fn discover(
    app: &tauri::AppHandle,
    mut settings: Value,
    root: Option<String>,
) -> Result<Value, String> {
    let roots = engine_roots(root);
    // Bootstrap only from a selected/known manifest or bounded venv folder.
    if !settings["python"]
        .as_str()
        .is_some_and(|p| PathBuf::from(p).is_file())
    {
        for root in &roots {
            for name in ["engine.json", "portable.json", "App/portable.json"] {
                if let Ok(data) = fs::read(root.join(name)) {
                    if let Ok(v) = serde_json::from_slice::<Value>(&data) {
                        if v["python"]
                            .as_str()
                            .is_some_and(|p| PathBuf::from(p).is_file())
                        {
                            settings["python"] = v["python"].clone();
                            break;
                        }
                    }
                }
            }
            if settings["python"]
                .as_str()
                .is_some_and(|p| PathBuf::from(p).is_file())
            {
                break;
            }
            if let Ok(entries) = fs::read_dir(root.join("environments")) {
                for entry in entries.flatten() {
                    let p = entry.path().join("Scripts/python.exe");
                    if p.is_file() {
                        settings["python"] = json!(p);
                        break;
                    }
                }
            }
        }
    }
    if !settings["python"]
        .as_str()
        .is_some_and(|p| PathBuf::from(p).is_file())
    {
        return Err("No installed AI Python found. Select the CineVerse engine folder, or use Advanced paths. This installer does not download the AI engine.".into());
    }
    run_short(app, "discover", settings, json!({"roots":roots}))
}
#[tauri::command]
fn save_settings(app: tauri::AppHandle, settings: Value) -> Result<(), String> {
    if !settings.is_object() {
        return Err("Settings must be an object".into());
    }
    fs::write(
        config_path(&app)?,
        serde_json::to_vec_pretty(&settings).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())
}
fn worker(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let path = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("worker/worker.py");
    if path.is_file() {
        return Ok(path);
    }
    #[cfg(debug_assertions)]
    {
        let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../worker/worker.py");
        if dev.is_file() {
            return Ok(dev);
        }
    }
    Err("Processing worker is missing. Reinstall CineVerse Desktop.".into())
}
fn command(app: &tauri::AppHandle, mode: &str, config: &Value) -> Result<Command, String> {
    let python = config["python"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("Choose the AI Python executable in Engine settings.")?;
    if !PathBuf::from(python).is_file() {
        return Err("AI Python executable was not found. Check Engine settings.".into());
    }
    let mut cmd = Command::new(python);
    cmd.arg("-u")
        .arg(worker(app)?)
        .arg(mode)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONNOUSERSITE", "1")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME");
    quiet(&mut cmd);
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
        cmd.env("CINEVERSE_OWN_PROCESS_GROUP", "1");
    }
    Ok(cmd)
}
fn run_short(
    app: &tauri::AppHandle,
    mode: &str,
    config: Value,
    request: Value,
) -> Result<Value, String> {
    let mut child = command(app, mode, &config)?
        .spawn()
        .map_err(|e| e.to_string())?;
    child
        .stdin
        .take()
        .ok_or("Worker input unavailable")?
        .write_all(
            json!({"config":config,"request":request})
                .to_string()
                .as_bytes(),
        )
        .map_err(|e| e.to_string())?;
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    serde_json::from_slice(&output.stdout).map_err(|e| format!("Invalid worker response: {e}"))
}
#[tauri::command]
async fn check_engine(app: tauri::AppHandle, settings: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_short(&app, "check", settings, json!({})))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn find_engine(
    app: tauri::AppHandle,
    settings: Value,
    root: Option<String>,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || discover(&app, settings, root))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn thermal_status(app: tauri::AppHandle, settings: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_short(&app, "thermal", settings, json!({})))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn enable_cpu_sensor(app: tauri::AppHandle, settings: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_short(
            &app,
            "sensor",
            settings,
            json!({"parentPid":std::process::id()}),
        )
    })
    .await
    .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn plan_conversion(
    app: tauri::AppHandle,
    settings: Value,
    request: Value,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_short(&app, "plan", settings, request))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
async fn list_jobs(app: tauri::AppHandle, settings: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_short(&app, "jobs", settings, json!({})))
        .await
        .map_err(|e| e.to_string())?
}

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn SetThreadExecutionState(flags: u32) -> u32;
    fn GetDriveTypeW(path: *const u16) -> u32;
}
struct WakeLock {
    #[cfg(target_os = "macos")]
    process: Option<std::process::Child>,
}
impl WakeLock {
    fn acquire() -> Self {
        #[cfg(windows)]
        unsafe {
            SetThreadExecutionState(0x80000001);
        };
        Self {
            #[cfg(target_os = "macos")]
            process: Command::new("/usr/bin/caffeinate")
                .args(["-i", "-w", &std::process::id().to_string()])
                .spawn()
                .ok(),
        }
    }
}
impl Drop for WakeLock {
    fn drop(&mut self) {
        #[cfg(target_os = "macos")]
        if let Some(mut p) = self.process.take() {
            let _ = p.kill();
            let _ = p.wait();
        }
        #[cfg(windows)]
        unsafe {
            SetThreadExecutionState(0x80000000);
        };
    }
}
#[tauri::command]
async fn probe_media(
    app: tauri::AppHandle,
    settings: Value,
    path: String,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let result = run_short(&app, "probe", settings, json!({"source":path}))?;
        app.asset_protocol_scope()
            .allow_file(&path)
            .map_err(|e| e.to_string())?;
        Ok(result)
    })
    .await
    .map_err(|e| e.to_string())?
}
fn stop_tree(pid: u32) {
    #[cfg(windows)]
    {
        let mut cmd = Command::new("taskkill");
        cmd.args(["/PID", &pid.to_string(), "/T", "/F"]);
        quiet(&mut cmd);
        let _ = cmd.output();
    }
    #[cfg(unix)]
    {
        extern "C" {
            fn kill(pid: i32, signal: i32) -> i32;
            fn getpgid(pid: i32) -> i32;
        }
        if unsafe { getpgid(pid as i32) } == pid as i32 {
            unsafe {
                kill(-(pid as i32), 15);
            }
        }
    }
}
#[tauri::command]
fn cancel_job(jobs: tauri::State<Jobs>) -> Result<(), String> {
    let lock = jobs.0.lock().map_err(|e| e.to_string())?;
    if let Some(active) = lock.as_ref() {
        active.cancelled.store(true, Ordering::SeqCst);
        stop_tree(active.pid);
    }
    Ok(())
}
#[tauri::command]
fn start_job(
    app: tauri::AppHandle,
    jobs: tauri::State<Jobs>,
    settings: Value,
    request: Value,
) -> Result<String, String> {
    let installer = app.state::<engine_install::Installer>();
    let setup = installer.0.lock().map_err(|e| e.to_string())?;
    if setup.is_some() {
        return Err("Finish engine setup before starting a conversion.".into());
    }
    let mut lock = jobs.0.lock().map_err(|e| e.to_string())?;
    if lock.is_some() {
        return Err("A conversion is already running.".into());
    }
    let mut child = command(&app, "run", &settings)?
        .spawn()
        .map_err(|e| e.to_string())?;
    let write = child
        .stdin
        .take()
        .ok_or("Worker input unavailable")?
        .write_all(
            json!({"config":settings,"request":request})
                .to_string()
                .as_bytes(),
        );
    if let Err(e) = write {
        let _ = child.kill();
        return Err(e.to_string());
    }
    let stdout = child.stdout.take().ok_or("Worker output unavailable")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Worker error output unavailable")?;
    let id = uuid::Uuid::new_v4().to_string();
    let cancelled = Arc::new(AtomicBool::new(false));
    *lock = Some(Active {
        id: id.clone(),
        pid: child.id(),
        cancelled: cancelled.clone(),
    });
    let job_id = id.clone();
    drop(lock);
    drop(setup);
    drop(installer);
    std::thread::spawn(move || {
        let _awake = WakeLock::acquire();
        let errors = std::thread::spawn(move || {
            use std::io::Read;
            let mut text = String::new();
            let _ = BufReader::new(stderr).read_to_string(&mut text);
            text
        });
        let mut terminal = None;
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(mut event) = serde_json::from_str::<Value>(&line) {
                event["jobId"] = json!(job_id);
                if event["type"] == "complete" || event["type"] == "error" {
                    terminal = Some(event);
                } else {
                    let _ = app.emit("conversion", event);
                }
            }
        }
        let status = child.wait();
        let error = errors.join().unwrap_or_default();
        let event = if cancelled.load(Ordering::SeqCst) {
            json!({"type":"cancelled","jobId":job_id,"message":"Conversion cancelled. Your source was not modified."})
        } else if status.as_ref().map(|s| s.success()).unwrap_or(false) {
            terminal.unwrap_or(json!({"type":"error","jobId":job_id,"message":"Worker stopped without producing a verified output."}))
        } else {
            terminal.unwrap_or(json!({"type":"error","jobId":job_id,"message":if error.is_empty(){"Processing stopped unexpectedly. Check available memory and Engine settings.".to_string()}else{error}}))
        };
        if let Some(path) = event["output"].as_str() {
            let _ = app.asset_protocol_scope().allow_file(path);
        }
        {
            let state = app.state::<Jobs>();
            if let Ok(mut lock) = state.0.lock() {
                if lock.as_ref().map(|a| a.id.as_str()) == Some(job_id.as_str()) {
                    *lock = None;
                }
            };
        }
        let _ = app.emit("conversion", event);
    });
    Ok(id)
}
#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    let input = PathBuf::from(path);
    let dir = if input.is_dir() {
        input
    } else {
        input.parent().ok_or("Invalid output path")?.to_path_buf()
    };
    let dir = dir.canonicalize().map_err(|e| e.to_string())?;
    #[cfg(windows)]
    let mut cmd = Command::new("explorer.exe");
    #[cfg(target_os = "macos")]
    let mut cmd = Command::new("/usr/bin/open");
    #[cfg(all(not(windows), not(target_os = "macos")))]
    let mut cmd = Command::new("xdg-open");
    cmd.arg(dir);
    cmd.spawn().map_err(|e| e.to_string())?;
    Ok(())
}
fn main() {
    // Reproducible setup-only path using the exact packaged bootstrap; no conversion.
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--setup-engine") {
        let result = (|| {
            let root = PathBuf::from(args.get(2).ok_or("Supply an empty engine folder")?);
            let profile = args.get(3).map(String::as_str).unwrap_or("cpu");
            let exe = std::env::current_exe().map_err(|e| e.to_string())?;
            let parent = exe.parent().ok_or("Missing resource folder")?;
            let resource = if cfg!(target_os = "macos") {
                parent
                    .parent()
                    .ok_or("Missing app bundle")?
                    .join("Resources")
            } else {
                parent.to_path_buf()
            };
            engine_install::run_install(&root, profile, &resource, &AtomicBool::new(false), &|v| {
                println!("{v}")
            })
        })();
        match result {
            Ok(v) => {
                println!("{v}");
                std::process::exit(0)
            }
            Err(e) => {
                eprintln!("{e}");
                std::process::exit(1)
            }
        }
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(Jobs::default())
        .manage(engine_install::Installer::default())
        .invoke_handler(tauri::generate_handler![
            engine_install::setup_info,
            engine_install::install_engine,
            engine_install::cancel_engine_setup,
            engine_install::open_cpu_driver,
            load_settings,
            save_settings,
            check_engine,
            find_engine,
            thermal_status,
            enable_cpu_sensor,
            probe_media,
            plan_conversion,
            list_jobs,
            start_job,
            cancel_job,
            open_folder
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Ok(lock) = window.state::<engine_install::Installer>().0.lock() {
                    if let Some(flag) = lock.as_ref() {
                        flag.store(true, Ordering::SeqCst);
                    }
                };
                let state = window.state::<Jobs>();
                if let Ok(lock) = state.0.lock() {
                    if let Some(active) = lock.as_ref() {
                        active.cancelled.store(true, Ordering::SeqCst);
                        stop_tree(active.pid);
                    }
                };
            }
        })
        .run(tauri::generate_context!())
        .expect("Unable to launch CineVerse Desktop");
}
