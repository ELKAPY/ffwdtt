import os
import sys
import json

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_INI_PATH = os.path.join(get_app_dir(), "config.ini")
SETTINGS_JSON_PATH = os.path.join(get_app_dir(), "settings.json")

DEFAULT_SETTINGS = {
    "close_action": None,  # None means "ask first time", "tray", "exit"
    "pcvpn_port": 24066,   # Port for PCVPN Bridge
    "pcvpn_enabled": False,# Independent PCVPN Bridge state
    "protocol": "dtls",    # "dtls" (Standard) or "rawtun" (Fast Raw-IP)
    "turn_tcp": False,     # TCP connection to TURN relay
    "obfs": "audio",       # "audio" or "video"
    "captcha_mode": "auto",# "auto", "wv", "rjs"
    "go_dns": "yandex",    # "yandex", "cloudflare", "google"
    "theme": "dark"
}

class ConfigManager:
    def __init__(self):
        self.config_ini_path = CONFIG_INI_PATH
        self.settings_json_path = SETTINGS_JSON_PATH
        self.ini_data = {
            "PEER": "1.2.3.4:56000",
            "PASSWORD": "",
            "VK_HASH": "",
            "WORKERS": "27"
        }
        self.settings = dict(DEFAULT_SETTINGS)
        self.load_all()

    def load_all(self):
        self.load_ini()
        self.load_settings()

    def load_ini(self):
        if not os.path.exists(self.config_ini_path):
            # Check fallback directory
            fallback = r"C:\Users\user\Downloads\portable_client\config.ini"
            if os.path.exists(fallback):
                self.config_ini_path = fallback

        if os.path.exists(self.config_ini_path):
            try:
                with open(self.config_ini_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            self.ini_data[k.strip().upper()] = v.strip()
            except Exception as e:
                print(f"[ConfigManager] Error reading config.ini: {e}")

    def save_ini(self, peer=None, password=None, vk_hash=None, workers=None):
        if peer is not None:
            self.ini_data["PEER"] = str(peer).strip()
        if password is not None:
            self.ini_data["PASSWORD"] = str(password).strip()
        if vk_hash is not None:
            self.ini_data["VK_HASH"] = str(vk_hash).strip()
        if workers is not None:
            self.ini_data["WORKERS"] = str(workers).strip()

        content = [
            "# Настройки подключения VK TURN",
            "# Укажите адрес и порт вашего сервера (VPS)",
            f"PEER={self.ini_data.get('PEER', '1.2.3.4:56000')}",
            "",
            "# Пароль подключения (из него выводится HKDF-SHA256 ключ)",
            f"PASSWORD={self.ini_data.get('PASSWORD', '')}",
            "",
            "# Хеш VK-звонка (можно несколько через запятую)",
            f"VK_HASH={self.ini_data.get('VK_HASH', '')}",
            "",
            "# Количество параллельных воркеров (по умолчанию 18)",
            f"WORKERS={self.ini_data.get('WORKERS', '27')}",
            ""
        ]

        target_path = os.path.join(get_app_dir(), "config.ini")
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content))
            self.config_ini_path = target_path
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config.ini: {e}")
            return False

    def load_settings(self):
        if os.path.exists(self.settings_json_path):
            try:
                with open(self.settings_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings.update(data)
            except Exception as e:
                print(f"[ConfigManager] Error loading settings.json: {e}")

    def save_settings(self, **kwargs):
        self.settings.update(kwargs)
        try:
            with open(self.settings_json_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving settings.json: {e}")
            return False

    @property
    def peer(self):
        self.load_ini()
        return self.ini_data.get("PEER", "1.2.3.4:56000")

    @property
    def password(self):
        self.load_ini()
        return self.ini_data.get("PASSWORD", "")

    @property
    def vk_hash(self):
        self.load_ini()
        return self.ini_data.get("VK_HASH", "")

    @property
    def workers(self):
        self.load_ini()
        return self.ini_data.get("WORKERS", "27")

    @property
    def close_action(self):
        return self.settings.get("close_action")

    @property
    def pcvpn_port(self):
        return int(self.settings.get("pcvpn_port", 24066))

    @property
    def pcvpn_enabled(self):
        return bool(self.settings.get("pcvpn_enabled", False))

    @property
    def protocol(self):
        return self.settings.get("protocol", "dtls")

    @property
    def turn_tcp(self):
        return bool(self.settings.get("turn_tcp", False))

    @property
    def obfs(self):
        return self.settings.get("obfs", "audio")

    @property
    def captcha_mode(self):
        return self.settings.get("captcha_mode", "auto")

    @property
    def go_dns(self):
        return self.settings.get("go_dns", "yandex")

    def get_vk_hashes(self):
        raw = self.vk_hash
        if not raw:
            return []
        return [h.strip() for h in raw.split(",") if h.strip()]

    def add_vk_hash(self, new_hash):
        new_hash = new_hash.strip()
        if not new_hash:
            return False
        hashes = self.get_vk_hashes()
        if new_hash not in hashes:
            hashes.append(new_hash)
            self.save_ini(vk_hash=",".join(hashes))
            return True
        return False

    def remove_vk_hash(self, target_hash):
        hashes = self.get_vk_hashes()
        if target_hash in hashes:
            hashes.remove(target_hash)
            self.save_ini(vk_hash=",".join(hashes))
            return True
        return False

    @staticmethod
    def calc_actual_workers(workers_val):
        try:
            n = int(workers_val)
            groups = max(1, n // 9)
            return groups * 9, groups
        except Exception:
            return 27, 3
