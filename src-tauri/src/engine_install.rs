//! Private runtime bootstrap and supervised setup; no system Python/Git required.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};

#[derive(Default)]
pub struct Installer(pub Mutex<Option<Arc<AtomicBool>>>);

pub fn default_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .local_data_dir()
        .map_err(|e| e.to_string())?
        .join("CineVerse")
        .join("Engines")
        .join(if cfg!(target_os = "macos") {
            "0.7-macos"
        } else {
            "0.8-auto"
        }))
}
fn resources(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let path = app.path().resource_dir().map_err(|e| e.to_string())?;
    if path.join("requirements/engine-manifest.json").is_file() {
        return Ok(path);
    }
    #[cfg(debug_assertions)]
    {
        return Ok(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".."));
    }
    #[cfg(not(debug_assertions))]
    Err("Setup resources are missing. Reinstall the application.".into())
}
fn cancelled(flag: &AtomicBool) -> Result<(), String> {
    if flag.load(Ordering::SeqCst) {
        Err("Setup cancelled. Verified downloads are retained for retry.".into())
    } else {
        Ok(())
    }
}
pub fn hash(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = file.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}
fn verified(path: &Path, expected: &str) -> Result<(), String> {
    if hash(path)? != expected {
        return Err("Download SHA-256 verification failed. Setup stopped before execution.".into());
    }
    Ok(())
}
fn download(
    asset: &Value,
    file: &Path,
    flag: &AtomicBool,
    emit: &dyn Fn(Value),
) -> Result<(), String> {
    cancelled(flag)?;
    let expected = asset["sha256"].as_str().ok_or("Missing download digest")?;
    if file.exists() {
        return verified(file, expected);
    }
    let url = asset["url"].as_str().ok_or("Missing download URL")?;
    let client = reqwest::blocking::Client::builder()
        .https_only(true)
        .user_agent("CineVerse-Desktop-setup/0.6")
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(180))
        .build()
        .map_err(|e| e.to_string())?;
    let mut response = client
        .get(url)
        .send()
        .and_then(|r| r.error_for_status())
        .map_err(|e| format!("Runtime download failed: {e}. Check your connection and retry."))?;
    let total = response.content_length();
    let part = file.with_extension("part");
    let mut output = File::create(&part).map_err(|e| e.to_string())?;
    let mut buf = [0u8; 65536];
    let mut done = 0u64;
    let mut last = Instant::now() - Duration::from_secs(1);
    loop {
        cancelled(flag)?;
        let n = response.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        done += n as u64;
        if done > 256 * 1024 * 1024 {
            return Err("Runtime download exceeds its size budget.".into());
        }
        output.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        if last.elapsed() > Duration::from_millis(200) {
            emit(
                json!({"type":"progress","stage":"Installing private Python","message":"Downloading the verified runtime","bytes":done,"totalBytes":total,"percent":total.map(|t|100.0*done as f64/t as f64)}),
            );
            last = Instant::now();
        }
    }
    output.sync_all().map_err(|e| e.to_string())?;
    drop(output);
    verified(&part, expected)?;
    fs::rename(part, file).map_err(|e| e.to_string())
}
fn valid_archive_path(path: &Path) -> bool {
    !path.is_absolute()
        && path
            .components()
            .all(|c| matches!(c, Component::Normal(_) | Component::CurDir))
        && !path.to_string_lossy().contains(':')
        && !path.to_string_lossy().contains('\\')
        && path
            .components()
            .next()
            .is_some_and(|c| c.as_os_str() == "python")
}
fn safe_link(path: &Path, target: &Path, symbolic: bool) -> bool {
    if target.is_absolute()
        || target.to_string_lossy().contains(':')
        || target.to_string_lossy().contains('\\')
    {
        return false;
    }
    let joined = if symbolic {
        path.parent().unwrap_or(Path::new("")).join(target)
    } else {
        target.to_path_buf()
    };
    let mut parts = Vec::new();
    for c in joined.components() {
        match c {
            Component::Normal(p) => parts.push(p),
            Component::CurDir => {}
            Component::ParentDir => {
                if parts.len() <= 1 {
                    return false;
                }
                parts.pop();
            }
            _ => return false,
        }
    }
    parts.first().is_some_and(|p| *p == "python")
}
fn unpack_python(archive: &Path, destination: &Path, flag: &AtomicBool) -> Result<(), String> {
    let gzip = flate2::read::GzDecoder::new(File::open(archive).map_err(|e| e.to_string())?);
    let mut tar = tar::Archive::new(gzip);
    let mut size = 0u64;
    for entry in tar.entries().map_err(|e| e.to_string())? {
        cancelled(flag)?;
        let mut entry = entry.map_err(|e| e.to_string())?;
        let kind = entry.header().entry_type();
        let path = entry.path().map_err(|e| e.to_string())?;
        let link_ok = if cfg!(unix) && (kind.is_symlink() || kind.is_hard_link()) {
            let target = entry
                .link_name()
                .map_err(|e| e.to_string())?
                .ok_or("Missing runtime link target")?;
            safe_link(&path, &target, kind.is_symlink())
        } else {
            false
        };
        if !valid_archive_path(&path) || !(kind.is_file() || kind.is_dir() || link_ok) {
            return Err("Unsafe runtime archive entry refused.".into());
        }
        size += entry.size();
        if size > 2 * 1024 * 1024 * 1024 {
            return Err("Runtime extraction exceeds its size budget.".into());
        }
        if !entry.unpack_in(destination).map_err(|e| e.to_string())? {
            return Err("Runtime archive path escapes its destination.".into());
        }
    }
    Ok(())
}
fn claim_root(root: &Path, identity: &str) -> Result<File, String> {
    if !root.is_absolute() || root.parent().is_none() || root.file_name().is_none() {
        return Err("Choose an absolute engine folder, not a drive root.".into());
    }
    fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let marker = root.join(".cineverse-managed.json");
    let expected = json!({"schema":1,"runtimeSha256":identity});
    if marker.exists() {
        let found: Value = serde_json::from_slice(&fs::read(&marker).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        if found != expected {
            return Err(
                "This folder belongs to another engine version. Choose a new empty folder.".into(),
            );
        }
    } else {
        if fs::read_dir(root)
            .map_err(|e| e.to_string())?
            .next()
            .is_some()
        {
            return Err(
                "Choose an empty folder. Existing installations and files will not be replaced."
                    .into(),
            );
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&marker)
            .map_err(|e| e.to_string())?;
        file.write_all(expected.to_string().as_bytes())
            .map_err(|e| e.to_string())?;
    }
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(false);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(0);
    }
    let file = options
        .open(root.join(".setup-running.lock"))
        .map_err(|_| {
            "Another setup is using this engine folder. Wait for it to finish.".to_string()
        })?;
    #[cfg(unix)]
    {
        use std::os::fd::AsRawFd;
        extern "C" {
            fn flock(fd: i32, op: i32) -> i32;
        }
        if unsafe { flock(file.as_raw_fd(), 6) } != 0 {
            return Err("Another setup is using this engine folder.".into());
        }
    }
    Ok(file)
}
#[cfg(windows)]
struct OwnedJob(*mut std::ffi::c_void);
#[cfg(windows)]
impl OwnedJob {
    fn attach(child: &std::process::Child) -> Result<Self, String> {
        use std::os::windows::io::AsRawHandle;
        #[repr(C)]
        #[derive(Default)]
        struct Basic {
            process_time: i64,
            job_time: i64,
            flags: u32,
            min: usize,
            max: usize,
            active: u32,
            affinity: usize,
            priority: u32,
            scheduling: u32,
        }
        #[repr(C)]
        #[derive(Default)]
        struct Info {
            basic: Basic,
            io: [u64; 6],
            process_memory: usize,
            job_memory: usize,
            peak_process: usize,
            peak_job: usize,
        }
        #[link(name = "kernel32")]
        extern "system" {
            fn CreateJobObjectW(a: *const u8, n: *const u16) -> *mut std::ffi::c_void;
            fn SetInformationJobObject(
                h: *mut std::ffi::c_void,
                c: i32,
                p: *const u8,
                s: u32,
            ) -> i32;
            fn AssignProcessToJobObject(h: *mut std::ffi::c_void, p: *mut std::ffi::c_void) -> i32;
        }
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let job = Self(handle);
        let mut info = Info::default();
        info.basic.flags = 0x2000;
        if unsafe {
            SetInformationJobObject(
                handle,
                9,
                &info as *const _ as *const u8,
                std::mem::size_of::<Info>() as u32,
            )
        } == 0
            || unsafe { AssignProcessToJobObject(handle, child.as_raw_handle()) } == 0
        {
            return Err(std::io::Error::last_os_error().to_string());
        }
        Ok(job)
    }
}
#[cfg(windows)]
impl Drop for OwnedJob {
    fn drop(&mut self) {
        #[link(name = "kernel32")]
        extern "system" {
            fn CloseHandle(h: *mut std::ffi::c_void) -> i32;
        }
        unsafe {
            CloseHandle(self.0);
        }
    }
}

