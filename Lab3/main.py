# # Task 1: Modify the system time using RTC
# from machine import Pin, PWM, RTC
# import time

# rtc = RTC() # create RTC object
# rtc.datetime((2026,10,5,0,15,3,0,0))
# # setup time / (year, month, day, weekday, hour, minute, second, subseconds)

# while True:
#     print(rtc.datetime()) # read time
#     time.sleep(1)


# # Task 2: OLED - system time on the screen
# from machine import Pin, I2C, RTC
# import ssd1306, time

# rtc = RTC()

# # using default address 0x3C
# i2c = I2C(sda=Pin(22), scl=Pin(20))
# display = ssd1306.SSD1306_I2C(128, 32, i2c) # OLED pixel number -> 128 Columns * 32 rows
# rtc.datetime((2026,10,5,0,15,20,0,0))

# # Print time on OLED
# while True:
#     current_time = rtc.datetime()

#     hour = current_time[4] # 15
#     minute =  current_time[5] # 20
#     second =  current_time[6] # 0

#     Time_text = str(hour) + ":" + str(minute) + ":" + str(second)

#     display.fill(0) # Clear the OLED screen
#     display.text(Time_text, 0, 0, 1) # x coordinate, y coordinate, 1 -> pixels on
#     display.show()

#     print(Time_text)
#     time.sleep(1)

# Task 3, 
# Checkpoint 1: A, B, C buttons to change the time
from machine import Pin, I2C, RTC
import ssd1306, time

button_a = Pin(26, Pin.IN, Pin.PULL_UP) # Pin(pin #(GPIO), mode, pull)
button_b = Pin(25, Pin.IN, Pin.PULL_UP)
button_c = Pin(4, Pin.IN, Pin.PULL_UP)

rtc = RTC()
rtc.datetime((2026,10,5,0,15,20,0,0))

i2c = I2C(sda=Pin(22), scl=Pin(20))
display = ssd1306.SSD1306_I2C(128, 32, i2c)

while True:
    # Button A
    if button_a.value() == 0:
        time.sleep(0.1) # debouncer delay

        if button_a.value() == 0: # confirm the button is still pressed
            current_time = rtc.datetime()
            hour = current_time[4]
            hour = hour + 1

            if hour == 24: # wrap back to 0
                hour = 0

            rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
                       hour, current_time[5], current_time[6], 0)) # update RTC with the new hour

            while button_a.value() == 0:
                pass # wait until the button is released

    # Button B
    if button_b.value() == 0:
        time.sleep(0.1)

        if button_b.value() == 0: # confirm the button is still pressed
            current_time = rtc.datetime()
            minute = current_time[5]
            minute = minute + 1

            if minute == 60: # wrap back to 0
                minute = 0

            rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
                       current_time[4], minute, current_time[6], 0)) # update RTC with the new minute

            while button_b.value() == 0:
                pass

    # Button C
    if button_c.value() == 0:
        time.sleep(0.1)

        if button_c.value() == 0: # confirm the button is still pressed
            current_time = rtc.datetime()
            second = current_time[6]
            second = second + 1

            if second == 60: # wrap back to 0
                second = 0

            rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
                       current_time[4], current_time[5], second, 0)) # update RTC with the new second

            while button_c.value() == 0:
                pass

    # print(rtc.datetime())

    current_time = rtc.datetime()
    hour = current_time[4]
    minute = current_time[5]
    second = current_time[6]
    Time_text = str(hour) + ":" + str(minute) + ":" + str(second)

    display.fill(0) # Clear the OLED screen
    display.text(Time_text, 0, 0, 1) # x coordinate, y coordinate, 1 -> pixels on
    display.show()

    # print(Time_text)
    time.sleep(0.1)

# Task 4, 
# Checkpoint 2: light sensor value + screen brightness from ambient light
# from machine import Pin, I2C, RTC, ADC
# import ssd1306, time

# sensor = ADC(Pin(34)) # light sensor on A4, same as Lab 2
# sensor.atten(ADC.ATTN_11DB)

# rtc = RTC()
# rtc.datetime((2026,10,5,0,15,20,0,0))

# i2c = I2C(sda=Pin(22), scl=Pin(20))
# display = ssd1306.SSD1306_I2C(128, 32, i2c)

# while True:
#     light = sensor.read() # 0 (dark) - 4095 (bright)
#     brightness = (light * 255) // 4095 # scale to the contrast range 0 - 255
#     display.contrast(brightness) # dim room -> dim screen, bright room -> bright screen

