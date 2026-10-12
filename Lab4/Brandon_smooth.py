"""Lab 4 Checkpoint 1: the Lab 3 page with continuous, seamless tilt scrolling.

The layout is the same as Brandon.py: clock at y=0, alarm at y=12,
and light/mode/alarm status at y=24. Upload this file separately from
Brandon.py so the original remains available for comparison.
"""

from machine import Pin, SPI, I2C, RTC, ADC, PWM
import struct
import time
import ssd1306


FRAME_MS = 33                 # Target approximately 30 frames/second.
LOG_MS = 200                  # Serial output approximately 5 times/second.
DEBOUNCE_MS = 30
ALARM_BLINK_MS = 100          # Preserve the original alarm blink/beep cadence.
COUNTS_PER_G = 256.0          # DATA_FORMAT=0x00: fixed 10-bit, +/-2g.
DEAD_ZONE_G = 0.20
MAX_SPEED_PX_S = 36.0
TILT_FILTER_SECONDS = 0.08
BRIGHTNESS_FILTER_SECONDS = 0.20
X_DIRECTION = -1              # Preserve the original -x direction.
Y_DIRECTION = 1               # Preserve the original +y direction.
DEBUG = True

SPI_READ = 0x80
SPI_MULTI_BYTE = 0x40
DATA_FORMAT = 0x31
POWER_CTL = 0x2D
DATAX0 = 0x32
MODE_NAMES = ("CLOCK", "SET TIME", "SET ALARM")


class DebouncedButton:
    """Return one event on release, without waiting for a held button."""

    def __init__(self, pin, now):
        self.pin = pin
        self.raw = pin.value()
        self.stable = self.raw
        self.changed_at = now

    def released(self, now):
        raw = self.pin.value()
        if raw != self.raw:
            self.raw = raw
            self.changed_at = now
        if raw != self.stable and time.ticks_diff(now, self.changed_at) >= DEBOUNCE_MS:
            self.stable = raw
            return raw == 1
        return False


def axis_speed(acceleration_g):
    """Map tilt to pixels/second, with a dead zone and a bounded speed."""
    magnitude = abs(acceleration_g)
    if magnitude <= DEAD_ZONE_G:
        return 0.0
    fraction = min((magnitude - DEAD_ZONE_G) / (1.0 - DEAD_ZONE_G), 1.0)
    speed = fraction * MAX_SPEED_PX_S
    return speed if acceleration_g > 0 else -speed


def draw_screen(display, time_text, alarm_text, status_text, offset_x, offset_y):
    """Draw one copy of the original three-line, 128x32 page."""
    display.text(time_text, offset_x, offset_y, 1)
    display.text(alarm_text, offset_x, offset_y + 12, 1)
    display.text(status_text, offset_x, offset_y + 24, 1)


def draw_wrapped_screen(display, time_text, alarm_text, status_text, text_x, text_y):
    """Draw four neighboring copies, then send exactly one OLED frame."""
    width = display.width
    height = display.height
    origin_x = int(text_x % width)
    origin_y = int(text_y % height)
    display.fill(0)
    for offset_x in (origin_x, origin_x - width):
        for offset_y in (origin_y, origin_y - height):
            draw_screen(display, time_text, alarm_text, status_text, offset_x, offset_y)
    display.show()