pub fn run_install(
    root: &Path,
    profile: &str,
    resource: &Path,
    flag: &AtomicBool,
    emit: &dyn Fn(Value),
) -> Result<Value, String> {
    if !cfg!(windows) && !cfg!(target_os = "macos") {
        return Err("Automatic setup supports Windows and Apple Silicon macOS.".into());
    }
    if !(matches!(profile, "auto" | "cpu")
        || cfg!(windows) && matches!(profile, "cuda" | "rocm")
        || cfg!(target_os = "macos") && profile == "mps")
    {
        return Err("Choose Automatic, CPU, NVIDIA or experimental AMD.".into());
    }
    let manifest: Value = serde_json::from_slice(
        &fs::read(resource.join("requirements/engine-manifest.json")).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let asset = if cfg!(target_os = "macos") {
        &manifest["macosArm64"]["bootstrapPython"]
    } else {
        &manifest["bootstrapPython"]
    };
    let digest = asset["sha256"].as_str().ok_or("Runtime digest missing")?;
    let _lock = claim_root(root, digest)?;
    // Check storage before downloading or executing anything.
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        extern "system" {
            fn GetDiskFreeSpaceExW(p: *const u16, a: *mut u64, t: *mut u64, f: *mut u64) -> i32;
        }
        let wide: Vec<u16> = root.as_os_str().encode_wide().chain(Some(0)).collect();
        let mut free = 0;
        if unsafe {
            GetDiskFreeSpaceExW(
                wide.as_ptr(),
                &mut free,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        } == 0
            || free < 15 * 1024 * 1024 * 1024
        {
            return Err(
                "Allow at least 15 GiB free in the engine location. Choose another drive.".into(),
            );
        }
    }
    let downloads = root.join("downloads");
    fs::create_dir_all(&downloads).map_err(|e| e.to_string())?;
    let archive = downloads.join("python-3.12.16.tar.gz");
    emit(
        json!({"type":"progress","stage":"Installing private Python","message":"No system Python or Git is required"}),
    );
    download(asset, &archive, flag, emit)?;
    let runtime = root.join("runtime");
    let python = runtime.join(if cfg!(target_os = "macos") {
        "python/bin/python3.12"
    } else {
        "python/python.exe"
    });
    let receipt = runtime.join(".runtime-ready");
    if !receipt.is_file() || fs::read_to_string(&receipt).unwrap_or_default() != digest {
        fs::create_dir_all(&runtime).map_err(|e| e.to_string())?;
        unpack_python(&archive, &runtime, flag)?;
        if !python.is_file() {
            return Err("The Python runtime is incomplete.".into());
        }
        fs::write(&receipt, digest).map_err(|e| e.to_string())?;
    }
    cancelled(flag)?;
    let mut cmd = Command::new(&python);
    cmd.arg("-u")
        .arg(resource.join(if cfg!(target_os = "macos") {
            "scripts/setup_macos.py"
        } else {
            "scripts/setup_engine.py"
        }))
        .args([
            "--install",
            "--resume",
            "--download-models",
            "--profile",
            profile,
            "--root",
        ])
        .arg(root)
        .env("PYTHONNOUSERSITE", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    super::quiet(&mut cmd);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
        cmd.env("CINEVERSE_OWN_PROCESS_GROUP", "1");
    }
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    #[cfg(windows)]
    let _job = match OwnedJob::attach(&child) {
        Ok(job) => job,
        Err(e) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(e);
        }
    };
    let stdout = child.stdout.take().ok_or("Missing setup output")?;
    let stderr = child.stderr.take().ok_or("Missing setup error output")?;
    let (tx, rx) = mpsc::channel();
    let err_tx = tx.clone();
    let readers = [
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if tx.send(line).is_err() {
                    break;
                }
            }
        }),
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                if err_tx.send(line).is_err() {
                    break;
                }
            }
        }),
    ];
    let mut log = OpenOptions::new()
        .append(true)
        .create(true)
        .open(root.join("setup.log"))
        .map_err(|e| e.to_string())?;
    let mut last = Vec::new();
    let mut result = None;
    let outcome = loop {
        if flag.load(Ordering::SeqCst) {
            if child.try_wait().map_err(|e| e.to_string())?.is_none() {
                super::stop_tree(child.id());
                let _ = child.kill();
            }
            let _ = child.wait();
            break Err("Setup cancelled. Verified downloads are retained for retry.".into());
        }
        match rx.recv_timeout(Duration::from_millis(100)) {
            Ok(line) => {
                let _ = writeln!(log, "{line}");
                last.push(line.clone());
                if last.len() > 12 {
                    last.remove(0);
                }
                match serde_json::from_str::<Value>(&line) {
                    Ok(event) if event["type"] == "installed" => result = Some(event),
                    Ok(event) if event["type"] == "progress" => emit(event),
                    _ => emit(
                        json!({"type":"log","message":line.chars().take(500).collect::<String>()}),
                    ),
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                let status = child.wait().map_err(|e| e.to_string())?;
                if !status.success() {
                    break Err(format!(
                        "Engine setup failed. Check your connection/free space and retry. {}",
                        last.join("\n")
                    ));
                }
                break result.ok_or_else(|| {
                    "Setup ended without a verified engine. See setup.log and retry.".into()
                });
            }
        }
    };
    for reader in readers {
        let _ = reader.join();
    }
    outcome
}
#[tauri::command]
pub fn setup_info(app: tauri::AppHandle) -> Result<Value, String> {
    Ok(
        json!({"defaultRoot":default_root(&app)?,"minimumGiB":if cfg!(target_os="macos"){8}else{15},"platform":if cfg!(target_os="macos"){"macos"}else{"windows"}}),
    )
}

