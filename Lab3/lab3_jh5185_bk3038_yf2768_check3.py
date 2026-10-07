# Checkpoint 3: alarm
# A -> alarm hour + 1, B -> alarm minute + 1, C -> alarm ON/OFF (also stops the alarm)
from machine import Pin, I2C, RTC, PWM
import ssd1306, time

button_a = Pin(26, Pin.IN, Pin.PULL_UP)
button_b = Pin(25, Pin.IN, Pin.PULL_UP)
button_c = Pin(4, Pin.IN, Pin.PULL_UP)

piezo = PWM(Pin(27), freq=1000, duty_u16=0) # duty 0 -> silent
led = Pin(13, Pin.OUT) # red LED on the board
led.value(0)

rtc = RTC()
rtc.datetime((2026,10,5,0,15,20,0,0))

i2c = I2C(sda=Pin(22), scl=Pin(20))
display = ssd1306.SSD1306_I2C(128, 32, i2c)

alarm_hour = 15
alarm_minute = 21
alarm_on = True
alarm_stopped = False # True after the ringing alarm is stopped with button C
blink = False

while True:
    current_time = rtc.datetime()
    hour = current_time[4]
    minute = current_time[5]
    second = current_time[6]

    alarm_match = alarm_on and hour == alarm_hour and minute == alarm_minute
    if not alarm_match:
        alarm_stopped = False # ready for the next time the alarm matches
    ringing = alarm_match and not alarm_stopped

    # Button A
    if button_a.value() == 0:
        time.sleep(0.1) # debouncer delay

        if button_a.value() == 0: # confirm the button is still pressed
            alarm_hour = alarm_hour + 1

            if alarm_hour == 24: # wrap back to 0
                alarm_hour = 0

            while button_a.value() == 0:
                pass # wait until the button is released

    # Button B
    if button_b.value() == 0:
        time.sleep(0.1)

        if button_b.value() == 0:
            alarm_minute = alarm_minute + 1

            if alarm_minute == 60: # wrap back to 0
                alarm_minute = 0

            while button_b.value() == 0:
                pass

    # Button C
    if button_c.value() == 0:
        time.sleep(0.1)

        if button_c.value() == 0:
            if ringing:
                alarm_stopped = True # stop the alarm that is going off
                ringing = False
            else:
                alarm_on = not alarm_on

            while button_c.value() == 0:
                pass

    Time_text = str(hour) + ":" + str(minute) + ":" + str(second)
    Alarm_text = "Alarm " + str(alarm_hour) + ":" + str(alarm_minute)
    if alarm_on:
        Alarm_text = Alarm_text + " ON"
    else:
        Alarm_text = Alarm_text + " OFF"

    display.fill(0)
    display.text(Time_text, 0, 0, 1)
    display.text(Alarm_text, 0, 12, 1)

    if ringing:
        blink = not blink # flips every loop -> beeping sound + flashing screen
        display.text("WAKE UP!", 0, 24, 1)
        display.invert(blink)
        led.value(blink)
        if blink:
            piezo.duty_u16(32768)
        else:
            piezo.duty_u16(0)
    else:
        display.invert(0)
        led.value(0)
        piezo.duty_u16(0)

    display.show()
    time.sleep(0.1)