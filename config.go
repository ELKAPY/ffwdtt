package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

type Settings struct {
	CloseAction               string `json:"close_action"` // "ask", "tray", "exit"
	PcvpnPort                 int    `json:"pcvpn_port"`
	PcvpnEnabled              bool   `json:"pcvpn_enabled"`
	Protocol                  string `json:"protocol"` // "dtls" or "rawtun"
	TurnTCP                   bool   `json:"turn_tcp"`
	Obfs                      string `json:"obfs"`         // "audio" or "video"
	CaptchaMode               string `json:"captcha_mode"` // "auto", "wv", "rjs"
	GoDNS                     string `json:"go_dns"`       // "yandex", "cloudflare", "google", etc.
	FirstLaunchShortcutHandled bool  `json:"first_launch_shortcut_handled"`
}

type ConfigManager struct {
	mu           sync.RWMutex
	iniPath      string
	settingsPath string
	Peer         string
	Password     string
	VkHash       string
	Workers      string
	Settings     Settings
}

func getAppDir() string {
	exe, err := os.Executable()
	if err == nil {
		return filepath.Dir(exe)
	}
	return "."
}

func NewConfigManager() *ConfigManager {
	dir := getAppDir()
	cm := &ConfigManager{
		iniPath:      filepath.Join(dir, "config.ini"),
		settingsPath: filepath.Join(dir, "settings.json"),
		Peer:         "1.2.3.4:56000",
		Password:     "",
		VkHash:       "",
		Workers:      "27",
		Settings: Settings{
			CloseAction:  "ask",
			PcvpnPort:    24066,
			PcvpnEnabled: false,
			Protocol:     "dtls",
			TurnTCP:      false,
			Obfs:         "audio",
			CaptchaMode:  "auto",
			GoDNS:        "yandex",
		},
	}
	cm.LoadAll()
	return cm
}

func (cm *ConfigManager) LoadAll() {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	// 1. Check fallback for config.ini if not found in root
	if _, err := os.Stat(cm.iniPath); os.IsNotExist(err) {
		fallback := filepath.Join(os.Getenv("USERPROFILE"), "Downloads", "portable_client", "config.ini")
		if _, errF := os.Stat(fallback); errF == nil {
			cm.iniPath = fallback
		}
	}

	// 2. Read config.ini
	if f, err := os.Open(cm.iniPath); err == nil {
		defer f.Close()
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 {
				k := strings.ToUpper(strings.TrimSpace(parts[0]))
				v := strings.TrimSpace(parts[1])
				switch k {
				case "PEER":
					cm.Peer = v
				case "PASSWORD":
					cm.Password = v
				case "VK_HASH":
					cm.VkHash = v
				case "WORKERS":
					cm.Workers = v
				}
			}
		}
	}

	// 3. Read settings.json
	if data, err := os.ReadFile(cm.settingsPath); err == nil {
		var s Settings
		if err := json.Unmarshal(data, &s); err == nil {
			if s.PcvpnPort <= 0 {
				s.PcvpnPort = 24066
			}
			if s.Protocol == "" {
				s.Protocol = "dtls"
			}
			if s.Obfs == "" {
				s.Obfs = "audio"
			}
			if s.CaptchaMode == "" {
				s.CaptchaMode = "auto"
			}
			if s.GoDNS == "" {
				s.GoDNS = "yandex"
			}
			cm.Settings = s
		}
	}
}

func (cm *ConfigManager) SaveIni(peer, password, vkHash, workers string) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	if peer != "" {
		cm.Peer = strings.TrimSpace(peer)
	}
	if password != "" {
		cm.Password = strings.TrimSpace(password)
	}
	if vkHash != "" {
		cm.VkHash = strings.TrimSpace(vkHash)
	}
	if workers != "" {
		cm.Workers = strings.TrimSpace(workers)
	}

	content := fmt.Sprintf(`# Настройки подключения VK TURN
# Укажите адрес и порт вашего сервера (VPS)
PEER=%s

# Пароль подключения (из него выводится HKDF-SHA256 ключ)
PASSWORD=%s

# Хеш VK-звонка (можно несколько через запятую)
VK_HASH=%s

# Количество параллельных воркеров (по умолчанию 18)
WORKERS=%s
`, cm.Peer, cm.Password, cm.VkHash, cm.Workers)

	target := filepath.Join(getAppDir(), "config.ini")
	return os.WriteFile(target, []byte(content), 0644)
}

func (cm *ConfigManager) SaveSettings(s Settings) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.Settings = s

	data, err := json.MarshalIndent(cm.Settings, "", "  ")
	if err != nil {
		return err
	}
	target := filepath.Join(getAppDir(), "settings.json")
	return os.WriteFile(target, data, 0644)
}

func (cm *ConfigManager) GetVkHashes() []string {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	if cm.VkHash == "" {
		return nil
	}
	var res []string
	for _, h := range strings.Split(cm.VkHash, ",") {
		h = strings.TrimSpace(h)
		if h != "" {
			res = append(res, h)
		}
	}
	return res
}

func (cm *ConfigManager) AddVkHash(newHash string) bool {
	newHash = strings.TrimSpace(newHash)
	if newHash == "" {
		return false
	}
	hashes := cm.GetVkHashes()
	for _, h := range hashes {
		if h == newHash {
			return false
		}
	}
	hashes = append(hashes, newHash)
	_ = cm.SaveIni("", "", strings.Join(hashes, ","), "")
	return true
}

func (cm *ConfigManager) RemoveVkHash(targetHash string) bool {
	hashes := cm.GetVkHashes()
	var updated []string
	found := false
	for _, h := range hashes {
		if h == targetHash {
			found = true
			continue
		}
		updated = append(updated, h)
	}
	if found {
		_ = cm.SaveIni("", "", strings.Join(updated, ","), "")
		return true
	}
	return false
}

func CalcActualWorkers(wStr string) (int, int) {
	n, err := strconv.Atoi(wStr)
	if err != nil || n < 9 {
		n = 27
	}
	groups := n / 9
	if groups <= 0 {
		groups = 1
	}
	return groups * 9, groups
}
