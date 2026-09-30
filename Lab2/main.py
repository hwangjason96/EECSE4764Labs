############################################################
# Name: Lab 2 Tasks all In one
# Authors: Brandon Kim, Yian Fan, Jae Sung Hwang
# Date Created: 9/29/26
# Date Modified: 9/29/26
# Modified By: Jae Sung Hwang
# Description:
#   This is where all of our code for Lab 2 is at.
############################################################


# #Task 1: Controlling the brightness using PWM Library
# from machine import Pin,PWM
# Pin(4, Pin.OUT).value(0)
# #LED variable declaration description:
# #   Pin(4) means that it is connected to GPIO A5
# #   freq = 1000 controls how fast the signals are going to A5
# led = PWM(Pin(4), freq = 1000)
# #   Duty Cycle controls how much of the wave is on HIGH and
# #   how much is LOW, this controls the Average Voltage in.
# #   In this case, it controls the LED's Brightness.
# dCycleLevel = 65535//10 #we will be making 10 levels of brightness.
# brightness = 1
# # While loop for the main body.
# while True:
#     # Since input is not assumed to be an integer, we cast.
#     try:
#         brightness = int(input("Control the Brightness (0-10): "))
#     except:
#         #if not an integer, we get out of the loop. simple exit.
#         print("Not a number! Goodbye!\n")
#         break
#     #we control duty cycle this way.
#     dCycle = dCycleLevel*brightness
#     led.duty_u16(dCycle)


# #Task 2: Vibration motor work.
# from machine import Pin,PWM

# #Vibration motor will be on GPIO A4 : Pin 36
# Pin(25, Pin.OUT).value(0)
# motor = PWM(Pin(25))
# freqLevel = 10000//10 #This will be our pitch
# dCycleLevel = 65535//10 #This will be our volume (avg voltage)
# volume = 1
# pitch = 1
# # While loop for the main body.
# while True:
#     # Since input is not assumed to be an integer, we cast.
#     try:
#         volume = int(input("Control the Volume (0-10): "))
#     except:
#         #if not an integer, we get out of the loop. simple exit.
#         print("Not a number! Goodbye!\n")
#         break
#     #we control duty cycle this way.
#     dCycle = dCycleLevel*volume
#     motor.duty_u16(dCycle)

#     #Cast again for pitch
#     try:
#         pitch = int(input("Control the pitch (0-10): "))
#     except:
#         #if not an integer, we get out of the loop. simple exit.
#         print("Not a number! Goodbye!\n")
#         break
#     #frequency
#     frequency = (freqLevel * pitch) + 10
#     motor.freq(frequency)

# #Task 3:
# # Connect the analog light sensor to the ADC input to the HUZZAH board and sample
# # at 1 Hz (1 sample per second). You will see that values you read out will be an integer
# # number. Try varying the readings from the light sensor by placing your finger on the
# # sensor and removing it. You can see what values you are getting by printing to the
# # serial port.
# from machine import Pin, PWM, ADC
# import time
# sensor = ADC(Pin(36))
# sensor.atten(ADC.ATTN_11DB)

# while True:
#     print(sensor.read_u16())
#     time.sleep_ms(200)


# #Checkpoint1: 
# from machine import Pin, PWM, ADC
# import time
# #sensor initialization
# sensor = ADC(Pin(36))
# sensor.atten(ADC.ATTN_11DB)

# #motor initialization
# motor = PWM(Pin(26), duty_u16=32768)

# #LED initialization
# lightOUT = PWM(Pin(4), freq = 1000)

# freqLevel = 10000//10
# dCycleLevel = 65535//10


# try:
#     while True:
#         #lightIn value is now from 0-10
#         sensorInput = sensor.read()
#         lightIN = (sensorInput * 11) // 4096

#         lightOUT.duty_u16(lightIN * dCycleLevel)
#         motor.freq((lightIN * freqLevel) + 10)
# except KeyboardInterrupt:
#     lightIN.deinit()
#     motor.deinit()
#     Pin(4, Pin.OUT).value(0)
#     Pin(26, Pin.OUT).value(0)
#     print("Goodbye!")

# # Checkpoint 2:
# from machine import Pin, PWM
# import time
# last_edge = 0
# was_pressed = False

# def pressedOrReleased(pin):
#     #global because it goes out of scope
#     global last_edge, was_pressed
#     #this returns how much time has elapsed since
#     #the start of the chip cycle.
#     now = time.ticks_ms()

#     #if the time of the last cycle, and
#     #the time elapsed currently is too short 
#     #(less than 50 ms)
#     if time.ticks_diff(now, last_edge) < 50:
#         #just get out, this is a bounce.
#         return
    
#     #check if this function was visited
#     #because the button was pressed
#     is_pressed = (pin.value() == 0)
#     #check if the function was visited at the same
#     #state of the button.
#     if is_pressed == was_pressed:
#         #then ignore it, 
#         return
#     #set the last time of button change to the time of now
#     last_edge = now
#     #the current state of button press is the last state
#     #(when this function is visisted again.)
#     was_pressed = is_pressed
#     if is_pressed:
#         print("I pressed it")
#     else:
#         print("I released it")


# button = Pin(25, Pin.IN, Pin.PULL_UP)
# #the flag for IRQ_FALLING is button PRESSED
# #the flag for IRQ_RISING is button RELEASED
# #handler is for the handler function when both flags are set to 1.
# button.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING, handler=pressedOrReleased)

# while True:
#     time.sleep_ms(100)


# # Checkpoint 3:
# from machine import Pin, PWM, ADC
# import time
# last_edge = 0
# was_pressed = False

# #sensor initialization
# sensor = ADC(Pin(36))
# sensor.atten(ADC.ATTN_11DB)

# #motor initialization
# motor = PWM(Pin(26), freq = 1000, duty_u16 = 0)

# #LED initialization
# lightOUT = PWM(Pin(4), freq = 1000, duty_u16 = 0)

# freqLevel = 10000//10
# dCycleLevel = 65535//10

# def pressedOrReleased(pin):
#     #global because it goes out of scope
#     global last_edge, was_pressed

#     now = time.ticks_ms()

#     if time.ticks_diff(now, last_edge) < 50:
#         return
    
#     is_pressed = (pin.value() == 0)
#     if is_pressed == was_pressed:
#         #then ignore it, 
#         return
#     #set the last time of button change to the time of now
#     last_edge = now
#     #the current state of button press is the last state
#     #(when this function is visisted again.)
#     was_pressed = is_pressed
#     if is_pressed:
#         print("I pressed it")
#     else:
#         print("I released it")


# button = Pin(25, Pin.IN, Pin.PULL_UP)
# #the flag for IRQ_FALLING is button PRESSED
# #the flag for IRQ_RISING is button RELEASED
# #handler is for the handler function when both flags are set to 1.
# button.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING, handler=pressedOrReleased)

# while True:
#     if was_pressed:
#         motor.duty_u16(32768)
#         sensorInput = sensor.read()
#         lightIN = (sensorInput * 11) // 4096
#         print(lightIN)
#         time.sleep_ms(200)
#         lightOUT.duty_u16(lightIN * dCycleLevel)
#         motor.freq((lightIN * freqLevel) + 10)
#     else:
#         lightOUT.duty_u16(0)
#         motor.duty_u16(0)
#     time.sleep_ms(50)
