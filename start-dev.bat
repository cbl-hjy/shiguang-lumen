@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  拾光开发环境（双服务器模式）
echo ============================================
echo [1/3] Starting backend (port 8000, --reload)...
rem 2026-08-27 开发工作流升级：--reload 自动重启（watchfiles，改 app/*.py 即生效，不用手动重启）；
rem --reload-dir app 限定监听目录（避免 frontend/node_modules 触发误重启）
start "" .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning --reload --reload-dir app

echo [2/3] Starting frontend (port 5173, Vite HMR)...
rem 2026-08-27 修正：vite root=启动目录（CAC 不认 --root）→ cd frontend 后启动
cd frontend
start "" node node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173
cd ..

echo [3/3] Waiting for services ready...
set /a tries=0
:wait_8000
set /a tries+=1
curl -s -o nul http://127.0.0.1:8000/healthz && goto ok_8000
if %tries% GEQ 30 goto fail_8000
timeout /t 1 /nobreak >nul
goto wait_8000
:ok_8000
echo   - backend 8000 ready
set /a tries=0
:wait_5173
set /a tries+=1
curl -s -o nul http://127.0.0.1:5173/ && goto ok_5173
if %tries% GEQ 30 goto fail_5173
timeout /t 1 /nobreak >nul
goto wait_5173
:ok_5173
echo   - frontend 5173 ready
echo ============================================
echo  ✅ 已就绪
echo  PC:  http://127.0.0.1:5173
echo  Phone (same WiFi): http://<PC-LAN-IP>:5173
echo  Find PC IP: ipconfig (IPv4 of WLAN)
echo ============================================
echo  提示：改 app/*.py 后端自动重启；改 frontend/src/* 页面即时热更新
echo        日志：8000 → 后端窗口；5173 → 前端窗口
timeout /t 3 >nul
exit /b 0

:fail_8000
echo  [ERROR] backend 8000 30 秒未就绪——看后端窗口日志
exit /b 1

:fail_5173
echo  [ERROR] frontend 5173 30 秒未就绪——看前端窗口日志
exit /b 1
