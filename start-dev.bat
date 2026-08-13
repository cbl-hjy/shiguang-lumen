@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting backend (port 8000)...
start "" .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
echo Starting frontend (port 5173, LAN accessible)...
cd /d "%~dp0frontend"
start "" node node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173
echo ============================================
echo  PC:  http://127.0.0.1:5173
echo  Phone (same WiFi): http://<PC-LAN-IP>:5173
echo  Find PC IP: ipconfig (IPv4 of WLAN)
echo ============================================
timeout /t 3 >nul