pub fn hardware_snapshot(resource: &Path) -> Result<Value, String> {
    #[cfg(not(windows))]
    {
        let _ = resource;
        return Ok(json!({"state":"not_required","gpus":[]}));
    }
    #[cfg(windows)]
    {
        let powershell =
            PathBuf::from(std::env::var_os("SystemRoot").ok_or("Windows directory unavailable")?)
                .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        let mut command = Command::new(powershell);
        command
            .args(["-NoProfile", "-NonInteractive", "-File"])
            .arg(resource.join("scripts/hardware_probe.ps1"))
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        super::quiet(&mut command);
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        let began = Instant::now();
        while child.try_wait().map_err(|e| e.to_string())?.is_none() {
            if began.elapsed() > Duration::from_secs(30) {
                let _ = child.kill();
                let _ = child.wait();
                return Ok(
                    json!({"state":"unavailable","gpus":[],"message":"Hardware detection timed out. Setup will use CPU compatibility."}),
                );
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let output = child.wait_with_output().map_err(|e| e.to_string())?;
        if !output.status.success() {
            return Ok(
                json!({"state":"unavailable","gpus":[],"message":"Hardware inventory unavailable. Setup will use CPU compatibility."}),
            );
        }
        serde_json::from_slice(&output.stdout).map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn hardware_info(app: tauri::AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || hardware_snapshot(&resources(&app)?))
        .await
        .map_err(|e| e.to_string())?
}
#[tauri::command]
pub fn install_engine(app: tauri::AppHandle, profile: String, root: String) -> Result<(), String> {
    let resource = resources(&app)?;
    // Match start_job's lock order to avoid a simultaneous-start deadlock.
    let state = app.state::<Installer>();
    let mut lock = state.0.lock().map_err(|e| e.to_string())?;
    if lock.is_some() {
        return Err("Setup is already running.".into());
    }
    let jobs = app.state::<super::Jobs>();
    let conversion = jobs.0.lock().map_err(|e| e.to_string())?;
    if conversion.is_some() {
        return Err("Wait for the conversion to finish before setting up an engine.".into());
    }
    let flag = Arc::new(AtomicBool::new(false));
    *lock = Some(flag.clone());
    drop(conversion);
    drop(lock);
    std::thread::spawn(move || {
        let _awake = super::WakeLock::acquire();
        let emit = |v| {
            let _ = app.emit("engine-setup", v);
        };
        let result = run_install(Path::new(&root), &profile, &resource, &flag, &emit);
        let event = match result {
            Ok(value) => {
                let config = value["config"].clone();
                match super::save_settings(app.clone(), config.clone()) {
                    Ok(()) => {
                        json!({"type":"complete","config":config,"warnings":value["warnings"]})
                    }
                    Err(e) => {
                        json!({"type":"error","message":format!("Engine installed, but settings could not be saved: {e}. Retry setup.")})
                    }
                }
            }
            Err(e) => {
                json!({"type":if flag.load(Ordering::SeqCst){"cancelled"}else{"error"},"message":e})
            }
        };
        {
            let state = app.state::<Installer>();
            if let Ok(mut lock) = state.0.lock() {
                *lock = None;
            };
        }
        let _ = app.emit("engine-setup", event);
    });
    Ok(())
}
#[tauri::command]
pub fn cancel_engine_setup(state: tauri::State<Installer>) -> Result<(), String> {
    if let Some(flag) = state.0.lock().map_err(|e| e.to_string())?.as_ref() {
        flag.store(true, Ordering::SeqCst);
    }
    Ok(())
}
#[tauri::command]
pub fn open_cpu_driver(app: tauri::AppHandle, settings: Value) -> Result<(), String> {
    if !cfg!(windows) {
        return Err("macOS uses system thermal state and needs no PawnIO driver.".into());
    }
    let resource = resources(&app)?;
    let manifest: Value = serde_json::from_slice(
        &fs::read(resource.join("requirements/engine-manifest.json")).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let path = PathBuf::from(
        settings["cpuDriverInstaller"]
            .as_str()
            .ok_or("Run automatic engine setup to download the signed driver installer.")?,
    );
    verified(
        &path,
        manifest["cpuDriver"]["sha256"]
            .as_str()
            .ok_or("Missing driver digest")?,
    )?;
    // The original signed installer remains interactive; the user handles UAC.
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "shell32")]
        extern "system" {
            fn ShellExecuteW(
                w: *mut std::ffi::c_void,
                v: *const u16,
                p: *const u16,
                a: *const u16,
                d: *const u16,
                s: i32,
            ) -> isize;
        }
        let verb: Vec<u16> = "open".encode_utf16().chain(Some(0)).collect();
        let file: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        let code = unsafe {
            ShellExecuteW(
                std::ptr::null_mut(),
                verb.as_ptr(),
                file.as_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                1,
            )
        };
        if code <= 32 {
            return Err(format!("Windows could not open the driver installer (code {code}). Approval may have been declined."));
        }
        Ok(())
    }
    #[cfg(not(windows))]
    {
        Err("The driver installer is Windows-only.".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn dir() -> PathBuf {
        let p = std::env::temp_dir().join(format!("cineverse-setup-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&p).unwrap();
        p
    }
    #[test]
    fn hash_mismatch_never_executes() {
        let p = dir().join("download");
        fs::write(&p, b"untrusted").unwrap();
        assert!(verified(&p, &"0".repeat(64)).is_err());
        assert_eq!(fs::read(&p).unwrap(), b"untrusted");
    }
    #[test]
    fn foreign_folder_is_preserved() {
        let p = dir();
        fs::write(p.join("keep.txt"), b"original").unwrap();
        assert!(claim_root(&p, "test").is_err());
        assert_eq!(fs::read(p.join("keep.txt")).unwrap(), b"original");
    }
    #[test]
    fn traversal_and_windows_alternate_streams_are_refused() {
        for path in [
            "../escape",
            "/absolute",
            "python/../escape",
            "python/file:stream",
            "python\\..\\escape",
            "other/file",
        ] {
            assert!(!valid_archive_path(Path::new(path)), "{path}");
        }
        assert!(valid_archive_path(Path::new("python/python.exe")));
    }
    #[test]
    fn runtime_link_targets_must_remain_inside_python() {
        let link = Path::new("python/bin/python3");
        assert!(safe_link(link, Path::new("python3.12"), true));
        assert!(safe_link(
            link,
            Path::new("../lib/libpython3.12.dylib"),
            true
        ));
        assert!(safe_link(link, Path::new("python/bin/python3.12"), false));
        for target in ["../../outside", "/tmp/outside", "C:/outside", "..\\outside"] {
            assert!(!safe_link(link, Path::new(target), true));
        }
        assert!(!safe_link(link, Path::new("../outside"), false));
    }
    #[test]
    fn runtime_marker_is_bound_and_cancel_is_explicit() {
        let p = dir();
        drop(claim_root(&p, "a").unwrap());
        assert!(claim_root(&p, "b").is_err());
        assert!(cancelled(&AtomicBool::new(true)).is_err());
        drop(claim_root(&p, "a").unwrap());
    }
    #[test]
    fn archive_symlinks_are_refused_before_extraction() {
        let p = dir();
        let f = File::create(p.join("bad.tar.gz")).unwrap();
        let gzip = flate2::write::GzEncoder::new(f, flate2::Compression::fast());
        let mut tar = tar::Builder::new(gzip);
        let mut h = tar::Header::new_gnu();
        h.set_entry_type(tar::EntryType::Symlink);
        h.set_size(0);
        h.set_mode(0o777);
        h.set_cksum();
        tar.append_link(&mut h, "python/link", "../../outside")
            .unwrap();
        tar.into_inner().unwrap().finish().unwrap();
        assert!(unpack_python(
            &p.join("bad.tar.gz"),
            &p.join("out"),
            &AtomicBool::new(false)
        )
        .is_err());
    }
    #[test]
    fn cancelled_download_does_not_contact_the_network() {
        let file = dir().join("missing");
        let asset = json!({"sha256":"0".repeat(64),"url":"https://invalid.invalid/runtime"});
        let result = download(&asset, &file, &AtomicBool::new(true), &|_| {});
        assert!(result.unwrap_err().contains("cancelled"));
        assert!(!file.exists());
    }
    #[cfg(windows)]
    #[test]
    fn closing_setup_job_stops_its_child_and_preserves_another_process() {
        let ping = PathBuf::from(std::env::var_os("SystemRoot").unwrap()).join("System32/ping.exe");
        let spawn = || {
            let mut c = Command::new(&ping);
            c.args(["-n", "60", "127.0.0.1"])
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            super::super::quiet(&mut c);
            c.spawn().unwrap()
        };
        let mut child = spawn();
        let mut other = spawn();
        let job = OwnedJob::attach(&child).unwrap();
        drop(job);
        let began = Instant::now();
        while child.try_wait().unwrap().is_none() && began.elapsed() < Duration::from_secs(5) {
            std::thread::sleep(Duration::from_millis(25));
        }
        let stopped = child.try_wait().unwrap().is_some();
        let preserved = other.try_wait().unwrap().is_none();
        let _ = child.kill();
        let _ = child.wait();
        let _ = other.kill();
        let _ = other.wait();
        assert!(stopped);
        assert!(preserved);
    }
}
