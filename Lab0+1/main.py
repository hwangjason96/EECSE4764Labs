'''
Program Name: Lab 1 EECSE4764
Authors: Byung Hyo "Brandon" Kim, Jae Sung Hwang, Ian (Please put your last name!)
Date Created: 09.22.26
Date Last Modified: 09.22.26
Modified By: Brandon
'''

from machine import Pin
import utime
import neopixel

# Power-enable for NeoPixel
pwr = Pin(2, Pin.OUT)
pwr.value(1) # turn on power

builtin_led = Pin(13, Pin.OUT)
np_led = neopixel.NeoPixel(Pin(0, Pin.OUT), 1)
builtin_led.value(1) # Built in LED - 1 is on
np_led[0] = (0, 0, 0) # NeoPixel LED - (0,0,0) is off
np_led.write()

# while True:
# 	builtin_led.value(not builtin_led.value())
# 	if np_led[0] == (0, 0 ,0):
# 		np_led[0] = (255, 255, 255)
# 	else:
# 		np_led[0] = (0, 0, 0)
	
# 	np_led.write()
# 	utime.sleep_ms(100)

# lab 1 part 1
while True:
# S
    for i in range(3):
        np_led[0] = (225, 0, 0)
        np_led.write()
        utime.sleep(0.5)

        np_led[0] = (0, 0, 0)
        np_led.write()
        utime.sleep(0.5)

    utime.sleep(1)
# O
    for i in range(3):
        np_led[0] = (225, 0, 0)
        np_led.write()
        utime.sleep(1.0)

        np_led[0] = (0, 0, 0)
        np_led.write()
        utime.sleep(0.5)

    utime.sleep(1)
# S
    for i in range(3):
        np_led[0] = (225, 0, 0)
        np_led.write()
        utime.sleep(0.5)

        np_led[0] = (0, 0, 0)
        np_led.write()
        utime.sleep(0.5)
		
    utime.sleep(2)
