FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# faster-whisper er valgfri (WHISPER_MODEL tom = ingen transskription). Modellen hentes ved første brug til /models.
RUN pip install --no-cache-dir faster-whisper
ENV HF_HOME=/models

WORKDIR /app
COPY deploy/wiki-inbox/bot.py /app/bot.py
COPY deploy/wiki-inbox/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENV WIKI_ROOT=/wiki
ENTRYPOINT ["/app/entrypoint.sh"]
