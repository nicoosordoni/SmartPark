#include <Adafruit_NeoPixel.h>

#define PIN 6           // Pin de datos conectado al DIN del NeoPixel
#define NUMPIXELS 1     // Número de LEDs (uno solo en este caso)

Adafruit_NeoPixel pixel(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);

void setup() {
  pixel.begin();        // Inicializa el NeoPixel
  pixel.show();         // Apaga todos los LEDs al inicio
}

void loop() {
  // Verde
  pixel.setPixelColor(0, pixel.Color(0, 255, 0));
  pixel.show();
  delay(1000);

  // Amarillo (Rojo + Verde)
  pixel.setPixelColor(0, pixel.Color(255, 255, 0));
  pixel.show();
  delay(1000);

  // Rojo
  pixel.setPixelColor(0, pixel.Color(255, 0, 0));
  pixel.show();
  delay(1000);
}