#     current_time = rtc.datetime()
#     hour = current_time[4]
#     minute = current_time[5]
#     second = current_time[6]
#     Time_text = str(hour) + ":" + str(minute) + ":" + str(second)

#     display.fill(0)
#     display.text(Time_text, 0, 0, 1)
#     display.text("Light: " + str(light), 0, 12, 1)
#     display.show()

#     # print(light, brightness)
#     time.sleep(0.1)

# # Part 3 Task 1:
# Checkpoint 3: alarm
# A -> alarm hour + 1, B -> alarm minute + 1, C -> alarm ON/OFF (also stops the alarm)
# from machine import Pin, I2C, RTC, PWM
# import ssd1306, time

# button_a = Pin(26, Pin.IN, Pin.PULL_UP)
# button_b = Pin(25, Pin.IN, Pin.PULL_UP)
# button_c = Pin(4, Pin.IN, Pin.PULL_UP)

# piezo = PWM(Pin(27), freq=1000, duty_u16=0) # duty 0 -> silent
# led = Pin(13, Pin.OUT) # red LED on the board
# led.value(0)

# rtc = RTC()
# rtc.datetime((2026,10,5,0,15,20,0,0))

# i2c = I2C(sda=Pin(22), scl=Pin(20))
# display = ssd1306.SSD1306_I2C(128, 32, i2c)

# alarm_hour = 15
# alarm_minute = 21
# alarm_on = True
# alarm_stopped = False # True after the ringing alarm is stopped with button C
# blink = False

# while True:
#     current_time = rtc.datetime()
#     hour = current_time[4]
#     minute = current_time[5]
#     second = current_time[6]

#     alarm_match = alarm_on and hour == alarm_hour and minute == alarm_minute
#     if not alarm_match:
#         alarm_stopped = False # ready for the next time the alarm matches
#     ringing = alarm_match and not alarm_stopped

#     # Button A
#     if button_a.value() == 0:
#         time.sleep(0.1) # debouncer delay

#         if button_a.value() == 0: # confirm the button is still pressed
#             alarm_hour = alarm_hour + 1

#             if alarm_hour == 24: # wrap back to 0
#                 alarm_hour = 0

#             while button_a.value() == 0:
#                 pass # wait until the button is released

#     # Button B
#     if button_b.value() == 0:
#         time.sleep(0.1)

#         if button_b.value() == 0:
#             alarm_minute = alarm_minute + 1

#             if alarm_minute == 60: # wrap back to 0
#                 alarm_minute = 0

#             while button_b.value() == 0:
#                 pass

#     # Button C
#     if button_c.value() == 0:
#         time.sleep(0.1)

#         if button_c.value() == 0:
#             if ringing:
#                 alarm_stopped = True # stop the alarm that is going off
#                 ringing = False
#             else:
#                 alarm_on = not alarm_on

#             while button_c.value() == 0:
#                 pass

#     Time_text = str(hour) + ":" + str(minute) + ":" + str(second)
#     Alarm_text = "Alarm " + str(alarm_hour) + ":" + str(alarm_minute)
#     if alarm_on:
#         Alarm_text = Alarm_text + " ON"
#     else:
#         Alarm_text = Alarm_text + " OFF"

#     display.fill(0)
#     display.text(Time_text, 0, 0, 1)
#     display.text(Alarm_text, 0, 12, 1)

#     if ringing:
#         blink = not blink # flips every loop -> beeping sound + flashing screen
#         display.text("WAKE UP!", 0, 24, 1)
#         display.invert(blink)
#         led.value(blink)
#         if blink:
#             piezo.duty_u16(32768)
#         else:
#             piezo.duty_u16(0)
#     else:
#         display.invert(0)
#         led.value(0)
#         piezo.duty_u16(0)

#     display.show()
#     time.sleep(0.1)


# Part 3 Task 2, Checkpoint 4: time + brightness + alarm in one system
# C -> change mode: CLOCK -> SET TIME -> SET ALARM -> CLOCK
# CLOCK:     A -> alarm ON/OFF
# SET TIME:  A -> hour + 1, B -> minute + 1
# SET ALARM: A -> alarm hour + 1, B -> alarm minute + 1
# Any button stops the alarm while it is going off
# from machine import Pin, I2C, RTC, ADC, PWM
# import ssd1306, time

