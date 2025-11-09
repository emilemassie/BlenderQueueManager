@ECHO ON
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe -m PyInstaller --clean -y -n BlenderQueueManager --noconsole --onefile --icon=./icons/blender_icon.png --add-data ./icons:icons --add-data ./ui:ui BlenderQueueManager.py
pause