FROM alpine:3.21

RUN wget -q https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-amd64 \
    -O /usr/local/bin/supercronic && \
    chmod +x /usr/local/bin/supercronic

COPY crontab /app/crontab

CMD ["supercronic", "/app/crontab"]
