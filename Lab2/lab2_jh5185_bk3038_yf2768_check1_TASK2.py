#Task 2: Vibration motor work.
from machine import Pin,PWM

#Vibration motor will be on GPIO A4 : Pin 36
Pin(25, Pin.OUT).value(0)
motor = PWM(Pin(25))
freqLevel = 10000//10 #This will be our pitch
dCycleLevel = 65535//10 #This will be our volume (avg voltage)
volume = 1
pitch = 1
# While loop for the main body.
while True:
    # Since input is not assumed to be an integer, we cast.
    try:
        volume = int(input("Control the Volume (0-10): "))
    except:
        #if not an integer, we get out of the loop. simple exit.
        print("Not a number! Goodbye!\n")
        break
    #we control duty cycle this way.
    dCycle = dCycleLevel*volume
    motor.duty_u16(dCycle)

    #Cast again for pitch
    try:
        pitch = int(input("Control the pitch (0-10): "))
    except:
        #if not an integer, we get out of the loop. simple exit.
        print("Not a number! Goodbye!\n")
        break
    #frequency
    frequency = (freqLevel * pitch) + 10
    motor.freq(frequency)

