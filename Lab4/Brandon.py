from machine import Pin, SPI, I2C, RTC, ADC, PWM
import time, ssd1306
# === SPI Setup ===
# Try the common HSPI pins on Feather Huzzah ESP32
spi = SPI(
    1, baudrate=5000000, polarity=1, phase=1, sck=Pin(5), mosi=Pin(19), miso=Pin(21)
)
cs = Pin(15, Pin.OUT)
cs.value(1)  # Deselect device by default

# SPI Commands
SPI_READ = 1 << 7
SPI_SINGLE_BYTE = 0 << 6


# === Test Device ID ===
def read_device_id():
    cs.value(0)
    spi.write(bytearray([SPI_READ | SPI_SINGLE_BYTE | 0x00]))  # DEVID register = 0x00
    buf = bytearray(1)
    spi.readinto(buf)
    cs.value(1)
    return buf[0]


# Main
device_id = read_device_id()
print(f"[TEST] Device ID read: 0x{device_id:02X}")

if device_id == 0xE5:
    print("[TEST] ADXL345 detected successfully!")
else:
    print("[TEST] ADXL345 not detected. Check wiring and SPI pins!")
import struct

SPI_MULTI_BYTE = 1 << 6
POWER_CTL = 0x2D
DATA_FORMAT = 0x31
DATAX0 = 0x32

def write_reg(reg, val):
    cs.value(0)
    spi.write(bytearray([reg, val]))  # bit 7 = 0 means write
    cs.value(1)

def read_accel():
    buf = bytearray(6)
    cs.value(0)
    spi.write(bytearray([SPI_READ | SPI_MULTI_BYTE | DATAX0]))
    spi.readinto(buf)
    cs.value(1)
    return struct.unpack("<hhh", buf)  # x, y, z as signed 16-bit, little-endian

write_reg(DATA_FORMAT, 0x00)  # +/-2g range, 4-wire SPI
write_reg(POWER_CTL, 0x08)    # set Measure bit -- chip starts in standby

# while True:
#     x, y, z = read_accel()
#     print("x={:.2f}g y={:.2f}g z={:.2f}g".format(x * 0.0039, y * 0.0039, z * 0.0039))
#     time.sleep(0.1)

# Part 3 Task 2, Checkpoint 4: time + brightness + alarm in one system
# C -> change mode: CLOCK -> SET TIME -> SET ALARM -> CLOCK
# CLOCK:     A -> alarm ON/OFF
# SET TIME:  A -> hour + 1, B -> minute + 1
# SET ALARM: A -> alarm hour + 1, B -> alarm minute + 1
# Any button stops the alarm while it is going off

button_a = Pin(26, Pin.IN, Pin.PULL_UP) # Pin(pin #(GPIO), mode, pull)
button_b = Pin(25, Pin.IN, Pin.PULL_UP)
button_c = Pin(4, Pin.IN, Pin.PULL_UP)

sensor = ADC(Pin(34)) # light sensor on A2
sensor.atten(ADC.ATTN_11DB)

piezo = PWM(Pin(27), freq=1000, duty_u16=0) # duty 0 -> silent
led = Pin(13, Pin.OUT) # red LED on the board
led.value(0)

rtc = RTC()
rtc.datetime((2026,10,5,0,15,20,0,0))

i2c = I2C(sda=Pin(22), scl=Pin(20))
display = ssd1306.SSD1306_I2C(128, 32, i2c)

mode = 0 # 0 -> CLOCK, 1 -> SET TIME, 2 -> SET ALARM
alarm_hour = 15
alarm_minute = 21
alarm_on = True
alarm_stopped = False # True after the ringing alarm is stopped with a button
blink = False
text_x = 0
text_y = 0

def pressed(button):
    if button.value() == 0:
        time.sleep(0.1) # debouncer delay

        if button.value() == 0: # confirm the button is still pressed
            while button.value() == 0:
                pass # wait until the button is released
            return True
    return False
