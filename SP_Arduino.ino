#include <Adafruit_NeoPixel.h>
#include <Servo.h>

#define NUM_SENSORS 4
#define DISTANCIA_UMBRAL 5     // cm - para ocupación
#define SERVO_UMBRAL 1        // cm - detección en barrera

// Configuración de ángulos de servos
#define ENTRADA_ABRIR 90
#define ENTRADA_CERRAR 0
#define SALIDA_ABRIR 0
#define SALIDA_CERRAR 90

// Pines sensores de lugares
const int trigPins[NUM_SENSORS] = {2, 4, 6, 8};
const int echoPins[NUM_SENSORS] = {3, 5, 7, 9};

// Pines Neopixels
const int ledPins[NUM_SENSORS] = {10, 11, 12, 13};

// Pines de barreras
const int servoTrigE = A1;
const int servoEchoE = A2;
const int servoPinE  = A0;
const int servoTrigS = A4;
const int servoEchoS = A5;
const int servoPinS  = A3;

Servo myservoE;
Servo myservoS;

Adafruit_NeoPixel pixels[NUM_SENSORS] = {
  Adafruit_NeoPixel(1, ledPins[0], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[1], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[2], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[3], NEO_GRB + NEO_KHZ800)
};

// Variables globales
unsigned long tiempoAperturaEntrada = 0;
unsigned long tiempoAperturaSalida = 0;
bool barreraEntradaAbierta = false;
bool barreraSalidaAbierta = false;

int reservas[NUM_SENSORS] = {0,0,0,0};
int estadoSensor[NUM_SENSORS] = {0,0,0,0};
String ultimoEstado = "";

// Variables para estabilidad
int contadorOcupado[NUM_SENSORS] = {0};
int contadorLibre[NUM_SENSORS] = {0};

