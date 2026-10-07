@echo off
rem raphael — CLI entry point (Windows side). Thin wrapper; all logic lives
rem in scripts\raphael_cli.py (stdlib-only Python). WSL uses scripts\raphael.
rem
rem Usage: scripts\raphael status|start|stop|restart|pause|resume|private on^|off
rem               logs [name] [-n N] [-f] ^| jobs [id] ^| cancel <id>
rem               ^| say <text> ^| selftest
rem Instance/port derive from RAPHAEL_INSTANCE/RAPHAEL_PORT (INTERFACES d).
setlocal
set "SCRIPT=%~dp0raphael_cli.py"

if defined RAPHAEL_PY goto run_env

where py >nul 2>nul
if not errorlevel 1 (set "INTERP=py -3" & goto run)
where python >nul 2>nul
if not errorlevel 1 (set "INTERP=python" & goto run)

echo raphael: no Python found (py -3 / python). Set RAPHAEL_PY to an interpreter path. 1>&2
exit /b 127

:run_env
set "INTERP=%RAPHAEL_PY%"

:run
%INTERP% "%SCRIPT%" %*
exit /b %ERRORLEVEL%
