import socket
import select
import threading
import struct
import re
import time

class PcvpnBridgeServer:
    def __init__(self, bind_ip="0.0.0.0", port=24066, upstream_socks=("127.0.0.1", 19050)):
        self.bind_ip = bind_ip
        self.port = port
        self.upstream_socks = upstream_socks
        self.mode = "vpn"  # "vpn" or "socks"
        self.running = False
        self.server_socket = None
        self.server_thread = None
        
        # Stats
        self.active_conns = 0
        self.total_conns = 0
        self.bytes_sent = 0
        self.bytes_recv = 0
        self._lock = threading.Lock()

    def set_mode(self, mode):
        self.mode = mode

    def set_port(self, port):
        if self.running and port != self.port:
            self.stop()
            self.port = port
            self.start()
        else:
            self.port = port

    def start(self):
        if self.running:
            return
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

    def _run_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.bind_ip, self.port))
            self.server_socket.listen(128)
            self.server_socket.settimeout(1.0)
            print(f"[PCVPN Bridge] Listening on {self.bind_ip}:{self.port} (SOCKS5 + HTTP CONNECT)")
        except Exception as e:
            print(f"[PCVPN Bridge] Bind error on port {self.port}: {e}")
            self.running = False
            return

        while self.running:
            try:
                client_sock, client_addr = self.server_socket.accept()
                with self._lock:
                    self.active_conns += 1
                    self.total_conns += 1
                t = threading.Thread(target=self._handle_client, args=(client_sock, client_addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                break

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

    def _handle_client(self, client_sock, client_addr):
        client_sock.settimeout(15.0)
        try:
            first_byte = client_sock.recv(1, socket.MSG_PEEK)
            if not first_byte:
                return

            if first_byte == b'\x05':
                self._handle_socks5(client_sock)
            else:
                self._handle_http(client_sock)
        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            with self._lock:
                self.active_conns = max(0, self.active_conns - 1)

    def _handle_socks5(self, client_sock):
        # 1. Version identifier / method selection message
        # VER | NMETHODS | METHODS
        header = client_sock.recv(2)
        if len(header) < 2 or header[0] != 5:
            return
        nmethods = header[1]
        methods = client_sock.recv(nmethods)
        # We accept NO AUTH (0x00)
        client_sock.sendall(b'\x05\x00')

        # 2. SOCKS5 request
        # VER 5 | CMD 1 (CONNECT) | RSV 0 | ATYP | DST.ADDR | DST.PORT
        req = client_sock.recv(4)
        if len(req) < 4 or req[0] != 5 or req[1] != 1:
            # Only CONNECT command supported
            client_sock.sendall(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
            return

        atyp = req[3]
        if atyp == 1:  # IPv4
            addr_bytes = client_sock.recv(4)
            dst_host = socket.inet_ntoa(addr_bytes)
        elif atyp == 3:  # Domain
            domain_len = client_sock.recv(1)[0]
            dst_host = client_sock.recv(domain_len).decode('utf-8', errors='replace')
        elif atyp == 4:  # IPv6
            addr_bytes = client_sock.recv(16)
            dst_host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
        else:
            client_sock.sendall(b'\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00')
            return

        port_bytes = client_sock.recv(2)
        dst_port = struct.unpack('>H', port_bytes)[0]

        # Connect upstream
        remote_sock = self._connect_upstream(dst_host, dst_port)
        if not remote_sock:
            client_sock.sendall(b'\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00')
            return

        # Success reply
        client_sock.sendall(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
        self._pipe_sockets(client_sock, remote_sock)

    def _handle_http(self, client_sock):
        # Read HTTP request header
        req_data = b""
        while b"\r\n\r\n" not in req_data and len(req_data) < 8192:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            req_data += chunk

        if not req_data:
            return

        first_line = req_data.split(b"\r\n")[0].decode('latin1', errors='replace')
        parts = first_line.split(" ")
        if len(parts) < 2:
            return

        method, target = parts[0], parts[1]

        if method.upper() == "CONNECT":
            # CONNECT host:port HTTP/1.1
            if ":" in target:
                host, port_s = target.split(":", 1)
                port = int(port_s)
            else:
                host, port = target, 443

            remote_sock = self._connect_upstream(host, port)
            if not remote_sock:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._pipe_sockets(client_sock, remote_sock)
        else:
            # Standard HTTP GET/POST/etc
            # Parse target URL
            m = re.match(r'^https?://([^/:]+)(?::(\d+))?(.*)$', target, re.I)
            if m:
                host = m.group(1)
                port = int(m.group(2)) if m.group(2) else 80
                path = m.group(3) or "/"
                # Rewrite first line
                rest = req_data.split(b"\r\n", 1)[1] if b"\r\n" in req_data else b""
                new_first_line = f"{method} {path} HTTP/1.1\r\n".encode('latin1')
                modified_req = new_first_line + rest
            else:
                host_header = None
                for line in req_data.split(b"\r\n"):
                    if line.lower().startswith(b"host:"):
                        host_header = line.split(b":", 1)[1].strip().decode('latin1')
                        break
                if not host_header:
                    return
                if ":" in host_header:
                    host, port_s = host_header.split(":", 1)
                    port = int(port_s)
                else:
                    host, port = host_header, 80
                modified_req = req_data

            remote_sock = self._connect_upstream(host, port)
            if not remote_sock:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return

            remote_sock.sendall(modified_req)
            self._pipe_sockets(client_sock, remote_sock)

    def _connect_upstream(self, host, port):
        if self.mode == "socks":
            # Forward through vk-turn-client local SOCKS5 proxy
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10.0)
                s.connect(self.upstream_socks)
                # SOCKS5 Handshake with upstream
                s.sendall(b'\x05\x01\x00')
                resp = s.recv(2)
                if resp != b'\x05\x00':
                    s.close()
                    return None
                # CONNECT command
                host_bytes = host.encode('utf-8')
                req = b'\x05\x01\x00\x03' + bytes([len(host_bytes)]) + host_bytes + struct.pack('>H', port)
                s.sendall(req)
                resp = s.recv(4)
                if len(resp) < 4 or resp[1] != 0:
                    s.close()
                    return None
                # Read remainder of SOCKS5 reply address
                atyp = resp[3]
                if atyp == 1:
                    s.recv(4 + 2)
                elif atyp == 3:
                    l = s.recv(1)[0]
                    s.recv(l + 2)
                elif atyp == 4:
                    s.recv(16 + 2)
                s.settimeout(None)
                return s
            except Exception:
                return None
        else:
            # VPN mode (or direct): outbound traffic is routed by OS network adapter
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10.0)
                s.connect((host, port))
                s.settimeout(None)
                return s
            except Exception:
                return None

    def _pipe_sockets(self, s1, s2):
        s1.setblocking(False)
        s2.setblocking(False)
        sockets = [s1, s2]
        try:
            while self.running:
                r, _, x = select.select(sockets, [], sockets, 60)
                if x:
                    break
                if not r:
                    continue
                for s in r:
                    data = s.recv(32768)
                    if not data:
                        return
                    dest = s2 if s is s1 else s1
                    dest.sendall(data)
                    with self._lock:
                        if s is s1:
                            self.bytes_recv += len(data)
                        else:
                            self.bytes_sent += len(data)
        except Exception:
            pass
        finally:
            try: s1.close()
            except Exception: pass
            try: s2.close()
            except Exception: pass

    def get_stats(self):
        with self._lock:
            return {
                "active_conns": self.active_conns,
                "total_conns": self.total_conns,
                "bytes_sent": self.bytes_sent,
                "bytes_recv": self.bytes_recv,
                "running": self.running,
                "port": self.port
            }
