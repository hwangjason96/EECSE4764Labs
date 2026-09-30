#Task 3:
# Connect the analog light sensor to the ADC input to the HUZZAH board and sample
# at 1 Hz (1 sample per second). You will see that values you read out will be an integer
# number. Try varying the readings from the light sensor by placing your finger on the
# sensor and removing it. You can see what values you are getting by printing to the
# serial port.
from machine import Pin, PWM, ADC
import time
sensor = ADC(Pin(36))
sensor.atten(ADC.ATTN_11DB)

while True:
    print(sensor.read_u16())
    time.sleep_ms(200)

