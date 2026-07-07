from flask import Flask, Response
import subprocess, os, signal, sys

app = Flask(__name__)
proc = None

def start_restream():
    global proc
    if proc is None:
        proc = subprocess.Popen(["/bin/bash", "/restream.sh"],
                                stdout=sys.stdout, stderr=sys.stderr)

@app.route("/")
def health():
    return Response("ok", status=200)

@app.route("/restart")
def restart():
    global proc
    if proc:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc = None
    start_restream()
    return Response("restarted", status=200)

if __name__ == "__main__":
    start_restream()
    app.run(host="0.0.0.0", port=8080)
