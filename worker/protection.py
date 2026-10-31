"""Single-conversion supervisor. The renderer is never responsible for stopping work."""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thermal.thermal_guard import Policy, identity, stop_tree

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
LIMITS = {'cpu': {'sustainedC': 95, 'immediateC': 100, 'seconds': 10},
          'gpu': {'sustainedC': 85, 'immediateC': 90, 'seconds': 10}}


class ProcessTree:
    """Windows job object also kills descendants if the supervisor crashes."""
    def __init__(self, child):
        self.handle = None
        if os.name != 'nt': return
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('processTime', c.c_int64), ('jobTime', c.c_int64), ('flags', w.DWORD),
                        ('minWorkingSet', c.c_size_t), ('maxWorkingSet', c.c_size_t),
                        ('activeProcesses', w.DWORD), ('affinity', c.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(n, c.c_uint64) for n in ('readOps', 'writeOps', 'otherOps', 'readBytes', 'writeBytes', 'otherBytes')]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('processMemory', c.c_size_t),
                        ('jobMemory', c.c_size_t), ('peakProcess', c.c_size_t), ('peakJob', c.c_size_t)]
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = self.kernel.CreateJobObjectW(None, None)
        if not handle: raise c.WinError(c.get_last_error())
        self.handle = handle
        info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(handle, 9, c.byref(info), c.sizeof(info)) or not self.kernel.AssignProcessToJobObject(handle, int(child._handle)):
            error = c.WinError(c.get_last_error()); self.close(); raise error

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None


def limit_cpu_process(child=None):
    """Bound the entire inherited Windows process tree to two logical CPUs.

    Library thread settings alone do not constrain PyAV/codec worker pools.
    Fail closed if the requested load budget cannot be applied.
    """
    if os.name != 'nt': return
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.GetProcessAffinityMask.argtypes = [w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
    kernel.SetProcessAffinityMask.argtypes = [w.HANDLE, c.c_size_t]
    kernel.SetPriorityClass.argtypes = [w.HANDLE, w.DWORD]
    handle = int(child._handle) if child is not None else -1  # current-process pseudo-handle
    allowed, system = c.c_size_t(), c.c_size_t()
    if not kernel.GetProcessAffinityMask(handle, c.byref(allowed), c.byref(system)):
        raise c.WinError(c.get_last_error())
    bits = [1 << n for n in range(c.sizeof(c.c_size_t) * 8) if allowed.value & (1 << n)]
    if not bits or not kernel.SetProcessAffinityMask(handle, sum(bits[:2])):
        raise c.WinError(c.get_last_error())
    if not kernel.SetPriorityClass(handle, 0x4000):  # BELOW_NORMAL_PRIORITY_CLASS
        raise c.WinError(c.get_last_error())


def mode(config):
    if config.get('resolvedBackend') == 'cpu' or config.get('backend') == 'cpu':
        return 'cpu'
    value = config.get('thermalMode', 'required')
    if value not in ('required', 'gpu'):
        raise ValueError('Choose CPU + GPU protection or explicitly select GPU only.')
    return value


def shell_path(value):
    # Tauri resources may use Win32 extended paths. Windows PowerShell treats
    # those as remote paths for signing policy; use the equivalent normal path.
    value = str(value)
    if value.startswith('\\\\?\\UNC\\'): return '\\\\' + value[8:]
    return value.removeprefix('\\\\?\\')


def cpu_reading(config, now=None):
    path = config.get('cpuSensorFile')
    if not path:
        raise ValueError('Enable the CPU sensor before converting. CPU compatibility requires CPU sensing.' if mode(config)=='cpu' else 'Enable the CPU sensor before converting, or explicitly choose GPU-only protection.')
    sample = Path(path)
    error = sample.with_name('sensor-error.json')
    if error.is_file():
        raise ValueError(json.loads(error.read_text(encoding='utf-8-sig')).get('error', 'CPU sensor failed.'))
    if not sample.is_file():
        raise ValueError('Waiting for CPU readings. Approve the Windows sensor prompt; PawnIO must be installed.')
    data = json.loads(sample.read_text(encoding='utf-8-sig'))
    age = (time.time() if now is None else now) - float(data['timestamp'])
    if not 0 <= age <= 6:
        raise ValueError('CPU reading is stale. Enable the CPU sensor again.')
    values = [float(s['c']) for s in data['sensors'] if 'distance' not in s['name'].lower()]
    if not values or any(not math.isfinite(v) or not 1 < v < 130 for v in values):
        raise ValueError('No valid CPU temperatures were returned.')
    return max(values)


def gpu_reading(config):
    import csv
    import io
    uuid = config.get('gpuUuid', '')
    if not uuid.startswith('GPU-'):
        raise ValueError('Check the engine to bind protection to its CUDA GPU.')
    result = subprocess.run([config.get('nvidiaSmi') or 'nvidia-smi.exe', '-i', uuid,
        '--query-gpu=uuid,temperature.gpu', '--format=csv,noheader,nounits'],
        capture_output=True, text=True, timeout=2, check=True, creationflags=FLAGS)
    rows = list(csv.reader(io.StringIO(result.stdout.strip())))
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][0].strip() != uuid:
        raise ValueError('NVIDIA returned a different GPU; protection cannot arm.')
    value = float(rows[0][1].strip())
    if not math.isfinite(value) or not 1 < value < 130:
        raise ValueError('Invalid GPU core temperature.')
    return value


