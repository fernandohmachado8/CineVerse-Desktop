"""Local, single-job CPU thermal guard. No network, AI calls or auto-resume."""
import argparse
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import subprocess
import time


class Policy:
    def __init__(self, name='CPU', sustained=95, immediate=100):
        self.hot_since = None
        self.name = name
        self.sustained = sustained
        self.immediate = immediate

    def sample(self, temperature, now):
        if not math.isfinite(temperature) or not 1 < temperature < 130:
            raise ValueError('Invalid '+self.name+' sensor reading')
        if temperature >= self.immediate:
            return f'{self.name} reached {self.immediate} C'
        if temperature >= self.sustained:
            if self.hot_since is None:
                self.hot_since = now
            if now - self.hot_since >= 10:
                return f'{self.name} stayed at or above {self.sustained} C for 10 seconds'
        else:
            self.hot_since = None
        return None


def identity(pid):
    if os.name!='nt':
        import psutil
        try:
            process=psutil.Process(pid)
            if not process.is_running() or process.status()==psutil.STATUS_ZOMBIE:return None
            return dict(pid=pid,path=process.exe(),created=process.create_time())
        except psutil.NoSuchProcess:return None
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise OSError(ctypes.get_last_error(), 'Cannot verify conversion process')
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value != 259:
            return None
        size = wintypes.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)) or not k.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'pid': pid, 'path': path.value, 'created': (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}
    finally:
        k.CloseHandle(handle)


def stop_tree(target):
    # Bind to creation time and executable, never to a reused PID alone.
    if identity(target['pid']) != target:
        raise RuntimeError('Bound process ended or changed; refusing to terminate another process')
    if os.name!='nt':
        import signal
        if os.getpgid(target['pid'])!=target['pid']:raise RuntimeError('Refusing to signal an unowned process group')
        os.killpg(target['pid'],signal.SIGTERM)
        time.sleep(.25)
        try:os.killpg(target['pid'],signal.SIGKILL)
        except ProcessLookupError:pass
        return 'Owned process group stopped'
    result = subprocess.run(['taskkill.exe', '/PID', str(target['pid']), '/T', '/F'], capture_output=True, text=True, creationflags=0x08000000)
    if identity(target['pid']) == target:
        raise RuntimeError('Could not stop bound conversion: ' + result.stderr)
    return result.stdout


def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf8')
    os.replace(tmp, path)


def sensor_lost(armed, now, last_good):
    return armed and now - last_good >= 30


def alert(message):
    # Separate process: a persistent local dialog must not block stopping the job.
    script = Path(__file__).with_name('alert.ps1')
    subprocess.Popen(['powershell.exe', '-NoProfile', '-File', str(script), '-Message', message], creationflags=0x08000000)


def run(config_path):
    cfg = json.loads(config_path.read_text(encoding='utf-8-sig'))
    root = config_path.parent
    status_path = root / 'status.json'
    sample_path = root / 'cpu-sample.json'
    target = cfg['target']
    if identity(target['pid']) != target:
        raise RuntimeError('Configured conversion is no longer running')
    policy = Policy()
    armed = False
    last_good = time.monotonic()
    last_stamp = None
    initial = time.monotonic()
    log = root / 'thermal-events.jsonl'

    def record(state, **details):
        data = dict(state=state, timestamp=time.time(), guardPid=os.getpid(), target=target, **details)
        atomic(status_path, data)
        return data

    record('waiting_for_sensor', message='Protection not active until a valid CPU reading is received')
    while identity(target['pid']) == target:
        now = time.monotonic()
        reason = None
        temperature = None
        try:
            reading = json.loads(sample_path.read_text(encoding='utf-8-sig'))
            stamp = reading['timestamp']
            if not 0 <= time.time() - stamp <= 6 or (last_stamp is not None and stamp < last_stamp):
                raise ValueError('Stale CPU sensor')
            sensors = [s for s in reading['sensors'] if 'distance' not in s['name'].lower()]
            temperature = max(float(s['c']) for s in sensors)
            reason = policy.sample(temperature, now)
            last_stamp = stamp
            last_good = now
            if not armed:
                armed = True
                alert('CineVerse CPU temperature protection is ACTIVE. Stop: 95 C for 10 seconds, or 100 C immediately. Missing readings for 30 seconds also stop this conversion.')
            record('active', cpuC=temperature, sensors=sensors, hotSeconds=0 if policy.hot_since is None else now-policy.hot_since, thresholds={'sustainedC':95,'seconds':10,'immediateC':100})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            policy.hot_since = None
            if sensor_lost(armed, now, last_good):
                reason = 'CPU sensor unavailable for 30 seconds after protection was armed'
            else:
                record('sensor_unavailable' if armed else 'waiting_for_sensor', message=str(exc), protectionPreviouslyArmed=armed)
            if not armed and now-initial > 300:
                record('not_armed', message='No valid CPU sensor received. Conversion was not stopped. Protection is NOT active.')
                alert('CineVerse temperature protection could NOT start: no valid CPU sensor. Conversion is still running without this guard.')
                return
        if reason:
            record('stopping', reason=reason, cpuC=temperature)
            result = stop_tree(target)
            event = record('stopped', reason=reason, cpuC=temperature, termination=result)
            with log.open('a', encoding='utf8') as f:
                f.write(json.dumps(event)+'\n')
            (root / 'sensor-stop.flag').write_text('thermal stop', encoding='ascii')
            alert('CineVerse conversion STOPPED: '+reason+'. Source movie untouched. Completed stages remain available for manual resume; current stage restarts.')
            return
        time.sleep(2)
    record('finished_monitoring', message='Bound conversion process ended; no other job will be monitored or stopped')
    (root / 'sensor-stop.flag').write_text('job ended', encoding='ascii')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    try:
        run(args.config)
    except Exception as exc:
        atomic(args.config.parent / 'status.json', {'state':'guard_error', 'message':str(exc), 'timestamp':time.time()})
        alert('CineVerse temperature guard ERROR. Protection cannot be guaranteed: '+str(exc))
        raise
