package main

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
)

type TunnelStats struct {
	ActiveWorkers int    `json:"active_workers"`
	DownMB        string `json:"down_mb"`
	UpMB          string `json:"up_mb"`
	TotalMB       string `json:"total_mb"`
}

type HashCheckResult struct {
	Idx     string `json:"idx"`
	Hash    string `json:"hash"`
	Status  string `json:"status"`
	Details string `json:"details"`
}

type TunnelManager struct {
	mu          sync.Mutex
	configMgr   *ConfigManager
	vpnCmd      *exec.Cmd
	bridge      *PcvpnBridge
	isConnected bool
	statusText  string
	lastPing    string
	stats       TunnelStats

	onLog    func(string)
	onStatus func(string, bool)
	onStats  func(TunnelStats)
}

func checkIsAdmin() bool {
	_, err := os.Open(`\\.\PHYSICALDRIVE0`)
	return err == nil
}

func RelaunchAsAdmin() {
	if checkIsAdmin() {
		return
	}
	exe, err := os.Executable()
	if err != nil {
		return
	}
	verb := "runas"
	cmd := exec.Command("powershell", "-NoProfile", "-Command", fmt.Sprintf("Start-Process -FilePath '%s' -Verb %s", exe, verb))
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}
	_ = cmd.Start()
	os.Exit(0)
}

func GetLocalLANIP() string {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return "127.0.0.1"
	}
	defer conn.Close()
	localAddr := conn.LocalAddr().(*net.UDPAddr)
	return localAddr.IP.String()
}

func GetMDNSHostname() string {
	h, err := os.Hostname()
	if err != nil {
		return "desktop.local"
	}
	return strings.ToLower(h) + ".local"
}

func NewTunnelManager(cm *ConfigManager) *TunnelManager {
	tm := &TunnelManager{
		configMgr:  cm,
		statusText: "Отключено",
		bridge:     NewPcvpnBridge(cm.Settings.PcvpnPort),
		stats: TunnelStats{
			ActiveWorkers: 0,
			DownMB:        "0.00",
			UpMB:          "0.00",
			TotalMB:       "0.00",
		},
	}
	return tm
}

func (tm *TunnelManager) getBinaryPath() string {
	dir := getAppDir()
	localExe := filepath.Join(dir, "vk-turn-client.exe")
	if _, err := os.Stat(localExe); err == nil {
		return localExe
	}
	fallback := filepath.Join(os.Getenv("USERPROFILE"), "Downloads", "portable_client", "vk-turn-client.exe")
	if _, err := os.Stat(fallback); err == nil {
		return fallback
	}
	return "vk-turn-client.exe"
}

func (tm *TunnelManager) StartVPN() error {
	tm.mu.Lock()
	if tm.vpnCmd != nil && tm.vpnCmd.Process != nil {
		tm.mu.Unlock()
		return nil
	}

	if !checkIsAdmin() {
		tm.mu.Unlock()
		tm.updateStatus("Ошибка: Требуются права Администратора", false)
		if tm.onLog != nil {
			tm.onLog("[ОШИБКА] Для режима VPN требуются права Администратора (создание сетевого адаптера WinTUN)!\n")
		}
		return fmt.Errorf("требуются права администратора")
	}

	exe := tm.getBinaryPath()
	workersCount := tm.configMgr.Workers
	isRawtun := tm.configMgr.Settings.Protocol == "rawtun"
	mode := "vpn"
	if isRawtun {
		mode = "rawtun"
	}

	// Build arguments matching start.bat
	args := []string{
		"-mode", mode,
		"-peer", tm.configMgr.Peer,
		"-password", tm.configMgr.Password,
		"-vk", tm.configMgr.VkHash,
		"-n", workersCount,
	}

	if isRawtun {
		args = append(args, "-notls")
	}
	if tm.configMgr.Settings.TurnTCP {
		args = append(args, "-turn-tcp")
	}
	if tm.configMgr.Settings.Obfs != "" && tm.configMgr.Settings.Obfs != "audio" {
		args = append(args, "-obfs", tm.configMgr.Settings.Obfs)
	}
	if tm.configMgr.Settings.CaptchaMode != "" && tm.configMgr.Settings.CaptchaMode != "auto" {
		args = append(args, "-captcha-mode", tm.configMgr.Settings.CaptchaMode)
	}
	if tm.configMgr.Settings.GoDNS != "" && tm.configMgr.Settings.GoDNS != "yandex" {
		args = append(args, "-go-dns", tm.configMgr.Settings.GoDNS)
	}

	cmd := exec.Command(exe, args...)
	cmd.Dir = filepath.Dir(exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		tm.mu.Unlock()
		return err
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		tm.mu.Unlock()
		tm.updateStatus("Ошибка запуска", false)
		return err
	}

	tm.vpnCmd = cmd
	tm.mu.Unlock()

	tm.updateStatus("Подключение...", false)

	go tm.readVpnLogs(stdout)
	return nil
}