def status(config):
    result = {'mode': mode(config), 'limits': LIMITS, 'ready': True, 'gpuUuid': config.get('gpuUuid')}
    required = ['cpu'] if result['mode'] == 'cpu' else ['gpu'] if result['mode'] == 'gpu' else ['cpu', 'gpu']
    for name, reader in [('cpu', cpu_reading), ('gpu', gpu_reading)]:
        if name == 'gpu' and result['mode'] == 'cpu':
            result[name] = {'state': 'not_used', 'message': 'CPU processing does not use or monitor a GPU.'}
            continue
        try:
            value = reader(config)
            result[name] = {'state': 'ready', 'c': value}
            if value >= LIMITS[name]['immediateC']:
                result[name].update(state='too_hot', message=f'{name.upper()} is above its immediate cutoff. Allow the PC to cool.')
                if name in required: result['ready'] = False
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            result[name] = {'state': 'unavailable', 'message': str(exc)}
            if name in required:
                result['ready'] = False
    return result


class Monitor:
    """Monotonic sustained limits; every required sensor fails closed after 30 s."""
    def __init__(self, config, now):
        self.config = config
        self.names = ['cpu'] if mode(config) == 'cpu' else ['cpu', 'gpu'] if mode(config) == 'required' else ['gpu']
        self.policies = {n: Policy(n.upper(), LIMITS[n]['sustainedC'], LIMITS[n]['immediateC']) for n in self.names}
        self.last_good = {n: now for n in self.names}

    def sample(self, now, readings):
        for name in self.names:
            value = readings.get(name, {}).get('c')
            if value is None:
                self.policies[name].hot_since = None
                if now - self.last_good[name] >= 30:
                    return f'{name.upper()} sensor unavailable for 30 seconds; conversion stopped.'
            else:
                self.last_good[name] = now
                reason = self.policies[name].sample(value, now)
                if reason:
                    return reason
        return None


