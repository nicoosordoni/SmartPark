import cv2
import easyocr
import re
import requests
import json
import serial
import time
import threading

from datetime import datetime
import numpy as np
from typing import Optional, Dict, List, Any

class SmartPark:
    def __init__(self,
                 firebase_url: str = "https://smartpark-253369-default-rtdb.firebaseio.com",
                 puerto_arduino: str = "COM7",
                 baud_rate: int = 9600,
                 conf_minima: float = 0.50,
                 num_sensors: int = 4,
                 camera_index: int = 0):
        
        # Configuration
        self.FIREBASE_URL = firebase_url
        self.PUERTO_ARDUINO = puerto_arduino
        self.BAUD_RATE = baud_rate
        self.CONF_MINIMA = conf_minima
        self.NUM_SENSORS = num_sensors
        self.camera_index = camera_index

        # State
        self.arduino: Optional[serial.Serial] = None
        self.cam: Optional[cv2.VideoCapture] = None
        self.reader: Optional[Any] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.latest_frame = None

        # Locks
        self.write_lock = threading.Lock()
        self._last_open_time_lock = threading.Lock()
        self.frame_lock = threading.Lock()

        # cooldown
        self.open_cooldown_ms = 3000
        self._last_open_time = 0

        # Logs with timestamp
        self.logs: List[str] = []
        self.log_lock = threading.Lock()
        self.max_logs = 500

        # Status tracking
        self._status = {
            "arduino_connected": False,
            "camera_connected": False,
            "recognition_active": False,
            "firebase_status": "unknown",
            "last_error": None
        }
        self.status_lock = threading.Lock()

    def update_status(self, **kwargs):
        with self.status_lock:
            self._status.update(kwargs)

    def get_status(self) -> dict:
        with self.status_lock:
            return dict(self._status)

    def log(self, msg: str):
        """Add timestamped log entry"""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        with self.log_lock:
            self.logs.append(line)
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]
        print(line)

    def get_logs(self) -> List[str]:
        """Get copy of recent logs"""
        with self.log_lock:
            return list(self.logs)

    @staticmethod
    def normalizar_patente(texto: str) -> str:
        if texto is None:
            return ""
        return re.sub(r"[^A-Z0-9]", "", str(texto).upper())

    @staticmethod
    def extraer_patente_de_texto(texto: str) -> str:
        try:
            if not texto:
                return ""
            texto_limpio = texto.replace(";", ",")
            data = json.loads(texto_limpio)
            if isinstance(data, list) and len(data) >= 2:
                return SmartPark.normalizar_patente(data[1])
            return ""
        except Exception:
            return ""

    def obtener_usuario_autorizado(self, patente_detectada: str) -> Optional[str]:
        try:
            patente_norm = self.normalizar_patente(patente_detectada)
            if not patente_norm:
                self.log("⚠️ No se recibió patente válida.")
                return None

            # Check Firebase
            url_base = f"{self.FIREBASE_URL}/Estacionamiento_inteligente.json"
            resp = requests.get(url_base, timeout=6)
            if resp.status_code != 200:
                self.log("❌ Error accediendo a Firebase.")
                self.update_status(firebase_status="error")
                return None

            self.update_status(firebase_status="connected")
            data = resp.json()
            
            if not isinstance(data, dict):
                self.log("❌ Estructura inválida en Firebase.")
                return None

            # Get reservations
            reservas_raw = data.get("Reservas", "[]")
            try:
                reservas = json.loads(reservas_raw) if isinstance(reservas_raw, str) else reservas_raw
            except:
                reservas = []

            if not reservas:
                self.log("⚠️ No hay reservas activas.")
                return None

            # Find matching plate
            for usuario in reservas:
                if not usuario:
                    continue
                datos_usuario = data.get(usuario)
                if not datos_usuario:
                    continue

                patente_usuario = self.extraer_patente_de_texto(datos_usuario)
                if self.normalizar_patente(patente_usuario) == patente_norm:
                    self.log(f"✅ Patente {patente_norm} pertenece al usuario con reserva: {usuario}")

                    # Remove reservation after entry
                    try:
                        nuevas_reservas = [u for u in reservas if u != usuario]
                        url_put = f"{self.FIREBASE_URL}/Estacionamiento_inteligente/Reservas.json"
                        requests.put(url_put, json=json.dumps(nuevas_reservas), timeout=6)
                        self.log(f"🗑️ Reserva eliminada para {usuario}")
                    except Exception as e:
                        self.log(f"⚠️ Error eliminando reserva: {e}")

                    return usuario

            self.log("🚫 Ninguna patente con reserva encontrada.")
            return None

        except Exception as e:
            self.log(f"❌ Error verificando reservas: {e}")
            self.update_status(firebase_status="error", last_error=str(e))
            return None

    def safe_send_command(self, cmd_str: str):
        try:
            with self.write_lock:
                if cmd_str.strip().upper() == "ABRIR":
                    with self._last_open_time_lock:
                        ahora = int(time.time() * 1000)
                        if ahora - self._last_open_time < self.open_cooldown_ms:
                            self.log("⏱️ Ignorado ABRIR por cooldown.")
                            return
                        self._last_open_time = ahora

                if self.arduino and self.arduino.is_open:
                    self.arduino.write((cmd_str + "\n").encode("utf-8"))
                    self.arduino.flush()
                    self.log(f"➡️ Enviado a Arduino: {cmd_str}")
                else:
                    self.log("❌ Puerto Arduino no disponible.")
                    self.update_status(arduino_connected=False)
        except Exception as e:
            self.log(f"❌ Error enviando a Arduino: {e}")
            self.update_status(arduino_connected=False, last_error=str(e))

    def subir_estado_firebase(self, estados: List[int]):
        try:
            url_get = f"{self.FIREBASE_URL}/estado/lugares.json"
            resp = requests.get(url_get, timeout=3)
            actuales = resp.json() if resp.status_code == 200 else {}

            fusion = {}
            for i in range(len(estados)):
                actual_fb = 0
                if isinstance(actuales, dict):
                    try:
                        actual_fb = int(actuales.get(str(i), 0))
                    except:
                        actual_fb = 0

                if actual_fb == 2 and estados[i] == 0:
                    fusion[str(i)] = 2
                else:
                    fusion[str(i)] = int(estados[i])

            ocupados = sum(1 for v in fusion.values() if v == 1)
            libres = sum(1 for v in fusion.values() if v == 0)

            data = {"libres": libres, "ocupados": ocupados, "lugares": fusion}
            url_put = f"{self.FIREBASE_URL}/estado.json"
            requests.put(url_put, json=data, timeout=3)
            self.log(f"☁️ Subido a Firebase: {data}")
            self.update_status(firebase_status="connected")

        except Exception as e:
            self.log(f"❌ Error al subir estado a Firebase: {e}")
            self.update_status(firebase_status="error", last_error=str(e))

    def marcar_llegada_en_firebase(self, usuario: str):
        try:
            if not usuario:
                return
            url = f"{self.FIREBASE_URL}/usuarios/{usuario}/estado.json"
            payload = {"llego": True}
            requests.patch(url, json=payload, timeout=5)
            self.log(f"📲 Marcado '{usuario}' como 'llegó' en Firebase.")
            self.update_status(firebase_status="connected")
        except Exception as e:
            self.log(f"⚠️ Error al marcar llegada: {e}")
            self.update_status(firebase_status="error", last_error=str(e))

    def start(self) -> bool:
        """Initialize and start recognition thread"""
        if self.running:
            self.log("⚠️ Reconocimiento ya en ejecución.")
            return False

        self.running = True
        self.update_status(recognition_active=True)

        # Initialize hardware
        try:
            self.arduino = serial.Serial(self.PUERTO_ARDUINO, self.BAUD_RATE, timeout=1)
            time.sleep(1.5)
            self.log(f"🔌 Conectado a {self.PUERTO_ARDUINO}")
            self.update_status(arduino_connected=True)
        except Exception as e:
            self.arduino = None
            self.log(f"⚠️ No se pudo abrir puerto Arduino {self.PUERTO_ARDUINO}: {e}")
            self.update_status(arduino_connected=False, last_error=str(e))

        try:
            self.reader = easyocr.Reader(["es"], gpu=False)
            self.log("✅ OCR inicializado")
        except Exception as e:
            self.reader = None
            self.log(f"⚠️ Error iniciando EasyOCR: {e}")
            self.update_status(last_error=str(e))

        try:
            self.cam = cv2.VideoCapture(self.camera_index)
            if not self.cam.isOpened():
                raise Exception("No se pudo abrir la cámara")
            self.update_status(camera_connected=True)
            self.log("� Cámara iniciada")
        except Exception as e:
            self.cam = None
            self.log(f"❌ Error abriendo cámara: {e}")
            self.update_status(camera_connected=False, last_error=str(e))

        # Start processing thread
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.log("🕒 Reconocimiento iniciado.")
        return True

    def stop(self):
        """Stop recognition and release resources"""
        if not self.running:
            self.log("⚠️ Reconocimiento no está en ejecución.")
            return

        self.running = False
        self.update_status(recognition_active=False)

        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None

        if self.cam:
            try:
                self.cam.release()
            except:
                pass
            self.cam = None
            self.update_status(camera_connected=False)

        if self.arduino:
            try:
                self.arduino.close()
            except:
                pass
            self.arduino = None
            self.update_status(arduino_connected=False)

        with self.frame_lock:
            self.latest_frame = None

        self.log("⏹️ Reconocimiento detenido.")

    def _run(self):
        """Main processing loop"""
        while self.running:
            # Read camera frame
            if self.cam:
                ret, frame = self.cam.read()
                if ret:
                    with self.frame_lock:
                        self.latest_frame = frame
                        
            # Handle Arduino input
            try:
                if self.arduino and self.arduino.in_waiting > 0:
                    linea = self.arduino.readline().decode(errors="ignore").strip()
                    if not linea:
                        continue

                    self.log(f"📥 Arduino: {linea}")
                    self.update_status(arduino_connected=True)

                    if linea.startswith("ESTADO:"):
                        try:
                            estados = [int(x) for x in linea.replace("ESTADO:", "").split(",")]
                            threading.Thread(target=self.subir_estado_firebase, 
                                          args=(estados,), daemon=True).start()
                        except Exception as e:
                            self.log(f"⚠️ Error procesando estados: {e}")

                    elif linea == "DETECTADO":
                        self.log("📸 Vehículo detectado. Esperando estabilización...")
                        # Get stable frame
                        time.sleep(0.6)
                        frame_proc = None
                        
                        if self.cam:
                            ret2, frame2 = self.cam.read()
                            frame_proc = frame2 if ret2 else self.latest_frame
                        else:
                            with self.frame_lock:
                                frame_proc = self.latest_frame

                        if frame_proc is None or self.reader is None:
                            self.log("⚠️ No hay frame o OCR no disponible.")
                            self.safe_send_command("DENEGADO")
                            continue

                        resultados = self.reader.readtext(frame_proc)
                        acceso_autorizado = False

                        for item in resultados:
                            # easyocr returns tuples that sometimes are (bbox, text, prob)
                            if len(item) == 3:
                                bbox, texto, conf = item
                            else:
                                texto = str(item)
                                conf = 0
                            patente = self.normalizar_patente(texto)
                            self.log(f"   • '{texto}' → '{patente}' (conf: {conf:.2f})")
                            if patente and conf >= self.CONF_MINIMA:
                                usuario = self.obtener_usuario_autorizado(patente)
                                if usuario:
                                    self.log(f"✅ Acceso autorizado: {usuario} ({patente}) — ABRIR")
                                    self.safe_send_command("ABRIR")
                                    self.marcar_llegada_en_firebase(usuario)
                                    acceso_autorizado = True
                                    break
                        if not acceso_autorizado:
                            self.log("🚫 Acceso denegado.")
                            self.safe_send_command("DENEGADO")

            except Exception as e:
                self.log(f"⚠️ Error en loop principal: {e}")
                self.update_status(last_error=str(e))

            time.sleep(0.02)

    def get_frame_jpeg(self) -> bytes:
        """Get latest frame as JPEG bytes for streaming"""
        with self.frame_lock:
            if self.latest_frame is None:
                # return empty gray image
                img = np.full((240, 320, 3), 128, dtype=np.uint8)
                _, buf = cv2.imencode('.jpg', img)
                return buf.tobytes()
            try:
                _, jpeg = cv2.imencode('.jpg', self.latest_frame)
                return jpeg.tobytes()
            except Exception as e:
                self.log(f"⚠️ Error codificando frame JPEG: {e}")
                return b''

    def manual_patente(self, patente: str) -> Dict[str, Any]:
        """Process manual plate entry"""
        patente_norm = self.normalizar_patente(patente)
        usuario = self.obtener_usuario_autorizado(patente_norm)
        if usuario:
            self.log(f"✅ Manual: Autorizado {usuario} ({patente_norm}) — enviando ABRIR.")
            self.safe_send_command("ABRIR")
            self.marcar_llegada_en_firebase(usuario)
            return {
                "status": "ok",
                "action": "ABRIR",
                "message": f"Acceso autorizado para {usuario}",
                "type": "success"
            }
        else:
            self.log(f"🚫 Manual: Patente {patente_norm} denegada.")
            self.safe_send_command("DENEGADO")
            return {
                "status": "denied",
                "action": "DENEGADO",
                "message": "Acceso denegado",
                "type": "error"
            }