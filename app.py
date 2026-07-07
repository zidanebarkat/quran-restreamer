from flask import Flask, Response, request, jsonify
import subprocess, os, signal, sys, threading, time, json

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
        wr('Downloading audio...')
        try:
            subprocess.run(['rm', '-f', '/tmp/track.*'], capture_output=True)
            subprocess.run(['yt-dlp', '-f', 'bestaudio', '-x', '--audio-format', 'mp3',
                '-o', '/tmp/track.%(ext)s', source], check=True, timeout=120, capture_output=True)
            if not os.path.exists('/tmp/track.mp3'):
                for f in os.listdir('/tmp'):
                    if f.startswith('track.'):
                        os.rename(f'/tmp/{f}', '/tmp/track.mp3')
                        break
            if not os.path.getsize('/tmp/track.mp3') > 0:
                raise Exception('empty file')
            wr('Audio ready')
        except Exception as e:
            wr(f'Audio download failed: {e}')
            if not stream_active:
                break
            time.sleep(5)
            continue

        af = f'volume={volume}'
        if pitch_enabled:
            af += f',asetrate=46000,aresample={sample_rate}'

        wr('Starting ffmpeg...')
        cmd = ['ffmpeg', '-nostdin', '-re',
            '-stream_loop', '-1', '-i', '/tmp/bg.mp4',
            '-stream_loop', '-1', '-i', '/tmp/track.mp3',
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'copy',
            '-af', af,
            '-ar', sample_rate,
            '-c:a', 'aac', '-b:a', bitrate,
            '-rtmp_live', 'live',
            '-f', 'flv', output]
        wr(f'ffmpeg: -c:v copy -c:a aac -b:a {bitrate}')

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
        wr('Restarting audio loop...')
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
<h1>🎬 Stream Panel <small>v3</small></h1>
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
      <div class="form-row">
        <div class="form-group">
          <label>Audio Bitrate</label>
          <select name="bitrate" id="bitrate">
            <option value="128k">128 kbps</option>
            <option value="192k" selected>192 kbps</option>
            <option value="256k">256 kbps</option>
            <option value="320k">320 kbps</option>
          </select>
        </div>
        <div class="form-group">
          <label>Volume</label>
          <input type="number" name="volume" id="volume" min="0.5" max="3" step="0.1">
        </div>
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
      <div class="form-group">
        <div class="toggle-group">
          <label class="toggle">
            <input type="checkbox" name="pitch" id="pitch">
            <span class="slider"></span>
          </label>
          <span class="toggle-label">Pitch Shift (anti Content ID)</span>
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
updateStatus();
setInterval(updateStatus, 3000);
setInterval(fetchLogs, 2000);
</script>
</body>
</html>'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
