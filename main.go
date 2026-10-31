package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const maxHistory = 100

type store struct {
	mu      sync.RWMutex
	dir     string
	latest  map[string]any
	history []map[string]any
	forward bool
}

func newStore(dir string, forward bool) *store {
	s := &store{dir: dir, forward: forward, latest: map[string]any{}}
	_ = os.MkdirAll(dir, 0755)
	s.latest = readObject(filepath.Join(dir, "latest.json"))
	s.history = readList(filepath.Join(dir, "history.json"))
	return s
}

func readObject(path string) map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return map[string]any{}
	}
	var value map[string]any
	if json.Unmarshal(data, &value) != nil {
		return map[string]any{}
	}
	return value
}

func readList(path string) []map[string]any {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var value []map[string]any
	if json.Unmarshal(data, &value) != nil {
		return nil
	}
	return value
}

func (s *store) save(data map[string]any) map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	data["_received_at"] = time.Now().Format(time.RFC3339Nano)
	s.latest = data
	s.history = append(s.history, data)
	if len(s.history) > maxHistory {
		s.history = s.history[len(s.history)-maxHistory:]
	}
	writeJSON(filepath.Join(s.dir, "latest.json"), data)
	writeJSON(filepath.Join(s.dir, "history.json"), s.history)
	if s.forward {
		workspace := os.Getenv("PICOCRAWL_WORKSPACE")
		if workspace == "" {
			workspace = filepath.Join(s.dir, "..", "..", "..", "phone_data")
		}
		_ = os.MkdirAll(workspace, 0755)
		writeJSON(filepath.Join(workspace, "latest.json"), data)
	}
	return data
}

func writeJSON(path string, value any) {
	data, err := json.MarshalIndent(value, "", "  ")
	if err == nil {
		_ = os.WriteFile(path, data, 0644)
	}
}

func (s *store) latestData() map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.latest
}

func (s *store) historyData(limit int) []map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if limit < 0 {
		limit = 0
	}
	if limit > len(s.history) {
		limit = len(s.history)
	}
	result := make([]map[string]any, limit)
	copy(result, s.history[len(s.history)-limit:])
	return result
}

func jsonResponse(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func phoneDataHandler(s *store, w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		if r.URL.Path == "/" || r.URL.Path == "/status" {
			jsonResponse(w, http.StatusOK, map[string]any{
				"service": "PicoClaw PhoneLink Server (Go)",
				"status": "running",
				"has_data": len(s.latestData()) > 0,
				"history_count": len(s.historyData(maxHistory)),
				"channels": map[string]string{
					"websocket": "ws://0.0.0.0:8766",
					"http_post": "POST /api/phone-data",
					"http_get": "GET /api/phone-data",
				},
			})
			return
		}
		if r.URL.Path == "/api/phone-data" {
			if r.URL.Query().Get("format") == "text" {
				w.Header().Set("Content-Type", "text/plain; charset=utf-8")
				_, _ = fmt.Fprint(w, formatText(s.latestData()))
			} else {
				jsonResponse(w, http.StatusOK, s.latestData())
			}
			return
		}
		if r.URL.Path == "/api/history" {
			limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
			if limit == 0 {
				limit = 20
			}
			history := s.historyData(limit)
			jsonResponse(w, http.StatusOK, map[string]any{"count": len(history), "data": history})
			return
		}
	case http.MethodPost:
		if r.URL.Path == "/api/phone-data" {
			defer r.Body.Close()
			var data map[string]any
			if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
				jsonResponse(w, http.StatusBadRequest, map[string]string{"error": "invalid json: " + err.Error()})
				return
			}
			saved := s.save(data)
			jsonResponse(w, http.StatusOK, map[string]any{"ok": true, "received": saved["timestampReadable"]})
			return
		}
	}
	jsonResponse(w, http.StatusNotFound, map[string]string{"error": "not found"})
}

func formatText(data map[string]any) string {
	if len(data) == 0 {
		return "暂无数据"
	}
	return fmt.Sprintf("📱 手机数据 (%v)\n\n📍 位置: %v, %v\n📱 应用: %v\n🔋 电量: %v%%\n📲 设备: %v %v\n📶 WiFi: %v\n",
		data["timestampReadable"], data["latitude"], data["longitude"], data["foregroundLabel"],
		data["batteryLevel"], data["deviceBrand"], data["deviceModel"], data["isWifiConnected"])
}

var upgrader = websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}

func websocketHandler(s *store, w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer conn.Close()
	for {
		var data map[string]any
		if err := conn.ReadJSON(&data); err != nil {
			return
		}
		saved := s.save(data)
		_ = conn.WriteJSON(map[string]any{
			"ok": true, "received": saved["timestampReadable"],
			"device": fmt.Sprintf("%v %v", saved["deviceBrand"], saved["deviceModel"]),
		})
	}
}

func main() {
	host := flag.String("host", "0.0.0.0", "监听地址")
	port := flag.Int("port", 8765, "HTTP 端口")
	wsPort := flag.Int("ws-port", 8766, "WebSocket 端口")
	forward := flag.Bool("forward", false, "转发到 PicoClaw workspace")
	dataDir := flag.String("data-dir", "data", "数据目录")
	flag.Parse()
	s := newStore(*dataDir, *forward)
	go func() {
		mux := http.NewServeMux()
		mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { websocketHandler(s, w, r) })
		log.Printf("WebSocket: ws://%s:%d", *host, *wsPort)
		log.Fatal(http.ListenAndServe(fmt.Sprintf("%s:%d", *host, *wsPort), mux))
	}()
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { phoneDataHandler(s, w, r) })
	log.Printf("HTTP: http://%s:%d", *host, *port)
	log.Fatal(http.ListenAndServe(fmt.Sprintf("%s:%d", *host, *port), mux))
}
