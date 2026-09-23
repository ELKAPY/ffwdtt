import os
import sys
import subprocess
import threading
import time
import re
import socket
import ctypes

from pcvpn_bridge import PcvpnBridgeServer

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_mdns_name():
    try:
        return f"{socket.gethostname().lower()}.local"
    except Exception:
        return "desktop.local"

class TunnelManager:
    def __init__(self, config_mgr):
        self.config_mgr = config_mgr
        
        # Main VPN process
        self.vpn_process = None
        self.status = "Остановлен"
        self.is_connected = False
        self.active_workers = 0
        self.traffic_mb = "0.00"
        self.down_mb = "0.00"
        self.up_mb = "0.00"
        self.last_ping = None
        
        # PCVPN Bridge
        self.bridge_process = None  # background socks helper if VPN is not running
        self.bridge = PcvpnBridgeServer(
            bind_ip="0.0.0.0",
            port=self.config_mgr.pcvpn_port,
            upstream_socks=("127.0.0.1", 19050)
        )
        self.is_bridge_active = False

        # Callbacks
        self.on_log = None
        self.on_status = None
        self.on_stats = None
        self.on_bridge_status = None

    def get_binary_path(self):
        local_exe = os.path.join(get_app_dir(), "vk-turn-client.exe")
        if os.path.exists(local_exe):
            return local_exe
        fallback = r"C:\Users\user\Downloads\portable_client\vk-turn-client.exe"
        if os.path.exists(fallback):
            return fallback
        return "vk-turn-client.exe"

    def get_working_dir(self):
        binary = self.get_binary_path()
        return os.path.dirname(os.path.abspath(binary))

    def ping_test(self, callback=None):
        def _run():
            exe = self.get_binary_path()
            cwd = self.get_working_dir()
            cmd = [
                exe,
                "-peer", self.config_mgr.peer,
                "-password", self.config_mgr.password,
                "-vk", self.config_mgr.vk_hash,
                "-ping-only"
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                ping_val = None
                for line in proc.stdout:
                    line = line.strip()
                    if "PING_RESULT|" in line:
                        parts = line.split("PING_RESULT|")
                        if len(parts) > 1:
                            ping_val = parts[1].strip() + " ms"
                proc.wait()
                self.last_ping = ping_val or "Таймаут"
            except Exception:
                self.last_ping = "Ошибка"
            if callback:
                callback(self.last_ping)
        
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ------------------ MAIN VPN ------------------
    def start_vpn(self):
        if self.vpn_process is not None:
            return

        if not is_admin():
            self._update_status("Ошибка: Нужны права Администратора", False)
            if self.on_log:
                self.on_log("[ОШИБКА] Для режима VPN требуются права Администратора (создание Wintun адаптера)!\nЗапустите приложение от имени Администратора.")
            return

        # If a background socks helper for bridge was running, stop it now
        if self.bridge_process is not None:
            self._kill_process(self.bridge_process)
            self.bridge_process = None

        exe = self.get_binary_path()
        cwd = self.get_working_dir()
        
        workers_count = self.config_mgr.workers
        cmd = [
            exe,
            "-mode", "vpn",
            "-peer", self.config_mgr.peer,
            "-password", self.config_mgr.password,
            "-vk", self.config_mgr.vk_hash,
            "-n", str(workers_count)
        ]
        
        captcha_mode = self.config_mgr.settings.get("captcha_mode", "auto")
        if captcha_mode:
            cmd.extend(["-captcha-mode", captcha_mode])
            
        go_dns = self.config_mgr.settings.get("go_dns", "yandex")
        if go_dns:
            cmd.extend(["-go-dns", go_dns])

        self._update_status("Подключение...", False)

        try:
            self.vpn_process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # Switch bridge to direct VPN mode if bridge is active
            if self.is_bridge_active:
                self.bridge.set_mode("vpn")

            t = threading.Thread(target=self._read_vpn_output, daemon=True)
            t.start()
        except Exception as e:
            self.vpn_process = None
            self._update_status(f"Ошибка запуска: {e}", False)
            if self.on_log:
                self.on_log(f"[ОШИБКА] Не удалось запустить процесс VPN: {e}\n")

    def _read_vpn_output(self):
        proc = self.vpn_process
        if not proc:
            return

        for line in proc.stdout:
            raw_line = line.rstrip()
            if self.on_log:
                self.on_log(raw_line)

            # Detect connection success
            if "[READY] Туннель готов к работе" in raw_line or "VPN запущен" in raw_line:
                self._update_status("Подключено", True)
            
            # Detect stats line:
            # [СТАТИСТИКА] Активных: 9 | Трафик: 0.00 МБ | ↓0.00 МБ / ↑0.00 МБ
            if "[СТАТИСТИКА]" in raw_line:
                m_act = re.search(r'Активных:\s*(\d+)', raw_line)
                m_down = re.search(r'↓([\d.]+)\s*МБ', raw_line)
                m_up = re.search(r'↑([\d.]+)\s*МБ', raw_line)
                m_total = re.search(r'Трафик:\s*([\d.]+)\s*МБ', raw_line)
                
                if m_act:
                    self.active_workers = int(m_act.group(1))
                if m_down:
                    self.down_mb = m_down.group(1)
                if m_up:
                    self.up_mb = m_up.group(1)
                if m_total:
                    self.traffic_mb = m_total.group(1)
                    
                if self.on_stats:
                    self.on_stats({
                        "workers": self.active_workers,
                        "down": self.down_mb,
                        "up": self.up_mb,
                        "total": self.traffic_mb
                    })

        proc.wait()
        exit_code = proc.returncode
        self.vpn_process = None
        self._update_status("Остановлен", False)
        if self.on_log:
            self.on_log(f"\n[КЛИЕНТ] Процесс VPN завершился с кодом {exit_code}.\n")

        # If bridge is active and VPN stopped, bring up background socks helper
        if self.is_bridge_active:
            self._ensure_bridge_backend()

    def stop_vpn(self):
        if self.vpn_process:
            self._kill_process(self.vpn_process)
            self.vpn_process = None
        self._update_status("Остановлен", False)

        # If bridge is still active, ensure background helper is running
        if self.is_bridge_active:
            self._ensure_bridge_backend()

    # ------------------ PCVPN BRIDGE (INDEPENDENT) ------------------
    def toggle_bridge(self):
        if self.is_bridge_active:
            self.stop_bridge()
        else:
            self.start_bridge()

    def start_bridge(self):
        if self.is_bridge_active:
            return

        self.bridge.set_port(self.config_mgr.pcvpn_port)
        self._ensure_bridge_backend()
        self.bridge.start()
        self.is_bridge_active = True

        if self.on_bridge_status:
            self.on_bridge_status(True)

        if self.on_log:
            self.on_log(f"[PCVPN] Мост запущен на порту {self.config_mgr.pcvpn_port} (SOCKS5 + HTTP CONNECT)")

    def stop_bridge(self):
        if not self.is_bridge_active:
            return

        self.bridge.stop()
        if self.bridge_process is not None:
            self._kill_process(self.bridge_process)
            self.bridge_process = None

        self.is_bridge_active = False

        if self.on_bridge_status:
            self.on_bridge_status(False)

        if self.on_log:
            self.on_log("[PCVPN] Мост остановлен.")

    def _ensure_bridge_backend(self):
        if self.vpn_process is not None and self.is_connected:
            # Main VPN is up, proxy routes direct via VPN adapter
            self.bridge.set_mode("vpn")
            if self.bridge_process is not None:
                self._kill_process(self.bridge_process)
                self.bridge_process = None
        else:
            # Main VPN is not active, launch background userspace socks helper
            self.bridge.set_mode("socks")
            if self.bridge_process is None:
                exe = self.get_binary_path()
                cwd = self.get_working_dir()
                cmd = [
                    exe,
                    "-mode", "socks",
                    "-peer", self.config_mgr.peer,
                    "-password", self.config_mgr.password,
                    "-vk", self.config_mgr.vk_hash,
                    "-n", str(self.config_mgr.workers),
                    "-socks", "127.0.0.1:19050"
                ]
                try:
                    self.bridge_process = subprocess.Popen(
                        cmd,
                        cwd=cwd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        bufsize=1,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    t = threading.Thread(target=self._read_bridge_helper_output, daemon=True)
                    t.start()
                except Exception as e:
                    if self.on_log:
                        self.on_log(f"[PCVPN] Ошибка запуска бэкенда моста: {e}")

    def _read_bridge_helper_output(self):
        proc = self.bridge_process
        if not proc:
            return
        for line in proc.stdout:
            raw_line = line.rstrip()
            # Only pipe relevant bridge log lines to main console if VPN is not running
            if self.vpn_process is None and self.on_log:
                if any(k in raw_line for k in ["[READY]", "[SOCKS]", "[СТАТИСТИКА]", "ошибка"]):
                    self.on_log(f"[PCVPN] {raw_line}")
        proc.wait()
        if self.bridge_process is proc:
            self.bridge_process = None

    def _kill_process(self, proc):
        if proc:
            try:
                pid = proc.pid
                if os.name == 'nt':
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    proc.terminate()
            except Exception:
                pass

    def stop_all(self):
        self.stop_vpn()
        self.stop_bridge()

    def _update_status(self, status_text, is_connected):
        self.status = status_text
        self.is_connected = is_connected
        if self.on_status:
            self.on_status(status_text, is_connected)
