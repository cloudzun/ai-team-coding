@echo off
cd /d "%~dp0"
echo Open http://127.0.0.1:4380/ in your browser. Press Ctrl+C to stop.
python -m http.server 4380 --directory .
