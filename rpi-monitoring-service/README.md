# Raspberry Pi Monitoring Service

FastAPI REST service for simple Raspberry Pi health checks.

## Endpoints

- `GET /health` - machine and service health data
- `GET /camera` - Raspberry Pi camera availability and detected cameras
- `GET /camera/image` - capture and return a JPEG image
- `GET /led` - Trinkey serial availability
- `POST /led/on` - turn on the Trinkey NeoPixel with HSV and brightness
- `POST /led/off` - turn off the Trinkey NeoPixel
- `POST /led/flash` - flash the Trinkey NeoPixel with HSV, brightness, duration, and count
- `GET /docs` - Swagger UI
- `GET /openapi.json` - OpenAPI schema

## Local Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Raspberry Pi Install

Copy this folder to `/home/hack/rpi-monitoring-service` on the Pi, then run:

```bash
cd /home/hack/rpi-monitoring-service
bash scripts/install_on_pi.sh
```

After installation:

- Health: `http://hackabot.local:8080/health`
- Swagger: `http://hackabot.local:8080/docs`

## LED Control

The Trinkey must run `trinkey/code.py` as `code.py` on its `CIRCUITPY` drive.
The installer uses USB serial at:

```text
/dev/serial/by-id/usb-Adafruit_QT2040_Trinkey_DF609C80671A2926-if00
```

Turn the LED on:

```bash
curl -X POST http://hackabot.local:8080/led/on \
  -H "Content-Type: application/json" \
  -d '{"hue":120,"saturation":1,"value":1,"brightness":0.3}'
```

Turn the LED off:

```bash
curl -X POST http://hackabot.local:8080/led/off
```

Flash the LED:

```bash
curl -X POST http://hackabot.local:8080/led/flash \
  -H "Content-Type: application/json" \
  -d '{"hue":0,"saturation":0,"value":1,"brightness":1,"duration_ms":150,"count":1,"gap_ms":100}'
```

## Camera Control

Check camera availability:

```bash
curl http://hackabot.local:8080/camera
```

Capture a JPEG:

```bash
curl "http://hackabot.local:8080/camera/image?width=1280&height=720&quality=90&timeout_ms=1000" \
  --output camera.jpg
```

Optional query parameters:

- `width` - image width, default `1280`
- `height` - image height, default `720`
- `quality` - JPEG quality from `1` to `100`, default `90`
- `timeout_ms` - camera warmup/capture timeout, default `1000`
- `hflip` - horizontal flip, default `false`
- `vflip` - vertical flip, default `false`

## Service Commands

```bash
sudo systemctl status rpi-monitoring-service
sudo systemctl restart rpi-monitoring-service
sudo journalctl -u rpi-monitoring-service -f
```
