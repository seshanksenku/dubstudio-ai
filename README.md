# DubStudio AI

A deployable, private, single-speaker video dubbing studio with a real model pipeline:

**Upload → Whisper transcription → NLLB translation → MMS speech → timed audio → MuseTalk 1.5 GPU lip-sync → MP4 download.**

The browser calls the backend. No simulated processing, paid voice API, or original-video fallback. Failed lip-sync produces a failed job. GitHub hosts this source; an NVIDIA GPU server runs the app.

## Current status

This repository includes the complete frontend, FastAPI API, persistent SQLite queue, separate GPU worker, Docker images, HTTPS proxy, and CPU tests. Model inference and the GPU Docker build still need validation on your GPU host. A live hosted deployment is not created by pushing this repository.

This is a first deployable research MVP, not an ElevenLabs quality equivalent. It uses a stock synthetic voice per language, replaces the original audio track (including music), and does not include voice cloning, speaker diarization, multi-face selection, or shot segmentation. Lip-sync quality must be visually reviewed; a valid MP4 does not guarantee accurate lip movements in every frame.

## Languages

English, Hindi, Telugu, Tamil, Spanish, French, German. Input can be detected automatically or selected. Unsupported detected languages return a clear error. A 60-second / 100 MB limit is the default. Start with a 5–10 second, forward-facing, clearly lit single-speaker clip without cuts or other faces.

## Online deployment

Use an Ubuntu 22.04 x86-64 GPU machine with Docker Engine, Docker Compose v2, NVIDIA driver and NVIDIA Container Toolkit. A practical starting configuration is 16 GB VRAM, 16 GB system RAM, and at least 60 GB free disk; requirements depend on clip length. GPU rental is separate from model/API costs. Do not use GitHub Pages, Vercel, or a CPU-only server for this worker.

1. Install the NVIDIA driver and Docker, then follow the [NVIDIA Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Verify GPU passthrough:

   ```bash
   docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
   ```

2. Clone the project:

   ```bash
   git clone https://github.com/seshanksenku/dubstudio-ai.git
   cd dubstudio-ai
   cp .env.example .env
   ```

3. Edit `.env`. Set a private password of at least 12 characters and a random session secret of at least 32 characters. Generate a secret with:

   ```bash
   python3 -c 'import secrets; print(secrets.token_hex(32))'
   ```

   Set `STUDIO_DOMAIN` to your hostname. Point its DNS A record to this server. Permit incoming TCP ports 80 and 443. Keep `COOKIE_SECURE=true` online. Do not commit `.env`.

4. Build both images. The GPU image isolates legacy MuseTalk dependencies from the speech pipeline and pins the MuseTalk code revision:

   ```bash
   docker compose build
   ```

   The first build is large and can take a while. It needs access to GitHub, PyTorch, OpenMMLab, and Python package indexes. MuseTalk's older native dependencies may require troubleshooting for your host. A build failure is not a completed installation.

5. Download lip-sync weights to the persistent model volume:

   ```bash
   docker compose run --rm worker /opt/muse/bin/python scripts/download_models.py
   ```

   This downloads MuseTalk 1.5, SD VAE, Whisper audio encoder, DWPose, and face-parser weights. Speech recognition, translation, and target-language TTS weights download from Hugging Face on first use. First-job processing may therefore take substantially longer.

6. Start the app:

   ```bash
   docker compose up -d
   docker compose logs -f worker
   ```

   Open `https://YOUR-STUDIO-DOMAIN`, sign in, and wait for “GPU worker connected.” The upload action remains disabled while the worker is offline. Caddy obtains HTTPS certificates automatically when DNS and ports are correct.

7. Upload a short spoken video, select the target language, and click **Translate + dub + lip-sync**. Review the translated transcript and output, then download the MP4.

## Test on a server without a domain

Set `STUDIO_DOMAIN=:80` and `COOKIE_SECURE=false` temporarily in `.env`, then use an SSH tunnel rather than exposing the unencrypted studio:

```bash
docker compose up -d api worker
```

On your computer:

```bash
ssh -L 8000:127.0.0.1:8000 USER@SERVER_IP
```

Open `http://localhost:8000`. Return to secure cookies and the domain/HTTPS setup for online use.

## GPU acceptance check (required before calling it working)

- Confirm `nvidia-smi` works inside the worker container.
- Confirm worker preflight passes and the interface reports it connected.
- Upload a 5–10 second single-face spoken clip; select a different language.
- Confirm every stage runs, the transcript is translated, and the downloaded MP4 has the new speech.
- Watch the entire output and check mouth movement against the new audio, including pauses.
- Test both English→Telugu and Hindi→English if those are your intended use cases.
- Test a corrupt file and a non-face clip; inspect failures, never accept an unchanged clip as successful dubbing.

The automated CPU tests do not validate model quality or CUDA inference. GPU integration is intentionally reported separately.

## Storage and operation

One private owner studio, one API process, one GPU worker. A process lock prevents a second worker from corrupting recovery behavior. SQLite atomically claims jobs and persists queue state. Running jobs become failed after a worker restart; queued jobs remain queued. There is no cancel/resume or automatic retry.

Uploads use generated filenames, size/duration validation, and authenticated job routes. The session cookie is HttpOnly, SameSite=Strict and Secure online. A small process-local login attempt limit is included. This is not a public multi-user SaaS platform. Add per-user identity, quotas, object storage, and stronger rate limiting before that expansion.

Media remains in the `jobs` Docker volume until you delete a finished project in the UI. Delete removes the original, intermediate files, and output. Back up persistent volumes if needed. Monitor disk usage; MuseTalk frame extraction consumes considerable temporary space. Keep uploads short. Do not run `docker compose down -v` unless you intend to delete project data and model caches.

Logs:

```bash
docker compose logs --tail=100 api worker
```

For a failed job, use its generated job ID to inspect the upstream log:

```bash
docker compose exec worker cat /data/JOB_ID/musetalk.log
```

If MMS needs romanization, `uroman` is included in the speech environment. Translation segments exceeding 512 tokens or requiring more than 2.5× speech speed fail with an actionable error rather than silently truncating speech. Stock TTS can sound less natural than commercial services.

## Development and CPU checks

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
python -m pytest -q
python -m compileall -q app scripts
node --check web/app.js
```

GitHub Actions runs these CPU checks. The full pipeline dependencies are in `requirements.txt`. The API image intentionally avoids installing large models; only the GPU worker performs inference.

## Model terms and references

The application code is MIT licensed. Model weights have their own terms. NLLB and MMS are **CC-BY-NC 4.0**, and NLLB is described by its publisher as a research model, not released for production deployment. This default stack is for noncommercial experimentation, not a commercial launch. Replace these models with appropriately licensed alternatives before monetizing. “Open models” does not mean unrestricted commercial use.

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [NLLB model card](https://huggingface.co/facebook/nllb-200-distilled-600M)
- [MMS Telugu model card](https://huggingface.co/facebook/mms-tts-tel)
- [MuseTalk official installation and inference](https://github.com/TMElyralab/MuseTalk)
- MuseTalk code pinned to `0a89dec45a0192b824e3cf4daf96c239440c5ed8`.
