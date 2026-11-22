#!/usr/bin/env sh
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null 2>&1 || { echo 'Please install FFmpeg first: https://ffmpeg.org/download.html'; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo 'Please install Python 3.11+ first.'; exit 1; }
if [ ! -f .venv/bin/python ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -r requirements.txt
printf '\nOpen http://127.0.0.1:8000/ in a browser. Press Ctrl+C to stop.\n\n'
python app.py
