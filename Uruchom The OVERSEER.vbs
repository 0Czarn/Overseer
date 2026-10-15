' Starts The OVERSEER (npm start in this folder) without a console window.
' Double-click this file, or the "The OVERSEER" shortcut next to it.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
If Not fso.FolderExists(folder & "\node_modules\electron") Then
  MsgBox "Electron is not installed - run ""npm install"" in:" & vbCrLf & folder, vbExclamation, "The OVERSEER"
  WScript.Quit 1
End If
shell.CurrentDirectory = folder
shell.Run "cmd /c npm start", 0, False
