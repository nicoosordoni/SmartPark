#include <Adafruit_NeoPixel.h>
#include <Servo.h>

#define NUM_SENSORS 4
#define DISTANCIA_UMBRAL 5  // Umbral para ocupación
#define SERVO_UMBRAL 1       // Umbral para barreras

// Pines sensores de lugar
const int trigPins[NUM_SENSORS] = { 2, 4, 6, 8 };
const int echoPins[NUM_SENSORS] = { 3, 5, 7, 9 };

// Pines Neopixels
const int ledPins[NUM_SENSORS] = { 10, 11, 12, 13 };

// Pines barreras
const int servoTrigE = A1;
const int servoEchoE = A2;
const int servoPinE = A0;
const int servoTrigS = A4;
const int servoEchoS = A5;
const int servoPinS = A3;
Servo myservoE;
Servo myservoS;

Adafruit_NeoPixel pixels[NUM_SENSORS] = {
  Adafruit_NeoPixel(1, ledPins[0], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[1], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[2], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[3], NEO_GRB + NEO_KHZ800)
};

unsigned long tiempoUltimaDeteccionS = 0;
bool barreraSalidaAbierta = false;

static String ultimoEstado = "";

// Nuevas variables mínimas
int reservas[NUM_SENSORS] = {0,0,0,0};        // 0=no reservado, 2=reservado
int estadoSensor[NUM_SENSORS] = {0,0,0,0};    // 0=libre (según sensor), 1=ocupado (sensor)

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
    pixels[i].begin();
    pixels[i].clear();
    pixels[i].show();
  }

  pinMode(servoTrigE, OUTPUT);
  pinMode(servoEchoE, INPUT);
  pinMode(servoTrigS, OUTPUT);
  pinMode(servoEchoS, INPUT);
  myservoE.attach(servoPinE);
  myservoS.attach(servoPinS);
  myservoE.write(0);
  myservoS.write(90);
}

void loop() {
  // Damos prioridad a las barreras: 5 chequeos rápidos antes de leer parking
  for (int i = 0; i < 5; i++) {
    controlarBarreraEntrada();
    controlarBarreraSalida();
  }

  // Luego se leen los sensores de lugares
  actualizarSensoresEstacionamiento();

  // También siempre revisar si llegó un mensaje RESERVA (por si no fue leído antes)
  if (Serial.available()) {
    String mensaje = Serial.readStringUntil('\n');
    mensaje.trim();
    if (mensaje.length() > 0) {
      // Si es RESERVA, procesar (si es otro comando, lo ignoramos aquí)
      if (mensaje.startsWith("RESERVA:")) {
        procesarReservaMensaje(mensaje);
      }
      // NOTA: comandos como "ABRIR" son atendidos dentro de controlarBarreraEntrada()
      //       (ese método también ahora maneja RESERVA: para evitar pérdida)
    }
  }
}

void controlarBarreraEntrada() {
  static bool esperandoValidacion = false;
  static unsigned long ultimaDeteccion = 0;

  int distancia = medirDistancia(servoTrigE, servoEchoE);

  if (distancia > 0 && distancia <= SERVO_UMBRAL && !esperandoValidacion) {
    Serial.println("DETECTADO");  // Avisar a Python
    esperandoValidacion = true;
    ultimaDeteccion = millis();
  }

  if (esperandoValidacion && Serial.available()) {
    String mensaje = Serial.readStringUntil('\n');
    mensaje.trim();
    if (mensaje.length() > 0) {
      // SI llega RESERVA: mientras esperamos validación, lo procesamos y no lo descartamos.
      if (mensaje.startsWith("RESERVA:")) {
        procesarReservaMensaje(mensaje);
      } else if (mensaje == "ABRIR") {
        myservoE.write(90);
        delay(3000);
        myservoE.write(0);
        esperandoValidacion = false;
      } // otros mensajes se ignoran
    }
  }

  if (esperandoValidacion && millis() - ultimaDeteccion > 5000) {
    esperandoValidacion = false;
  }
}

void controlarBarreraSalida() {
  int distancia = medirDistancia(servoTrigS, servoEchoS);
  if (distancia > 0 && distancia <= SERVO_UMBRAL) {
    Serial.println("DETECTADO SALIDA");
    myservoS.write(0);
    barreraSalidaAbierta = true;
    tiempoUltimaDeteccionS = millis();
  } else if (barreraSalidaAbierta) {
    if (millis() - tiempoUltimaDeteccionS > 3000) {
      myservoS.write(90);
      barreraSalidaAbierta = false;
    }
  } else {
    myservoS.write(90);
  }
}

void actualizarSensoresEstacionamiento() {
  String estado = "ESTADO:";
  for (int i = 0; i < NUM_SENSORS; i++) {
    int distancia = medirDistancia(trigPins[i], echoPins[i]);
    if (distancia > 0 && distancia <= DISTANCIA_UMBRAL) {
      estadoSensor[i] = 1;  // Ocupado por sensor
    } else {
      estadoSensor[i] = 0;  // Libre según sensor (pero si está reservado, lo trataremos luego)
    }
    estado += String(estadoSensor[i]);
    if (i < NUM_SENSORS - 1) estado += ",";
  }

  if (estado != ultimoEstado) {
    Serial.println(estado);
    ultimoEstado = estado;
  }

  // Actualizar LEDs teniendo en cuenta sensores + reservas
  actualizarLedsSegunEstados();
}

void actualizarLedsSegunEstados() {
  for (int i = 0; i < NUM_SENSORS; i++) {
    pixels[i].clear();
    // prioridad: si sensor detecta ocupado -> ROJO
    if (estadoSensor[i] == 1) {
      pixels[i].setPixelColor(0, pixels[i].Color(255, 0, 0));  // Rojo (ocupado)
    } else {
      // si no está ocupado por sensor, pero hay reserva==2 -> AMARILLO
      if (reservas[i] == 2) {
        pixels[i].setPixelColor(0, pixels[i].Color(255, 255, 0)); // Amarillo (reservado)
      } else {
        pixels[i].setPixelColor(0, pixels[i].Color(0, 255, 0));  // Verde (libre)
      }
    }
    pixels[i].show();
  }
}

// Procesa mensaje RESERVA:0,2,0,0  (lo llamamos desde donde se recibe)
void procesarReservaMensaje(String mensajeCompleto) {
  mensajeCompleto.replace("RESERVA:", "");
  // convertir a char[] para usar strtok
  char buf[128];
  mensajeCompleto.toCharArray(buf, sizeof(buf));
  char *token = strtok(buf, ",");
  int idx = 0;
  while (token != NULL && idx < NUM_SENSORS) {
    int val = atoi(token);
    if (val < 0) val = 0;
    if (val > 2) val = 0;
    reservas[idx] = val;
    token = strtok(NULL, ",");
    idx++;
  }
  // si sobran lugares no cubiertos, poner 0
  while (idx < NUM_SENSORS) {
    reservas[idx] = 0;
    idx++;
  }
  // aplicar inmediatamente colores
  actualizarLedsSegunEstados();
}

int medirDistancia(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duracion = pulseIn(echoPin, HIGH, 30000);
  if (duracion == 0) return -1;
  return duracion * 0.034 / 2;
}

