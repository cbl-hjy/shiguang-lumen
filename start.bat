@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem #21 安全护栏：0.0.0.0 监听必须 SHIGUANG_TOKEN 已配置（门锁没装不能开门）
findstr /C:"SHIGUANG_TOKEN=" .env >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .env 缺少 SHIGUANG_TOKEN —— 门锁没装不能开门（0.0.0.0 监听会裸奔）
    echo 配置方法：在 .env 加 SHIGUANG_TOKEN=随机字符串
    pause
    exit /b 1
)

rem 前端产物新鲜度（#B 2026-08-13）：启动 = 最新产物，从流程上消灭"旧产物"可能。
rem dist/build.json 时间戳由后端 index 路由暴露（响应头 X-Built-At + 启动日志），一眼可查服务的是哪天的产物
echo [build] 构建前端产物（幂等，几秒）...
cd /d "%~dp0frontend"
call npm run build >nul 2>&1
if errorlevel 1 (
    echo [build] 失败——但服务仍启动（可能用旧产物）。错误信息见上
)
cd /d "%~dp0"

rem 看门狗：拉起服务 + 崩溃自动重启 + 日志（Ctrl+C 优雅退出）
echo ============================================
echo  ShiguangGuard 看门狗启动
echo  Server: http://localhost:8000 （0.0.0.0，局域网可访问，token 已保护）
echo  崩溃自动重启 · 日志 data/service_guard.log
echo  Ctrl+C 停止（不会自动重启）
echo ============================================
.venv\Scripts\python.exe scripts\service_guard.py
