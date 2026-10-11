import json
import math
import subprocess

def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, timeout=3600, **kwargs)

def probe(path):
    result = run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path], capture_output=True, text=True)
    data = json.loads(result.stdout)
    duration = float(data['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid video duration')
    return duration, data['streams']

def tempo_chain(ratio):
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('Invalid speech duration')
    values = []
    while ratio > 2:
        values.append(2)
        ratio /= 2
    while ratio < .5:
        values.append(.5)
        ratio /= .5
    values.append(ratio)
    return ','.join(f'atempo={v:.8f}' for v in values)
