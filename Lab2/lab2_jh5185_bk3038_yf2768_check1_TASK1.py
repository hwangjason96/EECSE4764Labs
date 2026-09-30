#Task 1: Controlling the brightness using PWM Library
from machine import Pin,PWM
Pin(4, Pin.OUT).value(0)
#LED variable declaration description:
#   Pin(4) means that it is connected to GPIO A5
#   freq = 1000 controls how fast the signals are going to A5
led = PWM(Pin(4), freq = 1000)
#   Duty Cycle controls how much of the wave is on HIGH and
#   how much is LOW, this controls the Average Voltage in.
#   In this case, it controls the LED's Brightness.
dCycleLevel = 65535//10 #we will be making 10 levels of brightness.
brightness = 1
# While loop for the main body.
while True:
    # Since input is not assumed to be an integer, we cast.
    try:
        brightness = int(input("Control the Brightness (0-10): "))
    except:
        #if not an integer, we get out of the loop. simple exit.
        print("Not a number! Goodbye!\n")
        break
    #we control duty cycle this way.
    dCycle = dCycleLevel*brightness
    led.duty_u16(dCycle)