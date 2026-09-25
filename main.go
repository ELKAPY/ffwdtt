package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"unsafe"

	"github.com/jchv/go-webview2"
)

//go:embed ui/index.html
var uiHTML string

var (
	modUser32Close       = syscall.NewLazyDLL("user32.dll")
	modDwmapi            = syscall.NewLazyDLL("dwmapi.dll")
	procDefWindowProcW   = modUser32Close.NewProc("DefWindowProcW")
	procCallWindowProcW  = modUser32Close.NewProc("CallWindowProcW")
	procSetWindowLongPtr = modUser32Close.NewProc("SetWindowLongPtrW")
	procDestroyWindow    = modUser32Close.NewProc("DestroyWindow")
	procPostQuitMessage  = modUser32Close.NewProc("PostQuitMessage")
	procDwmSetWindowAttr = modDwmapi.NewProc("DwmSetWindowAttribute")
	procGetWindowRect    = modUser32Close.NewProc("GetWindowRect")

	origWndProc uintptr
	globalApp   *AppController
)

type RECT struct {
	Left   int32
	Top    int32
	Right  int32
	Bottom int32
}

func setDarkTitleBar(hwnd uintptr) {
	val := int32(1)
	// DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win11 / Win10 20H1+), 19 on older Win10
	_, _, _ = procDwmSetWindowAttr.Call(hwnd, 20, uintptr(unsafe.Pointer(&val)), 4)
	_, _, _ = procDwmSetWindowAttr.Call(hwnd, 19, uintptr(unsafe.Pointer(&val)), 4)
}

type AppController struct {
	w         webview2.WebView
	hwnd      uintptr
	cm        *ConfigManager
	tm        *TunnelManager
	tray      *TrayManager
	closingOK bool
}

func (a *AppController) SaveCurrentWindowSize() {
	if a == nil || a.hwnd == 0 {
		return
	}
	var r RECT
	procGetWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&r)))
	w := int(r.Right - r.Left)
	h := int(r.Bottom - r.Top)
	// Only save if window is not minimized or maximized offscreen
	if w >= 600 && h >= 500 && r.Left > -10000 {
		s := a.cm.Settings
		s.WindowWidth = w
		s.WindowHeight = h
		_ = a.cm.SaveSettings(s)
	}
}

func main() {
	// 1. Ensure elevated Administrator rights (essential for WinTUN network driver)
	RelaunchAsAdmin()

	cm := NewConfigManager()
	tm := NewTunnelManager(cm)

	initW := cm.Settings.WindowWidth
	if initW < 600 {
		initW = 840
	}
	initH := cm.Settings.WindowHeight
	if initH < 500 {
		initH = 760
	}

	w := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug:     true,
		AutoFocus: true,
		WindowOptions: webview2.WindowOptions{
			Title:     "WDTT — VK TURN Client",
			Width:     uint(initW),
			Height:    uint(initH),
			IconId:    1,
		},
	})
	if w == nil {
		fmt.Println("Error: Failed to initialize WebView2 window.")
		return
	}
	defer w.Destroy()

	hwnd := uintptr(w.Window())
	setDarkTitleBar(hwnd)
	app := &AppController{
		w:    w,
		hwnd: hwnd,
		cm:   cm,
		tm:   tm,
	}
	globalApp = app

	// 2. Setup System Tray
	iconPath := filepath.Join(getAppDir(), "app_icon.ico")
	tray := NewTrayManager(
		hwnd,
		iconPath,
		func() { // toggle VPN from tray
			_ = app.ToggleVPN()
		},
		func() { // restore window from tray
			app.RestoreWindow()
		},
		func() { // exit from tray
			app.CleanExit()
		},
	)
	app.tray = tray
	defer tray.Remove()

	// 3. Subclass window procedure to intercept [X] Close button
	subclassWindow(hwnd)

	// 4. Connect callbacks to Webview2 JS events
	tm.onLog = func(line string) {
		w.Dispatch(func() {
			data, _ := json.Marshal(line)
			w.Eval(fmt.Sprintf("window.onLogLine(%s);", string(data)))
		})
	}

	tm.onStatus = func(status string, connected bool) {
		w.Dispatch(func() {
			tray.UpdateStatus(connected, status)
			data, _ := json.Marshal(status)
			w.Eval(fmt.Sprintf("window.onStatusChange(%s, %t);", string(data), connected))
		})
	}

	tm.onStats = func(s TunnelStats) {
		w.Dispatch(func() {
			data, _ := json.Marshal(s)
			w.Eval(fmt.Sprintf("window.onStats(%s);", string(data)))
		})
	}

	// 5. Bind Go functions to JavaScript
	w.Bind("getConfig", app.GetConfig)
	w.Bind("getNetworkInfo", app.GetNetworkInfo)
	w.Bind("getHashes", app.GetHashes)
	w.Bind("addHash", app.AddHash)
	w.Bind("removeHash", app.RemoveHash)
	w.Bind("saveMainKey", app.SaveMainKey)
	w.Bind("saveAll", app.SaveAll)
	w.Bind("toggleVPN", app.ToggleVPN)
	w.Bind("toggleBridge", app.ToggleBridge)
	w.Bind("pingTest", app.PingTest)
	w.Bind("checkHashes", app.CheckHashes)
	w.Bind("createShortcut", app.CreateShortcut)
	w.Bind("dismissFirstRun", app.DismissFirstRun)
	w.Bind("handleCloseChoice", app.HandleCloseChoice)

	// 6. Set embedded HTML
	w.SetHtml(uiHTML)

	// 7. Run main event loop
	w.Run()
}

