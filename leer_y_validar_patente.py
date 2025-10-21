import cv2
import easyocr
import re
import requests
import json
import serial
import time
import threading


# pip install opencv-python easyocr requests pyserial torch torchvision
# cd "C:\Users\PC 5to\Desktop\SP_Nashe"
# py leer_y_validar_patente.py

# 🔧 Configuración
FIREBASE_URL = "https://smartpark-253369-default-rtdb.firebaseio.com"
PUERTO_ARDUINO = "COM7"   # Ajustá si corresponde
BAUD_RATE = 9600
CONF_MINIMA = 0.60
NUM_SENSORS = 4

# ---- Cache local de reservas (para evitar pisadas)
reservas_cache = [0] * NUM_SENSORS
reservas_lock = threading.Lock()

# Normalizador de patentes
def normalizar_patente(texto):
    return re.sub(r"[^A-Z0-9]", "", texto.upper())

# Obtener usuarios autorizados desde Firebase (tu versión)
def obtener_usuario_autorizado(patente_detectada):
    try:
        url = f"{FIREBASE_URL}/Estacionamiento_inteligente.json"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            print(f"❌ Error al obtener datos de Firebase: {response.status_code}")
            return None
        data = response.json()
        if not isinstance(data, dict):
            return None
        for usuario, valor in data.items():
            patente_registrada = ""
            if isinstance(valor, str):
                try:
                    info = json.loads(valor)
                    if isinstance(info, dict) and "Patente" in info:
                        patente_registrada = info["Patente"]
                except:
                    continue
            elif isinstance(valor, dict):
                if "Patente" in valor:
                    patente_registrada = valor["Patente"]
            if patente_registrada:
                patente_registrada = normalizar_patente(patente_registrada)
                if patente_registrada == patente_detectada:
                    return usuario
    except Exception as e:
        print(f"❌ Error en Firebase: {e}")
    return None

# Subir estado de lugares a Firebase (fusión que respeta reservas)
def subir_estado_firebase(estados):
    try:
        # 1) Leer estado actual de Firebase
        url_get = f"{FIREBASE_URL}/estado/lugares.json"
        resp = requests.get(url_get, timeout=3)
        actuales = resp.json() if resp.status_code == 200 else {}

        # 2) Fusionar: si Firebase o cache local tienen 2 y Arduino dice 0 -> mantener 2
        fusion = {}
        for i in range(len(estados)):
            # valor actual en Firebase (por key string)
            actual_fb = 0
            if isinstance(actuales, dict):
                try:
                    actual_fb = int(actuales.get(str(i), 0))
                except:
                    actual_fb = 0

            # valor en cache (thread-safe)
            with reservas_lock:
                cache_val = int(reservas_cache[i]) if i < len(reservas_cache) else 0

            # regla: si actual_fb==2 OR cache_val==2  AND Arduino reporta 0 -> mantenemos 2
            if (actual_fb == 2 or cache_val == 2) and estados[i] == 0:
                fusion[str(i)] = 2
            else:
                fusion[str(i)] = int(estados[i])

        # 3) Recalcular ocupados/libres (reservados no cuentan como libres)
        ocupados = sum(1 for v in fusion.values() if v == 1)
        libres = sum(1 for v in fusion.values() if v == 0)

        data = {
            "libres": libres,
            "ocupados": ocupados,
            "lugares": fusion
        }

        # 4) Subir la fusión
        url_put = f"{FIREBASE_URL}/estado.json"
        requests.put(url_put, json=data, timeout=3)
        print(f"☁️ Estado actualizado (fusionado): {data}")

    except Exception as e:
        print(f"❌ Error al subir estados: {e}")

# ------------------ HILO: monitorear reservas en Firebase (polling) ------------------
def monitorear_reservas():
    last_sent = None
    while True:
        try:
            url = f"{FIREBASE_URL}/estado/lugares.json"
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                lugares = [0] * NUM_SENSORS
                if isinstance(data, dict):
                    for i in range(NUM_SENSORS):
                        key = str(i)
                        v = data.get(key, 0)
                        try:
                            lugares[i] = int(v)
                        except:
                            lugares[i] = 0
                elif isinstance(data, list):
                    for i in range(min(NUM_SENSORS, len(data))):
                        try:
                            lugares[i] = int(data[i])
                        except:
                            lugares[i] = 0

                # Actualizar cache local (thread-safe)
                with reservas_lock:
                    for i in range(NUM_SENSORS):
                        reservas_cache[i] = lugares[i]

                mensaje = "RESERVA:" + ",".join(str(x) for x in lugares)
                # enviar solo si cambió el mensaje para no saturar el serial
                if mensaje != last_sent:
                    try:
                        arduino.write((mensaje + "\n").encode("utf-8"))
                        arduino.flush()
                        print("☁️ Firebase → Arduino:", mensaje)
                        last_sent = mensaje
                    except Exception as e_w:
                        print("❌ Error enviando a Arduino:", e_w)
        except Exception as e:
            print("⚠️ Error leyendo estado/lugares desde Firebase:", e)

        time.sleep(1)  # revisar cada 1 segundo (podés aumentar si lo querés menos frecuente)

# -------------------------------------------------------------------------------------

# Conectar con Arduino (igual que antes)
try:
    arduino = serial.Serial(PUERTO_ARDUINO, BAUD_RATE, timeout=1)
    time.sleep(2)
    print(f"🔌 Conectado a {PUERTO_ARDUINO}")
except Exception as e:
    print(f"❌ No se pudo abrir el puerto {PUERTO_ARDUINO}: {e}")
    exit()

# Lanzar hilo de reservas (AHORA que Arduino está abierto)
threading.Thread(target=monitorear_reservas, daemon=True).start()

# Inicializar OCR y cámara (tal cual tu código)
reader = easyocr.Reader(['es'], gpu=False)
cam = cv2.VideoCapture(0)
if not cam.isOpened():
    print("❌ No se pudo acceder a la cámara.")
    exit()

print("🕒 Esperando señal del Arduino ('DETECTADO')...")

# Bucle principal (igual que tenías)
while True:
    ret, frame = cam.read()
    if not ret:
        break

    cv2.imshow("Smart Park - Cámara en vivo", frame)

    if arduino.in_waiting > 0:
        linea = arduino.readline().decode().strip()
        print(f"📥 Arduino: {linea}")

        if linea.startswith("ESTADO:"):
            try:
                estados = [int(x) for x in linea.replace("ESTADO:", "").split(",")]
                threading.Thread(target=subir_estado_firebase, args=(estados,), daemon=True).start()
            except Exception as e:
                print("⚠️ Error parseando estado:", e)

        elif linea == "DETECTADO":
            print("📸 Vehículo detectado. Procesando imagen...")
            resultados = reader.readtext(frame)
            acceso_autorizado = False

            if resultados:
                for _, texto, conf in resultados:
                    patente = normalizar_patente(texto)
                    if conf >= CONF_MINIMA:
                        usuario = obtener_usuario_autorizado(patente)
                        if usuario:
                            print(f"✅ Acceso autorizado. Bienvenido {usuario} ({patente})")
                            arduino.write(b"ABRIR\n")
                            acceso_autorizado = True
                            break

            if not acceso_autorizado:
                print("🚫 Acceso denegado.")
                arduino.write(b"DENEGADO\n")

    if cv2.waitKey(1) == 27:  # ESC para salir
        break

cv2.destroyAllWindows()
cam.release()
arduino.close()