def start_cpu(config, parent_pid):
    """Elevate only the read-only CPU helper, never the converter/UI."""
    import ctypes
    import uuid
    library = Path(config.get('sensorLibrary') or '.') / 'LibreHardwareMonitorLib.dll'
    if not library.is_file():
        raise ValueError('LibreHardwareMonitor is missing. Locate its folder in Advanced paths. PawnIO must also be installed.')
    parent = identity(int(parent_pid))
    if not parent:
        raise ValueError('The parent application is no longer running.')
    root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CineVerse' / 'sensors' / uuid.uuid4().hex
    root.mkdir(parents=True)
    script = Path(__file__).with_name('cpu_session.ps1')
    import base64
    def quoted(value): return "'" + shell_path(value).replace("'", "''") + "'"
    launch_log = root / 'launch.log'
    command = ('try { & ' + quoted(script) + ' -Directory ' + quoted(root) +
               ' -Library ' + quoted(library.resolve()) + ' -ParentPid ' + str(parent['pid']) +
               ' -ParentCreated ' + str(parent['created']) +
               ' } catch { $_ | Out-File -LiteralPath ' + quoted(launch_log) + ' -Encoding utf8; exit 1 }')
    args = ['-NoProfile', '-NonInteractive', '-EncodedCommand', base64.b64encode(command.encode('utf-16-le')).decode('ascii')]
    from ctypes import wintypes as w
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('mask', w.ULONG), ('window', w.HWND), ('verb', w.LPCWSTR),
                    ('file', w.LPCWSTR), ('parameters', w.LPCWSTR), ('directory', w.LPCWSTR),
                    ('show', ctypes.c_int), ('instance', w.HINSTANCE), ('idList', ctypes.c_void_p),
                    ('className', w.LPCWSTR), ('classKey', w.HKEY), ('hotKey', w.DWORD),
                    ('icon', w.HANDLE), ('process', w.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True).ShellExecuteExW
    shell.argtypes = [ctypes.POINTER(ExecuteInfo)]; shell.restype = w.BOOL
    info = ExecuteInfo(); info.size = ctypes.sizeof(info); info.mask = 0x40  # keep process handle
    info.verb = 'runas'
    info.file = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    info.parameters = subprocess.list2cmdline(args); info.show = 0
    # The persistent helper must not inherit the short worker's IPC pipes.
    # Otherwise Rust waits for EOF until the entire app session ends.
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetStdHandle.argtypes = [w.DWORD]; k.GetStdHandle.restype = w.HANDLE
    k.GetHandleInformation.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k.SetHandleInformation.argtypes = [w.HANDLE, w.DWORD, w.DWORD]
    handles = []
    try:
        for number in (-10, -11, -12):
            handle = k.GetStdHandle(number & 0xffffffff); flags = w.DWORD()
            if handle and k.GetHandleInformation(handle, ctypes.byref(flags)) and flags.value & 1:
                if not k.SetHandleInformation(handle, 1, 0): raise ctypes.WinError(ctypes.get_last_error())
                handles.append((handle, flags.value & 1))
        if not shell(ctypes.byref(info)):
            raise ValueError(f'CPU sensor permission was declined or the helper could not start (Windows {ctypes.get_last_error()}). Protection is not active.')
    finally:
        for handle, flags in handles: k.SetHandleInformation(handle, 1, flags)
    if info.process:
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        k.CloseHandle.argtypes = [w.HANDLE]
        try:
            if k.WaitForSingleObject(info.process, 1000) == 0:
                code = w.DWORD(); k.GetExitCodeProcess(info.process, ctypes.byref(code))
                detail = launch_log.read_text(encoding='utf-8-sig')[-1800:] if launch_log.is_file() else ''
                raise ValueError(f'CPU sensor helper exited early (code {code.value}). Check the sensor library and PawnIO. Protection is not active. {detail}')
        finally:
            k.CloseHandle(info.process)
    return {'cpuSensorFile': str(root / 'cpu-sample.json')}