# button_a = Pin(26, Pin.IN, Pin.PULL_UP) # Pin(pin #(GPIO), mode, pull)
# button_b = Pin(25, Pin.IN, Pin.PULL_UP)
# button_c = Pin(4, Pin.IN, Pin.PULL_UP)

# sensor = ADC(Pin(34)) # light sensor on A2
# sensor.atten(ADC.ATTN_11DB)

# piezo = PWM(Pin(27), freq=1000, duty_u16=0) # duty 0 -> silent
# led = Pin(13, Pin.OUT) # red LED on the board
# led.value(0)

# rtc = RTC()
# rtc.datetime((2026,10,5,0,15,20,0,0))

# i2c = I2C(sda=Pin(22), scl=Pin(20))
# display = ssd1306.SSD1306_I2C(128, 32, i2c)

# mode = 0 # 0 -> CLOCK, 1 -> SET TIME, 2 -> SET ALARM
# alarm_hour = 15
# alarm_minute = 21
# alarm_on = True
# alarm_stopped = False # True after the ringing alarm is stopped with a button
# blink = False

# def pressed(button):
#     if button.value() == 0:
#         time.sleep(0.1) # debouncer delay

#         if button.value() == 0: # confirm the button is still pressed
#             while button.value() == 0:
#                 pass # wait until the button is released
#             return True
#     return False

# while True:
#     current_time = rtc.datetime()
#     hour = current_time[4]
#     minute = current_time[5]
#     second = current_time[6]

#     # Alarm only goes off on the clock screen, not while setting the time / alarm
#     alarm_match = alarm_on and mode == 0 and hour == alarm_hour and minute == alarm_minute
#     if not alarm_match:
#         alarm_stopped = False # ready for the next time the alarm matches
#     ringing = alarm_match and not alarm_stopped

#     a = pressed(button_a)
#     b = pressed(button_b)
#     c = pressed(button_c)

#     if ringing:
#         if a or b or c:
#             alarm_stopped = True # stop the alarm that is going off
#             ringing = False
#     else:
#         # Button C
#         if c:
#             mode = mode + 1
#             if mode == 3: # wrap back to CLOCK
#                 mode = 0

#         # Button A
#         if a:
#             if mode == 0:
#                 alarm_on = not alarm_on
#             elif mode == 1:
#                 hour = hour + 1
#                 if hour == 24: # wrap back to 0
#                     hour = 0
#                 rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
#                            hour, minute, second, 0)) # update RTC with the new hour
#             else:
#                 alarm_hour = alarm_hour + 1
#                 if alarm_hour == 24:
#                     alarm_hour = 0

#         # Button B
#         if b:
#             if mode == 1:
#                 minute = minute + 1
#                 if minute == 60: # wrap back to 0
#                     minute = 0
#                 rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
#                            hour, minute, second, 0)) # update RTC with the new minute
#             elif mode == 2:
#                 alarm_minute = alarm_minute + 1
#                 if alarm_minute == 60:
#                     alarm_minute = 0

#     # Screen brightness from ambient light
#     light = sensor.read() # 0 (dark) - 4095 (bright)
#     brightness = (light * 255) // 4095 # scale to the contrast range 0 - 255
#     display.contrast(brightness) # dim room -> dim screen, bright room -> bright screen

#     Time_text = str(hour) + ":" + str(minute) + ":" + str(second)
#     Alarm_text = "Alarm " + str(alarm_hour) + ":" + str(alarm_minute)
#     if alarm_on:
#         Alarm_text = Alarm_text + " ON"
#     else:
#         Alarm_text = Alarm_text + " OFF"

#     display.fill(0) # Clear the OLED screen
#     display.text(Time_text, 0, 0, 1) # x coordinate, y coordinate, 1 -> pixels on
#     display.text(Alarm_text, 0, 12, 1)

#     if ringing:
#         blink = not blink # flips every loop -> beeping sound + flashing screen
#         display.text("WAKE UP!", 0, 24, 1)
#         display.invert(blink)
#         led.value(blink)
#         if blink:
#             piezo.duty_u16(32768)
#         else:
#             piezo.duty_u16(0)
#     else:
#         display.invert(0)
#         led.value(0)
#         piezo.duty_u16(0)

#         if mode == 0:
#             display.text("Light: " + str(light), 0, 24, 1)
#         elif mode == 1:
#             display.text("SET TIME", 0, 24, 1)
#         else:
#             display.text("SET ALARM", 0, 24, 1)

#     display.show()

#     # print(Time_text, light, brightness)
#     time.sleep(0.1)
