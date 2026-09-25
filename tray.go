package main

import (
	"syscall"
	"unsafe"
)

var (
	modShell32          = syscall.NewLazyDLL("shell32.dll")
	modUser32           = syscall.NewLazyDLL("user32.dll")
	procShellNotifyIcon = modShell32.NewProc("Shell_NotifyIconW")
	procShowWindow      = modUser32.NewProc("ShowWindow")
	procSetForeground   = modUser32.NewProc("SetForegroundWindow")
	procCreatePopupMenu = modUser32.NewProc("CreatePopupMenu")
	procAppendMenuW     = modUser32.NewProc("AppendMenuW")
	procTrackPopupMenu  = modUser32.NewProc("TrackPopupMenu")
	procDestroyMenu     = modUser32.NewProc("DestroyMenu")
	procGetCursorPos    = modUser32.NewProc("GetCursorPos")
	procPostMessageW    = modUser32.NewProc("PostMessageW")
	procLoadImageW      = modUser32.NewProc("LoadImageW")
)

const (
	NIM_ADD        = 0x00000000
	NIM_MODIFY     = 0x00000001
	NIM_DELETE     = 0x00000002
	NIF_MESSAGE    = 0x00000001
	NIF_ICON       = 0x00000002
	NIF_TIP        = 0x00000004
	NIF_INFO       = 0x00000010
	NIIF_INFO      = 0x00000001

	WM_USER        = 0x0400
	WM_TRAY_MSG    = WM_USER + 101

	WM_LBUTTONUP   = 0x0202
	WM_RBUTTONUP   = 0x0205
	WM_LBUTTONDBLCLK = 0x0203

	SW_HIDE        = 0
	SW_RESTORE     = 9

	MF_STRING      = 0x00000000
	MF_SEPARATOR   = 0x00000800
	MF_DISABLED    = 0x00000002
	MF_GRAYED      = 0x00000001

	TPM_RIGHTBUTTON = 0x0002
	TPM_RETURNCMD   = 0x0100
)

type NOTIFYICONDATA struct {
	CbSize           uint32
	HWnd             uintptr
	UID              uint32
	UFlags           uint32
	UCallbackMessage uint32
	HIcon            uintptr
	SzTip            [128]uint16
	DwState          uint32
	DwStateMask      uint32
	SzInfo           [256]uint16
	UTimeoutOrVersion uint32
	SzInfoTitle      [64]uint16
	DwInfoFlags      uint32
	GuidItem         [16]byte
	HBalloonIcon     uintptr
}

type POINT struct {
	X int32
	Y int32
}

type TrayManager struct {
	hwnd        uintptr
	hIcon       uintptr
	nid         NOTIFYICONDATA
	visible     bool
	isConnected bool
	onToggle    func()
	onRestore   func()
	onExit      func()
}

func NewTrayManager(hwnd uintptr, iconPath string, onToggle, onRestore, onExit func()) *TrayManager {
	tm := &TrayManager{
		hwnd:      hwnd,
		onToggle:  onToggle,
		onRestore: onRestore,
		onExit:    onExit,
	}

	// Load ICO if available
	if iconPath != "" {
		pPath, _ := syscall.UTF16PtrFromString(iconPath)
		h, _, _ := procLoadImageW.Call(
			0,
			uintptr(unsafe.Pointer(pPath)),
			1, // IMAGE_ICON
			16, 16,
			0x00000010|0x00000040, // LR_LOADFROMFILE | LR_DEFAULTSIZE
		)
		tm.hIcon = h
	}

	tm.nid.CbSize = uint32(unsafe.Sizeof(tm.nid))
	tm.nid.HWnd = hwnd
	tm.nid.UID = 1
	tm.nid.UFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
	tm.nid.UCallbackMessage = WM_TRAY_MSG
	tm.nid.HIcon = tm.hIcon
	tm.setTip("WDTT — VPN Клиент")

	procShellNotifyIcon.Call(NIM_ADD, uintptr(unsafe.Pointer(&tm.nid)))
	tm.visible = true

	return tm
}

func (tm *TrayManager) setTip(tip string) {
	u16, _ := syscall.UTF16FromString(tip)
	for i := 0; i < len(tm.nid.SzTip); i++ {
		if i < len(u16) {
			tm.nid.SzTip[i] = u16[i]
		} else {
			tm.nid.SzTip[i] = 0
		}
	}
}

