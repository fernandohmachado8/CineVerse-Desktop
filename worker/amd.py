"""Conservative single-Radeon temperature binding. No NVIDIA tools or drivers.

Matches one visible ROCm device to one observed LibreHardwareMonitor GpuAmd
adapter by its full normalized model name. This is NOT PCI/UUID identification.
Ambiguous, renamed, stale, missing or differently named devices fail closed.
"""
import json
import math
from pathlib import Path
import re
import time


def model_name(value):
    if not isinstance(value,str):raise ValueError('Radeon model name is missing.')
    value=re.sub(r'\((?:tm|r)\)','',value.lower())
    value=re.sub(r'[^a-z0-9]','',value)
    return value.removeprefix('amd')


def gpu_reading(config,now=None):
    binding=config.get('gpuBinding') or {}
    if binding.get('hardwareType')!='GpuAmd' or binding.get('deviceCount')!=1 or not binding.get('name'):
        raise ValueError('Check the Radeon engine to bind its single GPU before enabling protection.')
    value=config.get('cpuSensorFile')
    if not value:raise ValueError('Enable CPU and Radeon sensors before converting.')
    sample=Path(value)
    error=sample.with_name('sensor-error.json')
    if error.is_file():raise ValueError('The CPU/Radeon sensor helper reported an error. Enable the sensors again.')
    data=json.loads(sample.read_text(encoding='utf-8-sig'))
    age=(time.time() if now is None else now)-float(data['timestamp'])
    if not 0<=age<=6:raise ValueError('Radeon reading is stale. Enable CPU and Radeon sensors again.')
    adapters=data.get('amdGpus',[])
    if not isinstance(adapters,list) or len(adapters)!=1:
        raise ValueError('Protection requires exactly one observed Radeon adapter. Missing or multiple AMD adapters cannot be bound safely; use CPU compatibility.')
    adapter=adapters[0]
    if adapter.get('hardwareType')!='GpuAmd' or not str(adapter.get('id','')).startswith('/gpu-amd/'):
        raise ValueError('The temperature sample does not identify a LibreHardwareMonitor Radeon adapter.')
    if not model_name(adapter.get('name')) or model_name(adapter['name'])!=model_name(binding['name']):
        raise ValueError('The Radeon sensor model differs from the selected ROCm GPU; protection cannot arm.')
    cores=[s for s in adapter.get('sensors',[]) if s.get('name')=='GPU Core']
    if len(cores)!=1:raise ValueError('A unique Radeon GPU Core temperature is required; hotspot/memory temperatures cannot substitute for it.')
    temperature=float(cores[0]['c'])
    if not math.isfinite(temperature) or not 1<temperature<130:raise ValueError('Invalid Radeon GPU core temperature.')
    return temperature
