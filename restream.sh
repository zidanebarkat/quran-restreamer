#!/bin/bash
PLAYLIST_URL="${PLAYLIST_URL:-https://archive.org/details/lifeways11_gmail_001_20180201_0110}"
OUTPUT_URL="${OUTPUT_URL:-rtmps://a.rtmp.youtube.com:443/live2/ru33-pe6q-z9gr-a2es-5t82}"
BG_URL="${BG_URL:-https://assets.mixkit.co/videos/22728/22728-720.mp4}"

echo "[quran] Starting..."
echo "[quran] PLAYLIST_URL=$PLAYLIST_URL"
echo "[quran] Waiting 10s for old connections to close..."
sleep 10

[ -z "$OUTPUT_URL" ] && { echo "Missing OUTPUT_URL"; exit 1; }

if [ ! -f /tmp/bg.mp4 ]; then
    echo "[quran] Downloading background video..."
    curl -sL "$BG_URL" -o /tmp/bg_orig.mp4
    if [ ! -s /tmp/bg_orig.mp4 ]; then
        echo "[quran] Failed to download background"
        exit 1
    fi
    echo "[quran] Pre-encoding background to 720p 10fps..."
    ffmpeg -nostdin -i /tmp/bg_orig.mp4 \
        -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
        -c:v libx264 -preset ultrafast -b:v 1500k -maxrate 2000k -bufsize 3000k \
        -r 10 -g 30 \
        -an \
        /tmp/bg.mp4 -y \
        -loglevel warning 2>&1
    rm -f /tmp/bg_orig.mp4
    echo "[quran] Background ready ($(du -h /tmp/bg.mp4 | cut -f1))"
fi

while true; do
    echo "[quran] Fetching..."
    title=$(yt-dlp --get-title "$PLAYLIST_URL" 2>/dev/null || echo "Track")
    rm -f /tmp/track.*
    yt-dlp -f bestaudio -x --audio-format mp3 -o "/tmp/track.%(ext)s" "$PLAYLIST_URL" >/dev/null 2>&1
    # yt-dlp may output .mp3 or other extension, ensure we have /tmp/track.mp3
    [ ! -f /tmp/track.mp3 ] && for f in /tmp/track.*; do [ -f "$f" ] && mv "$f" /tmp/track.mp3 && break; done 2>/dev/null
    if [ ! -s /tmp/track.mp3 ]; then
        echo "[quran] Download failed, retrying..."
        sleep 5
        continue
    fi
    echo "[quran] Downloaded: $title ($(du -h /tmp/track.mp3 | cut -f1))"
    echo "[quran] Downloaded ($(du -h /tmp/track.mp3 | cut -f1))"

    echo "[quran] Streaming continuously..."
    ffmpeg -nostdin -re -stream_loop -1 -i /tmp/bg.mp4 \
        -stream_loop -1 -i /tmp/track.mp3 \
        -map 0:v -map 1:a \
        -c:v copy \
        -af "volume=1.5,asetrate=46000,aresample=44100" \
        -ar 44100 -c:a aac -b:a 192k \
        -rtmp_live live \
        -f flv \
        "$OUTPUT_URL" \
        -loglevel warning -stats 2>&1 </dev/null

    echo "[quran] Stream stopped, refreshing audio..."
    sleep 2
done