def main():
    # Keep the wiring that was verified on COM7. Select is idle-high before SPI starts.
    cs = Pin(15, Pin.OUT, value=1)
    spi = SPI(1, baudrate=5000000, polarity=1, phase=1,
              sck=Pin(5), mosi=Pin(19), miso=Pin(21))
    piezo = None
    led = None
    display = None
    accel_buffer = bytearray(6)
    accel_command = bytes((SPI_READ | SPI_MULTI_BYTE | DATAX0,))

    def read_reg(reg):
        buf = bytearray(1)
        cs.value(0)
        try:
            spi.write(bytes((SPI_READ | reg,)))
            spi.readinto(buf)
        finally:
            cs.value(1)
        return buf[0]

    def write_reg(reg, value):
        cs.value(0)
        try:
            spi.write(bytes((reg, value)))
        finally:
            cs.value(1)

    def read_accel():
        cs.value(0)
        try:
            spi.write(accel_command)
            spi.readinto(accel_buffer)
        finally:
            cs.value(1)
        return struct.unpack("<hhh", accel_buffer)

    try:
        device_id = read_reg(0x00)
        print("[TEST] Device ID read: 0x%02X" % device_id)
        if device_id != 0xE5:
            raise RuntimeError("ADXL345 not detected; check the SPI wiring.")
        print("[TEST] ADXL345 detected successfully!")

        write_reg(POWER_CTL, 0x00)      # Standby while configuring.
        write_reg(DATA_FORMAT, 0x00)   # Four-wire SPI, +/-2g, fixed 10-bit.
        write_reg(0x2C, 0x0A)          # BW_RATE: normal power, 100 Hz samples.
        write_reg(0x2E, 0x00)          # INT_ENABLE: polling, no interrupt outputs.
        write_reg(0x38, 0x00)          # FIFO_CTL: bypass FIFO.
        write_reg(POWER_CTL, 0x08)     # Start measurement.
        time.sleep_ms(20)

        now = time.ticks_ms()
        button_a = DebouncedButton(Pin(26, Pin.IN, Pin.PULL_UP), now)
        button_b = DebouncedButton(Pin(25, Pin.IN, Pin.PULL_UP), now)
        button_c = DebouncedButton(Pin(4, Pin.IN, Pin.PULL_UP), now)
        sensor = ADC(Pin(34))
        sensor.atten(ADC.ATTN_11DB)
        piezo = PWM(Pin(27), freq=1000, duty_u16=0)
        led = Pin(13, Pin.OUT, value=0)
        rtc = RTC()
        # Preserve Brandon.py's demonstration start time and alarm.
        rtc.datetime((2026, 10, 5, 0, 15, 20, 0, 0))
        i2c = I2C(sda=Pin(22), scl=Pin(20))
        display = ssd1306.SSD1306_I2C(128, 32, i2c)

        mode = 0
        alarm_hour = 15
        alarm_minute = 21
        alarm_on = True
        alarm_stopped = False
        blink = False
        was_ringing = False
        last_blink = time.ticks_ms()
        text_x = 0.0
        text_y = 0.0
        raw_x, raw_y, raw_z = read_accel()
        filtered_x = raw_x / COUNTS_PER_G
        filtered_y = raw_y / COUNTS_PER_G
        filtered_brightness = (sensor.read() * 255) / 4095
        previous_contrast = -1
        last_frame = time.ticks_ms()
        last_log = last_frame
        frames_since_log = 0

        print("[SCROLL] Tilt X/Y to scroll; flat X/Y near 0g stops movement.")
        print("[SCROLL] Four-copy wrap, target ~30 FPS, serial log ~5 Hz.")

        while True:
            frame_start = time.ticks_ms()
            dt = max(0.0, min(time.ticks_diff(frame_start, last_frame) / 1000.0, 0.10))
            last_frame = frame_start
            raw_x, raw_y, raw_z = read_accel()
            alpha = dt / (TILT_FILTER_SECONDS + dt)
            filtered_x += alpha * (raw_x / COUNTS_PER_G - filtered_x)
            filtered_y += alpha * (raw_y / COUNTS_PER_G - filtered_y)
            speed_x = X_DIRECTION * axis_speed(filtered_x)
            speed_y = Y_DIRECTION * axis_speed(filtered_y)
            text_x = (text_x + speed_x * dt) % display.width
            text_y = (text_y + speed_y * dt) % display.height

            current_time = rtc.datetime()
            hour, minute, second = current_time[4:7]
            alarm_match = alarm_on and mode == 0 and hour == alarm_hour and minute == alarm_minute
            if not alarm_match:
                alarm_stopped = False
            ringing = alarm_match and not alarm_stopped
            a = button_a.released(frame_start)
            b = button_b.released(frame_start)
            c = button_c.released(frame_start)

            if ringing:
                if a or b or c:
                    alarm_stopped = True
                    ringing = False
            else:
                if c:
                    mode = (mode + 1) % 3
                if a:
                    if mode == 0:
                        alarm_on = not alarm_on
                    elif mode == 1:
                        hour = (hour + 1) % 24
                        rtc.datetime((current_time[0], current_time[1], current_time[2],
                                      current_time[3], hour, minute, second, 0))
                    else:
                        alarm_hour = (alarm_hour + 1) % 24
                if b:
                    if mode == 1:
                        minute = (minute + 1) % 60
                        rtc.datetime((current_time[0], current_time[1], current_time[2],
                                      current_time[3], hour, minute, second, 0))
                    elif mode == 2:
                        alarm_minute = (alarm_minute + 1) % 60

            light = sensor.read()
            brightness_alpha = dt / (BRIGHTNESS_FILTER_SECONDS + dt)
            target_brightness = (light * 255) / 4095
            filtered_brightness += brightness_alpha * (target_brightness - filtered_brightness)
            contrast = max(0, min(255, int(filtered_brightness)))
            if contrast != previous_contrast:
                display.contrast(contrast)
                previous_contrast = contrast

            time_text = "%02d:%02d:%02d" % (hour, minute, second)
            alarm_text = "Alarm %02d:%02d %s" % (alarm_hour, alarm_minute, "ON" if alarm_on else "OFF")
            if ringing:
                if not was_ringing:
                    blink = True
                    last_blink = frame_start
                elif time.ticks_diff(frame_start, last_blink) >= ALARM_BLINK_MS:
                    blink = not blink
                    last_blink = frame_start
                display.invert(blink)
                led.value(blink)
                piezo.duty_u16(32768 if blink else 0)
                status_text = "WAKE UP!"
            else:
                blink = False
                display.invert(0)
                led.value(0)
                piezo.duty_u16(0)
                status_text = "Light: %d" % light if mode == 0 else MODE_NAMES[mode]
            was_ringing = ringing

            draw_wrapped_screen(display, time_text, alarm_text, status_text, text_x, text_y)
            frames_since_log += 1
            log_elapsed = time.ticks_diff(frame_start, last_log)
            if DEBUG and log_elapsed >= LOG_MS:
                fps = frames_since_log * 1000.0 / log_elapsed
                print("raw=(%d,%d,%d) g=(%.2f,%.2f,%.2f) pos=(%.1f,%.1f) v=(%.1f,%.1f) fps=%.1f" %
                      (raw_x, raw_y, raw_z, raw_x / COUNTS_PER_G, raw_y / COUNTS_PER_G,
                       raw_z / COUNTS_PER_G, text_x, text_y, speed_x, speed_y, fps))
                last_log = frame_start
                frames_since_log = 0

            remaining = FRAME_MS - time.ticks_diff(time.ticks_ms(), frame_start)
            if remaining > 0:
                time.sleep_ms(remaining)
    except KeyboardInterrupt:
        print("[SCROLL] Stopped.")
    finally:
        cs.value(1)
        if piezo is not None:
            piezo.duty_u16(0)
        if led is not None:
            led.value(0)
        if display is not None:
            display.invert(0)
        spi.deinit()


if __name__ == "__main__":
    main()