HamletMonologue = (
    "To be, or not to be, that is the question:\n"
    "Whether 'tis nobler in the mind to suffer\n"
    "The slings and arrows of outrageous fortune,\n"
    "Or to take arms against a sea of troubles\n"
    "And by opposing end them. To die—to sleep,\n"
    "No more; and by a sleep to say we end\n"
    "The heart-ache and the thousand natural shocks\n"
    "That flesh is heir to: 'tis a consummation\n"
    "Devoutly to be wish'd. To die, to sleep;\n"
    "To sleep, perchance to dream—ay, there's the rub:\n"
    "For in that sleep of death what dreams may come,\n"
    "When we have shuffled off this mortal coil,\n"
    "Must give us pause—there's the respect\n"
    "That makes calamity of so long life.\n"
    "For who would bear the whips and scorns of time,\n"
    "Th'oppressor's wrong, the proud man's contumely,\n"
    "The pangs of dispriz'd love, the law's delay,\n"
    "The insolence of office, and the spurns\n"
    "That patient merit of th'unworthy takes,\n"
    "When he himself might his quietus make\n"
    "With a bare bodkin? Who would fardels bear,\n"
    "To grunt and sweat under a weary life,\n"
    "But that the dread of something after death,\n"
    "The undiscovere'd country, from whose bourn\n"
    "No traveller returns, puzzles the will,\n"
    "And makes us rather bear those ills we have\n"
    "Than fly to others that we know not of?\n"
    "Thus conscience doth make cowards of us all,\n"
    "And thus the native hue of resolution\n"
    "Is sicklied o'er with the pale cast of thought,\n"
    "And enterprises of great pith and moment\n"
    "With this regard their currents turn awry\n"
    "And lose the name of action."
)
while True:
    x, y, z = read_accel()

    # Lab 3 - clock and alarm
    current_time = rtc.datetime()
    hour = current_time[4]
    minute = current_time[5]
    second = current_time[6]

    # Alarm only goes off on the clock screen, not while setting the time / alarm
    alarm_match = alarm_on and mode == 0 and hour == alarm_hour and minute == alarm_minute
    if not alarm_match:
        alarm_stopped = False # ready for the next time the alarm matches
    ringing = alarm_match and not alarm_stopped

    a = pressed(button_a)
    b = pressed(button_b)
    c = pressed(button_c)

    if ringing:
        if a or b or c:
            alarm_stopped = True # stop the alarm that is going off
            ringing = False
    else:
        # Button C
        if c:
            mode = mode + 1
            if mode == 3: # wrap back to CLOCK
                mode = 0

        # Button A
        if a:
            if mode == 0:
                alarm_on = not alarm_on
            elif mode == 1:
                hour = hour + 1
                if hour == 24: # wrap back to 0
                    hour = 0
                rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
                           hour, minute, second, 0)) # update RTC with the new hour
            else:
                alarm_hour = alarm_hour + 1
                if alarm_hour == 24:
                    alarm_hour = 0

        # Button B
        if b:
            if mode == 1:
                minute = minute + 1
                if minute == 60: # wrap back to 0
                    minute = 0
                rtc.datetime((current_time[0], current_time[1], current_time[2], current_time[3],
                           hour, minute, second, 0)) # update RTC with the new minute
            elif mode == 2:
                alarm_minute = alarm_minute + 1
                if alarm_minute == 60:
                    alarm_minute = 0

    # Screen brightness from ambient light
    light = sensor.read() # 0 (dark) - 4095 (bright)
    brightness = (light * 255) // 4095 # scale to the contrast range 0 - 255
    display.contrast(brightness) # dim room -> dim screen, bright room -> bright screen

    Time_text = str(hour) + ":" + str(minute) + ":" + str(second)
    Alarm_text = "Alarm " + str(alarm_hour) + ":" + str(alarm_minute)
    if alarm_on:
        Alarm_text = Alarm_text + " ON"
    else:
        Alarm_text = Alarm_text + " OFF"

    display.fill(0) # Clear the OLED screen
    display.text(Time_text, -x, y, z+1) # x coordinate, y coordinate, 1 -> pixels on
    display.text(Alarm_text, -x, y+12, z+1)

    if ringing:
        blink = not blink # flips every loop -> beeping sound + flashing screen
        display.text("WAKE UP!", -x, y+24, z+1)
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

        if mode == 0:
            display.text("Light: " + str(light), -x, y+24, z+1)
        elif mode == 1:
            display.text("SET TIME", -x, y+24, z+1)
        else:
            display.text("SET ALARM", -x, y+24, z+1)

    display.show()

    # print(Time_text, light, brightness)
    time.sleep(0.1)