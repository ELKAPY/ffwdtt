package main

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type PcvpnBridge struct {
	port       int
	listener   net.Listener
	running    bool
	mu         sync.Mutex
	activeConn int64
	totalConn  int64
	bytesSent  int64
	bytesRecv  int64
	mode       string // "vpn" or "socks"
}

func NewPcvpnBridge(port int) *PcvpnBridge {
	return &PcvpnBridge{
		port: port,
		mode: "vpn",
	}
}

func (p *PcvpnBridge) Start(port int, mode string) error {
	p.mu.Lock()
	if p.running {
		p.mu.Unlock()
		return nil
	}
	p.port = port
	p.mode = mode

	addr := fmt.Sprintf("0.0.0.0:%d", p.port)
	l, err := net.Listen("tcp", addr)
	if err != nil {
		p.mu.Unlock()
		return err
	}
	p.listener = l
	p.running = true
	p.mu.Unlock()

	go p.serve()
	return nil
}

func (p *PcvpnBridge) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.running {
		return
	}
	p.running = false
	if p.listener != nil {
		_ = p.listener.Close()
		p.listener = nil
	}
}

func (p *PcvpnBridge) IsRunning() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.running
}

func (p *PcvpnBridge) serve() {
	for {
		conn, err := p.listener.Accept()
		if err != nil {
			break
		}
		atomic.AddInt64(&p.activeConn, 1)
		atomic.AddInt64(&p.totalConn, 1)

		go func(c net.Conn) {
			defer func() {
				_ = c.Close()
				atomic.AddInt64(&p.activeConn, -1)
			}()
			p.handleConnection(c)
		}(conn)
	}
}

func (p *PcvpnBridge) handleConnection(client net.Conn) {
	_ = client.SetDeadline(time.Now().Add(15 * time.Second))

	reader := bufio.NewReader(client)
	peek, err := reader.Peek(1)
	if err != nil {
		return
	}

	if peek[0] == 0x05 {
		p.handleSocks5(client, reader)
	} else {
		p.handleHTTP(client, reader)
	}
}

