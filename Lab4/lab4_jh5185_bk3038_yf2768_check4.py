from machine import Pin, SPI, I2C
import gc
import network
import struct
import time
import ssd1306
import urequests  # on newer MicroPython builds: `import requests as urequests`

NTFY_URL = "https://ntfy.sh/AIoTCUG36"  # the topic name is the last part of the URL
WIFI_TIMEOUT_MS = 30000
GEO_URL = (
    "http://ip-api.com/json/"
    "?fields=status,message,lat,lon,city,regionName,country,query,offset"
)
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
HTTP_TIMEOUT_S = 15
HTTP_ATTEMPTS = 3
TEXT_SPEED_PX_S = 16
SENT_HOLD_MS = 3000           # How long the "Sent..." confirmation stays up.
NTP_HOSTS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")
NTP_TIMEOUT_S = 10

FRAME_MS = 33                 # Target approximately 30 frames/second.
COUNTS_PER_G = 256.0          # DATA_FORMAT=0x00: fixed 10-bit, +/-2g.
DEAD_ZONE_G = 0.20
MAX_SPEED_PX_S = 36.0
TILT_FILTER_SECONDS = 0.08
X_DIRECTION = -1              # Preserve the original -x direction.
Y_DIRECTION = 1               # Preserve the original +y direction.
SCROLL_GAP_PX = 32            # Blank space between the end of the text and its repeat.

SPI_READ = 0x80
SPI_MULTI_BYTE = 0x40
DATA_FORMAT = 0x31
POWER_CTL = 0x2D
DATAX0 = 0x32

WEATHER_API = "0f0eaf4f4b16ae04541f3fb99a4f6725"

# ----------------------------- WiFi connection -----------------------------

def visible_networks(scan):
    """Keep the strongest access point for each visible SSID, in signal order."""
    result = []
    seen = set()
    for access_point in sorted(scan, key=lambda item: item[3], reverse=True):
        ssid = access_point[0]
        if ssid and ssid not in seen:
            seen.add(ssid)
            result.append(access_point)
    return result


def wait_for_wifi(wlan):
    """Wait for DHCP; a reported failure can belong to a previous attempt."""
    failure_states = (
        (network.STAT_WRONG_PASSWORD, "Wrong Wi-Fi password"),
        (network.STAT_NO_AP_FOUND, "Wi-Fi access point not found"),
        (network.STAT_CONNECT_FAIL, "Wi-Fi connection failed"),
    )
    started = time.ticks_ms()
    previous_status = None
    try:
        while not wlan.isconnected():
            status = wlan.status()
            if status != previous_status:
                print("[WIFI] Status:", status)
                previous_status = status
            # ESP32 v1.26 retains the last disconnect reason while a new connection
            # or automatic retry is running. Keep waiting for the bounded window.
            if time.ticks_diff(time.ticks_ms(), started) >= WIFI_TIMEOUT_MS:
                reason = "check SSID, password and hotspot compatibility"
                for code, message in failure_states:
                    if status == code:
                        reason = message
                        break
                if status in (210, 211):
                    reason = "access point security is incompatible with this connection"
                raise RuntimeError("Wi-Fi timeout (status=%s): %s" % (status, reason))
            time.sleep_ms(200)
    except BaseException:
        # Also cancel the driver's automatic retries when the user presses Ctrl+C.
        try:
            wlan.disconnect()
        except OSError:
            pass
        raise


