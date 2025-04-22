#include <Adafruit_NeoPixel.h>
#include <Servo.h>

#define NUM_SENSORS 4
#define DISTANCIA_UMBRAL 20 // Umbral para ocupación (Neopixels)
#define SERVO_UMBRAL 20      // Umbral para abrir barrera

// Pines sensores ultrasónicos (para Neopixels)
const int trigPins[NUM_SENSORS] = {2, 4, 6, 8};
const int echoPins[NUM_SENSORS] = {3, 5, 7, 9};

// Pines Neopixels
const int ledPins[NUM_SENSORS] = {10, 11, 12, 13};

// Servo y sensor extra
const int servoTrig = A1;
const int servoEcho = A2;
const int servoPin = A0;

Servo myservo;

Adafruit_NeoPixel pixels[NUM_SENSORS] = {
  Adafruit_NeoPixel(1, ledPins[0], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[1], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[2], NEO_GRB + NEO_KHZ800),
  Adafruit_NeoPixel(1, ledPins[3], NEO_GRB + NEO_KHZ800)
};

void setup() {
  Serial.begin(9600);

  for (int i = 0; i < NUM_SENSORS; i++) {
    pinMode(trigPins[i], OUTPUT);
    pinMode(echoPins[i], INPUT);
    pixels[i].begin();
    pixels[i].clear();
    pixels[i].show();
  }

  pinMode(servoTrig, OUTPUT);
  pinMode(servoEcho, INPUT);
  myservo.attach(servoPin);
  myservo.write(0); // Empieza cerrado
}

void loop() {
  // --- Lectura de los sensores de estacionamiento ---
  for (int i = 0; i < NUM_SENSORS; i++) {
    int distancia = medirDistancia(trigPins[i], echoPins[i]);

    Serial.print("Sensor ");
    Serial.print(i + 1);
    Serial.print(" - Distancia: ");
    Serial.print(distancia);
    Serial.println(" cm");

    pixels[i].clear();
    if (distancia <= DISTANCIA_UMBRAL && distancia > 0) {
      pixels[i].setPixelColor(0, pixels[i].Color(255, 0, 0)); // Rojo
    } else {
      pixels[i].setPixelColor(0, pixels[i].Color(0, 255, 0)); // Verde
    }
    pixels[i].show();
  }

  // --- Control del servomotor con el 5to sensor ---
  int distanciaServo = medirDistancia(servoTrig, servoEcho);
  Serial.print("Sensor BARRERA - Distancia: ");
  Serial.print(distanciaServo);
  Serial.println(" cm");

  if (distanciaServo > 0 && distanciaServo <= SERVO_UMBRAL) {
    myservo.write(90); // Abrir barrera
  } else {
    myservo.write(0); // Cerrar barrera
  }

  delay(500);
}

int medirDistancia(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH);
  int distancia = duration * 0.034 / 2;
  return distancia;
}
