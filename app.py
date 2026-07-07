from flask import Flask, Response, request, jsonify
import subprocess, os, signal, sys, threading, time, json, re, urllib.request

app = Flask(__name__)

stream_active = False
ffmpeg_proc = None
bg_thread = None
log_buffer = []
log_lock = threading.Lock()
bg_lock = threading.Lock()

DEFAULTS = {
    'source_url': 'https://archive.org/details/lifeways11_gmail_001_20180201_0110',
    'output_url': 'rtmps://a.rtmp.youtube.com:443/live2/ru33-pe6q-z9gr-a2es-5t82',
    'bg_url': 'https://assets.mixkit.co/videos/22728/22728-720.mp4',
    'bitrate': '192k',
    'volume': '1.5',
    'pitch': 'on',
    'sample_rate': '44100',
    'fps': '10',
    'resolution': '1280:720',
    'video_bitrate': '1500k',
}
config_path = '/tmp/panel_config.json'

def load_config():
    try:
        with open(config_path) as f:
            return json.load(f)
    except:
        return dict(DEFAULTS)

def save_config(cfg):
    with open(config_path, 'w') as f:
        json.dump(cfg, f)

def wr(msg):
    with log_lock:
        ts = time.strftime('%H:%M:%S')
        log_buffer.append(f'[{ts}] {msg}')
        if len(log_buffer) > 500:
            log_buffer[:] = log_buffer[-500:]
    print(f'[panel] {msg}', flush=True)

def kill_ffmpeg():
    global ffmpeg_proc
    p = ffmpeg_proc
    if p and p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            p.wait(timeout=5)
        except:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except:
                pass
    ffmpeg_proc = None

def scrape_tracks(url):
    wr(f'Scraping tracks from {url}...')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='replace')
        pattern = re.compile(r'href="(https://archive\.org/download/[^"]+\.mp3)"', re.I)
        matches = pattern.findall(html)
        if not matches:
            pattern = re.compile(r'href="(/download/[^"]+\.mp3)"', re.I)
            matches = ['https://archive.org' + m for m in pattern.findall(html)]
        seen = []
        for m in matches:
            if m not in seen:
                seen.append(m)
        wr(f'Found {len(seen)} tracks')
        return seen
    except Exception as e:
        wr(f'Scrape failed: {e}')
        return []

def get_bg_direct_url(bg_url):
    for ext in ['.mp4', '.webm', '.mov']:
        base = bg_url.rsplit('.', 1)[0] if '.' in bg_url.split('/')[-1] else bg_url
        if bg_url.endswith(ext):
            return bg_url
    return bg_url

def probe_duration(path_or_url):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', path_or_url],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return round(float(r.stdout.strip()), 1)
    except:
        pass
    return None

def bg_loop(cfg):
    global stream_active, ffmpeg_proc
    source = cfg['source_url']
    output = cfg['output_url']
    bg_url = cfg['bg_url']
    bitrate = cfg['bitrate']
    volume = cfg['volume']
    pitch_enabled = cfg.get('pitch', 'on') == 'on'
    sample_rate = cfg.get('sample_rate', '44100')
    fps = cfg.get('fps', '10')
    resolution = cfg.get('resolution', '1280:720')
    video_bitrate = cfg.get('video_bitrate', '1500k')

    wr('Pre-encoding background...')
    try:
        if not os.path.exists('/tmp/bg.mp4'):
            subprocess.run(['curl', '-sL', bg_url, '-o', '/tmp/bg_orig.mp4'],
                check=True, timeout=60, capture_output=True)
            w, h = resolution.split(':')
            subprocess.run(['ffmpeg', '-nostdin', '-i', '/tmp/bg_orig.mp4',
                '-vf', f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', video_bitrate,
                '-maxrate', '2000k', '-bufsize', '3000k', '-r', fps, '-g', '30', '-an',
                '/tmp/bg.mp4', '-y'], check=True, timeout=120, capture_output=True)
            os.remove('/tmp/bg_orig.mp4')
            wr('Background ready')
    except Exception as e:
        wr(f'Background failed: {e}')
        stream_active = False
        return

    while stream_active:
        tracks = scrape_tracks(source)
        if not tracks:
            wr('No tracks found, retrying in 30s...')
            time.sleep(30)
            continue

        playlist_path = '/tmp/playlist.txt'
        with open(playlist_path, 'w') as f:
            for t in tracks:
                f.write(f"file '{t}'\n")
        wr(f'Generated playlist with {len(tracks)} tracks (001 → {os.path.basename(tracks[-1])})')

        wr('Starting ffmpeg with playlist...')
        cmd = ['ffmpeg', '-nostdin', '-re',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-stream_loop', '-1',
            '-f', 'concat', '-safe', '0',
            '-i', playlist_path,
            '-i', '/tmp/bg.mp4',
            '-map', '1:v', '-map', '0:a',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', bitrate,
            '-rtmp_live', 'live',
            '-f', 'flv', output]
        wr(f'ffmpeg: concat playlist, -c:v copy -c:a aac -b:a {bitrate}')

        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 preexec_fn=os.setsid)
        except Exception as e:
            wr(f'ffmpeg spawn failed: {e}')
            time.sleep(5)
            continue

        ffmpeg_proc = p
        for line in iter(p.stdout.readline, b''):
            if not stream_active:
                kill_ffmpeg()
                break
            text = line.decode('utf-8', errors='replace').strip()
            if text and 'size=' in text and 'time=' in text:
                pass
            elif text:
                wr(text)
        p.wait()
        rc = p.returncode
        wr(f'ffmpeg exited ({rc})')
        ffmpeg_proc = None
        if not stream_active:
            break
        wr('Playlist ended, rescraping and restarting...')
        time.sleep(2)

    wr('Stream stopped')
    ffmpeg_proc = None
    stream_active = False

