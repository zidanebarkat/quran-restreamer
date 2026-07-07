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

get_audio_url() {
    url=$(yt-dlp -g "$1" 2>/dev/null | tail -1)
    echo "$url"
}

get_title() {
    yt-dlp --get-title "$1" 2>/dev/null || echo "Track"
}

while true; do
    echo "[quran] Fetching audio URL..."
    audio_url=$(get_audio_url "$PLAYLIST_URL")
    title=$(get_title "$PLAYLIST_URL")
    if [ -z "$audio_url" ]; then
        echo "[quran] Failed to get audio URL, retrying in 5s..."
        sleep 5
        continue
    fi

    echo "[quran] Playing: $title"

    while true; do
        start=$(date +%s)
        ffmpeg -nostdin -re -stream_loop -1 -i /tmp/bg.mp4 \
            -i "$audio_url" \
            -map 0:v -map 1:a \
            -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
            -c:v libx264 -preset ultrafast -b:v 1500k -maxrate 2000k -bufsize 3000k -r 10 -g 30 \
            -c:a aac -b:a 128k \
            -shortest \
            -rtmp_live live \
            -f flv \
            "$OUTPUT_URL" \
            -loglevel warning -stats 2>&1 </dev/null
        rc=$?
        elapsed=$(( $(date +%s) - start ))
        echo "[quran] ffmpeg exit=$rc after ${elapsed}s"
        [ "$elapsed" -ge 10 ] && break
        echo "[quran] Track too short, getting fresh URL..."
        audio_url=$(get_audio_url "$PLAYLIST_URL")
    done
done
