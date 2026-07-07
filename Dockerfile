FROM alpine:latest

RUN apk add --no-cache ffmpeg bash python3 py3-pip py3-flask curl && \
    pip3 install --break-system-packages yt-dlp

COPY app.py /app.py
COPY restream.sh /restream.sh
RUN chmod +x /restream.sh

CMD ["python3", "/app.py"]
