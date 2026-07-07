#!/bin/bash
PLAYLIST_URL="${PLAYLIST_URL:-https://soundcloud.com/slina-r/dgbfmanr9xd3}"
OUTPUT_URL="${OUTPUT_URL:-rtmps://a.rtmp.youtube.com:443/live2/ru33-pe6q-z9gr-a2es-5t82}"
BG_URL="${BG_URL:-https://assets.mixkit.co/videos/22728/22728-720.mp4}"

echo "[quran] Starting..."
echo "[quran] PLAYLIST_URL=$PLAYLIST_URL"

[ -z "$OUTPUT_URL" ] && { echo "Missing OUTPUT_URL"; exit 1; }

download_bg() {
    [ -f /tmp/bg.mp4 ] && return
    echo "[quran] Downloading background video..."
    curl -sL "$BG_URL" -o /tmp/bg.mp4
    if [ ! -s /tmp/bg.mp4 ]; then
        echo "[quran] Failed to download background"
        rm -f /tmp/bg.mp4
        return 1
    fi
    echo "[quran] Background downloaded ($(du -h /tmp/bg.mp4 | cut -f1))"
}

download_bg

while true; do
    echo "[quran] Fetching audio URL..."
    audio_url=$(yt-dlp -f http_mp3_0_1 -g "$PLAYLIST_URL" 2>/dev/null)
    title=$(yt-dlp --get-title "$PLAYLIST_URL" 2>/dev/null || echo "Track")
    if [ -z "$audio_url" ]; then
        echo "[quran] Failed to get URL, retrying in 5s..."
        sleep 5
        continue
    fi

    echo "[quran] Downloading: $title"
    rm -f /tmp/track.mp3
    curl -sL -o /tmp/track.mp3 "$audio_url"
    if [ ! -s /tmp/track.mp3 ]; then
        echo "[quran] Download failed, retrying..."
        sleep 5
        continue
    fi
    echo "[quran] Downloaded ($(du -h /tmp/track.mp3 | cut -f1))"

    echo "[quran] Streaming continuously..."
    ffmpeg -nostdin -re -stream_loop -1 -i /tmp/bg.mp4 \
        -stream_loop -1 -i /tmp/track.mp3 \
        -map 0:v -map 1:a \
        -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
        -c:v libx264 -preset ultrafast -b:v 1500k -maxrate 2000k -bufsize 3000k -r 10 -g 30 \
        -c:a aac -b:a 128k \
        -rtmp_live live \
        -f flv \
        "$OUTPUT_URL" \
        -loglevel warning -stats 2>&1 </dev/null

    echo "[quran] Stream stopped, refreshing audio..."
    sleep 2
done