@app.route('/')
def index():
    return HTML_PANEL

@app.route('/start')
def start_stream():
    global stream_active, bg_thread
    with bg_lock:
        if stream_active:
            return jsonify({'ok': False, 'error': 'Already live'})
        cfg = load_config()
        if not cfg.get('source_url') or not cfg.get('output_url'):
            return jsonify({'ok': False, 'error': 'Missing source or output URL'})
        wr('=== GOING LIVE ===')
        stream_active = True
        bg_thread = threading.Thread(target=bg_loop, args=(cfg,), daemon=True)
        bg_thread.start()
    return jsonify({'ok': True})

@app.route('/stop')
def stop_stream():
    global stream_active
    with bg_lock:
        if not stream_active:
            return jsonify({'ok': False, 'error': 'Not live'})
        wr('=== STOPPING ===')
        stream_active = False
        kill_ffmpeg()
    return jsonify({'ok': True})

@app.route('/config', methods=['POST'])
def update_config():
    data = request.get_json(force=True)
    cfg = load_config()
    for k in DEFAULTS:
        if k in data:
            cfg[k] = data[k]
    save_config(cfg)
    wr('Config saved')
    return jsonify({'ok': True, 'config': cfg})

@app.route('/tracks')
def get_tracks():
    cfg = load_config()
    tracks = scrape_tracks(cfg['source_url'])
    return jsonify({
        'count': len(tracks),
        'tracks': [os.path.basename(t) for t in tracks],
        'urls': tracks
    })

@app.route('/preview')
def preview():
    cfg = load_config()
    tracks = scrape_tracks(cfg['source_url'])
    if not tracks:
        return jsonify({'ok': False, 'error': 'No tracks found'})
    first_url = tracks[0]
    dur = probe_duration(first_url)
    return jsonify({
        'ok': True,
        'first_track': os.path.basename(first_url),
        'first_url': first_url,
        'duration_s': dur,
        'total_tracks': len(tracks),
        'bg_url': cfg['bg_url'],
        'bg_direct': get_bg_direct_url(cfg['bg_url'])
    })

