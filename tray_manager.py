import os
import sys
import threading
import pystray
from PIL import Image, ImageDraw

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

class TrayManager:
    def __init__(self, on_restore=None, on_toggle_tunnel=None, on_exit=None):
        self.on_restore = on_restore
        self.on_toggle_tunnel = on_toggle_tunnel
        self.on_exit = on_exit
        
        self.icon = None
        self.is_connected = False
        self.tray_thread = None
        
        # Load or generate icons
        self.icon_disconnected = self._create_icon_image((0, 229, 255))   # Cyan
        self.icon_connected = self._create_icon_image((0, 230, 118))      # Green
        self.icon_connecting = self._create_icon_image((255, 171, 0))     # Amber

    def _create_icon_image(self, color_rgb):
        icon_path = get_resource_path("app_icon.png")
        if os.path.exists(icon_path):
            try:
                base = Image.open(icon_path).convert("RGBA").resize((64, 64))
                draw = ImageDraw.Draw(base)
                draw.ellipse([42, 42, 60, 60], fill=color_rgb, outline=(20, 26, 38), width=2)
                return base
            except Exception:
                pass

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([6, 6, 58, 58], fill=(18, 24, 38), outline=color_rgb, width=4)
        draw.ellipse([22, 22, 42, 42], fill=color_rgb)
        return img

    def _build_menu(self):
        status_label = "● Статус: Подключено" if self.is_connected else "○ Статус: Отключено"
        action_label = "⏹ Отключить WDTT" if self.is_connected else "⚡ Подключить WDTT"

        return pystray.Menu(
            pystray.MenuItem("WDTT VPN", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(status_label, lambda: None, enabled=False),
            pystray.MenuItem(action_label, self._on_toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Открыть окно", self._on_restore, default=True),
            pystray.MenuItem("Выход", self._on_exit)
        )

    def start(self):
        if self.icon is not None:
            return

        self.icon = pystray.Icon(
            "wdtt_client",
            self.icon_disconnected,
            "WDTT - VPN Туннель",
            menu=self._build_menu()
        )
        
        self.tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        self.tray_thread.start()

    def _on_restore(self, icon=None, item=None):
        if self.on_restore:
            self.on_restore()

    def _on_toggle(self, icon=None, item=None):
        if self.on_toggle_tunnel:
            self.on_toggle_tunnel()

    def _on_exit(self, icon=None, item=None):
        if self.on_exit:
            self.on_exit()

    def update_status(self, is_connected, status_text=""):
        self.is_connected = is_connected
        if self.icon:
            if is_connected:
                self.icon.icon = self.icon_connected
                self.icon.title = f"WDTT - Подключено ({status_text})"
            elif "Подключение" in status_text:
                self.icon.icon = self.icon_connecting
                self.icon.title = "WDTT - Подключение..."
            else:
                self.icon.icon = self.icon_disconnected
                self.icon.title = "WDTT - Отключено"
            
            try:
                self.icon.menu = self._build_menu()
                self.icon.update_menu()
            except Exception:
                pass

    def notify(self, title, message):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
