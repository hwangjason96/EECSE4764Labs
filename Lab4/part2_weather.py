"""Lab 4 Part 2: Wi-Fi -> IP geolocation -> OpenWeatherMap -> OLED.

Upload this file as main.py, enter REPL, and press Ctrl+D.
Wi-Fi credentials and the OpenWeatherMap key are entered in REPL and kept in
memory. Leave the API key blank to demonstrate Checkpoint 2 alone.
Button C switches coordinates/weather. Weather updates every 10 minutes.
"""

import gc
import time


GEO_URL = (
    "http://ip-api.com/json/"
    "?fields=status,message,lat,lon,city,regionName,country,query"
)
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
WIFI_TIMEOUT_MS = 30000
HTTP_TIMEOUT_S = 15
WEATHER_REFRESH_MS = 600000
FRAME_MS = 50
DEBOUNCE_MS = 30
TEXT_SPEED_PX_S = 16


def show_lines(display, *lines):
    display.fill(0)
    for row, line in enumerate(lines[:3]):
        # The default font is 8x8: 16 characters fit on our 128-pixel OLED.
        text = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in str(line))
        display.text(text[:16], 0, row * 12, 1)
    display.show()


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
    import network

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


def connect_wifi(display):
    import network

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

    show_lines(display, "PART 2", "WiFi setup", "See terminal")
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
    show_lines(display, "WiFi", "Connecting...", "Wait up to 30s")
    if password:
        wlan.connect(ssid, password)
    else:
        wlan.connect(ssid)
    wait_for_wifi(wlan)
    print("[WIFI] Connected. Local IP:", wlan.ifconfig()[0])
    return wlan


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
        response = http_client().get(url, timeout=HTTP_TIMEOUT_S)
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
    }


def fetch_location():
    # No private/local IP is supplied: the API locates this request's public IP.
    location = parse_location(get_json(GEO_URL))
    print("[GEO] %s, %s, %s" %
          (location["city"], location["region"], location["country"]))
    print("[GEO] Latitude=%.4f Longitude=%.4f" % (location["lat"], location["lon"]))
    return location


def show_location(display, location):
    show_lines(display, location["city"],
               "Lat: %.4f" % location["lat"], "Lon: %.4f" % location["lon"])


def quote_query(value):
    result = ""
    for byte in value.encode("utf-8"):
        if 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte in (45, 46, 95, 126):
            result += chr(byte)
        else:
            result += "%%%02X" % byte
    return result


def weather_url(location, api_key):
    if not api_key:
        raise ValueError("OpenWeatherMap API key is empty")
    return ("%s?lat=%.4f&lon=%.4f&appid=%s&units=metric&lang=en" %
            (WEATHER_URL, location["lat"], location["lon"], quote_query(api_key)))


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


def fetch_weather(location, api_key):
    # HTTPS carries the key. Avoid printing the URL containing it.
    try:
        weather = parse_weather(get_json(weather_url(location, api_key)))
    except Exception as error:
        raise RuntimeError(str(error).replace(api_key, "[key]"))
    print("[WEATHER] %.1f C, %s" % (weather["temperature"], weather["description"]))
    return weather


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


class PageButton:
    def __init__(self, pin, now):
        self.pin = pin
        self.raw = self.stable = pin.value()
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


def main():
    from machine import Pin, I2C
    import ssd1306

    display = None
    try:
        i2c = I2C(sda=Pin(22), scl=Pin(20))
        if 0x3C not in i2c.scan():
            raise RuntimeError("OLED 0x3C not found; check its I2C wiring")
        display = ssd1306.SSD1306_I2C(128, 32, i2c)
        display.contrast(255)
        display.invert(0)
        print("[PART2] WiFi -> geolocation -> OpenWeatherMap")
        wlan = connect_wifi(display)
        show_lines(display, "Geolocation", "Loading...")
        location = fetch_location()
        show_location(display, location)
        print("[CHECK2] Coordinates displayed. This is approximate IP geolocation.")

        api_key = input("OpenWeatherMap API key (Enter = coordinates only): ").strip()
        weather = None
        if api_key:
            show_lines(display, "Weather", "Loading...")
            try:
                weather = fetch_weather(location, api_key)
            except Exception as error:
                print("[WEATHER]", error)
                print("[WEATHER] Keeping coordinates; Ctrl+D to restart with another key.")
        show_location(display, location)

        now = time.ticks_ms()
        button_c = PageButton(Pin(4, Pin.IN, Pin.PULL_UP), now)
        weather_page = weather is not None
        weather_due = time.ticks_add(now, WEATHER_REFRESH_MS)
        scroll_started = now
        print("[PART2] C: coordinates/weather. Ctrl+C: stop.")
        if weather is not None:
            print("[CHECK3] Temperature and description ready. Refresh interval: 10 min.")

        while True:
            now = time.ticks_ms()
            if button_c.released(now) and weather is not None:
                weather_page = not weather_page
                scroll_started = now

            if weather is not None and time.ticks_diff(now, weather_due) >= 0:
                # Reuse the geolocation coordinates, as required by Checkpoint 3.
                try:
                    if not wlan.isconnected():
                        raise RuntimeError("Wi-Fi disconnected; showing cached weather")
                    weather = fetch_weather(location, api_key)
                except Exception as error:
                    print("[WEATHER] Refresh failed:", error)
                weather_due = time.ticks_add(time.ticks_ms(), WEATHER_REFRESH_MS)

            if weather_page:
                show_weather(display, location, weather, time.ticks_diff(now, scroll_started))
            else:
                show_location(display, location)
            time.sleep_ms(FRAME_MS)
    except KeyboardInterrupt:
        print("[PART2] Stopped.")
    except Exception as error:
        print("[PART2] Error:", error)
        if display is not None:
            show_lines(display, "PART2 ERROR", "See terminal", "Ctrl+D restart")
    finally:
        if display is not None:
            display.invert(0)


if __name__ == "__main__":
    main()