func (tm *TrayManager) UpdateStatus(connected bool, statusText string) {
	tm.isConnected = connected
	if connected {
		tm.setTip("WDTT — Подключено")
	} else {
		tm.setTip("WDTT — Отключено")
	}
	procShellNotifyIcon.Call(NIM_MODIFY, uintptr(unsafe.Pointer(&tm.nid)))
}

func (tm *TrayManager) ShowBalloon(title, msg string) {
	tm.nid.UFlags |= NIF_INFO
	tU16, _ := syscall.UTF16FromString(title)
	for i := 0; i < len(tm.nid.SzInfoTitle); i++ {
		if i < len(tU16) {
			tm.nid.SzInfoTitle[i] = tU16[i]
		} else {
			tm.nid.SzInfoTitle[i] = 0
		}
	}
	mU16, _ := syscall.UTF16FromString(msg)
	for i := 0; i < len(tm.nid.SzInfo); i++ {
		if i < len(mU16) {
			tm.nid.SzInfo[i] = mU16[i]
		} else {
			tm.nid.SzInfo[i] = 0
		}
	}
	tm.nid.DwInfoFlags = NIIF_INFO
	procShellNotifyIcon.Call(NIM_MODIFY, uintptr(unsafe.Pointer(&tm.nid)))
	tm.nid.UFlags &^= NIF_INFO
}

func (tm *TrayManager) HandleMessage(lParam uintptr) {
	switch lParam {
	case WM_LBUTTONUP, WM_LBUTTONDBLCLK:
		if tm.onRestore != nil {
			tm.onRestore()
		}
	case WM_RBUTTONUP:
		tm.showContextMenu()
	}
}

func (tm *TrayManager) showContextMenu() {
	hMenu, _, _ := procCreatePopupMenu.Call()
	if hMenu == 0 {
		return
	}
	defer procDestroyMenu.Call(hMenu)

	titlePtr, _ := syscall.UTF16PtrFromString("WDTT VPN Client")
	procAppendMenuW.Call(hMenu, MF_STRING|MF_DISABLED|MF_GRAYED, 100, uintptr(unsafe.Pointer(titlePtr)))

	procAppendMenuW.Call(hMenu, MF_SEPARATOR, 0, 0)

	var stText string
	if tm.isConnected {
		stText = "● Статус: Подключено"
	} else {
		stText = "○ Статус: Отключено"
	}
	stPtr, _ := syscall.UTF16PtrFromString(stText)
	procAppendMenuW.Call(hMenu, MF_STRING|MF_DISABLED|MF_GRAYED, 101, uintptr(unsafe.Pointer(stPtr)))

	var actText string
	if tm.isConnected {
		actText = "⏹ Отключить WDTT"
	} else {
		actText = "⚡ Подключить WDTT"
	}
	actPtr, _ := syscall.UTF16PtrFromString(actText)
	procAppendMenuW.Call(hMenu, MF_STRING, 102, uintptr(unsafe.Pointer(actPtr)))

	procAppendMenuW.Call(hMenu, MF_SEPARATOR, 0, 0)

	openPtr, _ := syscall.UTF16PtrFromString("🖥️ Открыть окно")
	procAppendMenuW.Call(hMenu, MF_STRING, 103, uintptr(unsafe.Pointer(openPtr)))

	exitPtr, _ := syscall.UTF16PtrFromString("❌ Выход")
	procAppendMenuW.Call(hMenu, MF_STRING, 104, uintptr(unsafe.Pointer(exitPtr)))

	var pt POINT
	procGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))

	procSetForeground.Call(tm.hwnd)

	cmd, _, _ := procTrackPopupMenu.Call(
		hMenu,
		TPM_RIGHTBUTTON|TPM_RETURNCMD,
		uintptr(pt.X),
		uintptr(pt.Y),
		0,
		tm.hwnd,
		0,
	)

	switch cmd {
	case 102:
		if tm.onToggle != nil {
			tm.onToggle()
		}
	case 103:
		if tm.onRestore != nil {
			tm.onRestore()
		}
	case 104:
		if tm.onExit != nil {
			tm.onExit()
		}
	}
}

func (tm *TrayManager) Remove() {
	if tm.visible {
		procShellNotifyIcon.Call(NIM_DELETE, uintptr(unsafe.Pointer(&tm.nid)))
		tm.visible = false
	}
}
