from machine import Pin
import utime
import neopixel # Neopixel RGB LED control 

# Power-enable for NeoPixel
pwr = Pin(2, Pin.OUT)
pwr.value(1) # turn on power

builtin_led = Pin(13, Pin.OUT)
np_led = neopixel.NeoPixel(Pin(0, Pin.OUT), 1) # 연결된 NeoPixel 개수 1

builtin_led.value(1) # Built in LED -> 1 is on
np_led[0] = (0, 0, 0) # NeoPixel LED - (0,0,0) is off / default, initial value
np_led.write() # command to use Neopixel color LED

# while True:
#     builtin_led.value(not builtin_led.value()) # with using "not" pin 13 starts with 0
#     if np_led[0] == (0, 0 ,0):
#         np_led[0] = (0, 0, 255) # colors red, green, blue
#     else:
#         np_led[0] = (0, 0, 0)

#     np_led.write() # 위에서 바뀐 값을 LED에 적용
#     utime.sleep(1)

# Lab1 part 1
while True:
# 첫번째 점
    for i in range(3):
        np_led[0] = (225, 0, 0)
        np_led.write()
        utime.sleep(0.5)

        np_led[0] = (0, 0, 0)
        np_led.write()
        utime.sleep(0.5)

    utime.sleep(1)
# 두번째 점 
    for i in range(3):
        np_led[0] = (225, 0, 0)
        np_led.write()
        utime.sleep(1.0)

        np_led[0] = (0, 0, 0)
        np_led.write()
        utime.sleep(0.5)

    utime.sleep(1)
# 3번째 점
    for i in range(3):
        np_led[0] = (225, 0, 0)
        np_led.write()
        utime.sleep(0.5)

        np_led[0] = (0, 0, 0)
        np_led.write()
        utime.sleep(0.5)
    utime.sleep(2)

# # lab 1 part 2
# count = 0

# while True:
#     builtin_led.value(not builtin_led.value())

#     count += 1

#     utime.sleep(0.1)
    
#     if count == 5:
#         if np_led[0] == (0, 0, 0): # initial value
#             np_led[0] = (0,255,0) # Green
#         else:
#             np_led[0] = (0,0,0)

#         np_led.write()
#         count = 0