func (p *PcvpnBridge) handleSocks5(client net.Conn, r *bufio.Reader) {
	// 1. Auth negotiation
	header := make([]byte, 2)
	if _, err := io.ReadFull(r, header); err != nil || header[0] != 5 {
		return
	}
	numMethods := int(header[1])
	methods := make([]byte, numMethods)
	if _, err := io.ReadFull(r, methods); err != nil {
		return
	}
	// NO AUTH
	if _, err := client.Write([]byte{0x05, 0x00}); err != nil {
		return
	}

	// 2. Request details
	reqHead := make([]byte, 4)
	if _, err := io.ReadFull(r, reqHead); err != nil || reqHead[1] != 1 { // CMD 1 = CONNECT
		_ = client.SetDeadline(time.Now().Add(5 * time.Second))
		_, _ = client.Write([]byte{0x05, 0x07, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}

	var host string
	switch reqHead[3] {
	case 1: // IPv4
		ip := make([]byte, 4)
		if _, err := io.ReadFull(r, ip); err != nil {
			return
		}
		host = net.IP(ip).String()
	case 3: // Domain
		l, err := r.ReadByte()
		if err != nil {
			return
		}
		domain := make([]byte, l)
		if _, err := io.ReadFull(r, domain); err != nil {
			return
		}
		host = string(domain)
	case 4: // IPv6
		ip := make([]byte, 16)
		if _, err := io.ReadFull(r, ip); err != nil {
			return
		}
		host = net.IP(ip).String()
	default:
		return
	}

	portBuf := make([]byte, 2)
	if _, err := io.ReadFull(r, portBuf); err != nil {
		return
	}
	port := binary.BigEndian.Uint16(portBuf)
	target := net.JoinHostPort(host, strconv.Itoa(int(port)))

	// Connect upstream
	targetConn, err := p.connectUpstream(target)
	if err != nil {
		_, _ = client.Write([]byte{0x05, 0x04, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}
	defer targetConn.Close()

	// Reply success
	if _, err := client.Write([]byte{0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0}); err != nil {
		return
	}

	_ = client.SetDeadline(time.Time{})
	_ = targetConn.SetDeadline(time.Time{})

	p.pipe(client, targetConn)
}

func (p *PcvpnBridge) handleHTTP(client net.Conn, r *bufio.Reader) {
	req, err := http.ReadRequest(r)
	if err != nil {
		return
	}

	if req.Method == http.MethodConnect {
		targetConn, err := p.connectUpstream(req.Host)
		if err != nil {
			_, _ = client.Write([]byte("HTTP/1.1 502 Bad Gateway\r\n\r\n"))
			return
		}
		defer targetConn.Close()

		if _, err := client.Write([]byte("HTTP/1.1 200 Connection Established\r\n\r\n")); err != nil {
			return
		}

		_ = client.SetDeadline(time.Time{})
		_ = targetConn.SetDeadline(time.Time{})
		p.pipe(client, targetConn)
	} else {
		host := req.Host
		if !strings.Contains(host, ":") {
			host = net.JoinHostPort(host, "80")
		}
		targetConn, err := p.connectUpstream(host)
		if err != nil {
			_, _ = client.Write([]byte("HTTP/1.1 502 Bad Gateway\r\n\r\n"))
			return
		}
		defer targetConn.Close()

		_ = req.Write(targetConn)
		_ = client.SetDeadline(time.Time{})
		_ = targetConn.SetDeadline(time.Time{})
		p.pipe(client, targetConn)
	}
}

func (p *PcvpnBridge) connectUpstream(target string) (net.Conn, error) {
	if p.mode == "socks" {
		// Forward through local SOCKS5 127.0.0.1:19050
		conn, err := net.DialTimeout("tcp", "127.0.0.1:19050", 10*time.Second)
		if err != nil {
			return nil, err
		}
		// Handshake
		if _, err := conn.Write([]byte{0x05, 0x01, 0x00}); err != nil {
			_ = conn.Close()
			return nil, err
		}
		reply := make([]byte, 2)
		if _, err := io.ReadFull(conn, reply); err != nil || reply[1] != 0 {
			_ = conn.Close()
			return nil, fmt.Errorf("socks upstream auth error")
		}
		// Connect command
		host, portStr, _ := net.SplitHostPort(target)
		port, _ := strconv.Atoi(portStr)
		req := []byte{0x05, 0x01, 0x00, 0x03, byte(len(host))}
		req = append(req, []byte(host)...)
		pBytes := make([]byte, 2)
		binary.BigEndian.PutUint16(pBytes, uint16(port))
		req = append(req, pBytes...)

		if _, err := conn.Write(req); err != nil {
			_ = conn.Close()
			return nil, err
		}
		respHead := make([]byte, 4)
		if _, err := io.ReadFull(conn, respHead); err != nil || respHead[1] != 0 {
			_ = conn.Close()
			return nil, fmt.Errorf("socks upstream connect error")
		}
		// Discard remaining addr bytes
		switch respHead[3] {
		case 1:
			io.CopyN(io.Discard, conn, 4+2)
		case 3:
			l, _ := conn.Read(make([]byte, 1))
			io.CopyN(io.Discard, conn, int64(l)+2)
		case 4:
			io.CopyN(io.Discard, conn, 16+2)
		}
		return conn, nil
	}

	// VPN mode or direct OS connection
	return net.DialTimeout("tcp", target, 10*time.Second)
}

func (p *PcvpnBridge) pipe(s1, s2 net.Conn) {
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		n, _ := io.Copy(s2, s1)
		atomic.AddInt64(&p.bytesRecv, n)
		if tc, ok := s2.(*net.TCPConn); ok {
			_ = tc.CloseWrite()
		}
	}()

	go func() {
		defer wg.Done()
		n, _ := io.Copy(s1, s2)
		atomic.AddInt64(&p.bytesSent, n)
		if tc, ok := s1.(*net.TCPConn); ok {
			_ = tc.CloseWrite()
		}
	}()

	wg.Wait()
}
