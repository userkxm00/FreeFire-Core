@echo off
chcp 65001 >nul
echo.
echo ================================================================
echo 🚀 جاري رفع المشروع إلى GitHub: userkxm00/FreeFire-Core
echo ================================================================
echo.

"C:\Program Files\Git\cmd\git.exe" push -u origin main

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ تم رفع المشروع بنجاح إلى المستودع:
    echo 🔗 https://github.com/userkxm00/FreeFire-Core
    echo.
) else (
    echo.
    echo ❌ حدث خطأ أو مطلوب تسجيل الدخول إلى GitHub في المتصفح.
    echo.
)

pause
