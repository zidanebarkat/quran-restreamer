#!/bin/bash
PLAYLIST_URL="${PLAYLIST_URL:-https://soundcloud.com/alzahra-alkindi/sets/clige9q6twbc}"
OUTPUT_URL="${OUTPUT_URL:-}"

echo "[quran] Starting..."
echo "[quran] PLAYLIST_URL=$PLAYLIST_URL"

[ -z "$OUTPUT_URL" ] && { echo "Missing OUTPUT_URL"; exit 1; }

pick_color() {
    local h=$(date +%H)
    if [ "$h" -ge 6 ] && [ "$h" -lt 12 ]; then
        echo "0x1a237e"   # morning deep blue
    elif [ "$h" -ge 12 ] && [ "$h" -lt 18 ]; then
        echo "0x004d40"   # afternoon dark green
    elif [ "$h" -ge 18 ] && [ "$h" -lt 20 ]; then
        echo "0x4a148c"   # evening purple
    else
        echo "0x0a1628"   # night dark blue
    fi
}

while true; do
    echo "[quran] Fetching playlist..."
    yt-dlp --flat-playlist --get-url "$PLAYLIST_URL" 2>/dev/null > /tmp/playlist.txt
    if [ ! -s /tmp/playlist.txt ]; then
        echo "[quran] Failed to fetch playlist, retrying in 30s..."
        sleep 30
        continue
    fi

    while IFS= read -r track_url; do
        [ -z "$track_url" ] && continue
        echo "[quran] Getting audio URL for: $track_url"
        audio_url=$(yt-dlp -g "$track_url" 2>/dev/null | tail -1)
        if [ -z "$audio_url" ]; then
            echo "[quran] Failed to get audio, skipping..."
            sleep 2
            continue
        fi

        color=$(pick_color)
        echo "[quran] Playing track with color=$color"

        ffmpeg -re \
            -f lavfi -i "color=c=$color:s=1280x720:r=10" \
            -i "$audio_url" \
            -c:v libx264 -preset ultrafast -b:v 300k -r 10 -g 30 \
            -c:a aac -b:a 96k \
            -shortest \
            -f flv "$OUTPUT_URL" \
            -loglevel warning -stats 2>&1

        echo "[quran] Track ended, next in 3s..."
        sleep 3
    done < /tmp/playlist.txt

    echo "[quran] Playlist finished, restarting from beginning..."
    sleep 10
done
