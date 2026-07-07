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
    echo "[quran] Fetching source..."

    yt-dlp --flat-playlist --dump-single-json "$PLAYLIST_URL" 2>/dev/null > /tmp/playlist.json
    if [ ! -s /tmp/playlist.json ]; then
        echo "[quran] Failed to fetch, retrying in 30s..."
        sleep 30
        continue
    fi

    mode=$(python3 -c "
import json
with open('/tmp/playlist.json') as f:
    data = json.load(f)
entries = data.get('entries')
print('playlist' if entries else 'single')
" 2>/dev/null)

    if [ "$mode" = "playlist" ]; then
        python3 -c "
import json
with open('/tmp/playlist.json') as f:
    data = json.load(f)
urls = [e['url'] for e in data.get('entries', []) if e.get('url')]
with open('/tmp/tracks.txt','w') as out:
    for u in urls:
        out.write(u + '\n')
" 2>/dev/null

        echo "[quran] Downloading $(wc -l < /tmp/tracks.txt) tracks..."
        > /tmp/concat.txt
        > /tmp/audio_list.txt
        idx=0
        while IFS= read -r url; do
            [ -z "$url" ] && continue
            idx=$((idx + 1))
            title=$(yt-dlp --get-title "$url" 2>/dev/null || echo "Track $idx")
            echo "[quran] Downloading ($idx): $title"
            yt-dlp -x --audio-format m4a -o "/tmp/track_${idx}.%(ext)s" "$url" 2>/dev/null
            found=$(ls /tmp/track_${idx}.* 2>/dev/null | head -1)
            if [ -n "$found" ]; then
                echo "file '$found'" >> /tmp/concat.txt
                echo "$found" >> /tmp/audio_list.txt
            fi
        done < /tmp/tracks.txt

        if [ -s /tmp/concat.txt ]; then
            echo "[quran] Merging audio tracks..."
            ffmpeg -nostdin -f concat -safe 0 -i /tmp/concat.txt -c copy /tmp/all_audio.m4a 2>/dev/null
        else
            echo "[quran] No tracks downloaded, retrying..."
            sleep 30
            continue
        fi
    else
        title=$(yt-dlp --get-title "$PLAYLIST_URL" 2>/dev/null || echo "Single track")
        echo "[quran] Downloading: $title"
        yt-dlp -x --audio-format m4a -o "/tmp/track.%(ext)s" "$PLAYLIST_URL" 2>/dev/null
        found=$(ls /tmp/track.* 2>/dev/null | head -1)
        if [ -z "$found" ]; then
            echo "[quran] Download failed, retrying..."
            sleep 30
            continue
        fi
        cp "$found" /tmp/all_audio.m4a
    fi

    if [ ! -f /tmp/all_audio.m4a ] || [ ! -s /tmp/all_audio.m4a ]; then
        echo "[quran] No audio available, retrying..."
        sleep 30
        continue
    fi

    echo "[quran] Streaming continuously..."
    ffmpeg -nostdin -re -stream_loop -1 -i /tmp/bg.mp4 \
        -stream_loop -1 -i /tmp/all_audio.m4a \
        -map 0:v -map 1:a \
        -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" \
        -c:v libx264 -preset veryfast -b:v 2000k -maxrate 2200k -bufsize 4000k -r 10 -g 30 \
        -c:a aac -b:a 128k \
        -rtmp_live live \
        -f flv \
        "$OUTPUT_URL" \
        -loglevel warning -stats 2>&1 </dev/null

    echo "[quran] Stream stopped, restarting in 10s..."
    sleep 10
done
