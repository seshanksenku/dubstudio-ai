"""Real model inference. Never substitute the original video for a failed lip-sync."""
import gc
import json
import math
import os
import sys
from pathlib import Path
from app.config import DATA, LANGUAGES
from app.media import run, probe, tempo_chain
from app import store

MUSE = Path(os.getenv('MUSETALK_DIR', '/opt/MuseTalk'))
MUSE_PYTHON = os.getenv('MUSETALK_PYTHON', '/opt/muse/bin/python')
WEIGHTS = ['musetalkV15/unet.pth', 'musetalkV15/musetalk.json', 'sd-vae/config.json', 'sd-vae/diffusion_pytorch_model.bin', 'whisper/config.json', 'whisper/pytorch_model.bin', 'whisper/preprocessor_config.json', 'dwpose/dw-ll_ucoco_384.pth', 'face-parse-bisent/79999_iter.pth', 'face-parse-bisent/resnet18-5c106cde.pth']

def preflight():
    if not (MUSE / 'scripts/inference.py').exists() or not Path(MUSE_PYTHON).exists():
        raise RuntimeError('MuseTalk environment missing. Build the GPU image.')
    missing = [p for p in WEIGHTS if not (MUSE / 'models' / p).exists()]
    if missing:
        raise RuntimeError('Missing model weights: '+', '.join(missing))
    run([MUSE_PYTHON, '-c', 'import torch; from mmcv.ops import nms; assert torch.cuda.is_available(), "NVIDIA GPU unavailable"'])

