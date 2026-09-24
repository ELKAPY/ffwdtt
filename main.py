import os
import sys
import time
import socket
import threading
import subprocess
import tkinter as tk
import customtkinter as ctk
from PIL import Image

from config_manager import ConfigManager
from tunnel_manager import TunnelManager, is_admin, get_lan_ip, get_mdns_name
from tray_manager import TrayManager

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(p):
            return p
    if getattr(sys, 'frozen', False):
        p = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), relative_path)
        if os.path.exists(p):
            return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def create_desktop_shortcut():
    app_dir = get_app_dir()
    target = os.path.join(app_dir, "WDTT.exe")
    if not os.path.exists(target):
        target = os.path.join(app_dir, "start.bat")
    ico = os.path.join(app_dir, "app_icon.ico")
    
    # Try win32com
    try:
        import win32com.client
        sh = win32com.client.Dispatch("WScript.Shell")
        desktop = sh.SpecialFolders("Desktop")
        sc = sh.CreateShortcut(os.path.join(desktop, "WDTT.lnk"))
        sc.TargetPath = target
        sc.WorkingDirectory = app_dir
        if os.path.exists(ico):
            sc.IconLocation = f"{ico},0"
        sc.Description = "WDTT VPN Client"
        sc.Save()
        return True
    except Exception:
        pass

    # Fallback to powershell
    try:
        ps_code = f'$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath("Desktop"); $s = $ws.CreateShortcut("$d\\WDTT.lnk"); $s.TargetPath = "{target}"; $s.WorkingDirectory = "{app_dir}"; $s.IconLocation = "{ico},0"; $s.Save()'
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], creationflags=0x08000000 if os.name == 'nt' else 0)
        return True
    except Exception:
        return False

# Appearance settings
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLOR_BG = "#0B0F19"
COLOR_CARD = "#111827"
COLOR_CARD_BORDER = "#1F293D"
COLOR_ACCENT = "#00E5FF"
COLOR_ACCENT_HOVER = "#00B4D8"
COLOR_SUCCESS = "#10B981"
COLOR_SUCCESS_HOVER = "#059669"
COLOR_WARNING = "#F59E0B"
COLOR_DANGER = "#EF4444"
COLOR_DANGER_HOVER = "#DC2626"
COLOR_TEXT_PRIMARY = "#F9FAFB"
COLOR_TEXT_SECONDARY = "#9CA3AF"
COLOR_TEXT_MUTED = "#6B7280"

class CloseConfirmDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_choice):
        super().__init__(parent)
        self.parent = parent
        self.on_choice = on_choice
        
        self.title("Закрытие WDTT")
        self.geometry("460x280")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_CARD)
        
        self.transient(parent)
        self.grab_set()
        
        x = parent.winfo_x() + (parent.winfo_width() // 2) - 230
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 140
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

        self.dont_show_again_var = ctk.BooleanVar(value=True)
        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=25, pady=25)

        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        title_lbl = ctk.CTkLabel(
            header_frame,
            text="Куда свернуть приложение?",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY
        )
        title_lbl.pack(anchor="w")

        desc_lbl = ctk.CTkLabel(
            container,
            text="Вы можете свернуть окно в системный трей возле часов.\nТуннель и мост для телефона продолжат стабильно работать в фоне.\nЛибо можно закрыть программу полностью.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_SECONDARY,
            justify="left"
        )
        desc_lbl.pack(anchor="w", pady=(0, 15))

        cb = ctk.CTkCheckBox(
            container,
            text="Запомнить выбор (больше не показывать)",
            variable=self.dont_show_again_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            border_color=COLOR_CARD_BORDER
        )
        cb.pack(anchor="w", pady=(0, 20))

        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", side="bottom")

        btn_exit = ctk.CTkButton(
            btn_frame,
            text="Закрыть полностью",
            fg_color="#261E27",
            hover_color=COLOR_DANGER_HOVER,
            text_color=COLOR_DANGER,
            border_width=1,
            border_color=COLOR_DANGER,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            height=38,
            command=self._choose_exit
        )
        btn_exit.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_tray = ctk.CTkButton(
            btn_frame,
            text="В системный трей",
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            height=38,
            command=self._choose_tray
        )
        btn_tray.pack(side="right", fill="x", expand=True)

    def _choose_tray(self):
        save_choice = self.dont_show_again_var.get()
        self.destroy()
        self.on_choice("tray", save_choice)

    def _choose_exit(self):
        save_choice = self.dont_show_again_var.get()
        self.destroy()
        self.on_choice("exit", save_choice)


class WdttApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.config_mgr = ConfigManager()
        self.tunnel_mgr = TunnelManager(self.config_mgr)
        self.tray_mgr = TrayManager(
            on_restore=self._restore_from_tray,
            on_toggle_tunnel=self._tray_toggle_vpn,
            on_exit=self._clean_exit
        )
        
        # Window configuration
        self.title("WDTT — VPN & PCVPN Client")
        self.geometry("820x680")
        self.minsize(760, 620)
        self.configure(fg_color=COLOR_BG)
        
        # Load app icon
        icon_path = get_resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.protocol("WM_DELETE_WINDOW", self.on_close_clicked)

        # Session timer
        self.conn_start_time = None
        self.timer_running = False

        # Build UI
        self._build_header()
        self._build_tabs()
        self._build_tab_tunnel()
        self._build_tab_pcvpn()
        self._build_tab_settings()
        self._build_tab_console()

        # Connect Tunnel Manager callbacks
        self.tunnel_mgr.on_log = self._handle_log_line
        self.tunnel_mgr.on_status = self._handle_status_change
        self.tunnel_mgr.on_stats = self._handle_stats_update
        self.tunnel_mgr.on_bridge_status = self._handle_bridge_status_change

        # Start tray
        self.tray_mgr.start()
        
        # Select default tab
        self._select_tab("tunnel")

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=0, height=70)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Brand
        brand_frame = ctk.CTkFrame(header, fg_color="transparent")
        brand_frame.pack(side="left", padx=25, pady=12)

        title_lbl = ctk.CTkLabel(
            brand_frame,
            text="WDTT",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLOR_ACCENT
        )
        title_lbl.pack(side="left")

        subtitle_lbl = ctk.CTkLabel(
            brand_frame,
            text="TUNNEL",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLOR_TEXT_SECONDARY
        )
        subtitle_lbl.pack(side="left", padx=(6, 0), pady=(3, 0))

        # Admin Badge
        admin_state = is_admin()
        admin_text = "🛡️ ADMIN" if admin_state else "⚠️ USER"
        admin_color = COLOR_SUCCESS if admin_state else COLOR_WARNING
        admin_badge = ctk.CTkLabel(
            brand_frame,
            text=admin_text,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=admin_color,
            fg_color="#1F2937",
            corner_radius=6,
            padx=8,
            pady=3
        )
        admin_badge.pack(side="left", padx=(12, 0))

        # Status Pills in Header (VPN + PCVPN)
        status_frame = ctk.CTkFrame(header, fg_color="transparent")
        status_frame.pack(side="right", padx=25)

        self.bridge_pill = ctk.CTkLabel(
            status_frame,
            text="📱 МОСТ: ВЫКЛ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
            fg_color="#182030",
            corner_radius=10,
            padx=10,
            pady=5
        )
        self.bridge_pill.pack(side="right", padx=(8, 0))

        self.status_pill = ctk.CTkLabel(
            status_frame,
            text="● VPN: ОТКЛЮЧЕН",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
            fg_color="#182030",
            corner_radius=10,
            padx=12,
            pady=5
        )
        self.status_pill.pack(side="right")

    def _build_tabs(self):
        self.nav_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD, corner_radius=10, height=44)
        self.nav_frame.pack(fill="x", padx=25, pady=(15, 10))

        self.tab_buttons = {}
        tabs = [
            ("tunnel", "⚡ VPN Туннель"),
            ("pcvpn", "📱 PCVPN Мост"),
            ("settings", "⚙️ Настройки"),
            ("console", "📜 Консоль и Логи")
        ]

        for tab_id, tab_label in tabs:
            btn = ctk.CTkButton(
                self.nav_frame,
                text=tab_label,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color="transparent",
                text_color=COLOR_TEXT_SECONDARY,
                hover_color="#1F293D",
                corner_radius=8,
                height=34,
                command=lambda tid=tab_id: self._select_tab(tid)
            )
            btn.pack(side="left", padx=4, pady=5, expand=True, fill="x")
            self.tab_buttons[tab_id] = btn

        self.page_container = ctk.CTkFrame(self, fg_color="transparent")
        self.page_container.pack(fill="both", expand=True, padx=25, pady=(0, 15))

        self.pages = {}

    def _select_tab(self, tab_id):
        for tid, page in self.pages.items():
            if tid == tab_id:
                page.pack(fill="both", expand=True)
                self.tab_buttons[tid].configure(fg_color="#1F293D", text_color=COLOR_ACCENT)
            else:
                page.pack_forget()
                self.tab_buttons[tid].configure(fg_color="transparent", text_color=COLOR_TEXT_SECONDARY)

    # ------------------ TAB 1: TUNNEL ------------------
    def _build_tab_tunnel(self):
        page = ctk.CTkFrame(self.page_container, fg_color="transparent")
        self.pages["tunnel"] = page

        # First Launch Shortcut Prompt
        if not self.config_mgr.settings.get("first_launch_shortcut_handled", False):
            self.first_run_card = ctk.CTkFrame(page, fg_color="#182338", corner_radius=10, border_width=1, border_color=COLOR_ACCENT)
            self.first_run_card.pack(fill="x", pady=(0, 10), padx=2)

            f_content = ctk.CTkFrame(self.first_run_card, fg_color="transparent")
            f_content.pack(fill="x", padx=15, pady=8)

            ctk.CTkLabel(
                f_content,
                text="📌 Создать ярлык WDTT на Рабочем столе для быстрого запуска?",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=COLOR_TEXT_PRIMARY
            ).pack(side="left")

            btn_dismiss = ctk.CTkButton(
                f_content,
                text="✕ Позже",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color="transparent",
                hover_color="#222C40",
                text_color=COLOR_TEXT_MUTED,
                width=65,
                height=28,
                command=self._dismiss_shortcut_banner
            )
            btn_dismiss.pack(side="right", padx=(6, 0))

            btn_make_sc = ctk.CTkButton(
                f_content,
                text="Создать ярлык",
                font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color="#000000",
                height=28,
                command=self._create_shortcut_and_dismiss
            )
            btn_make_sc.pack(side="right")

        # Hero Card: VPN Control
        hero_card = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        hero_card.pack(fill="x", pady=(0, 12), padx=2)

        hero_content = ctk.CTkFrame(hero_card, fg_color="transparent")
        hero_content.pack(fill="x", padx=25, pady=20)

        # Big VPN Button
        btn_wrapper = ctk.CTkFrame(hero_content, fg_color="transparent")
        btn_wrapper.pack(side="left", padx=(5, 25))

        self.btn_connect = ctk.CTkButton(
            btn_wrapper,
            text="ПОДКЛЮЧИТЬ VPN",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            width=200,
            height=60,
            corner_radius=30,
            command=self._toggle_vpn
        )
        self.btn_connect.pack()

        # Hero Info Right
        hero_info = ctk.CTkFrame(hero_content, fg_color="transparent")
        hero_info.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            hero_info,
            text="ГЛАВНЫЙ СЕТЕВОЙ ТУННЕЛЬ (WINTUN / VPN):",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED
        ).pack(anchor="w", pady=(0, 4))

        self.lbl_main_status = ctk.CTkLabel(
            hero_info,
            text="VPN отключен. Нажмите кнопку слева для запуска туннеля.",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLOR_TEXT_SECONDARY
        )
        self.lbl_main_status.pack(anchor="w", pady=(0, 8))

        # Quick Bridge Control row in Hero
        bridge_bar = ctk.CTkFrame(hero_info, fg_color="#0D111A", corner_radius=8, height=36)
        bridge_bar.pack(fill="x")
        bridge_bar.pack_propagate(False)

        self.lbl_hero_bridge = ctk.CTkLabel(
            bridge_bar,
            text=f"📱 Мост для телефона: Остановлен (порт {self.config_mgr.pcvpn_port})",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.lbl_hero_bridge.pack(side="left", padx=12)

        self.btn_hero_bridge = ctk.CTkButton(
            bridge_bar,
            text="Включить мост",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#182030",
            hover_color="#222C40",
            text_color=COLOR_ACCENT,
            width=110,
            height=26,
            command=self._toggle_bridge
        )
        self.btn_hero_bridge.pack(side="right", padx=6)

        # Cards Grid: Server, Workers, Traffic, Session
        grid_frame = ctk.CTkFrame(page, fg_color="transparent")
        grid_frame.pack(fill="x", pady=(0, 12))
        grid_frame.columnconfigure((0, 1, 2, 3), weight=1)

        # Card 1: Server & Ping
        c1 = ctk.CTkFrame(grid_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        c1.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        ctk.CTkLabel(c1, text="СЕРВЕР", font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(10, 2))
        self.lbl_card_peer = ctk.CTkLabel(c1, text=self.config_mgr.peer, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=COLOR_TEXT_PRIMARY)
        self.lbl_card_peer.pack(anchor="w", padx=15, pady=(0, 4))
        self.btn_ping = ctk.CTkButton(
            c1,
            text="⚡ Пинг",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color="#182030",
            hover_color="#222C40",
            text_color=COLOR_ACCENT,
            height=24,
            command=self._check_ping
        )
        self.btn_ping.pack(anchor="w", padx=15, pady=(0, 10))

        # Card 2: Workers
        c2 = ctk.CTkFrame(grid_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        c2.grid(row=0, column=1, padx=4, sticky="nsew")
        ctk.CTkLabel(c2, text="ВОРКЕРЫ", font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(10, 2))
        
        act_w, grp = ConfigManager.calc_actual_workers(self.config_mgr.workers)
        self.lbl_card_workers = ctk.CTkLabel(c2, text=f"{self.config_mgr.workers} в конфиге", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=COLOR_TEXT_PRIMARY)
        self.lbl_card_workers.pack(anchor="w", padx=15, pady=(0, 2))
        self.lbl_card_workers_sub = ctk.CTkLabel(c2, text=f"Запуск: {act_w} ({grp} гр. по 9)", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED)
        self.lbl_card_workers_sub.pack(anchor="w", padx=15, pady=(0, 10))

        # Card 3: Traffic
        c3 = ctk.CTkFrame(grid_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        c3.grid(row=0, column=2, padx=4, sticky="nsew")
        ctk.CTkLabel(c3, text="ТРАФИК", font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(10, 2))
        self.lbl_card_traffic = ctk.CTkLabel(c3, text="0.00 МБ", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=COLOR_TEXT_PRIMARY)
        self.lbl_card_traffic.pack(anchor="w", padx=15, pady=(0, 2))
        self.lbl_card_traffic_sub = ctk.CTkLabel(c3, text="↓ 0.00 / ↑ 0.00", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED)
        self.lbl_card_traffic_sub.pack(anchor="w", padx=15, pady=(0, 10))

        # Card 4: Session Duration
        c4 = ctk.CTkFrame(grid_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        c4.grid(row=0, column=3, padx=(6, 0), sticky="nsew")
        ctk.CTkLabel(c4, text="СЕССИЯ", font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(10, 2))
        self.lbl_card_session = ctk.CTkLabel(c4, text="00:00:00", font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"), text_color=COLOR_TEXT_PRIMARY)
        self.lbl_card_session.pack(anchor="w", padx=15, pady=(0, 2))
        self.lbl_card_session_sub = ctk.CTkLabel(c4, text="Отключено", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED)
        self.lbl_card_session_sub.pack(anchor="w", padx=15, pady=(0, 10))

        # Key Input Card
        key_card = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        key_card.pack(fill="x", pady=(0, 10), padx=2)

        key_header_frame = ctk.CTkFrame(key_card, fg_color="transparent")
        key_header_frame.pack(fill="x", padx=20, pady=(14, 6))

        ctk.CTkLabel(
            key_header_frame,
            text="🔑 КЛЮЧ ПОДКЛЮЧЕНИЯ / VK ХЕШ ЗВОНКА",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY
        ).pack(side="left")

        ctk.CTkLabel(
            key_header_frame,
            text="(Сохраняется в config.ini)",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=8)

        pool_len = len(self.config_mgr.get_vk_hashes())
        self.lbl_pool_badge = ctk.CTkLabel(
            key_header_frame,
            text=f"({pool_len} в пуле)" if pool_len > 1 else "",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_SUCCESS
        )
        self.lbl_pool_badge.pack(side="left", padx=4)

        key_row = ctk.CTkFrame(key_card, fg_color="transparent")
        key_row.pack(fill="x", padx=20, pady=(0, 14))

        self.key_entry = ctk.CTkEntry(
            key_row,
            placeholder_text="Вставьте ключ подключения (VK Call Hash link)...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#0D111A",
            border_color=COLOR_CARD_BORDER,
            text_color=COLOR_TEXT_PRIMARY,
            height=38
        )
        self.key_entry.insert(0, self.config_mgr.vk_hash)
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_save_key = ctk.CTkButton(
            key_row,
            text="Сохранить",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            width=110,
            height=38,
            command=self._save_key_from_main
        )
        self.btn_save_key.pack(side="right")

        # Clean PC VPN Bridge notice on launch screen
        promo_banner = ctk.CTkFrame(page, fg_color="#101724", corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        promo_banner.pack(fill="x", pady=(0, 5), padx=2)
        promo_content = ctk.CTkFrame(promo_banner, fg_color="transparent")
        promo_content.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(
            promo_content,
            text="📱 Поддержка PC VPN Bridge (Android)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLOR_ACCENT
        ).pack(side="left")
        ctk.CTkLabel(
            promo_content,
            text="— локальный прокси-мост для смартфона",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY
        ).pack(side="left", padx=6)
        btn_go_bridge = ctk.CTkButton(
            promo_content,
            text="Мост →",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#182030",
            hover_color="#222C40",
            text_color=COLOR_ACCENT,
            width=80,
            height=26,
            command=lambda: self._select_tab("pcvpn")
        )
        btn_go_bridge.pack(side="right")

    # ------------------ TAB 2: PCVPN BRIDGE ------------------
    def _build_tab_pcvpn(self):
        page = ctk.CTkFrame(self.page_container, fg_color="transparent")
        self.pages["pcvpn"] = page

        # Hero Banner with Independent Toggle Button
        banner = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        banner.pack(fill="x", pady=(0, 12))

        b_content = ctk.CTkFrame(banner, fg_color="transparent")
        b_content.pack(fill="x", padx=20, pady=16)

        b_left = ctk.CTkFrame(b_content, fg_color="transparent")
        b_left.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            b_left,
            text="📱 ЛОКАЛЬНЫЙ SOCKS5 / HTTP ПРОКСИ-МОСТ",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLOR_ACCENT
        ).pack(anchor="w")

        ctk.CTkLabel(
            b_left,
            text="Сетевой шлюз для внешних устройств и смартфонов в локальной сети Wi-Fi.\nВключается и выключается независимо от главного VPN на компьютере.\nПоддерживает протоколы SOCKS5 и HTTP CONNECT на едином порту.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_SECONDARY,
            justify="left"
        ).pack(anchor="w", pady=(4, 0))

        # Independent Button to Start/Stop Bridge
        b_right = ctk.CTkFrame(b_content, fg_color="transparent")
        b_right.pack(side="right", padx=(15, 0))

        self.btn_tab_bridge = ctk.CTkButton(
            b_right,
            text="ВКЛЮЧИТЬ МОСТ",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            width=170,
            height=46,
            corner_radius=23,
            command=self._toggle_bridge
        )
        self.btn_tab_bridge.pack(pady=4)

        self.lbl_tab_bridge_status = ctk.CTkLabel(
            b_right,
            text="Статус: Остановлен",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.lbl_tab_bridge_status.pack()

        # Connection details card
        details_card = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        details_card.pack(fill="x", pady=(0, 12))

        d_inner = ctk.CTkFrame(details_card, fg_color="transparent")
        d_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(
            d_inner,
            text="ПАРАМЕТРЫ ДЛЯ ВВОДА В ПРИЛОЖЕНИИ НА ТЕЛЕФОНЕ:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED
        ).pack(anchor="w", pady=(0, 10))

        lan_ip = get_lan_ip()
        mdns = get_mdns_name()
        port = str(self.config_mgr.pcvpn_port)

        fields = [
            ("📡 IP-адрес ПК в Wi-Fi:", lan_ip),
            ("🏷️ Имя устройства (mDNS):", mdns),
            ("🔌 Порт прокси:", port)
        ]

        for label_text, val in fields:
            row = ctk.CTkFrame(d_inner, fg_color="#0D111A", corner_radius=8, height=42)
            row.pack(fill="x", pady=4)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=label_text, font=ctk.CTkFont(family="Segoe UI", size=12), text_color=COLOR_TEXT_SECONDARY).pack(side="left", padx=15)
            val_lbl = ctk.CTkLabel(row, text=val, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=COLOR_ACCENT)
            val_lbl.pack(side="left", padx=10)

            btn_copy = ctk.CTkButton(
                row,
                text="Скопировать",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color="#182030",
                hover_color="#222C40",
                text_color=COLOR_TEXT_PRIMARY,
                width=100,
                height=28,
                command=lambda v=val: self._copy_to_clipboard(v, "Скопировано!")
            )
            btn_copy.pack(side="right", padx=10)

        # Big copy button for mobile app
        btn_copy_all = ctk.CTkButton(
            d_inner,
            text="📋 Скопировать всё для приложения PC VPN Bridge",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            height=40,
            command=lambda: self._copy_to_clipboard(f"Host: {lan_ip} ({mdns})\nPort: {port}\nProtocols: SOCKS5 / HTTP", "Параметры скопированы в буфер!")
        )
        btn_copy_all.pack(fill="x", pady=(14, 0))

        # Instructions card
        inst_card = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        inst_card.pack(fill="both", expand=True)

        i_inner = ctk.CTkFrame(inst_card, fg_color="transparent")
        i_inner.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(
            i_inner,
            text="ПАРАМЕТРЫ И ИНСТРУКЦИЯ ПОДКЛЮЧЕНИЯ:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED
        ).pack(anchor="w", pady=(0, 8))

        steps = [
            "1. Подключите смартфон и этот компьютер к одной Wi-Fi сети.",
            f"2. В настройках прокси смартфона или клиенте укажите IP-адрес ({lan_ip}) или имя ПК ({mdns}).",
            f"3. В поле порта укажите {port} (протокол SOCKS5 или HTTP).",
            "4. Логин и пароль оставьте пустыми (авторизация не требуется).",
            "5. Нажмите «Подключить» на телефоне — трафик пойдет через прокси-мост."
        ]

        for s in steps:
            ctk.CTkLabel(
                i_inner,
                text=s,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=COLOR_TEXT_SECONDARY,
                justify="left"
            ).pack(anchor="w", pady=2)

    # ------------------ TAB 3: SETTINGS ------------------
    def _build_tab_settings(self):
        page = ctk.CTkScrollableFrame(self.page_container, fg_color="transparent")
        self.pages["settings"] = page

        # 1. Card: Основные параметры сервера (Server Config)
        card1 = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        card1.pack(fill="x", pady=(0, 12))
        c1_inner = ctk.CTkFrame(card1, fg_color="transparent")
        c1_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(c1_inner, text="ПАРАМЕТРЫ СЕРВЕРА VK TURN (CONFIG.INI)", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=COLOR_ACCENT).pack(anchor="w", pady=(0, 12))

        # Peer
        ctk.CTkLabel(c1_inner, text="Адрес сервера (PEER IP:Port):", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.entry_peer = ctk.CTkEntry(c1_inner, fg_color="#0D111A", border_color=COLOR_CARD_BORDER, text_color=COLOR_TEXT_PRIMARY, height=36)
        self.entry_peer.insert(0, self.config_mgr.peer)
        self.entry_peer.pack(fill="x", pady=(2, 10))

        # Password
        ctk.CTkLabel(c1_inner, text="Пароль подключения (PASSWORD):", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.entry_password = ctk.CTkEntry(c1_inner, fg_color="#0D111A", border_color=COLOR_CARD_BORDER, text_color=COLOR_TEXT_PRIMARY, height=36)
        self.entry_password.insert(0, self.config_mgr.password)
        self.entry_password.pack(fill="x", pady=(2, 10))

        # Workers section with calculation & explanation
        w_header_frame = ctk.CTkFrame(c1_inner, fg_color="transparent")
        w_header_frame.pack(fill="x", pady=(2, 0))

        ctk.CTkLabel(
            w_header_frame,
            text="Количество воркеров (WORKERS):",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED
        ).pack(side="left")

        self.lbl_workers_calc = ctk.CTkLabel(
            w_header_frame,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_ACCENT
        )
        self.lbl_workers_calc.pack(side="left", padx=10)

        self.entry_workers = ctk.CTkEntry(c1_inner, fg_color="#0D111A", border_color=COLOR_CARD_BORDER, text_color=COLOR_TEXT_PRIMARY, height=36)
        self.entry_workers.insert(0, str(self.config_mgr.workers))
        self.entry_workers.pack(fill="x", pady=(2, 4))
        self.entry_workers.bind("<KeyRelease>", self._on_workers_input_changed)

        # Worker Presets row (Multiples of 9)
        presets_frame = ctk.CTkFrame(c1_inner, fg_color="transparent")
        presets_frame.pack(fill="x", pady=(0, 5))

        ctk.CTkLabel(
            presets_frame,
            text="Группы по 9:",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=(0, 6))

        for p_val in [18, 27, 36, 45, 54]:
            btn_p = ctk.CTkButton(
                presets_frame,
                text=str(p_val),
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#182030",
                hover_color="#222C40",
                text_color=COLOR_TEXT_PRIMARY,
                width=45,
                height=24,
                command=lambda v=p_val: self._set_worker_preset(v)
            )
            btn_p.pack(side="left", padx=3)

        self._update_workers_calc_label()

        # 2. Card: Пул VK-хешей и звонков (VK Hash Pool & Health Check)
        card_pool = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        card_pool.pack(fill="x", pady=(0, 12))
        cp_inner = ctk.CTkFrame(card_pool, fg_color="transparent")
        cp_inner.pack(fill="x", padx=20, pady=16)

        cp_top = ctk.CTkFrame(cp_inner, fg_color="transparent")
        cp_top.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            cp_top,
            text="ПУЛ VK-ХЕШЕЙ (ОТКАЗОУСТОЙЧИВОСТЬ)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLOR_ACCENT
        ).pack(side="left")

        self.btn_check_hashes = ctk.CTkButton(
            cp_top,
            text="⚡ Проверить хеши",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#182030",
            hover_color="#222C40",
            text_color=COLOR_ACCENT,
            height=28,
            command=self._test_hashes_pool
        )
        self.btn_check_hashes.pack(side="right")

        ctk.CTkLabel(
            cp_inner,
            text="Клиент поддерживает несколько ссылок на звонки. При обрыве или блокировке одного звонка\nклиент автоматически переключается на запасной без разрыва связи.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            justify="left"
        ).pack(anchor="w", pady=(0, 10))

        # Dynamic Hash List Container
        self.hash_list_frame = ctk.CTkFrame(cp_inner, fg_color="#0D111A", corner_radius=8)
        self.hash_list_frame.pack(fill="x", pady=(0, 10))
        self._refresh_hash_pool_ui()

        # Add Hash Row
        add_row = ctk.CTkFrame(cp_inner, fg_color="transparent")
        add_row.pack(fill="x")

        self.entry_new_hash = ctk.CTkEntry(
            add_row,
            placeholder_text="Вставьте ссылку на звонок VK или хеш...",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#0D111A",
            border_color=COLOR_CARD_BORDER,
            text_color=COLOR_TEXT_PRIMARY,
            height=34
        )
        self.entry_new_hash.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_add_h = ctk.CTkButton(
            add_row,
            text="+ Добавить в пул",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            width=130,
            height=34,
            command=self._add_hash_to_pool
        )
        btn_add_h.pack(side="right")

        # 3. Card: Режим туннелирования (DTLS vs Raw-IP)
        card_proto = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        card_proto.pack(fill="x", pady=(0, 12))
        cpr_inner = ctk.CTkFrame(card_proto, fg_color="transparent")
        cpr_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(cpr_inner, text="РЕЖИМ ШИФРОВАНИЯ И ПРОТОКОЛ", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=COLOR_ACCENT).pack(anchor="w", pady=(0, 8))

        self.seg_protocol = ctk.CTkSegmentedButton(
            cpr_inner,
            values=["🛡️ Стандартный DTLS (Рекомендуется)", "⚡ Сверхбыстрый Raw-IP (-notls)"],
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            selected_color=COLOR_ACCENT,
            selected_hover_color=COLOR_ACCENT_HOVER,
            unselected_color="#182030",
            unselected_hover_color="#222C40",
            text_color="#000000",
            command=self._on_protocol_changed
        )
        current_proto = self.config_mgr.protocol
        self.seg_protocol.set("⚡ Сверхбыстрый Raw-IP (-notls)" if current_proto == "rawtun" else "🛡️ Стандартный DTLS (Рекомендуется)")
        self.seg_protocol.pack(fill="x", pady=(0, 8))

        self.lbl_proto_desc = ctk.CTkLabel(
            cpr_inner,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            justify="left"
        )
        self.lbl_proto_desc.pack(anchor="w")
        self._update_proto_desc(current_proto)

        # 4. Card: Обход блокировок и цензуры (Bypass & Obfuscation)
        card_bypass = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        card_bypass.pack(fill="x", pady=(0, 12))
        cb_inner = ctk.CTkFrame(card_bypass, fg_color="transparent")
        cb_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(cb_inner, text="ОБХОД БЛОКИРОВОК И МАСКИРОВКА ТРАФИКА", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=COLOR_ACCENT).pack(anchor="w", pady=(0, 10))

        # TCP TURN switch
        self.var_turn_tcp = ctk.BooleanVar(value=self.config_mgr.turn_tcp)
        sw_tcp = ctk.CTkSwitch(
            cb_inner,
            text="Режим TCP TURN (-turn-tcp) — обход блокировок UDP (Ростелеком и др.)",
            variable=self.var_turn_tcp,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            progress_color=COLOR_ACCENT
        )
        sw_tcp.pack(anchor="w", pady=(0, 10))

        # Obfs Mode
        ctk.CTkLabel(cb_inner, text="Режим обфускации WebRTC пакетов (-obfs):", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.combo_obfs = ctk.CTkComboBox(
            cb_inner,
            values=["audio", "video"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#0D111A",
            border_color=COLOR_CARD_BORDER,
            button_color="#1F293D",
            height=34
        )
        self.combo_obfs.set(self.config_mgr.obfs)
        self.combo_obfs.pack(fill="x", pady=(2, 10))

        # Captcha Mode
        ctk.CTkLabel(cb_inner, text="Режим обхода капчи (-captcha-mode):", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.combo_captcha = ctk.CTkComboBox(
            cb_inner,
            values=["auto", "wv", "rjs"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#0D111A",
            border_color=COLOR_CARD_BORDER,
            button_color="#1F293D",
            height=34
        )
        self.combo_captcha.set(self.config_mgr.captcha_mode)
        self.combo_captcha.pack(fill="x", pady=(2, 10))

        # DNS Mode
        ctk.CTkLabel(cb_inner, text="DNS-резолвер серверов VK (-go-dns):", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.combo_dns = ctk.CTkComboBox(
            cb_inner,
            values=["yandex", "cloudflare", "google", "doh-yandex", "doh-cloudflare"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#0D111A",
            border_color=COLOR_CARD_BORDER,
            button_color="#1F293D",
            height=34
        )
        self.combo_dns.set(self.config_mgr.go_dns)
        self.combo_dns.pack(fill="x", pady=(2, 4))

        # 5. Card: Системные настройки (App Settings)
        card_sys = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=14, border_width=1, border_color=COLOR_CARD_BORDER)
        card_sys.pack(fill="x", pady=(0, 12))
        cs_inner = ctk.CTkFrame(card_sys, fg_color="transparent")
        cs_inner.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(cs_inner, text="СИСТЕМНЫЕ НАСТРОЙКИ", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), text_color=COLOR_ACCENT).pack(anchor="w", pady=(0, 10))

        # PCVPN Port
        ctk.CTkLabel(cs_inner, text="Порт прокси для телефона (PCVPN):", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.entry_pcvpn_port = ctk.CTkEntry(cs_inner, fg_color="#0D111A", border_color=COLOR_CARD_BORDER, text_color=COLOR_TEXT_PRIMARY, height=36)
        self.entry_pcvpn_port.insert(0, str(self.config_mgr.pcvpn_port))
        self.entry_pcvpn_port.pack(fill="x", pady=(2, 10))

        # Close Action Preference
        ctk.CTkLabel(cs_inner, text="Действие при нажатии на крестик [X]:", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w")
        self.combo_close_action = ctk.CTkComboBox(
            cs_inner,
            values=["Спрашивать каждый раз", "Сворачивать в трей", "Закрывать программу"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#0D111A",
            border_color=COLOR_CARD_BORDER,
            button_color="#1F293D",
            height=36
        )
        current_action = self.config_mgr.close_action
        if current_action == "tray":
            self.combo_close_action.set("Сворачивать в трей")
        elif current_action == "exit":
            self.combo_close_action.set("Закрывать программу")
        else:
            self.combo_close_action.set("Спрашивать каждый раз")
        self.combo_close_action.pack(fill="x", pady=(2, 10))

        # Desktop Shortcut Button
        btn_make_shortcut = ctk.CTkButton(
            cs_inner,
            text="📌 Создать ярлык на Рабочем столе",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#182030",
            hover_color="#222C40",
            text_color=COLOR_ACCENT,
            height=36,
            command=self._create_shortcut_from_settings
        )
        btn_make_shortcut.pack(fill="x", pady=(0, 4))

        # Save Button
        btn_save_all = ctk.CTkButton(
            page,
            text="💾 Сохранить все настройки",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            height=42,
            command=self._save_all_settings
        )
        btn_save_all.pack(fill="x", pady=(0, 20))

    def _on_workers_input_changed(self, event=None):
        self._update_workers_calc_label()

    def _update_workers_calc_label(self):
        val = self.entry_workers.get().strip()
        act_w, grp = ConfigManager.calc_actual_workers(val)
        if val:
            try:
                raw_int = int(val)
                if raw_int != act_w:
                    self.lbl_workers_calc.configure(text=f"→ Фактически запустится: {act_w} ({grp} групп по 9)", text_color=COLOR_WARNING)
                else:
                    self.lbl_workers_calc.configure(text=f"→ {act_w} воркеров ({grp} групп по 9)", text_color=COLOR_SUCCESS)
            except Exception:
                self.lbl_workers_calc.configure(text="")

    def _set_worker_preset(self, val):
        self.entry_workers.delete(0, "end")
        self.entry_workers.insert(0, str(val))
        self._update_workers_calc_label()

    # ------------------ TAB 4: CONSOLE ------------------
    def _build_tab_console(self):
        page = ctk.CTkFrame(self.page_container, fg_color="transparent")
        self.pages["console"] = page

        tools = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=10, height=44)
        tools.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            tools,
            text="ТРАНСЛЯЦИЯ ЛОГОВ VK-TURN-CLIENT В РЕАЛЬНОМ ВРЕМЕНИ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=15)

        btn_clear = ctk.CTkButton(
            tools,
            text="Очистить",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#1F293D",
            hover_color="#2D3748",
            width=80,
            height=28,
            command=self._clear_logs
        )
        btn_clear.pack(side="right", padx=(5, 10), pady=8)

        btn_copy_logs = ctk.CTkButton(
            tools,
            text="Скопировать лог",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#1F293D",
            hover_color="#2D3748",
            width=120,
            height=28,
            command=self._copy_logs
        )
        btn_copy_logs.pack(side="right", pady=8)

        self.log_textbox = ctk.CTkTextbox(
            page,
            fg_color="#080C14",
            text_color="#A7F3D0",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1,
            border_color=COLOR_CARD_BORDER,
            corner_radius=10,
            wrap="none"
        )
        self.log_textbox.pack(fill="both", expand=True)

    # ------------------ ACTIONS & CALLBACKS ------------------
    def _toggle_vpn(self):
        if self.tunnel_mgr.is_connected or self.tunnel_mgr.status == "Подключение...":
            self.tunnel_mgr.stop_vpn()
        else:
            # Sync key from entry
            vkhash_val = self.key_entry.get().strip()
            if vkhash_val and vkhash_val != self.config_mgr.vk_hash:
                self.config_mgr.save_ini(vk_hash=vkhash_val)
                self.entry_vkhash.delete(0, "end")
                self.entry_vkhash.insert(0, vkhash_val)

            self.tunnel_mgr.start_vpn()

    def _tray_toggle_vpn(self):
        self.after(0, self._toggle_vpn)

    def _toggle_bridge(self):
        self.tunnel_mgr.toggle_bridge()
        self.config_mgr.save_settings(pcvpn_enabled=self.tunnel_mgr.is_bridge_active)

    def _check_ping(self):
        self.btn_ping.configure(text="Замер...", state="disabled")
        def _on_ping_done(val):
            self.after(0, lambda: self._apply_ping_result(val))
        self.tunnel_mgr.ping_test(callback=_on_ping_done)

    def _apply_ping_result(self, val):
        self.btn_ping.configure(text=f"⚡ {val}", state="normal")

    def _save_key_from_main(self):
        vkhash_val = self.key_entry.get().strip()
        if vkhash_val:
            self.config_mgr.save_ini(vk_hash=vkhash_val)
            self.entry_vkhash.delete(0, "end")
            self.entry_vkhash.insert(0, vkhash_val)
            self.btn_save_key.configure(text="✓ Сохранено", fg_color=COLOR_SUCCESS)
            self.after(2000, lambda: self.btn_save_key.configure(text="Сохранить", fg_color=COLOR_ACCENT))

    def _save_all_settings(self):
        peer = self.entry_peer.get().strip()
        password = self.entry_password.get().strip()
        workers = self.entry_workers.get().strip()
        pcvpn_port_str = self.entry_pcvpn_port.get().strip()

        # Update config.ini
        self.config_mgr.save_ini(peer=peer, password=password, workers=workers)
        self.lbl_card_peer.configure(text=peer)
        
        act_w, grp = ConfigManager.calc_actual_workers(workers)
        self.lbl_card_workers.configure(text=f"{workers} в конфиге")
        self.lbl_card_workers_sub.configure(text=f"Запуск: {act_w} ({grp} гр. по 9)")

        # Update settings.json
        try:
            pcvpn_port = int(pcvpn_port_str)
        except Exception:
            pcvpn_port = 24066

        close_choice = self.combo_close_action.get()
        if "трей" in close_choice:
            close_action = "tray"
        elif "Закрывать" in close_choice:
            close_action = "exit"
        else:
            close_action = None

        proto_choice = "rawtun" if "Raw-IP" in self.seg_protocol.get() else "dtls"
        turn_tcp = self.var_turn_tcp.get()
        obfs = self.combo_obfs.get()
        captcha = self.combo_captcha.get()
        dns = self.combo_dns.get()

        self.config_mgr.save_settings(
            pcvpn_port=pcvpn_port,
            close_action=close_action,
            protocol=proto_choice,
            turn_tcp=turn_tcp,
            obfs=obfs,
            captcha_mode=captcha,
            go_dns=dns
        )

        self._sync_main_key_display()
        self._show_toast("✓ Все настройки успешно сохранены!")

    def _refresh_hash_pool_ui(self, check_results=None):
        if not hasattr(self, "hash_list_frame"):
            return
        for widget in self.hash_list_frame.winfo_children():
            widget.destroy()

        hashes = self.config_mgr.get_vk_hashes()
        if not hashes:
            ctk.CTkLabel(
                self.hash_list_frame,
                text="Пул пуст. Добавьте хотя бы один хеш звонка.",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLOR_TEXT_MUTED
            ).pack(padx=12, pady=10)
            return

        for idx, h in enumerate(hashes, 1):
            row = ctk.CTkFrame(self.hash_list_frame, fg_color="transparent", height=32)
            row.pack(fill="x", padx=10, pady=3)

            short_h = h if len(h) <= 46 else (h[:43] + "...")
            lbl = ctk.CTkLabel(
                row,
                text=f"{idx}. {short_h}",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLOR_TEXT_PRIMARY
            )
            lbl.pack(side="left")

            if check_results and idx <= len(check_results):
                res = check_results[idx - 1]
                st = res.get("status")
                st_color = COLOR_SUCCESS if st == "ok" else COLOR_DANGER
                st_txt = "✓ Активен" if st == "ok" else "✕ Ошибка"
                ctk.CTkLabel(
                    row,
                    text=st_txt,
                    font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                    text_color=st_color
                ).pack(side="left", padx=8)

            btn_del = ctk.CTkButton(
                row,
                text="✕",
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#261E27",
                hover_color=COLOR_DANGER_HOVER,
                text_color=COLOR_DANGER,
                width=24,
                height=24,
                corner_radius=4,
                command=lambda target=h: self._remove_hash_from_pool(target)
            )
            btn_del.pack(side="right")

    def _add_hash_to_pool(self):
        new_val = self.entry_new_hash.get().strip()
        if new_val:
            ok = self.config_mgr.add_vk_hash(new_val)
            if ok:
                self.entry_new_hash.delete(0, "end")
                self._refresh_hash_pool_ui()
                self._sync_main_key_display()
                self._show_toast("✓ Хеш добавлен в пул!")
            else:
                self._show_toast("Этот хеш уже есть в пуле.")

    def _remove_hash_from_pool(self, target_h):
        self.config_mgr.remove_vk_hash(target_h)
        self._refresh_hash_pool_ui()
        self._sync_main_key_display()
        self._show_toast("Хеш удален из пула.")

    def _sync_main_key_display(self):
        hashes = self.config_mgr.get_vk_hashes()
        first_h = hashes[0] if hashes else ""
        if hasattr(self, "key_entry"):
            self.key_entry.delete(0, "end")
            self.key_entry.insert(0, first_h)
        if hasattr(self, "lbl_pool_badge"):
            self.lbl_pool_badge.configure(text=f"({len(hashes)} в пуле)" if len(hashes) > 1 else "")

    def _test_hashes_pool(self):
        self.btn_check_hashes.configure(text="Проверка...", state="disabled")
        def _on_done(results):
            self.after(0, lambda: self._apply_hash_check_results(results))
        self.tunnel_mgr.check_hashes(callback=_on_done)

    def _apply_hash_check_results(self, results):
        self.btn_check_hashes.configure(text="⚡ Проверить хеши", state="normal")
        self._refresh_hash_pool_ui(check_results=results)
        ok_count = sum(1 for r in results if r.get("status") == "ok")
        self._show_toast(f"Проверка завершена: {ok_count} из {len(results)} активны.")

    def _on_protocol_changed(self, val):
        proto = "rawtun" if "Raw-IP" in val else "dtls"
        self._update_proto_desc(proto)

    def _update_proto_desc(self, proto):
        if proto == "rawtun":
            self.lbl_proto_desc.configure(
                text="⚡ Прямой туннель без DTLS-оверхеда (-notls). Минимальный пинг.\n⚠️ Внимание: VPS-сервер должен быть запущен с флагом -listen-direct!",
                text_color=COLOR_WARNING
            )
        else:
            self.lbl_proto_desc.configure(
                text="🛡️ Полная маскировка под настоящий звонок VK. Надежный стек WireGuard поверх WinTUN.\nРаботает с любыми стандартными серверами из коробки.",
                text_color=COLOR_TEXT_SECONDARY
            )

    def _show_toast(self, msg):
        self.lbl_main_status.configure(text=msg, text_color=COLOR_SUCCESS)
        self.after(3500, lambda: self._update_main_status_text())

    def _handle_log_line(self, line):
        self.after(0, lambda: self._append_log(line))

    def _append_log(self, line):
        self.log_textbox.insert("end", line + "\n")
        self.log_textbox.see("end")

    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def _copy_logs(self):
        txt = self.log_textbox.get("1.0", "end")
        self._copy_to_clipboard(txt, "Логи скопированы!")

    def _copy_to_clipboard(self, text, message):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._show_toast(message)

    def _handle_status_change(self, status_text, is_connected):
        self.after(0, lambda: self._apply_status_change(status_text, is_connected))

    def _apply_status_change(self, status_text, is_connected):
        self.tray_mgr.update_status(is_connected, status_text)
        
        if is_connected:
            self.status_pill.configure(text="● VPN: ПОДКЛЮЧЕН", text_color=COLOR_SUCCESS, fg_color="#0F2E22")
            self.btn_connect.configure(text="ОТКЛЮЧИТЬ VPN", fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER, text_color="#FFFFFF")
            self.lbl_main_status.configure(text="Главный VPN туннель активен. Весь трафик ПК защищен.", text_color=COLOR_SUCCESS)
            self.lbl_card_session_sub.configure(text="Активен", text_color=COLOR_SUCCESS)
            
            if not self.timer_running:
                self.conn_start_time = time.time()
                self.timer_running = True
                self._update_session_timer()
        elif "Подключение" in status_text:
            self.status_pill.configure(text="● VPN: ПОДКЛЮЧЕНИЕ...", text_color=COLOR_WARNING, fg_color="#2E2410")
            self.btn_connect.configure(text="ОТМЕНА", fg_color=COLOR_WARNING, hover_color="#D97706", text_color="#000000")
            self.lbl_main_status.configure(text="Установка соединения через VK TURN сервер...", text_color=COLOR_WARNING)
        else:
            self.status_pill.configure(text="○ VPN: ОТКЛЮЧЕН", text_color=COLOR_TEXT_MUTED, fg_color="#182030")
            self.btn_connect.configure(text="ПОДКЛЮЧИТЬ VPN", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#000000")
            self._update_main_status_text()
            self.lbl_card_session_sub.configure(text="Отключено", text_color=COLOR_TEXT_MUTED)
            self.timer_running = False

    def _handle_bridge_status_change(self, is_active):
        self.after(0, lambda: self._apply_bridge_status_change(is_active))

    def _apply_bridge_status_change(self, is_active):
        port = self.config_mgr.pcvpn_port
        if is_active:
            self.bridge_pill.configure(text=f"📱 МОСТ: АКТИВЕН ({port})", text_color=COLOR_SUCCESS, fg_color="#0F2E22")
            self.lbl_hero_bridge.configure(text=f"📱 Мост для телефона: Активен на порту {port}", text_color=COLOR_SUCCESS)
            self.btn_hero_bridge.configure(text="Остановить мост", text_color=COLOR_DANGER, fg_color="#261E27")
            self.btn_tab_bridge.configure(text="ОСТАНОВИТЬ МОСТ", fg_color=COLOR_DANGER, hover_color=COLOR_DANGER_HOVER, text_color="#FFFFFF")
            self.lbl_tab_bridge_status.configure(text=f"Статус: Активен на порту {port}", text_color=COLOR_SUCCESS)
        else:
            self.bridge_pill.configure(text="📱 МОСТ: ВЫКЛ", text_color=COLOR_TEXT_MUTED, fg_color="#182030")
            self.lbl_hero_bridge.configure(text=f"📱 Мост для телефона: Остановлен (порт {port})", text_color=COLOR_TEXT_MUTED)
            self.btn_hero_bridge.configure(text="Включить мост", text_color=COLOR_ACCENT, fg_color="#182030")
            self.btn_tab_bridge.configure(text="ВКЛЮЧИТЬ МОСТ", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="#000000")
            self.lbl_tab_bridge_status.configure(text="Статус: Остановлен", text_color=COLOR_TEXT_MUTED)

    def _update_main_status_text(self):
        if not self.tunnel_mgr.is_connected:
            self.lbl_main_status.configure(text="VPN отключен. Нажмите кнопку слева для запуска туннеля.", text_color=COLOR_TEXT_SECONDARY)

    def _handle_stats_update(self, stats):
        self.after(0, lambda: self._apply_stats_update(stats))

    def _apply_stats_update(self, stats):
        workers = stats.get("workers", 0)
        self.lbl_card_workers_sub.configure(text=f"{workers} активно", text_color=COLOR_SUCCESS if workers > 0 else COLOR_TEXT_MUTED)
        
        down = stats.get("down", "0.00")
        up = stats.get("up", "0.00")
        total = stats.get("total", "0.00")
        self.lbl_card_traffic.configure(text=f"{total} МБ")
        self.lbl_card_traffic_sub.configure(text=f"↓ {down} / ↑ {up}")

    def _update_session_timer(self):
        if self.timer_running and self.conn_start_time:
            elapsed = int(time.time() - self.conn_start_time)
            hrs = elapsed // 3600
            mins = (elapsed % 3600) // 60
            secs = elapsed % 60
            self.lbl_card_session.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")
            self.after(1000, self._update_session_timer)

    # ------------------ SHORTCUT HELPERS ------------------
    def _create_shortcut_and_dismiss(self):
        create_desktop_shortcut()
        self.config_mgr.save_settings(first_launch_shortcut_handled=True)
        if hasattr(self, "first_run_card") and self.first_run_card:
            self.first_run_card.destroy()
        self._show_toast("✓ Ярлык создан на Рабочем столе!")

    def _dismiss_shortcut_banner(self):
        self.config_mgr.save_settings(first_launch_shortcut_handled=True)
        if hasattr(self, "first_run_card") and self.first_run_card:
            self.first_run_card.destroy()

    def _create_shortcut_from_settings(self):
        ok = create_desktop_shortcut()
        if ok:
            self._show_toast("✓ Ярлык создан на Рабочем столе!")
        else:
            self._show_toast("Не удалось создать ярлык.")

    # ------------------ WINDOW CLOSE & TRAY ------------------
    def on_close_clicked(self):
        action = self.config_mgr.close_action
        if action == "tray":
            self._minimize_to_tray()
        elif action == "exit":
            self._clean_exit()
        else:
            CloseConfirmDialog(self, on_choice=self._handle_close_dialog_choice)

    def _handle_close_dialog_choice(self, choice, save_choice):
        if save_choice:
            self.config_mgr.save_settings(close_action=choice)
            if hasattr(self, "combo_close_action"):
                self.combo_close_action.set("Сворачивать в трей" if choice == "tray" else "Закрывать программу")

        if choice == "tray":
            self._minimize_to_tray()
        else:
            self._clean_exit()

    def _minimize_to_tray(self):
        self.withdraw()
        self.tray_mgr.notify(
            "WDTT свернут в трей",
            "Приложение продолжает работу в фоновом режиме. Нажмите дважды на иконку в трее, чтобы открыть."
        )

    def _restore_from_tray(self):
        self.after(0, self._do_restore)

    def _do_restore(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _clean_exit(self):
        self.tunnel_mgr.stop_all()
        self.tray_mgr.stop()
        self.destroy()
        sys.exit(0)

if __name__ == "__main__":
    app = WdttApp()
    app.mainloop()
