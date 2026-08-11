@echo off
title Agnes IA - Serveur local
cd /d "E:\SteamLibrary\steamapps\common\Grand Theft Auto V\Agnes_IA"
set PY="C:\Users\tomg-\AppData\Local\Programs\Python\Python313\python.exe"
echo ============================================
echo  Agnes IA - demarrage du serveur local
echo  URL: http://127.0.0.1:8765
echo  Logs: server-local.log / server-local.err.log
echo  Fermez cette fenetre pour arreter le serveur
echo ============================================
%PY% -m uvicorn server:app --host 127.0.0.1 --port 8765 >> server-local.log 2>> server-local.err.log
pause
