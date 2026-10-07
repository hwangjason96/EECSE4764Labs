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