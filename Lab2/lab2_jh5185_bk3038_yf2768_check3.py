# Checkpoint 3:
from machine import Pin, PWM, ADC
import time
last_edge = 0
was_pressed = False

#sensor initialization
sensor = ADC(Pin(36))
sensor.atten(ADC.ATTN_11DB)

#motor initialization
motor = PWM(Pin(26), freq = 1000, duty_u16 = 0)

#LED initialization
lightOUT = PWM(Pin(4), freq = 1000, duty_u16 = 0)

freqLevel = 10000//10
dCycleLevel = 65535//10

def pressedOrReleased(pin):
    #global because it goes out of scope
    global last_edge, was_pressed
    #this returns how much time has elapsed since
    #the start of the chip cycle.
    now = time.ticks_ms()

    if time.ticks_diff(now, last_edge) < 50:
        return
    
    is_pressed = (pin.value() == 0)

    if is_pressed == was_pressed:
        #then ignore it, 
        return
    #set the last time of button change to the time of now
    last_edge = now
    #the current state of button press is the last state
    #(when this function is visisted again.)
    was_pressed = is_pressed
    if is_pressed:
        print("I pressed it")
    else:
        print("I released it")


button = Pin(25, Pin.IN, Pin.PULL_UP)
#the flag for IRQ_FALLING is button PRESSED
#the flag for IRQ_RISING is button RELEASED
#handler is for the handler function when both flags are set to 1.
button.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING, handler=pressedOrReleased)

while True:
    if was_pressed:
        motor.duty_u16(32768)
        sensorInput = sensor.read()
        lightIN = (sensorInput * 11) // 4096
        print(lightIN)
        time.sleep_ms(200)
        lightOUT.duty_u16(lightIN * dCycleLevel)
        motor.freq((lightIN * freqLevel) + 10)
    else:
        lightOUT.duty_u16(0)
        motor.duty_u16(0)
    time.sleep_ms(50)