def connect_wifi():
    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)
    if wlan.isconnected():
        print("[WIFI] Already connected. Local IP:", wlan.ifconfig()[0])
        return wlan

    # A soft reboot does not necessarily restart the ESP32 Wi-Fi driver.
    # Cancel any previous request before restarting the station and scanning.
    try:
        wlan.disconnect()
    except OSError:
        pass
    wlan.active(False)
    time.sleep_ms(250)
    wlan.active(True)
    time.sleep_ms(250)

    print("[WIFI] Scanning...")
    networks = visible_networks(wlan.scan())
    print("0: Type an SSID manually")
    for number, access_point in enumerate(networks, 1):
        print("%d: %s  RSSI=%d  security=%d" %
              (number, access_point[0].decode("utf-8", "replace"),
               access_point[3], access_point[4]))

    while True:
        try:
            choice = int(input("Choose WiFi number: "))
            if 0 <= choice <= len(networks):
                break
        except ValueError:
            pass
        print("Enter a number between 0 and %d." % len(networks))

    if choice == 0:
        ssid = input("WiFi SSID: ")
        password = input("WiFi password (Enter for open network): ")
    else:
        access_point = networks[choice - 1]
        ssid = access_point[0]
        password = "" if access_point[4] == 0 else input("WiFi password: ")
    if not ssid:
        raise RuntimeError("Wi-Fi SSID cannot be empty")

    # Permit retries during our 30-second window; wait_for_wifi disconnects on
    # timeout so a failed hotspot connection will not retry indefinitely.
    try:
        wlan.config(reconnects=-1)
    except (ValueError, OSError):
        pass
    label = ssid.decode("utf-8", "replace") if isinstance(ssid, bytes) else ssid
    print("[WIFI] Connecting to %s; retries enabled, timeout 30s" % label)
    if password:
        wlan.connect(ssid, password)
    else:
        wlan.connect(ssid)
    wait_for_wifi(wlan)
    print("[WIFI] Connected. Local IP:", wlan.ifconfig()[0])
    return wlan


# ----------------------------- ntfy.sh protocol ----------------------------

def send(message, title=None, priority=None, tags=None):
    # ntfy publishes whatever is in the POST body as the notification text.
    # Optional extras go in HTTP headers.
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = str(priority)  # 1 (min) to 5 (max)
    if tags:
        headers["Tags"] = tags  # comma-separated, e.g. "warning,thermometer"

    # Encode first so Content-Length counts bytes, not characters.
    r = urequests.post(NTFY_URL, data=message.encode("utf-8"), headers=headers)
    status = r.status_code
    print("ntfy status:", status)  # 200 = delivered to the topic
    # ntfy replies with the stored message as JSON; "time" is the server's
    # Unix timestamp (UTC seconds), used as a clock if NTP is unavailable.
    sent_at = None
    if status == 200:
        try:
            sent_at = r.json().get("time")
        except Exception:
            pass
    r.close()  # always close, or the board leaks sockets and runs out of memory
    return status, sent_at


def receive(since="10m"):
    # /json returns one JSON object per line; poll=1 makes the server
    # return cached messages and close, instead of holding the stream open.
    r = urequests.get(NTFY_URL + "/json?poll=1&since=" + since)
    text = r.text
    r.close()
    for line in text.split("\n"):
        if line:
            print(line)

# ----------------------------- Weather protocol ----------------------------

def http_client():
    try:
        import requests
        return requests
    except ImportError:
        try:
            import urequests
            return urequests
        except ImportError:
            raise RuntimeError(
                "Missing requests. In connected REPL: import mip; mip.install('requests')"
            )


def get_json(url):
    """Bound the request and close its response, including every error path."""
    response = None
    try:
        # Timeouts and dropped connections raise OSError; retry those a few times.
        for attempt in range(1, HTTP_ATTEMPTS + 1):
            try:
                response = http_client().get(url, timeout=HTTP_TIMEOUT_S)
                break
            except OSError as error:
                print("[HTTP] Attempt %d/%d failed: %s" % (attempt, HTTP_ATTEMPTS, error))
                if attempt == HTTP_ATTEMPTS:
                    raise RuntimeError("No response after %d attempts; check Internet access"
                                       % HTTP_ATTEMPTS)
                gc.collect()
                time.sleep_ms(1000)
        status = response.status_code
        if status == 401:
            raise RuntimeError("HTTP 401: check OpenWeatherMap key/activation/access")
        if status == 429:
            raise RuntimeError("HTTP 429: API rate limit; wait before retrying")
        if status != 200:
            raise RuntimeError("API returned HTTP %d" % status)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("API returned non-JSON; check Internet/login portal")
        if not isinstance(data, dict):
            raise RuntimeError("API returned an unexpected JSON format")
        return data
    finally:
        if response is not None:
            response.close()
        gc.collect()


def parse_location(data):
    if data.get("status") != "success":
        raise RuntimeError("Geolocation failed: %s" % data.get("message", "unknown error"))
    try:
        latitude = float(data["lat"])
        longitude = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Geolocation response has no valid coordinates")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise RuntimeError("Geolocation coordinates are outside valid ranges")
    return {
        "lat": latitude,
        "lon": longitude,
        "city": str(data.get("city") or "Location"),
        "region": str(data.get("regionName") or ""),
        "country": str(data.get("country") or ""),
        "offset": int(data.get("offset") or 0),  # local time minus UTC, in seconds
    }


