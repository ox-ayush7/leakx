# 💧 LeakX — Smart Water Leak Detection & Monitoring System

Real-time IoT-based water pipeline leak detection with live dashboard, 
critical alarms, remote valve control and leak reporting.

## 🚀 Features

- 📡 Simulated IoT sensor pipeline (flow + pressure telemetry every 2s)
- 🧠 Threshold-based leak detection (Flow > 12 L/min + Pressure < 30 PSI)
- 🖥️ Live SCADA-style dashboard (real-time graph, gauge, KPI cards)
- 🚨 Full-screen critical alarm with siren on leak detection
- 🔧 Remote valve isolation (one-click operator response)
- ⬇️ CSV leak report download
- 🔌 REST API — production-ready for real ESP32/hardware sensors

## 🛠️ Tech Stack

- **Backend:** Python, FastAPI
- **Frontend:** HTML/CSS/JS (embedded, served by backend)
- **Data:** CSV telemetry store

## ▶️ Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Dashboard automatically opens at: `http://127.0.0.1:8000`

## 🔌 API Endpoints

| Endpoint | Description |
|---|---|
| `/` | Live dashboard |
| `/latest` | Latest sensor reading |
| `/readings` | Full telemetry data |
| `/alerts` | Leak alerts |
| `/water-loss` | Estimated water loss |
| `/zones` | Zone health status |
| `/valve` | Valve status |
| `/valve/close` | Shut valve (isolate leak) |
| `/valve/open` | Reopen valve |
| `/report` | Download CSV leak report |

## 📝 Note

Sensors are simulated (digital twin). The architecture is production-ready — 
real hardware sensors (ESP32, flow meters) can push data to the same REST API.

## 👤 Author

**Ayush** — [ox-ayush7](https://github.com/ox-ayush7)
