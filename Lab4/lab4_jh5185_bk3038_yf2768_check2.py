"""Lab 4 Checkpoint 2: Wi-Fi -> IP geolocation -> OLED.

Upload this file as main.py, enter REPL, and press Ctrl+D.
Wi-Fi credentials are entered in REPL and kept in memory.
The latitude and longitude of the current location are shown on the OLED.
"""

import gc
import time


GEO_URL = (
    "http://ip-api.com/json/"
    "?fields=status,message,lat,lon,city,regionName,country,query"
)
WIFI_TIMEOUT_MS = 30000
HTTP_TIMEOUT_S = 15


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

    show_lines(display, "CHECKPOINT 2", "WiFi setup", "See terminal")
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
        print("[CHECK2] WiFi -> geolocation")
        connect_wifi(display)
        show_lines(display, "Geolocation", "Loading...")
        location = fetch_location()
        show_location(display, location)
        print("[CHECK2] Coordinates displayed. This is approximate IP geolocation.")
    except KeyboardInterrupt:
        print("[CHECK2] Stopped.")
    except Exception as error:
        print("[CHECK2] Error:", error)
        if display is not None:
            show_lines(display, "CHECK2 ERROR", "See terminal", "Ctrl+D restart")
    finally:
        if display is not None:
            display.invert(0)


if __name__ == "__main__":
    main()