def fetch_location():
    # No private/local IP is supplied: the API locates this request's public IP.
    location = parse_location(get_json(GEO_URL))
    print("[GEO] %s, %s, %s" %
          (location["city"], location["region"], location["country"]))
    print("[GEO] Latitude=%.4f Longitude=%.4f" % (location["lat"], location["lon"]))
    return location


def quote_query(value):
    result = ""
    for byte in value.encode("utf-8"):
        if 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte in (45, 46, 95, 126):
            result += chr(byte)
        else:
            result += "%%%02X" % byte
    return result


def weather_url(location):
    if not WEATHER_API:
        raise ValueError("OpenWeatherMap API key is empty")
    return ("%s?lat=%.4f&lon=%.4f&appid=%s&units=metric&lang=en" %
            (WEATHER_URL, location["lat"], location["lon"], quote_query(WEATHER_API)))


def parse_weather(data):
    if str(data.get("cod", 200)) != "200":
        raise RuntimeError("OpenWeatherMap rejected the weather request")
    try:
        temperature = float(data["main"]["temp"])
        description = data["weather"][0]["description"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Weather response is missing temperature/description")
    if not (-273.15 <= temperature <= 1000) or not isinstance(description, str) or not description:
        raise RuntimeError("Weather response has invalid temperature/description")
    return {"temperature": temperature, "description": description}


def fetch_weather(location):
    # HTTPS carries the key. Avoid printing the URL containing it.
    try:
        weather = parse_weather(get_json(weather_url(location)))
    except Exception as error:
        raise RuntimeError(str(error).replace(WEATHER_API, "[key]"))
    print("[WEATHER] %.1f C, %s" % (weather["temperature"], weather["description"]))
    return weather


# ----------------------------- Display protocol ----------------------------

def show_lines(display, *lines):
    display.fill(0)
    for row, line in enumerate(lines[:3]):
        # The default font is 8x8: 16 characters fit on our 128-pixel OLED.
        text = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in str(line))
        display.text(text[:16], 0, row * 12, 1)
    display.show()


def show_location(display, location):
    show_lines(display, location["city"],
               "Lat: %.4f" % location["lat"], "Lon: %.4f" % location["lon"])


def show_weather(display, location, weather, elapsed_ms):
    show_lines_buffer = (
        location["city"], "Temp: %.1f C" % weather["temperature"]
    )
    display.fill(0)
    for row, line in enumerate(show_lines_buffer):
        text = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in line)
        display.text(text[:16], 0, row * 12, 1)
    description = weather["description"]
    if len(description) <= 16:
        display.text(description, 0, 24, 1)
    else:
        # Move long descriptions across the bottom row so no words are lost.
        period = len(description) * 8 + 16
        shift = int(elapsed_ms * TEXT_SPEED_PX_S / 1000) % period
        display.text(description, -shift, 24, 1)
        display.text(description, period - shift, 24, 1)
    display.show()


# --------------------------- Tilt-scroll protocol --------------------------

def accel_read_reg(spi, cs, reg):
    buf = bytearray(1)
    cs.value(0)
    try:
        spi.write(bytes((SPI_READ | reg,)))
        spi.readinto(buf)
    finally:
        cs.value(1)
    return buf[0]


def accel_write_reg(spi, cs, reg, value):
    cs.value(0)
    try:
        spi.write(bytes((reg, value)))
    finally:
        cs.value(1)


def accel_init(spi, cs):
    device_id = accel_read_reg(spi, cs, 0x00)
    if device_id != 0xE5:
        raise RuntimeError("ADXL345 not detected; check the SPI wiring.")
    accel_write_reg(spi, cs, POWER_CTL, 0x00)     # Standby while configuring.
    accel_write_reg(spi, cs, DATA_FORMAT, 0x00)   # Four-wire SPI, +/-2g, fixed 10-bit.
    accel_write_reg(spi, cs, 0x2C, 0x0A)          # BW_RATE: normal power, 100 Hz samples.
    accel_write_reg(spi, cs, 0x2E, 0x00)          # INT_ENABLE: polling, no interrupt outputs.
    accel_write_reg(spi, cs, 0x38, 0x00)          # FIFO_CTL: bypass FIFO.
    accel_write_reg(spi, cs, POWER_CTL, 0x08)     # Start measurement.
    time.sleep_ms(20)


