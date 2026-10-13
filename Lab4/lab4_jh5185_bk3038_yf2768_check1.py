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
    # TILT -> SPEED MAP (one axis)
    #
    #   a = tilt reading in g (0 = flat, +/-1 = that axis points straight down)
    #   D = DEAD_ZONE_G    = 0.20 g
    #   V = MAX_SPEED_PX_S = 36 px/s
    #
    #                |a| - D
    #   fraction = -----------      clamped to at most 1
    #                1.0 - D
    #
    #   speed = sign(a) * fraction * V        (and speed = 0 if |a| <= D)
    #
    #   speed (px/s)
    #     +36 |                  ________
    #         |                 /
    #       0 |_______-0.2_____/
    #         |      /     +0.2      +1.0    a (g)
    #         |     /
    #     -36 |____/
    #
    # Subtracting D (instead of just cutting off below it) makes the speed
    # start from 0 at the edge of the dead zone, so there is no sudden jump.
    # Dividing by (1 - D) rescales the remaining 0.2..1.0 g range to 0..1.
    #
    # Example: a = -0.60 g
    #   fraction = (0.60 - 0.20) / (1.00 - 0.20) = 0.40 / 0.80 = 0.5
    #   speed    = -(0.5 * 36) = -18 px/s
    magnitude = abs(acceleration_g)
    if magnitude <= DEAD_ZONE_G:
        return 0.0
    fraction = min((magnitude - DEAD_ZONE_G) / (1.0 - DEAD_ZONE_G), 1.0)
    speed = fraction * MAX_SPEED_PX_S
    return speed if acceleration_g > 0 else -speed


def draw_screen(display, time_text, alarm_text, status_text, offset_x, offset_y):
    """Draw one copy of the original three-line, 128x32 page."""
    # (offset_x, offset_y) is the top-left corner of the page. The font is
    # 8 px tall, so rows at +0, +12, +24 fill y = 0..31 with 4 px gaps.
    # Offsets may be negative: pixels that land off-screen are just clipped.
    display.text(time_text, offset_x, offset_y, 1)
    display.text(alarm_text, offset_x, offset_y + 12, 1)
    display.text(status_text, offset_x, offset_y + 24, 1)


