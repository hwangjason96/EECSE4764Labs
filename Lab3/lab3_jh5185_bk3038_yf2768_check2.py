# Checkpoint 2: light sensor value + screen brightness from ambient light
from machine import Pin, I2C, RTC, ADC
import ssd1306, time

sensor = ADC(Pin(34)) # light sensor on A2 (GPIO 34)
sensor.atten(ADC.ATTN_11DB)

rtc = RTC()
rtc.datetime((2026,10,5,0,15,20,0,0))

i2c = I2C(sda=Pin(22), scl=Pin(20))
display = ssd1306.SSD1306_I2C(128, 32, i2c)

while True:
    light = sensor.read() # 0 (dark) - 4095 (bright)
    brightness = (light * 255) // 4095 # scale to the contrast range 0 - 255
    display.contrast(brightness) # dim room -> dim screen, bright room -> bright screen

    current_time = rtc.datetime()
    hour = current_time[4]
    minute = current_time[5]
    second = current_time[6]
    Time_text = str(hour) + ":" + str(minute) + ":" + str(second)

    display.fill(0)
    display.text(Time_text, 0, 0, 1)
    display.text("Light: " + str(light), 0, 12, 1)
    display.show()

    # print(light, brightness)
    time.sleep(0.1)