# Checkpoint 2:
from machine import Pin, PWM
import time
last_edge = 0
was_pressed = False

def pressedOrReleased(pin):
    #global because it goes out of scope
    global last_edge, was_pressed
    #this returns how much time has elapsed since
    #the start of the chip cycle.
    now = time.ticks_ms()

    #if the time of the last cycle, and
    #the time elapsed currently is too short 
    #(less than 50 ms)
    if time.ticks_diff(now, last_edge) < 50:
        #just get out, this is a bounce.
        return
    
    #check if this function was visited
    #because the button was pressed
    is_pressed = (pin.value() == 0)
    #check if the function was visited at the same
    #state of the button.
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
    time.sleep_ms(100)