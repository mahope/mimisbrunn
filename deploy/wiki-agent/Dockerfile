FROM python:3.12-slim

RUN apt-get update && apt-get install -y git cron curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir imap_tools pyyaml

WORKDIR /app

COPY scripts/ /app/scripts/
COPY crontab /etc/cron.d/wiki-agent
RUN chmod 0644 /etc/cron.d/wiki-agent && crontab /etc/cron.d/wiki-agent

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
