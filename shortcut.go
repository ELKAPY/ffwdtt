package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func CreateDesktopShortcut() bool {
	dir := getAppDir()
	targetExe := filepath.Join(dir, "WDTT.exe")
	if _, err := os.Stat(targetExe); os.IsNotExist(err) {
		targetExe = filepath.Join(dir, "start.bat")
	}
	iconPath := filepath.Join(dir, "app_icon.ico")

	psCmd := fmt.Sprintf(`$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut("$d\WDTT.lnk"); $s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; $s.IconLocation = '%s,0'; $s.Description = 'WDTT VPN Client'; $s.Save()`,
		targetExe, dir, iconPath)

	cmd := exec.Command("powershell", "-NoProfile", "-Command", psCmd)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}
	return cmd.Run() == nil
}