def accel_read(spi, cs, buffer):
    # Command byte: bit 7 = read, bit 6 = multi-byte, bits 5..0 = register.
    cs.value(0)
    try:
        spi.write(bytes((SPI_READ | SPI_MULTI_BYTE | DATAX0,)))
        spi.readinto(buffer)
    finally:
        cs.value(1)
    # The 6 bytes are X0,X1,Y0,Y1,Z0,Z1: three little-endian signed 16-bit ints.
    return struct.unpack("<hhh", buffer)


def axis_speed(acceleration_g):
    """Map tilt to pixels/second, with a dead zone and a bounded speed."""
    magnitude = abs(acceleration_g)
    if magnitude <= DEAD_ZONE_G:
        return 0.0
    fraction = min((magnitude - DEAD_ZONE_G) / (1.0 - DEAD_ZONE_G), 1.0)
    speed = fraction * MAX_SPEED_PX_S
    return speed if acceleration_g > 0 else -speed


def draw_wrapped_text(display, lines, page_width, page_height, text_x, text_y):
    """Draw four neighboring copies of the page, then send one OLED frame."""
    # Same four-copy wrap as Checkpoint 1, except the page is as wide as the
    # longest line (not the screen), so lines longer than 128 px scroll through.
    origin_x = int(text_x % page_width)
    origin_y = int(text_y % page_height)
    display.fill(0)
    for offset_x in (origin_x, origin_x - page_width):
        for offset_y in (origin_y, origin_y - page_height):
            for row, line in enumerate(lines):
                display.text(line, offset_x, offset_y + row * 12, 1)
    display.show()


def scroll_text(display, spi, cs, text):
    """Tilt X/Y to slide the text; it wraps around in both directions."""
    # One page row per "\n"-separated line, 12 px apart like Checkpoint 1.
    text = "".join(ch if 32 <= ord(ch) <= 126 or ch == "\n" else "?" for ch in text)
    lines = text.split("\n")
    longest = max(len(line) for line in lines)
    page_width = max(display.width, longest * 8 + SCROLL_GAP_PX)
    page_height = max(display.height, (len(lines) - 1) * 12 + 8)
    accel_buffer = bytearray(6)
    text_x = 0.0
    text_y = 0.0
    # Seed the filters with a real first reading so they do not ramp up from 0.
    raw_x, raw_y, raw_z = accel_read(spi, cs, accel_buffer)
    filtered_x = raw_x / COUNTS_PER_G
    filtered_y = raw_y / COUNTS_PER_G
    last_frame = time.ticks_ms()

    while True:
        # dt = seconds since the previous frame, clamped so a slow frame
        # cannot make the text jump.
        frame_start = time.ticks_ms()
        dt = max(0.0, min(time.ticks_diff(frame_start, last_frame) / 1000.0, 0.10))
        last_frame = frame_start

        # Low-pass filter the tilt, then tilt -> speed -> position.
        raw_x, raw_y, raw_z = accel_read(spi, cs, accel_buffer)
        alpha = dt / (TILT_FILTER_SECONDS + dt)
        filtered_x += alpha * (raw_x / COUNTS_PER_G - filtered_x)
        filtered_y += alpha * (raw_y / COUNTS_PER_G - filtered_y)
        speed_x = X_DIRECTION * axis_speed(filtered_x)
        speed_y = Y_DIRECTION * axis_speed(filtered_y)
        text_x = (text_x + speed_x * dt) % page_width
        text_y = (text_y + speed_y * dt) % page_height

        draw_wrapped_text(display, lines, page_width, page_height, text_x, text_y)

        # Sleep for whatever is left of the 33 ms frame budget.
        remaining = FRAME_MS - time.ticks_diff(time.ticks_ms(), frame_start)
        if remaining > 0:
            time.sleep_ms(remaining)


# ----------------------------------- Main ----------------------------------