func (tm *TunnelManager) readVpnLogs(pipeReader io.ReadCloser) {
	defer pipeReader.Close()

	scanner := bufio.NewScanner(pipeReader)
	for scanner.Scan() {
		line := scanner.Text()
		if tm.onLog != nil {
			tm.onLog(line)
		}

		// Detect errors
		if strings.Contains(line, "Access is denied") || strings.Contains(line, "Ошибка запуска WinTUN") || strings.Contains(line, "CreateTUN ошибка") {
			tm.updateStatus("Ошибка: WinTUN (нужны права Администратора)", false)
		} else if strings.Contains(line, "Failed to create private namespace") || strings.Contains(line, "Failed to take device installation mutex") {
			tm.updateStatus("Ошибка: WinTUN (нужны права Администратора)", false)
		} else if strings.Contains(line, "[READY]") || strings.Contains(line, "VPN запущен") || strings.Contains(line, "Userspace WireGuard up") || strings.Contains(line, "WireGuard Конфиг") || strings.Contains(line, "[ПРЯМОЙ] Без DTLS") || strings.Contains(line, "[WINTUN-WG]") {
			if !tm.isConnected {
				tm.updateStatus("Подключено", true)
			}
		}

		// Statistics parsing
		if strings.Contains(line, "[СТАТИСТИКА]") {
			reAct := regexp.MustCompile(`Активных:\s*(\d+)`)
			reDown := regexp.MustCompile(`↓([\d.]+)\s*МБ`)
			reUp := regexp.MustCompile(`↑([\d.]+)\s*МБ`)
			reTot := regexp.MustCompile(`Трафик:\s*([\d.]+)\s*МБ`)

			if m := reAct.FindStringSubmatch(line); len(m) > 1 {
				tm.stats.ActiveWorkers, _ = strconv.Atoi(m[1])
			}
			if m := reDown.FindStringSubmatch(line); len(m) > 1 {
				tm.stats.DownMB = m[1]
			}
			if m := reUp.FindStringSubmatch(line); len(m) > 1 {
				tm.stats.UpMB = m[1]
			}
			if m := reTot.FindStringSubmatch(line); len(m) > 1 {
				tm.stats.TotalMB = m[1]
			}

			// If workers are active or traffic is flowing, tunnel is definitely connected
			if (tm.stats.ActiveWorkers > 0 || tm.stats.TotalMB != "0.00") && !tm.isConnected {
				tm.updateStatus("Подключено", true)
			}

			if tm.onStats != nil {
				tm.onStats(tm.stats)
			}
		}
	}

	tm.mu.Lock()
	if tm.vpnCmd != nil {
		_ = tm.vpnCmd.Wait()
		tm.vpnCmd = nil
	}
	tm.mu.Unlock()

	tm.updateStatus("Отключено", false)
}

func (tm *TunnelManager) StopVPN() {
	tm.mu.Lock()
	if tm.vpnCmd != nil && tm.vpnCmd.Process != nil {
		pid := tm.vpnCmd.Process.Pid
		killCmd := exec.Command("taskkill", "/F", "/T", "/PID", strconv.Itoa(pid))
		killCmd.SysProcAttr = &syscall.SysProcAttr{
			HideWindow:    true,
			CreationFlags: 0x08000000,
		}
		_ = killCmd.Run()
		tm.vpnCmd = nil
	}
	tm.mu.Unlock()
	tm.updateStatus("Отключено", false)
}

func (tm *TunnelManager) ToggleBridge() bool {
	if tm.bridge.IsRunning() {
		tm.bridge.Stop()
		if tm.onLog != nil {
			tm.onLog("[PCVPN] Мост остановлен.\n")
		}
		return false
	}
	port := tm.configMgr.Settings.PcvpnPort
	if port <= 0 {
		port = 24066
	}
	err := tm.bridge.Start(port, "vpn")
	if err != nil {
		if tm.onLog != nil {
			tm.onLog(fmt.Sprintf("[PCVPN ОШИБКА] Не удалось открыть порт %d: %v\n", port, err))
		}
		return false
	}
	if tm.onLog != nil {
		tm.onLog(fmt.Sprintf("[PCVPN] Мост запущен на порту %d (SOCKS5 + HTTP CONNECT)\n", port))
	}
	return tm.bridge.IsRunning()
}

func (tm *TunnelManager) IsBridgeRunning() bool {
	return tm.bridge.IsRunning()
}

func (tm *TunnelManager) PingTest() string {
	exe := tm.getBinaryPath()
	cmd := exec.Command(exe,
		"-peer", tm.configMgr.Peer,
		"-password", tm.configMgr.Password,
		"-vk", tm.configMgr.VkHash,
		"-ping-only",
	)
	cmd.Dir = filepath.Dir(exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "Ошибка"
	}
	for _, line := range strings.Split(string(out), "\n") {
		if strings.Contains(line, "PING_RESULT|") {
			parts := strings.Split(line, "PING_RESULT|")
			if len(parts) > 1 {
				return strings.TrimSpace(parts[1]) + " ms"
			}
		}
	}
	return "Таймаут"
}

func (tm *TunnelManager) CheckHashes() []HashCheckResult {
	exe := tm.getBinaryPath()
	cmd := exec.Command(exe,
		"-peer", tm.configMgr.Peer,
		"-password", tm.configMgr.Password,
		"-vk", tm.configMgr.VkHash,
		"-check-hashes",
	)
	cmd.Dir = filepath.Dir(exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x08000000,
	}
	out, _ := cmd.CombinedOutput()
	var results []HashCheckResult
	for _, line := range strings.Split(string(out), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "HASH_CHECK|") {
			p := strings.Split(line, "|")
			if len(p) >= 5 {
				results = append(results, HashCheckResult{
					Idx:     p[1],
					Hash:    p[2],
					Status:  p[3],
					Details: p[4],
				})
			}
		}
	}
	return results
}

func (tm *TunnelManager) updateStatus(text string, connected bool) {
	tm.statusText = text
	tm.isConnected = connected
	if tm.onStatus != nil {
		tm.onStatus(text, connected)
	}
}