def draw_wrapped_screen(display, time_text, alarm_text, status_text, text_x, text_y):
    """Draw four neighboring copies, then send exactly one OLED frame."""
    # WRAP-AROUND DISPLAY MATH
    #
    #   W = 128, H = 32   (screen size == page size)
    #
    #   ox = int(text_x mod W)      -> always 0..127
    #   oy = int(text_y mod H)      -> always 0..31
    #
    # The page is drawn with its top-left corner at (ox, oy). Because the
    # page is exactly as big as the screen, shifting it right by ox pushes
    # its last ox columns off the right edge. Those columns have to come
    # back in on the left, which is the same page drawn one screen-width
    # earlier, at ox - W. Same idea vertically with oy - H.
    #
    # So the page is drawn at all four combinations:
    #
    #        (ox - W, oy - H) | (ox, oy - H)
    #        -----------------+----------------
    #        (ox - W, oy)     | (ox, oy)
    #
    #   x: ox-W            0       ox            W
    #      |---- copy B ---|-------|             |
    #                      |       |--- copy A --|------- (clipped)
    #                      [====== screen =======]
    #
    #   copy A (at ox)     shows its first W - ox columns on screen x = ox..W-1
    #   copy B (at ox - W) shows its last  ox     columns on screen x = 0..ox-1
    #   (W - ox) + ox = W  -> every screen column is covered exactly once.
    #
    # Example: text_x = 100 -> ox = 100
    #   copy A at x = 100  : page columns 0..27   on screen columns 100..127
    #   copy B at x = -28  : page columns 28..127 on screen columns 0..99
    #
    # Everything is drawn into the framebuffer first and show() is called
    # once, so the OLED never displays a half-drawn frame.
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
    # ADXL345 SPI command byte: bit 7 = read, bit 6 = multi-byte, bits 5..0 = register.
    #   0x80 | 0x40 | 0x32 = 0xF2  -> "read several bytes starting at DATAX0"
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
        # The 6 bytes are X0,X1,Y0,Y1,Z0,Z1 (low byte first for each axis).
        # "<hhh" = little-endian, three signed 16-bit ints:
        #   value = low_byte + 256 * high_byte   (as two's complement)
        # To convert to g: g = counts / COUNTS_PER_G = counts / 256
        #   (+/-2g, 10-bit mode is ~3.9 mg per count, and 1 / 0.0039 = 256)
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
        # Seed the filters with a real first reading so they do not have to
        # ramp up from 0 when the loop starts.
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
            # ---- 1. Time step -------------------------------------------------
            # dt = seconds since the previous frame (ms / 1000), clamped to
            # 0..0.10 s. Normally dt is about 0.033 s. The upper clamp stops
            # the text from teleporting if one frame takes unusually long.
            frame_start = time.ticks_ms()
            dt = max(0.0, min(time.ticks_diff(frame_start, last_frame) / 1000.0, 0.10))
            last_frame = frame_start

            # ---- 2. Smooth the tilt reading ----------------------------------
            # LOW-PASS FILTER (exponential moving average)
            #
            #   x   = new raw sample in g  (raw counts / 256)
            #   y   = filtered value
            #   tau = TILT_FILTER_SECONDS = 0.08 s   (filter time constant)
            #
            #              dt
            #   alpha = --------            (0 < alpha < 1)
            #           tau + dt
            #
            #   y_new = y_old + alpha * (x - y_old)
            #         = (1 - alpha) * y_old + alpha * x
            #
            # Each frame the filtered value moves a fraction alpha of the way
            # toward the new sample. Small alpha = smoother but laggier.
            # Computing alpha from dt keeps the smoothing the same in real
            # time even when the frame rate changes.
            #
            # Example at 30 FPS: alpha = 0.033 / (0.08 + 0.033) = 0.29
            #   y_old = 0.00 g, x = 0.50 g -> y_new = 0 + 0.29 * 0.50 = 0.146 g
            raw_x, raw_y, raw_z = read_accel()
            alpha = dt / (TILT_FILTER_SECONDS + dt)
            filtered_x += alpha * (raw_x / COUNTS_PER_G - filtered_x)
            filtered_y += alpha * (raw_y / COUNTS_PER_G - filtered_y)

            # ---- 3. Tilt -> speed -> position --------------------------------
            # See axis_speed() for the tilt -> px/s map. X_DIRECTION and
            # Y_DIRECTION are +/-1 and only flip which way the text moves.
            #
            # POSITION UPDATE (distance = speed * time, then wrap)
            #
            #   text_x = (text_x + speed_x * dt) mod 128
            #   text_y = (text_y + speed_y * dt) mod 32
            #
            # Example at full tilt: 36 px/s * 0.033 s = 1.19 px per frame.
            # The position is kept as a float so those fractions of a pixel
            # add up over frames instead of being rounded away.
            #
            # The mod keeps the position inside one screen. Python's % always
            # returns a non-negative result for a positive divisor, so moving
            # left past 0 wraps correctly:  (-1.5) % 128 = 126.5
            speed_x = X_DIRECTION * axis_speed(filtered_x)
            speed_y = Y_DIRECTION * axis_speed(filtered_y)
            text_x = (text_x + speed_x * dt) % display.width
            text_y = (text_y + speed_y * dt) % display.height

            # ---- 4. Clock, alarm, and buttons --------------------------------
            # The alarm rings while the clock's hour:minute equals the alarm's,
            # until a button is pressed. alarm_stopped resets once the minute
            # no longer matches, so the alarm can ring again the next day.

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
                # The % makes each counter roll over: mode 2 -> 0,
                # hour 23 -> 0, minute 59 -> 0.
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

            # ---- 5. Light sensor -> OLED brightness ---------------------------
            # Rescale the 12-bit ADC reading (0..4095) to contrast (0..255):
            #
            #   target = light * 255 / 4095
            #
            # Then the same low-pass filter as the tilt, with tau = 0.20 s:
            #
            #   alpha = dt / (0.20 + dt)        (about 0.14 at 30 FPS)
            #   b_new = b_old + alpha * (target - b_old)
            #
            # The larger tau makes brightness change more slowly than tilt, so
            # the screen fades instead of flickering. The max/min clamps the
            # result to the 0..255 range the display accepts, and the contrast
            # command is only sent over I2C when the integer value changes.
            light = sensor.read()
            brightness_alpha = dt / (BRIGHTNESS_FILTER_SECONDS + dt)
            target_brightness = (light * 255) / 4095
            filtered_brightness += brightness_alpha * (target_brightness - filtered_brightness)
            contrast = max(0, min(255, int(filtered_brightness)))
            if contrast != previous_contrast:
                display.contrast(contrast)
                previous_contrast = contrast

            # ---- 6. Build the text and drive the alarm outputs ----------------
            # While ringing, blink flips every ALARM_BLINK_MS (100 ms), which
            # is a 200 ms full cycle = 5 Hz. The screen invert, LED, and piezo
            # all follow it. duty_u16 = 32768 out of 65535 is a 50% duty cycle.
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

            # ---- 7. Draw, log, and pace the frame -----------------------------
            # fps = frames drawn / elapsed seconds
            #     = frames_since_log * 1000 / log_elapsed_ms
            #   e.g. 6 frames in 200 ms -> 6 * 1000 / 200 = 30 FPS
            #
            # Frame pacing: sleep for whatever is left of the 33 ms budget.
            #   remaining = FRAME_MS - (time spent on this frame)
            #   1000 ms / 33 ms = about 30 frames per second
            # If the frame already took longer than 33 ms, there is no sleep.
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