def ntp_utc_seconds():
    """Ask NTP servers for the UTC time; return None if none of them answer."""
    # Done by hand instead of with ntptime, whose older versions hard-code a
    # 1 s timeout. The reply counts seconds from 1900 rather than 1970, which
    # is fine here because build_summary only keeps the time of day.
    import socket

    request = bytearray(48)
    request[0] = 0x1B  # LI = 0, version = 3, mode = 3 (client request)
    for host in NTP_HOSTS:
        sock = None
        try:
            address = socket.getaddrinfo(host, 123)[0][-1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(NTP_TIMEOUT_S)
            sock.sendto(request, address)
            reply = sock.recv(48)
            if len(reply) < 44:
                raise RuntimeError("short reply")
            # Bytes 40..43 hold the server's transmit time in whole seconds.
            seconds = struct.unpack("!I", reply[40:44])[0]
            if seconds == 0:
                raise RuntimeError("empty timestamp")
            print("[TIME] Got the time from", host)
            return seconds
        except Exception as error:
            print("[TIME] %s failed: %s" % (host, error))
        finally:
            if sock is not None:
                sock.close()
    return None


def build_summary(location, weather, utc_seconds):
    if utc_seconds is None:
        time_text = "n/a"
    else:
        # Only the time of day is needed, so the epoch (1970 or 2000) does not
        # matter: shift UTC by the geolocation offset and keep seconds-in-day.
        seconds = (int(utc_seconds) + location["offset"]) % 86400
        time_text = "%02d:%02d:%02d" % (
            seconds // 3600, seconds % 3600 // 60, seconds % 60)
    return ("Location: Lon %.4f, Lat %.4f\nWeather: %.1f C, %s\nTime: %s" %
            (location["lon"], location["lat"], weather["temperature"],
             weather["description"], time_text))


def main():
    # Select is idle-high before SPI starts.
    cs = Pin(15, Pin.OUT, value=1)
    spi = None
    display = None
    try:
        i2c = I2C(sda=Pin(22), scl=Pin(20))
        if 0x3C not in i2c.scan():
            raise RuntimeError("OLED 0x3C not found; check its I2C wiring")
        display = ssd1306.SSD1306_I2C(128, 32, i2c)
        display.contrast(255)
        display.invert(0)
        spi = SPI(1, baudrate=5000000, polarity=1, phase=1,
                  sck=Pin(5), mosi=Pin(19), miso=Pin(21))
        accel_init(spi, cs)

        show_lines(display, "WiFi setup", "See terminal")
        connect_wifi()

        # Coordinates stay on screen while the weather request is running.
        show_lines(display, "Geolocation", "Loading...")
        print("Connecting to ip-api.com (geolocation)...")
        location = fetch_location()
        show_location(display, location)
        print("Connecting to OpenWeatherMap...")
        weather = fetch_weather(location)

        # Weather stays on screen while the ntfy request is running.
        show_weather(display, location, weather, 0)
        message = "%s: %.1f C, %s" % (
            location["city"], weather["temperature"], weather["description"])
        print("Connecting to ntfy.sh...")
        status, sent_at = send(message, title="Lab 4 weather")
        if status != 200:
            raise RuntimeError("ntfy returned HTTP %d" % status)
        show_lines(display, "Sent the weather", "information to", "ntfy!")

        # Read the clock last, so the time marks the end of the protocol.
        # Prefer NTP; otherwise fall back to ntfy's server timestamp.
        print("Connecting to NTP time server...")
        utc_seconds = ntp_utc_seconds()
        if utc_seconds is None and sent_at is not None:
            print("[TIME] Using the ntfy.sh server timestamp instead of NTP.")
            utc_seconds = sent_at
        time.sleep_ms(SENT_HOLD_MS)
        summary = build_summary(location, weather, utc_seconds)
        print("[SUMMARY]")
        print(summary)
        print("[SCROLL] Tilt X/Y to slide the summary. Ctrl+C: stop.")
        scroll_text(display, spi, cs, summary)
    except KeyboardInterrupt:
        print("[MAIN] Stopped.")
    except Exception as error:
        print("[MAIN] Error:", error)
        if display is not None:
            show_lines(display, "ERROR", "See terminal", "Ctrl+D restart")
    finally:
        cs.value(1)
        if display is not None:
            display.invert(0)
        if spi is not None:
            spi.deinit()


if __name__ == "__main__":
    main()
