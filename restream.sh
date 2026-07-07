#!/bin/bash
PLAYLIST_URL="${PLAYLIST_URL:-https://soundcloud.com/alzahra-alkindi/sets/clige9q6twbc}"
OUTPUT_URL="${OUTPUT_URL:-rtmps://a.rtmp.youtube.com:443/live2/ru33-pe6q-z9gr-a2es-5t82}"

echo "[quran] Starting..."
echo "[quran] PLAYLIST_URL=$PLAYLIST_URL"

[ -z "$OUTPUT_URL" ] && { echo "Missing OUTPUT_URL"; exit 1; }

pick_color() {
    local h=$(date +%H)
    if [ "$h" -ge 6 ] && [ "$h" -lt 12 ]; then
        echo "0x1a237e"   # morning deep blue
    elif [ "$h" -ge 12 ] && [ "$h" -lt 17 ]; then
        echo "0x004d40"   # afternoon dark green
    elif [ "$h" -ge 17 ] && [ "$h" -lt 19 ]; then
        echo "0x4a148c"   # evening purple
    else
        echo "0x0a1628"   # night dark blue
    fi
}

get_track_title() {
    yt-dlp --get-title "$1" 2>/dev/null
}

while true; do
    echo "[quran] Fetching playlist..."
    yt-dlp --flat-playlist --dump-single-json "$PLAYLIST_URL" 2>/dev/null > /tmp/playlist.json
    if [ ! -s /tmp/playlist.json ]; then
        echo "[quran] Failed to fetch playlist, retrying in 30s..."
        sleep 30
        continue
    fi

    python3 -c "
import json
with open('/tmp/playlist.json') as f:
    data = json.load(f)
for e in data.get('entries', []):
    print(e.get('url', ''))
" > /tmp/playlist_urls.txt

    track_num=0
    while IFS= read -r track_url; do
        [ -z "$track_url" ] && continue
        track_num=$((track_num + 1))

        echo "[quran] ($track_num) Getting audio..."
        audio_url=$(yt-dlp -g "$track_url" 2>/dev/null | tail -1)
        title=$(get_track_title "$track_url" 2>/dev/null || echo "Track $track_num")
        if [ -z "$audio_url" ]; then
            echo "[quran] Failed to get audio, skipping..."
            sleep 2
            continue
        fi

        color=$(pick_color)
        echo "[quran] Playing: $title"

        ffmpeg -nostdin -re -thread_queue_size 512 \
            -f lavfi -i "color=c=$color:s=1280x720:r=5" \
            -i "$audio_url" \
            -c:v libx264 -preset veryfast -b:v 2000k -maxrate 2200k -bufsize 4000k -r 10 -g 30 \
            -c:a aac -b:a 128k \
            -shortest \
            -rtmp_live live \
            -f flv \
            "$OUTPUT_URL" \
            -loglevel warning -stats 2>&1 </dev/null

        echo "[quran] Track ended, next in 3s..."
        sleep 3
    done < /tmp/playlist_urls.txt

    echo "[quran] Playlist finished, restarting from beginning..."
    sleep 10
done
