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

get_track_title() {
    yt-dlp --get-title "$1" 2>/dev/null
}

download_bg

play_track() {
    local track_url="$1"
    local track_num="$2"
    echo "[quran] ($track_num) Getting audio..."
    audio_url=$(yt-dlp -g "$track_url" 2>/dev/null | tail -1)
    title=$(get_track_title "$track_url" 2>/dev/null || echo "Track $track_num")
    if [ -z "$audio_url" ]; then
        echo "[quran] Failed to get audio, skipping..."
        sleep 2
        return
    fi

    echo "[quran] Playing: $title"

    if [ -f /tmp/bg.mp4 ]; then
        ffmpeg -nostdin -re -stream_loop -1 -i /tmp/bg.mp4 \
            -i "$audio_url" \
            -map 0:v -map 1:a \
            -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
            -c:v libx264 -preset veryfast -b:v 2000k -maxrate 2200k -bufsize 4000k -r 10 -g 30 \
            -c:a aac -b:a 128k \
            -shortest \
            -rtmp_live live \
            -f flv \
            "$OUTPUT_URL" \
            -loglevel warning -stats 2>&1 </dev/null
    else
        download_bg
        ffmpeg -nostdin -re -thread_queue_size 512 \
            -f lavfi -i "color=c=0x0a1628:s=1280x720:r=5" \
            -i "$audio_url" \
            -c:v libx264 -preset veryfast -b:v 2000k -maxrate 2200k -bufsize 4000k -r 10 -g 30 \
            -c:a aac -b:a 128k \
            -shortest \
            -rtmp_live live \
            -f flv \
            "$OUTPUT_URL" \
            -loglevel warning -stats 2>&1 </dev/null
    fi

    echo "[quran] Track ended, next in 3s..."
    sleep 3
}

while true; do
    echo "[quran] Fetching source..."
    yt-dlp --flat-playlist --dump-single-json "$PLAYLIST_URL" 2>/dev/null > /tmp/playlist.json
    if [ ! -s /tmp/playlist.json ]; then
        echo "[quran] Failed to fetch, retrying in 30s..."
        sleep 30
        continue
    fi

    python3 -c "
import json
with open('/tmp/playlist.json') as f:
    data = json.load(f)
entries = data.get('entries')
if entries:
    for e in entries:
        print(e.get('url', ''))
else:
    print('__single__')
" > /tmp/playlist_urls.txt

    read -r first_line < /tmp/playlist_urls.txt
    if [ "$first_line" = "__single__" ]; then
        while true; do
            play_track "$PLAYLIST_URL" 1
        done
    else
        track_num=0
        while IFS= read -r track_url; do
            [ -z "$track_url" ] && continue
            track_num=$((track_num + 1))
            play_track "$track_url" "$track_num"
        done < /tmp/playlist_urls.txt
    fi

    echo "[quran] Source finished, restarting..."
    sleep 10
done
