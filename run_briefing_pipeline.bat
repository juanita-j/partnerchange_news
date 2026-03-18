@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 이 배치 파일을 작업 스케줄러에서 실행하면 됨
python run_briefing_pipeline.py

rem 종료 코드 그대로 반환 (작업 스케줄러에서 실패 감지 가능)
exit /b %ERRORLEVEL%
