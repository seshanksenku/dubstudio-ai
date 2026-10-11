"""Run with /opt/muse/bin/python; uses the isolated MuseTalk hub dependency."""
from pathlib import Path
from huggingface_hub import snapshot_download
root = Path('/opt/MuseTalk/models')
specs = [
    ('TMElyralab/MuseTalk', root, ['musetalkV15/*']),
    ('stabilityai/sd-vae-ft-mse', root / 'sd-vae', ['config.json', 'diffusion_pytorch_model.bin']),
    ('openai/whisper-tiny', root / 'whisper', ['config.json', 'pytorch_model.bin', 'preprocessor_config.json']),
    ('yzd-v/DWPose', root / 'dwpose', ['dw-ll_ucoco_384.pth']),
    ('ManyOtherFunctions/face-parse-bisent', root / 'face-parse-bisent', ['79999_iter.pth', 'resnet18-5c106cde.pth']),
]
for repo, directory, patterns in specs:
    print('Downloading', repo, flush=True)
    snapshot_download(repo, local_dir=directory, allow_patterns=patterns)
print('MuseTalk weights downloaded. Speech/translation/TTS models download on first job.')