def process(row):
    import numpy as np
    import soundfile as sf
    import torch
    import yaml
    from faster_whisper import WhisperModel
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, VitsModel

    id = row['id']
    payload = json.loads(row['payload'])
    folder = DATA / id
    duration = payload['duration']
    def stage(label, progress):
        store.update(id, stage=label, progress=progress)
    stage('Preparing video', 5)
    normalized = folder / f'{id}.mp4'
    # Fixed, generated paths are safe for upstream MuseTalk shell commands.
    run(['ffmpeg', '-y', '-v', 'error', '-i', folder / payload['input'], '-map', '0:v:0', '-an', '-vf', "fps=25,scale='min(1280,iw)':-2", '-c:v', 'libx264', '-pix_fmt', 'yuv420p', normalized])
    audio = folder / 'source.wav'
    run(['ffmpeg', '-y', '-v', 'error', '-i', folder / payload['input'], '-vn', '-ac', '1', '-ar', '16000', audio])
    stage('Transcribing speech', 15)
    # CPU inference keeps GPU memory available and avoids CTranslate2/CUDA version conflicts.
    asr = WhisperModel(os.getenv('WHISPER_MODEL', 'small'), device='cpu', compute_type='int8')
    items, info = asr.transcribe(str(audio), language=None if payload['source'] == 'auto' else payload['source'], vad_filter=True)
    segments = [{'start': s.start, 'end': s.end, 'text': s.text.strip()} for s in items if s.text.strip()]
    source = info.language
    del asr
    gc.collect()
    if source not in LANGUAGES:
        raise RuntimeError(f'Detected language {source} is not supported by this version')
    if not segments:
        raise RuntimeError('No spoken speech detected')
    stage('Translating speech', 30)
    target = payload['target']
    if source != target:
        model_id = 'facebook/nllb-200-distilled-600M'
        tokenizer = AutoTokenizer.from_pretrained(model_id, src_lang=LANGUAGES[source][1])
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id).eval()
        for s in segments:
            tokens = tokenizer(s['text'], return_tensors='pt')
            if tokens['input_ids'].shape[1] > 512:
                raise RuntimeError('Speech segment too long to translate safely. Try a shorter clip.')
            with torch.inference_mode():
                output = model.generate(**tokens, forced_bos_token_id=tokenizer.convert_tokens_to_ids(LANGUAGES[target][1]), max_new_tokens=512)
            s['translated'] = tokenizer.batch_decode(output, skip_special_tokens=True)[0]
        del model, tokenizer
        gc.collect()
    else:
        for s in segments:
            s['translated'] = s['text']
    stage('Generating timed dubbed speech', 45)
    tts_id = 'facebook/mms-tts-'+LANGUAGES[target][2]
    tokenizer = AutoTokenizer.from_pretrained(tts_id)
    tts = VitsModel.from_pretrained(tts_id).eval()
    sample_rate = 16000
    timeline = np.zeros(math.ceil(duration * sample_rate), dtype=np.float32)
    for i, s in enumerate(segments):
        start = max(0, min(duration, s['start']))
        # Use available pause before next segment to reduce unnatural speed changes.
        end = min(duration, segments[i+1]['start'] if i+1 < len(segments) else duration)
        window = end-start
        if window <= 0:
            raise RuntimeError('Overlapping speech timestamps. Use a single-speaker clip.')
        tokens = tokenizer(s['translated'], return_tensors='pt')
        with torch.inference_mode():
            waveform = tts(**tokens).waveform[0].cpu().numpy()
        raw = folder / f'speech_{i}.wav'
        sf.write(raw, waveform, tts.config.sampling_rate)
        speech_duration = len(waveform) / tts.config.sampling_rate
        ratio = max(1., speech_duration/window)
        if ratio > 2.5:
            raise RuntimeError('Translation is too long for the speech window. Try a clip with slower speech.')
        fitted = folder / f'fitted_{i}.wav'
        run(['ffmpeg', '-y', '-v', 'error', '-i', raw, '-af', tempo_chain(ratio), '-ar', str(sample_rate), '-ac', '1', fitted])
        samples, _ = sf.read(fitted, dtype='float32')
        offset = round(start*sample_rate)
        count = min(len(samples), round(window*sample_rate), len(timeline)-offset)
        timeline[offset:offset+count] = samples[:count]
        stage('Generating timed dubbed speech', 45+int(15*(i+1)/len(segments)))
    sf.write(folder / 'dub.wav', timeline, sample_rate)
    (folder / 'transcript.json').write_text(json.dumps({'source': source, 'target': target, 'segments': segments}, ensure_ascii=False))
    del tts, tokenizer
    gc.collect()
    stage('Generating lip movements on GPU', 65)
    config = folder / 'inference.yaml'
    config.write_text(yaml.safe_dump({'job': {'video_path': str(normalized), 'audio_path': str(folder / 'dub.wav'), 'result_name': 'synced.mp4'}}))
    results = folder / 'muse_results'
    with (folder / 'musetalk.log').open('w') as log:
        run([MUSE_PYTHON, '-m', 'scripts.inference', '--inference_config', config, '--result_dir', results, '--unet_model_path', 'models/musetalkV15/unet.pth', '--unet_config', 'models/musetalkV15/musetalk.json', '--version', 'v15', '--batch_size', '4', '--use_float16', '--ffmpeg_path', '/usr/bin'], cwd=MUSE, stdout=log, stderr=log)
    synced = results / 'v15' / 'synced.mp4'
    # Upstream catches some errors and exits zero. Require valid output explicitly.
    if not synced.exists():
        raise RuntimeError('MuseTalk produced no video. Inspect the job musetalk.log; use a clearly visible face.')
    output_duration, streams = probe(synced)
    if abs(output_duration-duration) > 1 or not any(s['codec_type'] == 'video' for s in streams):
        raise RuntimeError('Lip-sync output failed duration/stream validation')
    stage('Exporting MP4', 95)
    run(['ffmpeg', '-y', '-v', 'error', '-i', synced, '-i', folder / 'dub.wav', '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', '-t', str(duration), folder / 'dubbed.mp4'])
    final_duration, streams = probe(folder / 'dubbed.mp4')
    if abs(final_duration-duration) > 1 or not any(s['codec_type'] == 'audio' for s in streams):
        raise RuntimeError('Export validation failed')
    store.update(id, status='completed', stage='Ready to download', progress=100)