def supervise(config, request, emit):
    # Bind independently of a stale UI configuration to the device used by iw3/RIFE.
    import torch
    from hardware import capabilities
    profile = capabilities(config, torch, probe=bool(config.get('ffmpeg')))
    config = dict(config, backend=profile['backend'], resolvedBackend=profile['backend'], gpuUuid=profile.get('gpuUuid'))
    if profile['backend'] == 'cpu':
        # Hide CUDA even when explicitly testing compatibility on an NVIDIA PC.
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
    initial = status(config)
    last_reading = initial
    emit('thermal', **initial, state='checking')
    if not initial['ready']:
        missing = [initial[n].get('message', n) for n in ('cpu', 'gpu')
                   if initial[n]['state'] != 'ready' and n in (['cpu'] if initial['mode'] == 'cpu' else ['gpu'] if initial['mode'] == 'gpu' else ['cpu', 'gpu'])]
        raise ValueError('Temperature protection could not arm. Conversion was not started. ' + ' '.join(missing))
    monitor = Monitor(config, time.monotonic())
    reason = monitor.sample(time.monotonic(), initial)
    if reason:
        raise ValueError('Temperature is already above the immediate cutoff. ' + reason)
    command = [sys.executable, '-u', str(Path(__file__).with_name('worker.py')), 'convert']
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding='utf8', errors='replace', creationflags=FLAGS)
    target = None
    tree = None
    terminal = None
    stopped = False
    events = queue.Queue()
    errors = []
    def read_lines():
        for line in child.stdout:
            try: events.put(json.loads(line))
            except ValueError: pass
    def read_errors():
        for line in child.stderr:
            errors.append(line)
            if len(errors) > 100: errors.pop(0)
    threads = [threading.Thread(target=read_lines, daemon=True), threading.Thread(target=read_errors, daemon=True)]
    audit = []
    work = None
    def record(event):
        nonlocal work
        if event.get('workDir'): work = Path(event['workDir'])
        if event.get('type') == 'thermal':
            audit.append(dict(event, timestamp=time.time()))
            # Bounded buffer while the job folder is not yet announced.
            if len(audit) > 100: audit.pop(0)
        if work and audit:
            with (work / 'protection.jsonl').open('a', encoding='utf8') as f:
                for item in audit: f.write(json.dumps(item) + '\n')
            audit.clear()
        emit(event['type'], **{k: v for k, v in event.items() if k != 'type'})
    try:
        if profile['backend'] == 'cpu': limit_cpu_process(child)
        tree = ProcessTree(child)
        target = identity(child.pid)
        if not target: raise RuntimeError('Conversion process ended before protection was attached.')
        for thread in threads: thread.start()
        child.stdin.write(json.dumps({'config': config, 'request': request})); child.stdin.close()
        record(dict(type='thermal', **initial, state='active'))
        next_poll = time.monotonic() + 2
        while True:
            try:
                event = events.get(timeout=.1)
                if event['type'] in ('complete', 'error'):
                    terminal = event
                else:
                    record(event)
            except queue.Empty:
                pass
            if child.poll() is not None and not threads[0].is_alive() and events.empty(): break
            if time.monotonic() >= next_poll:
                reading = status(config)
                last_reading = reading
                reason = monitor.sample(time.monotonic(), reading)
                record(dict(type='thermal', **reading, state='sensor_unavailable' if not reading['ready'] else 'active'))
                if reason:
                    record(dict(type='thermal', **reading, state='stopping', reason=reason))
                    stop_tree(target)
                    stopped = True
                    raise RuntimeError('Thermal protection stopped this conversion: ' + reason +
                        ' Your source is untouched. Completed stages can be resumed manually; allow the PC to cool first.')
                next_poll = time.monotonic() + 2
        for thread in threads: thread.join(timeout=2)
        if child.returncode or not terminal:
            raise RuntimeError(terminal.get('message', '') if terminal else 'Conversion ended unexpectedly. ' + ''.join(errors)[-2000:])
        record(dict(type='thermal', **last_reading, state='finished'))
        record(terminal)
    finally:
        # Includes malformed events, output failures and unexpected supervisor errors.
        # A failed monitor must never leave its converter running unprotected.
        try:
            if child.poll() is None:
                if target: stop_tree(target)
                else: child.kill()
        finally:
            if tree: tree.close()
            child.wait(timeout=10)
            for stream in (child.stdout, child.stderr):
                stream.close()
        if stopped and work:
            (work / 'thermal-stop.json').write_text(json.dumps({'reason': reason, 'timestamp': time.time()}), encoding='utf8')