preview_clip_lock = threading.Lock()
@app.route('/preview_clip')
def preview_clip():
    if not preview_clip_lock.acquire(blocking=False):
        return jsonify({'ok': False, 'error': 'Already generating'}), 429
    try:
        cfg = load_config()
        tracks = scrape_tracks(cfg['source_url'])
        if not tracks:
            return jsonify({'ok': False, 'error': 'No tracks'}), 400
        first_url = tracks[0]
        bg_url = cfg['bg_url']
        wr('Generating preview clip...')
        clip_path = '/tmp/preview_clip.mp4'
        subprocess.run(['rm', '-f', clip_path], capture_output=True)

        subprocess.run(['curl', '-sL', '-o', '/tmp/_p_bg.mp4', bg_url],
            check=True, timeout=60, capture_output=True)
        subprocess.run(['curl', '-sL', '-o', '/tmp/_p_audio.mp3', first_url],
            check=True, timeout=60, capture_output=True)

        subprocess.run(['ffmpeg', '-nostdin', '-y',
            '-i', '/tmp/_p_bg.mp4',
            '-i', '/tmp/_p_audio.mp3',
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-t', '15',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            clip_path], check=True, timeout=120, capture_output=True)

        os.remove('/tmp/_p_bg.mp4')
        os.remove('/tmp/_p_audio.mp3')

        if not os.path.exists(clip_path):
            return jsonify({'ok': False, 'error': 'Failed to generate'}), 500

        wr('Preview clip ready')
        return jsonify({'ok': True, 'url': '/clip.mp4'})
    except Exception as e:
        wr(f'Preview clip failed: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        preview_clip_lock.release()

@app.route('/clip.mp4')
def serve_clip():
    path = '/tmp/preview_clip.mp4'
    if not os.path.exists(path):
        return 'Not found', 404
    return open(path, 'rb').read(), 200, {'Content-Type': 'video/mp4'}

@app.route('/status')
def get_status():
    return jsonify({
        'live': stream_active,
        'config': load_config()
    })

@app.route('/logs')
def get_logs():
    with log_lock:
        return '\n'.join(log_buffer[-100:]), 200, {'Content-Type': 'text/plain'}

HTML_PANEL = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quran Restream Panel</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.container{max-width:1200px;margin:0 auto;padding:20px}
h1{font-size:24px;margin-bottom:20px;color:#fff;display:flex;align-items:center;gap:12px}
h1 small{font-size:13px;color:#8b949e;font-weight:400}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px}
.card h2{font-size:16px;margin-bottom:16px;color:#f0f6fc}
.form-group{margin-bottom:14px}
.form-group label{display:block;font-size:13px;color:#8b949e;margin-bottom:4px}
.form-group input,.form-group select{width:100%;padding:8px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;font-family:inherit}
.form-group input:focus,.form-group select:focus{outline:none;border-color:#58a6ff}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.toggle-group{display:flex;gap:12px;align-items:center;margin-top:4px}
.toggle{position:relative;display:inline-block;width:44px;height:24px}
.toggle input{opacity:0;width:0;height:0}
.toggle .slider{position:absolute;cursor:pointer;inset:0;background-color:#30363d;border-radius:24px;transition:.3s}
.toggle .slider::before{content:"";position:absolute;height:18px;width:18px;left:3px;bottom:3px;background-color:#fff;border-radius:50%;transition:.3s}
.toggle input:checked+.slider{background-color:#238636}
.toggle input:checked+.slider::before{transform:translateX(20px)}
.toggle-label{font-size:13px;color:#8b949e}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 24px;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;transition:.2s;text-decoration:none}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-green{background:#238636;color:#fff}
.btn-green:hover:not(:disabled){background:#2ea043}
.btn-red{background:#da3633;color:#fff}
.btn-red:hover:not(:disabled){background:#f85149}
.btn-blue{background:#1f6feb;color:#fff}
.btn-blue:hover:not(:disabled){background:#388bfd}
.btn-grey{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-grey:hover:not(:disabled){background:#30363d}
.btn-sm{padding:6px 14px;font-size:13px}
.actions{display:flex;gap:12px;align-items:center;margin-top:16px;flex-wrap:wrap}
.status-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.status-dot.live{background:#3fb950;box-shadow:0 0 8px #3fb950}
.status-dot.stopped{background:#f85149}
.status-text{font-size:14px;font-weight:600}
.log-box{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;height:400px;overflow-y:auto;font-family:'Cascadia Code','Fira Code',monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-all}
.log-box .info{color:#8b949e}
.log-box .warn{color:#d29922}
.log-box .err{color:#f85149}
.log-box .ok{color:#3fb950}
.status-bar{display:flex;align-items:center;gap:16px;padding:12px 16px;background:#0d1117;border:1px solid #30363d;border-radius:6px;margin-bottom:16px;flex-wrap:wrap}
.status-bar .stat{font-size:13px;color:#8b949e}
.status-bar .stat strong{color:#c9d1d9}
@media(max-width:768px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
<h1>🎬 Stream Panel <small>v5</small></h1>
<div class="status-bar" id="statusBar">
  <span><span class="status-dot" id="statusDot"></span><span class="status-text" id="statusText">Checking...</span></span>
</div>
<div class="grid">
  <div class="card">
    <h2>Configuration</h2>
    <form id="configForm">
      <div class="form-group">
        <label>Audio Source URL</label>
        <input type="url" name="source_url" id="source_url" placeholder="https://archive.org/details/...">
      </div>
      <div class="form-group">
        <label>YouTube RTMPS Output URL</label>
        <input type="text" name="output_url" id="output_url" placeholder="rtmps://a.rtmp.youtube.com/...">
      </div>
      <div class="form-group">
        <label>Background Video URL</label>
        <input type="url" name="bg_url" id="bg_url" placeholder="https://...mp4">
      </div>
      <div class="form-group">
        <label>Audio Bitrate</label>
        <select name="bitrate" id="bitrate">
          <option value="128k">128 kbps</option>
          <option value="192k" selected>192 kbps</option>
          <option value="256k">256 kbps</option>
          <option value="320k">320 kbps</option>
        </select>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Resolution</label>
          <select name="resolution" id="resolution">
            <option value="1280:720">720p</option>
            <option value="1920:1080">1080p</option>
            <option value="854:480">480p</option>
          </select>
        </div>
        <div class="form-group">
          <label>FPS</label>
          <select name="fps" id="fps">
            <option value="10">10</option>
            <option value="15">15</option>
            <option value="24">24</option>
            <option value="30">30</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Video Bitrate</label>
          <select name="video_bitrate" id="video_bitrate">
            <option value="1000k">1 Mbps</option>
            <option value="1500k" selected>1.5 Mbps</option>
            <option value="2000k">2 Mbps</option>
            <option value="3000k">3 Mbps</option>
          </select>
        </div>
        <div class="form-group">
          <label>Sample Rate</label>
          <select name="sample_rate" id="sample_rate">
            <option value="44100">44100 Hz</option>
            <option value="48000">48000 Hz</option>
          </select>
        </div>
      </div>
      <div style="margin-top:12px;display:flex;gap:8px">
        <button type="button" class="btn btn-blue btn-sm" onclick="saveConfig()">💾 Save</button>
      </div>
    </form>
  </div>
  <div class="card">
    <h2>Control & Logs</h2>
    <div class="actions">
      <button class="btn btn-green" id="btnGoLive" onclick="goLive()">▶ Go Live</button>
      <button class="btn btn-red" id="btnStop" onclick="stopStream()" disabled>⏹ Stop</button>
      <button class="btn btn-grey btn-sm" onclick="clearLogs()">🗑 Clear</button>
    </div>
    <div class="log-box" id="logBox">Waiting...</div>
  </div>
</div>

<div class="card" style="margin-top:20px">
  <h2>🎬 Studio Preview</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
    <div>
      <label style="font-size:13px;color:#8b949e;display:block;margin-bottom:6px">Combined Stream Preview (bg + audio)</label>
      <div style="background:#000;border-radius:6px;overflow:hidden;max-height:240px">
        <video id="combinedPreview" controls style="width:100%;max-height:240px;display:block"
          poster="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='180'%3E%3Crect fill='%23161b22' width='320' height='180'/%3E%3Ctext x='50%25' y='50%25' fill='%238b949e' font-family='sans-serif' font-size='14' text-anchor='middle' dy='.3em'%3EGenerate preview%3C/text%3E%3C/svg%3E">
          Your browser doesn't support video.
        </video>
      </div>
      <button class="btn btn-grey btn-sm" onclick="generateCombinedPreview()" style="margin-top:8px">🎬 Generate Combined Preview (15s)</button>
      <span id="previewInfo" style="font-size:12px;color:#8b949e;margin-left:8px"></span>
      <div id="previewProgress" style="font-size:12px;color:#d29922;margin-top:4px;display:none">Generating...</div>
    </div>
    <div>
      <label style="font-size:13px;color:#8b949e;display:block;margin-bottom:6px">Source Info</label>
      <div id="trackList" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px;height:240px;overflow-y:auto;font-size:12px;font-family:monospace;color:#8b949e">
        Generate preview to verify source
      </div>
      <button class="btn btn-grey btn-sm" onclick="sourceInfo()" style="margin-top:8px">📡 Source Info</button>
      <span id="trackCount" style="font-size:12px;color:#8b949e;margin-left:8px"></span>
    </div>
  </div>
</div>
</div>
<script>
function applyForm(c) {
  if (!c) return;
  for (const [k,v] of Object.entries(c)) {
    const el = document.getElementById(k);
    if (!el) continue;
    if (el.type === 'checkbox') el.checked = v === 'on' || v === true;
    else el.value = v;
  }
}
function readForm() {
  const d = {};
  document.querySelectorAll('#configForm input,#configForm select').forEach(el => {
    d[el.name] = el.type === 'checkbox' ? (el.checked ? 'on' : 'off') : el.value;
  });
  return d;
}
function saveConfig() {
  const data = readForm();
  fetch('/config', {method:'POST', body:JSON.stringify(data), headers:{'Content-Type':'application/json'}})
    .then(r=>r.json()).then(d=>{ addLog('Config saved','ok'); })
    .catch(e=>addLog('Save failed','err'));
}
function goLive() {
  saveConfig();
  document.getElementById('btnGoLive').disabled = true;
  addLog('Starting...','info');
  fetch('/start').then(r=>r.json()).then(d=>{
    if(!d.ok) { addLog('Error: '+d.error,'err'); document.getElementById('btnGoLive').disabled = false; }
  }).catch(e=>{ addLog('Start failed','err'); document.getElementById('btnGoLive').disabled = false; });
}
function stopStream() {
  document.getElementById('btnStop').disabled = true;
  addLog('Stopping...','warn');
  fetch('/stop').then(r=>r.json()).then(d=>{
    addLog(d.ok ? 'Stopped' : 'Error: '+d.error, d.ok ? 'warn' : 'err');
  }).catch(e=>addLog('Stop failed','err'));
}
function clearLogs() { document.getElementById('logBox').innerHTML = ''; }
function addLog(msg,cls='info') {
  const box = document.getElementById('logBox');
  const ts = new Date().toLocaleTimeString();
  box.innerHTML += '<span class="'+cls+'">['+ts+'] '+msg+'</span>\n';
  box.scrollTop = box.scrollHeight;
}
function updateStatus() {
  fetch('/status').then(r=>r.json()).then(d=>{
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');
    if(d.live) {
      dot.className = 'status-dot live';
      txt.textContent = '● LIVE';
      document.getElementById('btnGoLive').disabled = true;
      document.getElementById('btnStop').disabled = false;
    } else {
      dot.className = 'status-dot stopped';
      txt.textContent = '○ Stopped';
      document.getElementById('btnGoLive').disabled = false;
      document.getElementById('btnStop').disabled = true;
    }
    if(d.config) applyForm(d.config);
  }).catch(()=>{});
}
function fetchLogs() {
  fetch('/logs').then(r=>r.text()).then(t=>{
    const box = document.getElementById('logBox');
    if(t) box.innerHTML = t;
    box.scrollTop = box.scrollHeight;
  }).catch(()=>{});
}
function generateCombinedPreview() {
  const vid = document.getElementById('combinedPreview');
  const info = document.getElementById('previewInfo');
  const prog = document.getElementById('previewProgress');
  info.textContent = '';
  prog.style.display = 'block';
  prog.textContent = 'Generating 15s preview (bg + audio)...';
  fetch('/preview_clip').then(r=>r.json()).then(d=>{
    prog.style.display = 'none';
    if(!d.ok) { info.textContent = 'Error: '+d.error; return; }
    vid.src = d.url;
    vid.play().catch(()=>{});
    info.textContent = 'Ready — bg + first track combined';
  }).catch(e=>{ prog.style.display = 'none'; info.textContent = 'Failed: '+e; });
}
function sourceInfo() {
  const box = document.getElementById('trackList');
  const cnt = document.getElementById('trackCount');
  box.innerHTML = 'Scanning...';
  fetch('/tracks').then(r=>r.json()).then(d=>{
    cnt.textContent = d.count+' tracks';
    if(d.tracks.length===0) { box.innerHTML = 'No tracks found'; return; }
    box.innerHTML = d.tracks.map((t,i)=>'<span style="color:'+(i===0?'#58a6ff':'#8b949e')+'">'+
      String(i+1).padStart(3,'0')+'. '+t+'</span>').join('\n');
  }).catch(e=>{ box.innerHTML = 'Failed: '+e; });
}
updateStatus();
setInterval(updateStatus, 3000);
setInterval(fetchLogs, 2000);
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
