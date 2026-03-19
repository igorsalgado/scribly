FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    pulseaudio-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG WHISPER_MODEL=medium
RUN python -c "\
from faster_whisper import WhisperModel; \
WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8'); \
print('Whisper ${WHISPER_MODEL} ready')"

ARG HF_TOKEN
RUN python -c "\
from pyannote.audio import Pipeline; \
pipeline = Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', use_auth_token='${HF_TOKEN}'); \
print('Pyannote ready' if pipeline is not None else 'Pyannote unavailable: check HF_TOKEN access and accept the gated model terms')"

RUN mkdir -p /app/output /app/data

CMD ["arq", "settings.WorkerSettings"]
