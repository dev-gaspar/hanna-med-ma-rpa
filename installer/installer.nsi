; HannaMed RPA Installer Script
!define APPNAME "HannaMedRPA"
!define COMPANYNAME "HannaMed"
!define DESCRIPTION "RPA Agent for Medical Assistant"
!define VERSIONMAJOR 1
!define VERSIONMINOR 0
!define VERSIONBUILD 0

!define INSTALLDIR "$APPDATA\${APPNAME}"
!define DISPLAYNAME "HannaMed RPA"

Name "${DISPLAYNAME}"
OutFile "HannaMed-RPA-Setup.exe"
InstallDir "${INSTALLDIR}"
RequestExecutionLevel user

; Modern UI
!include "MUI2.nsh"

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"

; Installer sections
Section "Install"
    ; Set output path
    SetOutPath "$INSTDIR"
    
    ; Copy main executable
    File "..\dist\HannaMedRPA.exe"
    
    ; Create bin directory and copy cloudflared
    SetOutPath "$INSTDIR\bin"
    File "..\bin\cloudflared.exe"
    
    ; Create config directories
    SetOutPath "$INSTDIR"
    CreateDirectory "$INSTDIR\.cloudflared"
    CreateDirectory "$INSTDIR\logs"
    CreateDirectory "$INSTDIR\config"
    
    ; Create desktop shortcut
    CreateShortcut "$DESKTOP\${DISPLAYNAME}.lnk" "$INSTDIR\HannaMedRPA.exe" "" "$INSTDIR\HannaMedRPA.exe" 0
    
    ; Create start menu shortcuts
    CreateDirectory "$SMPROGRAMS\${DISPLAYNAME}"
    CreateShortcut "$SMPROGRAMS\${DISPLAYNAME}\${DISPLAYNAME}.lnk" "$INSTDIR\HannaMedRPA.exe" "" "$INSTDIR\HannaMedRPA.exe" 0
    CreateShortcut "$SMPROGRAMS\${DISPLAYNAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0
    
    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; Write registry info for Add/Remove Programs
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayName" "${DISPLAYNAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "Publisher" "${COMPANYNAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayVersion" "${VERSIONMAJOR}.${VERSIONMINOR}.${VERSIONBUILD}"
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "VersionMajor" ${VERSIONMAJOR}
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "VersionMinor" ${VERSIONMINOR}
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "NoRepair" 1
    
    ; Success message
    MessageBox MB_OK "¡${DISPLAYNAME} se ha instalado correctamente!$\n$\nPuede iniciar la aplicación desde el acceso directo en el escritorio o desde el menú inicio." /SD IDOK
SectionEnd

; Uninstaller section
Section "Uninstall"
    ; Stop any running processes
    ; (User should close the app before uninstalling, but just in case)
    
    ; Delete files
    Delete "$INSTDIR\HannaMedRPA.exe"
    Delete "$INSTDIR\bin\cloudflared.exe"
    Delete "$INSTDIR\Uninstall.exe"
    
    ; Delete shortcuts
    Delete "$DESKTOP\${DISPLAYNAME}.lnk"
    Delete "$SMPROGRAMS\${DISPLAYNAME}\${DISPLAYNAME}.lnk"
    Delete "$SMPROGRAMS\${DISPLAYNAME}\Uninstall.lnk"
    RMDir "$SMPROGRAMS\${DISPLAYNAME}"
    
    ; Ask user if they want to keep configuration
    MessageBox MB_YESNO "¿Desea eliminar también la configuración y los logs?$\n$\n(Si planea reinstalar, puede mantener la configuración)" /SD IDNO IDYES delete_config IDNO keep_config
    
    delete_config:
        RMDir /r "$INSTDIR\.cloudflared"
        RMDir /r "$INSTDIR\logs"
        RMDir /r "$INSTDIR\config"
        Goto done_config
    
    keep_config:
        ; Keep config files
        MessageBox MB_OK "La configuración se ha mantenido en:$\n$INSTDIR" /SD IDOK
    
    done_config:
    
    ; Remove directories
    RMDir /r "$INSTDIR\bin"
    RMDir "$INSTDIR"
    
    ; Remove from registry
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
    
    MessageBox MB_OK "${DISPLAYNAME} se ha desinstalado correctamente." /SD IDOK
SectionEnd