func subclassWindow(hwnd uintptr) {
	cb := syscall.NewCallback(customWndProc)
	ret, _, _ := procSetWindowLongPtr.Call(hwnd, uintptr(^uint(3)), cb) // GWLP_WNDPROC = -4
	origWndProc = ret
}

func customWndProc(hwnd uintptr, msg uint32, wParam, lParam uintptr) uintptr {
	if msg == WM_TRAY_MSG {
		if globalApp != nil && globalApp.tray != nil {
			globalApp.tray.HandleMessage(lParam)
		}
		return 0
	}

	if msg == 0x0010 { // WM_CLOSE
		if globalApp != nil {
			globalApp.SaveCurrentWindowSize()
			action := globalApp.cm.Settings.CloseAction
			if action == "tray" {
				procShowWindow.Call(hwnd, SW_HIDE)
				globalApp.tray.ShowBalloon("WDTT свёрнут в трей", "Приложение продолжает работать в фоне. Кликните по иконке в трее, чтобы открыть.")
				return 0 // Prevent window destroy
			} else if action == "exit" {
				globalApp.CleanExit()
				return 0
			} else {
				// Show custom in-UI confirmation modal
				globalApp.w.Eval("window.onCloseRequested();")
				return 0 // Cancel immediate close
			}
		}
	}

	ret, _, _ := procCallWindowProcW.Call(origWndProc, hwnd, uintptr(msg), wParam, lParam)
	return ret
}

func (a *AppController) RestoreWindow() {
	a.w.Dispatch(func() {
		procShowWindow.Call(a.hwnd, SW_RESTORE)
		procSetForeground.Call(a.hwnd)
	})
}

func (a *AppController) CleanExit() {
	a.SaveCurrentWindowSize()
	a.tm.StopVPN()
	a.tm.bridge.Stop()
	if a.tray != nil {
		a.tray.Remove()
	}
	procDestroyWindow.Call(a.hwnd)
	procPostQuitMessage.Call(0)
	os.Exit(0)
}

func (a *AppController) GetConfig() map[string]interface{} {
	a.cm.LoadAll()
	return map[string]interface{}{
		"peer":     a.cm.Peer,
		"password": a.cm.Password,
		"workers":  a.cm.Workers,
		"hashes":   a.cm.GetVkHashes(),
		"settings": a.cm.Settings,
	}
}

func (a *AppController) GetNetworkInfo() map[string]string {
	return map[string]string{
		"ip":   GetLocalLANIP(),
		"mdns": GetMDNSHostname(),
	}
}

func (a *AppController) GetHashes() []string {
	return a.cm.GetVkHashes()
}

func (a *AppController) AddHash(h string) bool {
	return a.cm.AddVkHash(h)
}

func (a *AppController) RemoveHash(h string) bool {
	return a.cm.RemoveVkHash(h)
}

func (a *AppController) SaveMainKey(k string) bool {
	_ = a.cm.SaveIni("", "", k, "")
	return true
}

func (a *AppController) SaveAll(peer, password, workers string, pcvpnPort int, closeAction, protocol string, turnTcp bool, obfs, captcha, dns string) bool {
	_ = a.cm.SaveIni(peer, password, "", workers)

	s := a.cm.Settings
	s.PcvpnPort = pcvpnPort
	s.CloseAction = closeAction
	s.Protocol = protocol
	s.TurnTCP = turnTcp
	s.Obfs = obfs
	s.CaptchaMode = captcha
	s.GoDNS = dns
	_ = a.cm.SaveSettings(s)

	return true
}

func (a *AppController) ToggleVPN() bool {
	if a.tm.isConnected {
		a.tm.StopVPN()
		return false
	}
	err := a.tm.StartVPN()
	return err == nil
}

func (a *AppController) ToggleBridge() bool {
	return a.tm.ToggleBridge()
}

func (a *AppController) PingTest() string {
	return a.tm.PingTest()
}

func (a *AppController) CheckHashes() []HashCheckResult {
	return a.tm.CheckHashes()
}

func (a *AppController) CreateShortcut() bool {
	return CreateDesktopShortcut()
}

func (a *AppController) DismissFirstRun() {
	s := a.cm.Settings
	s.FirstLaunchShortcutHandled = true
	_ = a.cm.SaveSettings(s)
}

func (a *AppController) HandleCloseChoice(action string, dontAskAgain bool) {
	a.SaveCurrentWindowSize()
	if dontAskAgain {
		s := a.cm.Settings
		s.CloseAction = action
		_ = a.cm.SaveSettings(s)
	}

	if action == "tray" {
		procShowWindow.Call(a.hwnd, SW_HIDE)
		a.tray.ShowBalloon("WDTT свёрнут в трей", "Приложение продолжает работать в фоне. Кликните по иконке в трее, чтобы открыть.")
	} else {
		a.CleanExit()
	}
}