// -----------------------------------------------------------------------------
// SETUP
// -----------------------------------------------------------------------------
void setup() {
  Serial.begin(9600);

  for (int i=0; i<NUM_SENSORS; i++) {
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

  myservoE.write(ENTRADA_CERRAR);
  myservoS.write(SALIDA_CERRAR);
}

// -----------------------------------------------------------------------------
// LOOP PRINCIPAL
// -----------------------------------------------------------------------------
void loop() {
  leerComandosSerial();
  controlarBarreraEntrada();
  controlarBarreraSalida();
  actualizarSensoresEstacionamiento();
}

// -----------------------------------------------------------------------------
// LECTURA DE COMANDOS SERIAL
// -----------------------------------------------------------------------------
void leerComandosSerial() {
  while (Serial.available()) {
    String mensaje = Serial.readStringUntil('\n');
    mensaje.trim();

    if (mensaje.startsWith("RESERVA:")) {
      procesarReservaMensaje(mensaje);
    } 
    else if (mensaje == "ABRIR") {
      Serial.println("🟢 Comando ABRIR recibido → abriendo barrera entrada");
      myservoE.write(ENTRADA_ABRIR);
      tiempoAperturaEntrada = millis();
      barreraEntradaAbierta = true;
    } 
    else if (mensaje == "DENEGADO") {
      Serial.println("🚫 Acceso denegado");
    }
  }
}

// -----------------------------------------------------------------------------
// CONTROL BARRERA DE ENTRADA
// -----------------------------------------------------------------------------
void controlarBarreraEntrada() {
  static bool esperandoValidacion = false;
  static unsigned long ultimaDeteccion = 0;

  int distancia = medirDistanciaPromedio(servoTrigE, servoEchoE);

  if (distancia > 0 && distancia <= SERVO_UMBRAL && !esperandoValidacion && !barreraEntradaAbierta) {
    Serial.println("DETECTADO");
    esperandoValidacion = true;
    ultimaDeteccion = millis();
  }

  if (barreraEntradaAbierta && millis() - tiempoAperturaEntrada > 5000) {
    myservoE.write(ENTRADA_CERRAR);
    barreraEntradaAbierta = false;
    esperandoValidacion = false;
  }

  if (esperandoValidacion && millis() - ultimaDeteccion > 6000) {
    esperandoValidacion = false;
  }
}

// -----------------------------------------------------------------------------
// CONTROL BARRERA DE SALIDA
// -----------------------------------------------------------------------------
void controlarBarreraSalida() {
  int distancia = medirDistanciaPromedio(servoTrigS, servoEchoS);

  if (distancia > 0 && distancia <= SERVO_UMBRAL && !barreraSalidaAbierta) {
    Serial.println("🚗 Vehículo detectado en salida → abriendo");
    myservoS.write(SALIDA_ABRIR);
    tiempoAperturaSalida = millis();
    barreraSalidaAbierta = true;
  }

  if (barreraSalidaAbierta && millis() - tiempoAperturaSalida > 5000) {
    myservoS.write(SALIDA_CERRAR);
    barreraSalidaAbierta = false;
  }
}

// -----------------------------------------------------------------------------
// DETECCIÓN DE OCUPACIÓN DE LUGARES (CON HISTÉRESIS AJUSTADA)
// -----------------------------------------------------------------------------
void actualizarSensoresEstacionamiento() {
  String estado = "ESTADO:";

  for (int i=0; i<NUM_SENSORS; i++) {
    int distancia = medirDistanciaPromedio(trigPins[i], echoPins[i]);

    // Si no hay lectura válida o el objeto está muy cerca, se considera ocupado
    if (distancia == -1 || distancia < 2 || distancia <= DISTANCIA_UMBRAL) {
      contadorOcupado[i]++;
      contadorLibre[i] = 0;
      if (contadorOcupado[i] >= 2 && estadoSensor[i] != 1) {
        estadoSensor[i] = 1;
      }
    } else if (distancia > DISTANCIA_UMBRAL) {
      contadorLibre[i]++;
      contadorOcupado[i] = 0;
      if (contadorLibre[i] >= 2 && estadoSensor[i] != 0) {
        estadoSensor[i] = 0;
      }
    }

    estado += String(estadoSensor[i]);
    if (i < NUM_SENSORS-1) estado += ",";
  }

  if (estado != ultimoEstado) {
    Serial.println(estado);
    ultimoEstado = estado;
  }

  actualizarLedsSegunEstados();
}

// -----------------------------------------------------------------------------
// LEDS SEGÚN ESTADO
// -----------------------------------------------------------------------------
void actualizarLedsSegunEstados() {
  for (int i=0; i<NUM_SENSORS; i++) {
    pixels[i].clear();
    if (reservas[i] == 2) {
      pixels[i].setPixelColor(0, pixels[i].Color(255, 255, 0)); // amarillo reservado
    } else if (estadoSensor[i] == 1) {
      pixels[i].setPixelColor(0, pixels[i].Color(255, 0, 0));   // rojo ocupado
    } else {
      pixels[i].setPixelColor(0, pixels[i].Color(0, 255, 0));   // verde libre
    }
    pixels[i].show();
  }
}

// -----------------------------------------------------------------------------
// PROCESAR RESERVAS
// -----------------------------------------------------------------------------
void procesarReservaMensaje(String mensajeCompleto) {
  mensajeCompleto.replace("RESERVA:", "");
  char buf[64];
  mensajeCompleto.toCharArray(buf, sizeof(buf));
  char *token = strtok(buf, ",");
  int i=0;
  while (token && i<NUM_SENSORS) {
    reservas[i++] = atoi(token);
    token = strtok(NULL, ",");
  }
  actualizarLedsSegunEstados();
}

// -----------------------------------------------------------------------------
// MEDIR DISTANCIA PROMEDIADA (ANTI-RUIDO Y RÁPIDA)
// -----------------------------------------------------------------------------
int medirDistanciaPromedio(int trigPin, int echoPin) {
  const int N = 3; // lecturas promediadas
  long suma = 0;
  int validas = 0;

  for (int i = 0; i < N; i++) {
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    long duracion = pulseIn(echoPin, HIGH, 25000);
    if (duracion > 0) {
      suma += duracion * 0.034 / 2;
      validas++;
    }
    delay(5);
  }

  if (validas == 0) return -1;
  return suma / validas;
}
