@echo off
REM Double-click this to launch Artemis (brain + desktop client) with no terminals.
REM It runs scripts\launch-artemis.ps1, which starts the brain hidden and opens the client.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch-artemis.ps1"
