#Checkpoint1: 
from machine import Pin, PWM, ADC
import time
#sensor initialization
sensor = ADC(Pin(36))
sensor.atten(ADC.ATTN_11DB)

#motor initialization
motor = PWM(Pin(26), duty_u16=32768)

#LED initialization
lightOUT = PWM(Pin(4), freq = 1000)

freqLevel = 10000//10
dCycleLevel = 65535//10


try:
    while True:
        #lightIn value is now from 0-10
        sensorInput = sensor.read()
        lightIN = (sensorInput * 11) // 4096

        lightOUT.duty_u16(lightIN * dCycleLevel)
        motor.freq((lightIN * freqLevel) + 10)
except KeyboardInterrupt:
    lightIN.deinit()
    motor.deinit()
    Pin(4, Pin.OUT).value(0)
    Pin(26, Pin.OUT).value(0)
    print("Goodbye!")