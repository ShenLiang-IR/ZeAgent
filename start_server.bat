@echo off
REM 启动Agent API服务器 (Windows)
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

set "CONDA_BIN=D:\ProgramData\miniconda3\condabin\conda.bat"
set "CONDA_ENV=install_deb_refactor"

echo ==========================================
echo 启动 DeepAgents API 服务器
echo ==========================================

if not exist "%CONDA_BIN%" (
    echo 错误: 未检测到 conda (%CONDA_BIN%)
    echo 请确认 miniconda3 已安装到 D:\ProgramData\miniconda3
    pause
    exit /b 1
)

call "%CONDA_BIN%" activate "%CONDA_ENV%" 2>nul
if errorlevel 1 (
    echo 错误: conda 环境 "%CONDA_ENV%" 不存在
    echo 请先创建: conda create -n %CONDA_ENV% python=3.13
    pause
    exit /b 1
)

set "CONFIG_JSON=config\agent_config.json"
set "CONFIG_JSON_EXAMPLE=config\agent_config.json.example"

if not exist "%CONFIG_JSON%" (
    echo 错误: 找不到 %CONFIG_JSON%
    if exist "%CONFIG_JSON_EXAMPLE%" (
        echo 请先复制 %CONFIG_JSON_EXAMPLE% 为 %CONFIG_JSON% 并配置 API 密钥
    ) else (
        echo 请先创建 %CONFIG_JSON% 并填入 API 配置
    )
    pause
    exit /b 1
)

echo.
echo 启动服务器...
echo API地址: http://localhost:8072
echo API文档: http://localhost:8072/docs
echo.
echo 按 Ctrl+C 停止服务器
echo ==========================================
echo.

python server.py

pause
