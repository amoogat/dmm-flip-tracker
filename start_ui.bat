@echo off
echo Starting DMM Flip Tracker UI...
echo.
echo Will open at: http://localhost:8501
echo (Use a different port? Run: streamlit run tracker_ui.py --server.port 8502)
echo.
echo Press Ctrl+C to stop
echo.
streamlit run tracker_ui.py
pause
