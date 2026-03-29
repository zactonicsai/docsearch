@echo off
REM ──────────────────────────────────────────────────────────────
REM run_tests.bat — Run DocMS worker test suite with coverage (Windows)
REM ──────────────────────────────────────────────────────────────
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo ===============================================
echo   DocMS Worker — Test Suite (Windows)
echo ===============================================

REM ── 1. Check Python ────────────────────────────────────────
echo.
echo [1/5] Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   ERROR: Python not found. Install Python 3.10+ and add to PATH.
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo   Found: %%i

REM ── 2. Install / upgrade dependencies ──────────────────────
echo.
echo [2/5] Installing dependencies...

REM Force-reinstall pydantic pair first to fix any cached mismatch
pip install --force-reinstall --no-cache-dir pydantic pydantic-core --quiet 2>nul

if exist requirements-test.txt (
    pip install --upgrade -r requirements-test.txt --quiet 2>nul
) else (
    pip install --upgrade pytest pytest-asyncio pytest-cov pytest-mock httpx elasticsearch temporalio --quiet 2>nul
)

if %ERRORLEVEL% neq 0 (
    echo   WARNING: pip install failed. Retrying with --user flag...
    pip install --force-reinstall --no-cache-dir pydantic pydantic-core --quiet --user 2>nul
    if exist requirements-test.txt (
        pip install --upgrade -r requirements-test.txt --quiet --user 2>nul
    ) else (
        pip install --upgrade pytest pytest-asyncio pytest-cov pytest-mock httpx elasticsearch temporalio --quiet --user 2>nul
    )
)
echo   Done.

REM ── 3. Verify critical imports ─────────────────────────────
echo.
echo [3/5] Verifying imports...

python -c "import pytest_cov" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   ERROR: pytest-cov is not installed. Run:
    echo       pip install pytest-cov
    exit /b 1
)
echo   pytest-cov .... OK

python -c "import temporalio" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   ERROR: temporalio is not installed. Run:
    echo       pip install temporalio
    exit /b 1
)
echo   temporalio .... OK

REM Quick pydantic sanity check — warn but don't block
python -c "import pydantic" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   WARNING: pydantic import failed. Tests may still work.
    echo   To fix:  pip install --force-reinstall pydantic pydantic-core
) else (
    echo   pydantic ...... OK
)

REM ── 4. Set default env vars ────────────────────────────────
echo.
echo [4/5] Setting environment...
if not defined ELASTICSEARCH_URL set "ELASTICSEARCH_URL=http://localhost:9200"
if not defined BACKEND_URL set "BACKEND_URL=http://localhost:8080"
if not defined TEMPORAL_HOST set "TEMPORAL_HOST=localhost:7233"
echo   ELASTICSEARCH_URL=%ELASTICSEARCH_URL%
echo   BACKEND_URL=%BACKEND_URL%
echo   TEMPORAL_HOST=%TEMPORAL_HOST%

REM ── 5. Run tests with coverage ─────────────────────────────
echo.
echo [5/5] Running pytest with coverage...
echo.

python -m pytest ^
    --cov=shared ^
    --cov=activities ^
    --cov=workflows ^
    --cov=worker ^
    --cov=run_worker ^
    --cov-config=pyproject.toml ^
    --cov-report=term-missing ^
    --cov-report=html:htmlcov ^
    --cov-report=xml:coverage.xml ^
    --cov-branch ^
    -v ^
    --tb=short ^
    %*

set TEST_EXIT=%ERRORLEVEL%

REM ── Summary ────────────────────────────────────────────────
echo.
echo ===============================================
if %TEST_EXIT% equ 0 (
    echo   [PASS] All tests passed
) else (
    echo   [FAIL] Some tests failed (exit code: %TEST_EXIT%)
    echo.
    echo   If you see pydantic ImportError, run this manually:
    echo       pip install --force-reinstall --no-cache-dir pydantic pydantic-core
    echo.
)
echo   Coverage report: htmlcov\index.html
echo   XML report:      coverage.xml
echo ===============================================

exit /b %TEST_EXIT%
