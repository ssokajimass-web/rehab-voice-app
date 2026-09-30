@echo off
chcp 65001 > nul
echo ==============================================
echo  リハビリ音声ガイド Webアプリを起動しています...
echo ==============================================
python "%~dp0scripts\start_server.py"
pause
