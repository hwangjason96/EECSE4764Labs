"""
Lab 4, Checkpoint 4 -- "Where am I, what is the weather, and what time is it?"

WHAT THIS PROGRAM DOES, START TO FINISH
---------------------------------------
    1. Bring up the hardware: SSD1306 OLED on I2C, ADXL345 accelerometer on SPI.
    2. Join a Wi-Fi network chosen by the user in the terminal.
    3. Ask ip-api.com where this board's public IP address is   -> lat / lon / city.
    4. Ask OpenWeatherMap what the weather is at that lat / lon -> temperature / text.
    5. Push that weather to a phone through ntfy.sh.
    6. Ask an NTP server what time it is (ntfy's own timestamp is the backup).
    7. Build a three-line summary and let the user tilt the board to slide it
       around the OLED forever, wrapping at every edge.

HOW THE FILE IS LAID OUT
------------------------
    Configuration constants
    Wi-Fi connection        visible_networks, wait_for_wifi, connect_wifi
    ntfy.sh protocol        send, receive
    Weather protocol        http_client, get_json, parse_location, fetch_location,
                            quote_query, weather_url, parse_weather, fetch_weather
    Display protocol        show_lines, show_location, show_weather
    Tilt-scroll protocol    accel_read_reg, accel_write_reg, accel_init, accel_read,
                            axis_speed, draw_wrapped_text, scroll_text
    Main                    ntp_utc_seconds, build_summary, main
    MATHEMATICAL APPENDIX   every formula used above, derived (sections M1..M10)

Each function header says what the function is for, what goes in and out, and why
it is written the way it is. Whenever a header says "see M#", the derivation is in
the appendix at the bottom of the file.

WIRING ASSUMED BY main()
------------------------
    OLED  (I2C, address 0x3C):  SDA = GPIO 22, SCL = GPIO 20
    ADXL345 (SPI bus 1):        SCK = GPIO 5,  MOSI = GPIO 19, MISO = GPIO 21,
                                CS  = GPIO 15
"""

from machine import Pin, SPI, I2C
import gc
import network
import struct
import time
import ssd1306
import urequests  # on newer MicroPython builds: `import requests as urequests`

# ------------------------------ Configuration ------------------------------
#
# Network endpoints and patience limits.
#   NTFY_URL         The last path segment is the ntfy topic; anyone subscribed to
#                    that topic receives what we POST.
#   GEO_URL          `fields=` asks ip-api.com for only the keys we use, which keeps
#                    the JSON small enough to parse comfortably on the board.
#   WIFI_TIMEOUT_MS  Total time we wait for an IP address before giving up.
#   HTTP_TIMEOUT_S / HTTP_ATTEMPTS   Per-request socket timeout and retry count.
#   NTP_HOSTS        Tried in order; the first one that answers wins.
NTFY_URL = "https://ntfy.sh/AIoTCUG36"
WIFI_TIMEOUT_MS = 30000
GEO_URL = (
    "http://ip-api.com/json/"
    "?fields=status,message,lat,lon,city,regionName,country,query,offset"
)
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
HTTP_TIMEOUT_S = 15
HTTP_ATTEMPTS = 3
NTP_HOSTS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")
NTP_TIMEOUT_S = 10
WEATHER_API = "0f0eaf4f4b16ae04541f3fb99a4f6725"

# Display timing.
#   TEXT_SPEED_PX_S  Speed of the automatic marquee in show_weather (see M9).
#   SENT_HOLD_MS     How long the "Sent..." confirmation stays on screen.
#   FRAME_MS         Frame budget of the tilt-scroll loop: 33 ms is about 30 fps.
TEXT_SPEED_PX_S = 16
SENT_HOLD_MS = 3000
FRAME_MS = 33

# Tilt-scroll tuning. These five numbers fully define how the text "feels".
#   COUNTS_PER_G         Sensor scale in fixed 10-bit, +/-2g mode (see M2).
#   DEAD_ZONE_G          Tilt below this is treated as "held flat" (see M4).
#   MAX_SPEED_PX_S       Scroll speed when an axis reads a full 1 g (see M4).
#   TILT_FILTER_SECONDS  Time constant of the low-pass filter (see M3).
#   X/Y_DIRECTION        +1 or -1; flips an axis so the text follows the tilt.
#   SCROLL_GAP_PX        Blank space between the end of the text and its repeat.
COUNTS_PER_G = 256.0
DEAD_ZONE_G = 0.20
MAX_SPEED_PX_S = 36.0
TILT_FILTER_SECONDS = 0.08
X_DIRECTION = -1
Y_DIRECTION = 1
SCROLL_GAP_PX = 32

# ADXL345 register addresses and SPI command bits (see M1).
SPI_READ = 0x80
SPI_MULTI_BYTE = 0x40
DATA_FORMAT = 0x31
POWER_CTL = 0x2D
DATAX0 = 0x32


# ----------------------------- WiFi connection -----------------------------

def visible_networks(scan):
    """
    Turn a raw Wi-Fi scan into a clean menu: one entry per network name,
    strongest signal first.

    Input
        scan: the list returned by wlan.scan(). Each item is a tuple
              (ssid, bssid, channel, RSSI, security, hidden).
    Output
        A list of those same tuples, filtered and reordered.

    Why it is needed
        A campus network is broadcast by many access points, so the raw scan
        lists the same name many times. Sorting by RSSI (index 3) in descending
        order first means the first time we meet a name it is the strongest
        access point for it; the `seen` set then drops every later duplicate.
        Hidden networks report an empty SSID and are skipped, because there is
        nothing to show in a menu (option 0 lets the user type one instead).
        RSSI is in dBm and negative, so "largest" means "closest to zero".
    """
    result = []
    seen = set()
    for access_point in sorted(scan, key=lambda item: item[3], reverse=True):
        ssid = access_point[0]
        if ssid and ssid not in seen:
            seen.add(ssid)
            result.append(access_point)
    return result


def wait_for_wifi(wlan):
    """
    Block until the station has an IP address, or raise after WIFI_TIMEOUT_MS.

    Input
        wlan: a station interface on which connect() has already been called.
    Output
        None. Returning normally means "connected".
    Raises
        RuntimeError carrying the driver's status code and a readable reason.

    How it works
        connect() only *starts* joining; association and DHCP happen in the
        background. This function polls every 200 ms (at most 150 polls, see
        M10) and prints the status code each time it changes, so the terminal
        shows the progression without being flooded.

    Two decisions worth knowing about
        * A failure status is NOT treated as final while the timer is running.
          On ESP32 MicroPython v1.26 the driver keeps reporting the previous
          attempt's disconnect reason while a new attempt or an automatic retry
          is in progress, so bailing out early would abort connections that are
          about to succeed. The status is only translated into a reason once
          the whole window has expired. Codes 210 and 211 are ESP32-specific
          and mean the access point's security mode is not usable.
        * The handler catches BaseException, not Exception, so that Ctrl+C
          (KeyboardInterrupt) also passes through it. Either way we call
          disconnect() to stop the driver's background retries, then re-raise
          so the caller still sees the original error.
    """
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
        try:
            wlan.disconnect()
        except OSError:
            pass
        raise


def connect_wifi():
    """
    Interactive Wi-Fi setup: scan, let the user pick a network, join it.

    Output
        The connected station interface (network.WLAN).
    Raises
        RuntimeError if the SSID is empty or the connection times out.

    Steps
        1. Shortcut. If the board is already connected (typical after a soft
           reboot with Ctrl+D) return immediately; no need to ask again.
        2. Reset the radio. A soft reboot restarts Python but not necessarily
           the ESP32 Wi-Fi driver, which may still be retrying an old request.
           disconnect() followed by active(False) -> active(True) with short
           pauses gives a known-clean station before scanning.
        3. Scan and print a numbered menu (via visible_networks). Entry 0 is
           "type an SSID manually", for hidden networks or ones that were
           missed by the scan.
        4. Read the choice in a loop until it is an integer in 0..len(menu).
        5. Ask for a password only if one is needed: security == 0 means an
           open network, so the prompt is skipped.
        6. Allow unlimited driver retries (reconnects=-1) so a slow phone
           hotspot gets several chances inside our 30 s window. This is safe
           only because wait_for_wifi() disconnects when the window expires;
           otherwise a bad password would retry forever. Ports that do not
           support the setting raise, and that is ignored.
        7. Connect and wait.

    Note on types: a scanned SSID is `bytes`, a typed one is `str`. connect()
    accepts both; `label` exists only to print either one readably.
    """
    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)
    if wlan.isconnected():
        print("[WIFI] Already connected. Local IP:", wlan.ifconfig()[0])
        return wlan

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
    """
    Publish one push notification to our ntfy.sh topic.

    Input
        message:  the notification body (str).
        title:    optional bold heading.
        priority: optional 1 (min) .. 5 (max).
        tags:     optional comma-separated tags, e.g. "warning,thermometer".
    Output
        (status, sent_at)
        status:   the HTTP status code; 200 means the topic accepted it.
        sent_at:  the server's Unix timestamp for the message (UTC seconds),
                  or None if it could not be read.

    The protocol
        ntfy is deliberately simple: an HTTP POST to the topic URL, where the
        request body IS the notification text. Everything optional travels in
        HTTP headers (Title, Priority, Tags), so the body never needs escaping.

    Details that matter
        * The message is encoded to UTF-8 bytes before posting, so that the
          Content-Length header counts bytes rather than characters. The two
          differ as soon as the text contains a non-ASCII character.
        * ntfy answers with the stored message as JSON, and its "time" field is
          the server's clock. We keep it because main() uses it as a fallback
          clock when no NTP server can be reached.
        * The response is always closed. Each open response holds a socket and
          a buffer; on a microcontroller, leaking them quickly exhausts both.
    """
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = str(priority)
    if tags:
        headers["Tags"] = tags

    r = urequests.post(NTFY_URL, data=message.encode("utf-8"), headers=headers)
    status = r.status_code
    print("ntfy status:", status)
    sent_at = None
    if status == 200:
        try:
            sent_at = r.json().get("time")
        except Exception:
            pass
    r.close()
    return status, sent_at


def receive(since="10m"):
    """
    Print the messages recently published to our ntfy.sh topic.

    Input
        since: how far back to look, in ntfy's duration syntax ("10m", "1h").
    Output
        None; each message is printed as one line of JSON.

    The `/json` endpoint streams one JSON object per line and normally keeps
    the connection open forever, waiting for new messages. `poll=1` changes
    that: the server sends what it has cached and closes, so the call returns.

    This is a debugging helper for the REPL. main() never calls it.
    """
    r = urequests.get(NTFY_URL + "/json?poll=1&since=" + since)
    text = r.text
    r.close()
    for line in text.split("\n"):
        if line:
            print(line)


# ----------------------------- Weather protocol ----------------------------

def http_client():
    """
    Return whichever HTTP module this MicroPython build provides.

    The library was renamed: newer firmware ships `requests`, older firmware
    ships `urequests`. Both expose the same get()/post() interface, so the
    caller does not care which one comes back. If neither exists, the error
    message contains the exact REPL command that installs it.
    """
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
    """
    HTTP GET a URL and return its body as a dictionary -- or fail with a
    message a human can act on.

    Input
        url: the full address, query string included.
    Output
        dict parsed from the JSON response.
    Raises
        RuntimeError for every failure mode, each with its own explanation.

    Both web APIs in this lab go through this one function, so all of the
    defensive behaviour lives in a single place:

        Network trouble  Timeouts and dropped connections arrive as OSError.
                         They are retried up to HTTP_ATTEMPTS times, one second
                         apart, with a garbage collection in between because a
                         failed TLS handshake leaves large buffers behind.
        HTTP 401         The API key is wrong or not activated yet.
        HTTP 429         We are being rate limited.
        Any other non-200  Reported with its number.
        Body is not JSON   Usually a captive-portal login page pretending to
                           be the site we asked for.
        JSON is not an object  We expect {...}, not a list or a bare value.

    The `finally` block runs on success AND on every error path above. It
    closes the response (freeing its socket) and collects garbage, so a failed
    request cannot leave the board with less memory for the next one.
    """
    response = None
    try:
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
    """
    Validate an ip-api.com reply and reduce it to the six fields we use.

    Input
        data: the dict returned by get_json(GEO_URL).
    Output
        {"lat", "lon", "city", "region", "country", "offset"}
        lat / lon are floats in degrees; offset is the location's local time
        minus UTC, in seconds (for example -14400 for New York in summer).
    Raises
        RuntimeError if the service reports failure, if a coordinate is missing
        or not a number, or if it lies outside the globe.

    ip-api.com answers HTTP 200 even when the lookup fails and signals the
    failure inside the JSON ("status": "fail"), so that field is checked first.
    The range test (|lat| <= 90, |lon| <= 180) catches corrupted replies before
    they are forwarded to the weather service. Text fields get safe defaults
    through `or`, so a missing city never crashes the display code later.
    """
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
        "offset": int(data.get("offset") or 0),
    }


def fetch_location():
    """
    Find out where the board is, using nothing but its Internet connection.

    Output
        The location dict described in parse_location().

    The request names no IP address on purpose. ip-api.com then looks up the
    address the request arrived from, which is the router's PUBLIC address.
    The board's own address (192.168.x.x or similar) is private and would mean
    nothing to a geolocation service. The answer is therefore the location of
    the Internet connection -- city-level accuracy, not GPS accuracy.
    """
    location = parse_location(get_json(GEO_URL))
    print("[GEO] %s, %s, %s" %
          (location["city"], location["region"], location["country"]))
    print("[GEO] Latitude=%.4f Longitude=%.4f" % (location["lat"], location["lon"]))
    return location


def quote_query(value):
    """
    Percent-encode a string so it is safe inside a URL query (see M10).

    Input
        value: any text.
    Output
        The same text with every byte outside the "unreserved" set replaced by
        %XX, where XX is that byte in uppercase hexadecimal.

    The unreserved characters, which pass through unchanged, are the letters,
    the digits, and - . _ ~ (ASCII 45, 46, 95, 126). Everything else could be
    mistaken for URL syntax -- & separates parameters, = separates a name from
    its value, a space ends the URL -- so it is escaped. Encoding works on
    UTF-8 bytes, so a non-ASCII character becomes several %XX groups.

    MicroPython has no urllib.parse.quote, which is why this is written out.
    """
    result = ""
    for byte in value.encode("utf-8"):
        if 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte in (45, 46, 95, 126):
            result += chr(byte)
        else:
            result += "%%%02X" % byte
    return result


def weather_url(location):
    """
    Build the OpenWeatherMap "current weather" URL for a location.

    Input
        location: a dict with "lat" and "lon".
    Output
        The complete request URL (str). It contains the API key -- never print it.
    Raises
        ValueError if no API key is configured.

    Query parameters
        lat, lon      the coordinates, 4 decimal places (about 11 m, see M10)
        appid         the API key, percent-encoded by quote_query
        units=metric  temperature in degrees Celsius instead of kelvin
        lang=en       description text in English
    """
    if not WEATHER_API:
        raise ValueError("OpenWeatherMap API key is empty")
    return ("%s?lat=%.4f&lon=%.4f&appid=%s&units=metric&lang=en" %
            (WEATHER_URL, location["lat"], location["lon"], quote_query(WEATHER_API)))


def parse_weather(data):
    """
    Validate an OpenWeatherMap reply and keep only temperature and description.

    Input
        data: the dict returned by get_json(weather_url(...)).
    Output
        {"temperature": float in degrees C, "description": str}
    Raises
        RuntimeError if the reply reports an error, lacks either field, or
        holds a value that cannot be real.

    The reply nests what we want: data["main"]["temp"] and
    data["weather"][0]["description"]. A single try/except covers every way
    that path can be broken (missing key, empty list, wrong type).

    "cod" is OpenWeatherMap's own status code. It is a number in some replies
    and a string in others, so it is compared as a string. The temperature
    check rejects anything below absolute zero (-273.15 C), which can only be
    a parsing or unit mistake.
    """
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
    """
    Get the current weather at a location.

    Input
        location: the dict from fetch_location().
    Output
        The weather dict described in parse_weather().

    The API key travels inside the URL, so two precautions keep it private:
    the request uses HTTPS (the URL is encrypted in transit), and any error
    raised on the way is re-raised with the key replaced by "[key]", because
    some network errors include the full URL in their message and main()
    prints error messages to the terminal.
    """
    try:
        weather = parse_weather(get_json(weather_url(location)))
    except Exception as error:
        raise RuntimeError(str(error).replace(WEATHER_API, "[key]"))
    print("[WEATHER] %.1f C, %s" % (weather["temperature"], weather["description"]))
    return weather


# ----------------------------- Display protocol ----------------------------

def show_lines(display, *lines):
    """
    Clear the OLED and show up to three short lines of text.

    Input
        display: the SSD1306 driver object.
        *lines:  up to three values; each is converted with str().
    Output
        None; the screen is updated.

    Geometry (see M8)
        The built-in font is 8 x 8 pixels and the screen is 128 x 32, so one
        row holds 16 characters and three rows fit at y = 0, 12 and 24. Extra
        lines and extra characters are cut off rather than drawn off-screen.

    Character safety
        The font only contains printable ASCII (codes 32..126). Anything else
        -- an accented letter in a city name, for instance -- is shown as "?"
        instead of a random glyph.

    Drawing only changes a buffer in RAM. Nothing appears until show() sends
    that buffer to the panel over I2C.
    """
    display.fill(0)
    for row, line in enumerate(lines[:3]):
        text = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in str(line))
        display.text(text[:16], 0, row * 12, 1)
    display.show()


def show_location(display, location):
    """
    Show the geolocation result: city on top, latitude and longitude below.

    This screen is left up while the weather request runs, so the user always
    sees the result of the step that just finished.
    """
    show_lines(display, location["city"],
               "Lat: %.4f" % location["lat"], "Lon: %.4f" % location["lon"])


def show_weather(display, location, weather, elapsed_ms):
    """
    Show the weather: city, temperature, and a description that scrolls
    sideways by itself if it is too long to fit.

    Input
        display:    the SSD1306 driver object.
        location:   dict with "city".
        weather:    dict with "temperature" and "description".
        elapsed_ms: time since the animation started. The function draws the
                    one frame that belongs to that instant.
    Output
        None; the screen is updated.

    Rows 0 and 1 are drawn like show_lines(). Row 2 has two cases:
        * 16 characters or fewer: drawn as-is.
        * longer: drawn as a marquee. The text slides left at TEXT_SPEED_PX_S
          and a second copy follows one period behind, so the start of the
          text re-enters on the right as its end leaves on the left (see M9).

    Because the frame depends only on elapsed_ms, the function keeps no state:
    calling it in a loop with a growing elapsed_ms animates it. main() calls it
    once with elapsed_ms = 0, so in this checkpoint the description is shown
    at its starting position while the ntfy request runs.
    """
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
        period = len(description) * 8 + 16
        shift = int(elapsed_ms * TEXT_SPEED_PX_S / 1000) % period
        display.text(description, -shift, 24, 1)
        display.text(description, period - shift, 24, 1)
    display.show()


# --------------------------- Tilt-scroll protocol --------------------------

def accel_read_reg(spi, cs, reg):
    """
    Read one register of the ADXL345.

    Input
        spi: the configured SPI bus.   cs: the chip-select pin.
        reg: the register address (0x00..0x3F).
    Output
        The register's value, an int 0..255.

    An SPI transaction is: pull CS low, send a command byte, exchange data,
    raise CS. The command byte is the address with bit 7 set, which means
    "read" (see M1). The `finally` guarantees CS returns high even if the bus
    raises, so one failed transfer cannot leave the chip selected and corrupt
    the next one.
    """
    buf = bytearray(1)
    cs.value(0)
    try:
        spi.write(bytes((SPI_READ | reg,)))
        spi.readinto(buf)
    finally:
        cs.value(1)
    return buf[0]


def accel_write_reg(spi, cs, reg, value):
    """
    Write one register of the ADXL345.

    Input
        reg: the register address.   value: the byte to store.

    Two bytes are sent inside one CS-low window: the address with bit 7 clear
    ("write", see M1), then the value.
    """
    cs.value(0)
    try:
        spi.write(bytes((reg, value)))
    finally:
        cs.value(1)


def accel_init(spi, cs):
    """
    Check that an ADXL345 is really connected, then configure and start it.

    Raises
        RuntimeError if the device does not identify itself correctly.

    Identity check
        Register 0x00 (DEVID) is read-only and always holds 0xE5. Reading
        anything else means bad wiring, the wrong SPI mode, or a different
        chip, and it is far better to stop here than to scroll on garbage.

    Configuration, in order
        POWER_CTL   = 0x00  Standby. Settings are changed while not measuring.
        DATA_FORMAT = 0x00  4-wire SPI, +/-2 g range, fixed 10-bit resolution,
                            right-justified. This is what makes the scale
                            256 counts per g (see M2).
        BW_RATE (0x2C)    = 0x0A  100 samples per second, normal power. That is
                                  about 3x our 30 fps frame rate, so each frame
                                  reads a fresh sample.
        INT_ENABLE (0x2E) = 0x00  No interrupts; the loop polls instead.
        FIFO_CTL (0x38)   = 0x00  Bypass the FIFO, so a read always returns the
                                  newest sample, never a queued old one.
        POWER_CTL   = 0x08  Set the Measure bit: start sampling.

    The 20 ms pause afterwards covers two sample periods at 100 Hz, so valid
    data is waiting before the first read.
    """
    device_id = accel_read_reg(spi, cs, 0x00)
    if device_id != 0xE5:
        raise RuntimeError("ADXL345 not detected; check the SPI wiring.")
    accel_write_reg(spi, cs, POWER_CTL, 0x00)
    accel_write_reg(spi, cs, DATA_FORMAT, 0x00)
    accel_write_reg(spi, cs, 0x2C, 0x0A)
    accel_write_reg(spi, cs, 0x2E, 0x00)
    accel_write_reg(spi, cs, 0x38, 0x00)
    accel_write_reg(spi, cs, POWER_CTL, 0x08)
    time.sleep_ms(20)


def accel_read(spi, cs, buffer):
    """
    Read all three acceleration axes in a single SPI transaction.

    Input
        buffer: a 6-byte bytearray owned by the caller.
    Output
        (x, y, z) as signed integers in raw sensor counts. Divide by
        COUNTS_PER_G to get g (see M2).

    Why one burst instead of six single reads
        The command byte sets the read bit AND the multi-byte bit, starting at
        DATAX0 (see M1). The chip then sends registers 0x32..0x37 back to back,
        and it holds all six steady for the duration of the burst. The three
        axes are therefore guaranteed to come from the same sample; six
        separate reads could straddle an update and mix two samples.

    Decoding
        The bytes arrive as X0 X1 Y0 Y1 Z0 Z1, low byte first. The format
        string "<hhh" means little-endian, three signed 16-bit integers, which
        is exactly that layout and also handles negative values (see M2).

    Why the buffer is passed in
        This runs 30 times a second. Reusing one buffer avoids allocating a new
        object each frame, which would make the garbage collector pause the
        animation every so often.
    """
    cs.value(0)
    try:
        spi.write(bytes((SPI_READ | SPI_MULTI_BYTE | DATAX0,)))
        spi.readinto(buffer)
    finally:
        cs.value(1)
    return struct.unpack("<hhh", buffer)


def axis_speed(acceleration_g):
    """
    Convert how far one axis is tilted into how fast the text should move.

    Input
        acceleration_g: the filtered reading of one axis, in g. Held still,
                        this equals the sine of the tilt angle (see M4).
    Output
        Speed in pixels per second. The sign follows the sign of the tilt, and
        the magnitude never exceeds MAX_SPEED_PX_S.

    The mapping has three regions (formula and worked numbers in M4):
        * Dead zone: |a| <= DEAD_ZONE_G gives exactly 0. No hand holds a board
          perfectly level and the sensor is never noise-free, so without this
          the text would drift constantly.
        * Linear ramp: speed rises in a straight line from 0 at the edge of
          the dead zone to MAX_SPEED_PX_S at 1 g. Subtracting the dead zone
          first makes the speed start from zero instead of jumping, so the
          response is continuous.
        * Saturation: beyond 1 g (a shake or a tap) the speed is clamped, so a
          jolt cannot throw the text across the screen.

    The work is done on the magnitude and the sign is restored at the end,
    which keeps left/right and up/down perfectly symmetric.
    """
    magnitude = abs(acceleration_g)
    if magnitude <= DEAD_ZONE_G:
        return 0.0
    fraction = min((magnitude - DEAD_ZONE_G) / (1.0 - DEAD_ZONE_G), 1.0)
    speed = fraction * MAX_SPEED_PX_S
    return speed if acceleration_g > 0 else -speed


def draw_wrapped_text(display, lines, page_width, page_height, text_x, text_y):
    """
    Draw one frame of the text so that it wraps around every screen edge.

    Input
        lines:        the text, one string per row.
        page_width,
        page_height:  the size of the repeating "page" that holds the text.
        text_x,
        text_y:       where the page's top-left corner currently is, in pixels.
    Output
        None; one complete frame is sent to the OLED.

    The idea
        Imagine the page printed again and again as wallpaper, and the screen
        as a window looking at it. Moving the text means sliding the wallpaper.
        The window can never show more than four tiles at once: the one whose
        corner is at (origin_x, origin_y), and its neighbours one page to the
        left, one page up, and diagonally up-left. Drawing those four copies
        is therefore always enough (proof in M7).

    Reducing the position modulo the page size keeps the corner inside one
    page, so the same four copies work no matter how far the text has moved.
    The display driver clips whatever falls outside the screen, so no clipping
    logic is needed here. Rows are 12 px apart, the same spacing show_lines()
    uses.

    Unlike Checkpoint 1, the page can be WIDER than the screen (it is as wide
    as the longest line), which is what lets a line longer than 128 px scroll
    all the way through.
    """
    origin_x = int(text_x % page_width)
    origin_y = int(text_y % page_height)
    display.fill(0)
    for offset_x in (origin_x, origin_x - page_width):
        for offset_y in (origin_y, origin_y - page_height):
            for row, line in enumerate(lines):
                display.text(line, offset_x, offset_y + row * 12, 1)
    display.show()


def scroll_text(display, spi, cs, text):
    """
    Let the user slide text around the OLED by tilting the board. Runs until
    interrupted with Ctrl+C.

    Input
        text: the text to show; "\\n" separates rows.
    Output
        Never returns normally.

    Setup
        * Characters the font cannot draw become "?" (newlines are kept, since
          they separate the rows).
        * The page is sized to the text (see M6): as wide as the longest line
          plus SCROLL_GAP_PX of blank space, and never smaller than the screen.
        * The filter state is seeded with a real first reading. Starting it at
          0 would make the text lurch for the first few frames while the
          filter caught up with the board's actual tilt.

    Each frame of the loop
        1. Measure dt, the real time since the previous frame, in seconds.
           Every later step is scaled by dt, so the scroll speed stays correct
           in pixels per SECOND even when a frame runs long. dt is clamped to
           0.10 s so one very slow frame (a garbage collection, say) cannot
           make the text jump (see M5).
        2. Read the accelerometer and convert counts to g (see M2).
        3. Low-pass filter each axis to remove hand tremor and sensor noise.
           The blend factor alpha is recomputed from dt every frame, so the
           amount of smoothing does not depend on the frame rate (see M3).
        4. Convert tilt to speed with axis_speed() (see M4).
        5. Integrate: position += speed * dt, then wrap modulo the page size
           (see M5).
        6. Draw the frame with draw_wrapped_text() (see M7).
        7. Sleep for whatever is left of the FRAME_MS budget, so frames are
           evenly spaced and the CPU is not spinning for no reason (see M10).

    Time is measured with ticks_ms()/ticks_diff() rather than plain
    subtraction because the millisecond counter eventually wraps around, and
    ticks_diff() gives the right answer across that wrap.

    The Z axis is read (it comes for free in the same burst) but not used:
    only X and Y describe which way the board is leaning.
    """
    text = "".join(ch if 32 <= ord(ch) <= 126 or ch == "\n" else "?" for ch in text)
    lines = text.split("\n")
    longest = max(len(line) for line in lines)
    page_width = max(display.width, longest * 8 + SCROLL_GAP_PX)
    page_height = max(display.height, (len(lines) - 1) * 12 + 8)
    accel_buffer = bytearray(6)
    text_x = 0.0
    text_y = 0.0
    raw_x, raw_y, raw_z = accel_read(spi, cs, accel_buffer)
    filtered_x = raw_x / COUNTS_PER_G
    filtered_y = raw_y / COUNTS_PER_G
    last_frame = time.ticks_ms()

    while True:
        frame_start = time.ticks_ms()
        dt = max(0.0, min(time.ticks_diff(frame_start, last_frame) / 1000.0, 0.10))
        last_frame = frame_start

        raw_x, raw_y, raw_z = accel_read(spi, cs, accel_buffer)
        alpha = dt / (TILT_FILTER_SECONDS + dt)
        filtered_x += alpha * (raw_x / COUNTS_PER_G - filtered_x)
        filtered_y += alpha * (raw_y / COUNTS_PER_G - filtered_y)
        speed_x = X_DIRECTION * axis_speed(filtered_x)
        speed_y = Y_DIRECTION * axis_speed(filtered_y)
        text_x = (text_x + speed_x * dt) % page_width
        text_y = (text_y + speed_y * dt) % page_height

        draw_wrapped_text(display, lines, page_width, page_height, text_x, text_y)

        remaining = FRAME_MS - time.ticks_diff(time.ticks_ms(), frame_start)
        if remaining > 0:
            time.sleep_ms(remaining)


# ----------------------------------- Main ----------------------------------

def ntp_utc_seconds():
    """
    Ask Internet time servers what time it is.

    Output
        Whole seconds of UTC counted from 1 January 1900 (the NTP epoch), or
        None if none of the servers in NTP_HOSTS answered.

    The exchange (SNTP, the simple form of NTP; packet layout in M10)
        Send one 48-byte UDP packet to port 123 and receive one 48-byte reply.
        Only the first request byte is non-zero: 0x1B announces "version 3,
        client". In the reply, bytes 40..43 are the whole-seconds part of the
        server's transmit timestamp, stored big-endian (network byte order),
        which is what the struct format "!I" reads.

    Robustness
        Each host gets its own socket and NTP_TIMEOUT_S seconds. Any problem --
        DNS failure, timeout, a reply that is too short, a zero timestamp --
        is printed and the loop moves on to the next host. The socket is closed
        in `finally` whichever way the attempt ends.

    Why not the built-in `ntptime` module
        Older versions hard-code a 1 second timeout, which is too short on a
        phone hotspot. Writing the request by hand lets us choose the timeout.

    About the 1900 epoch
        The result is NOT converted to the Unix (1970) epoch. It does not need
        to be: build_summary() keeps only the time of day, and the two epochs
        differ by a whole number of days (see M10).
    """
    import socket

    request = bytearray(48)
    request[0] = 0x1B
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
    """
    Compose the three-line text that the user scrolls at the end.

    Input
        location:    dict with "lon", "lat" and "offset" (seconds from UTC).
        weather:     dict with "temperature" and "description".
        utc_seconds: a UTC timestamp in seconds from ANY epoch that starts at
                     midnight UTC (NTP's 1900 or Unix's 1970), or None.
    Output
        A str of the form
            Location: Lon -73.9626, Lat 40.8075
            Weather: 18.3 C, scattered clouds
            Time: 14:07:52

    Local time of day (derivation in M10)
        Add the location's UTC offset to get local seconds, then keep the
        remainder after dividing by 86400 (the seconds in a day). That
        remainder is "seconds since local midnight", which splits into hours,
        minutes and seconds by integer division. Python's % always returns a
        non-negative result, so locations west of Greenwich (negative offset)
        work without a special case.

    If no clock was available at all, the time is shown as "n/a" instead of
    showing something wrong.
    """
    if utc_seconds is None:
        time_text = "n/a"
    else:
        seconds = (int(utc_seconds) + location["offset"]) % 86400
        time_text = "%02d:%02d:%02d" % (
            seconds // 3600, seconds % 3600 // 60, seconds % 60)
    return ("Location: Lon %.4f, Lat %.4f\nWeather: %.1f C, %s\nTime: %s" %
            (location["lon"], location["lat"], weather["temperature"],
             weather["description"], time_text))


def main():
    """
    Run the whole checkpoint, from hardware bring-up to the tilt-scroll loop.

    Hardware bring-up
        * The chip-select pin is created already HIGH. CS is active-low, so
          this keeps the accelerometer deselected while the SPI bus starts up
          and stops it from misreading start-up glitches as a command.
        * The I2C bus is scanned for address 0x3C before the display driver is
          created, so a loose OLED wire produces a clear message instead of an
          obscure bus error.
        * SPI uses polarity=1, phase=1 ("mode 3"), the only mode the ADXL345
          supports, at 5 MHz, the fastest clock it allows (see M1).

    The protocol, and what the OLED shows at each stage
        "WiFi setup"                  -> connect_wifi()
        "Geolocation / Loading..."    -> fetch_location()
        city, latitude, longitude     -> fetch_weather()   (stays up meanwhile)
        city, temperature, weather    -> send() to ntfy    (stays up meanwhile)
        "Sent the weather..."         -> ntp_utc_seconds(), then SENT_HOLD_MS
        the scrolling summary         -> scroll_text(), forever

        Each result remains visible while the NEXT network request is running,
        so the screen is never blank during a wait.

    Getting the time
        The clock is read last, so the time shown marks the end of the
        protocol. NTP is preferred. If every NTP server fails, the timestamp
        ntfy.sh returned when it accepted our message is used instead; if that
        is missing too, the summary simply says "n/a".

    Error handling
        KeyboardInterrupt (Ctrl+C)  Quiet, deliberate stop.
        Any other exception         Printed to the terminal, with a short
                                    pointer to it on the OLED. Every helper
                                    raises with a readable message, so one
                                    handler here is enough for the whole file.
        finally                     Always runs: deselects the accelerometer,
                                    restores normal (non-inverted) video, and
                                    releases the SPI bus, so the program can be
                                    restarted from the REPL without a reset.
        `spi` and `display` start as None so that the cleanup code knows which
        of them were actually created before a failure.
    """
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

        show_lines(display, "Geolocation", "Loading...")
        print("Connecting to ip-api.com (geolocation)...")
        location = fetch_location()
        show_location(display, location)
        print("Connecting to OpenWeatherMap...")
        weather = fetch_weather(location)

        show_weather(display, location, weather, 0)
        message = "%s: %.1f C, %s" % (
            location["city"], weather["temperature"], weather["description"])
        print("Connecting to ntfy.sh...")
        status, sent_at = send(message, title="Lab 4 weather")
        if status != 200:
            raise RuntimeError("ntfy returned HTTP %d" % status)
        show_lines(display, "Sent the weather", "information to", "ntfy!")

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


# =============================================================================
#                            MATHEMATICAL APPENDIX
# =============================================================================
#
# Every number below is computed from the constants at the top of this file.
# Change a constant and the matching result changes with it.
#
# Symbols
#     a      acceleration along one axis, in g  (1 g = 9.81 m/s^2)
#     theta  tilt angle of that axis away from horizontal
#     dt     time between two frames, in seconds
#     tau    filter time constant        = TILT_FILTER_SECONDS = 0.08 s
#     d      dead zone                   = DEAD_ZONE_G         = 0.20 g
#     Vmax   top scroll speed            = MAX_SPEED_PX_S      = 36 px/s
#     W, H   page width and height in pixels
#     x, y   position of the page's top-left corner in pixels
#
#
# M1. THE SPI COMMAND BYTE
# ------------------------
# The first byte of every ADXL345 transaction is laid out as
#
#     bit:    7      6     5  4  3  2  1  0
#           [R/W]  [MB]   [ register address ]
#
#     R/W = 1 to read, 0 to write          -> SPI_READ       = 0x80 = 1000 0000
#     MB  = 1 to continue into the next
#           registers automatically        -> SPI_MULTI_BYTE = 0x40 = 0100 0000
#
# The flags and the 6-bit address occupy different bits, so OR combines them:
#
#     burst read from DATAX0:  0x80 | 0x40 | 0x32
#                           =  1000 0000 | 0100 0000 | 0011 0010
#                           =  1111 0010  =  0xF2
#     single read of DEVID:    0x80 | 0x00  =  0x80
#     single write POWER_CTL:  0x2D            (bit 7 already 0)
#
# SPI "mode 3" (polarity = 1, phase = 1) means the clock idles HIGH and data is
# sampled on the rising edge, as the ADXL345 datasheet requires.
#
#
# M2. RAW COUNTS -> g
# -------------------
# Byte order. Each axis arrives as two bytes, low byte first (little-endian):
#
#     unsigned = low + 256 * high
#
# Sign. The value is in 16-bit two's complement:
#
#     value = unsigned             if unsigned <  32768
#     value = unsigned - 65536     if unsigned >= 32768
#
#     Example: bytes 0x00, 0xFF -> unsigned = 0 + 256 * 255 = 65280
#                               -> value    = 65280 - 65536  = -256
#
# Scale. DATA_FORMAT = 0x00 selects 10-bit resolution over the +/-2 g range.
# Ten bits give 2^10 = 1024 codes spread across 4 g:
#
#     1024 counts / 4 g  =  256 counts per g        (COUNTS_PER_G)
#     1 count            =  1/256 g  =  0.0039 g  =  3.9 mg
#
#     a = value / 256
#
#     Examples:  value =  256 -> a = +1.00 g   (axis pointing straight up)
#                value = -256 -> a = -1.00 g
#                value =   51 -> a ~  0.20 g   (edge of the dead zone)
#
#
# M3. THE LOW-PASS FILTER (smoothing the tilt)
# --------------------------------------------
# Goal: follow slow, deliberate tilts but ignore fast jitter.
#
# The continuous model is a first-order low-pass filter (the same equation as
# an RC circuit), with input u(t) and output f(t):
#
#     tau * df/dt + f = u
#
# Discretise it with the backward-Euler rule, df/dt ~ (f_new - f_old) / dt:
#
#     tau * (f_new - f_old) / dt + f_new = u
#     f_new * (tau + dt) = tau * f_old + dt * u
#     f_new = f_old + [dt / (tau + dt)] * (u - f_old)
#
# Naming the bracket alpha gives exactly the line in scroll_text():
#
#     alpha = dt / (tau + dt)
#     f_new = f_old + alpha * (u - f_old)
#
# Reading it: each frame the output moves a fraction alpha of the way from
# where it was to the new measurement. Since 0 <= alpha < 1 for any dt >= 0,
# the update can never overshoot or become unstable, whatever the frame rate.
#
# Numbers at the nominal frame time, dt = 0.033 s:
#
#     alpha = 0.033 / (0.08 + 0.033) = 0.033 / 0.113 = 0.292
#
#     Step response. If the tilt jumps from 0 to 1, the remaining error
#     shrinks by (1 - alpha) = 0.708 every frame:
#
#         frame   1      2      3      4      5      6      7
#         output  0.292  0.499  0.645  0.749  0.822  0.874  0.911
#
#         63 % is reached in about 3 frames (~0.10 s) and 90 % in about
#         7 frames (~0.23 s): quick enough to feel direct, slow enough to
#         swallow tremor.
#
#     Cutoff frequency of the continuous filter:
#
#         f_c = 1 / (2 * pi * tau) = 1 / (2 * 3.1416 * 0.08) = 1.99 Hz
#
#         Motion slower than ~2 Hz passes; hand tremor (roughly 8-12 Hz) and
#         sensor noise are strongly reduced.
#
# Why alpha is recomputed from dt each frame instead of being a constant: a
# fixed alpha smooths "per frame", so the filter would get slower whenever the
# frame rate dropped. Deriving alpha from the real dt keeps tau = 0.08 s true
# in real time.
#
#
# M4. TILT -> SPEED (dead zone, ramp, saturation)
# -----------------------------------------------
# Physics. Held still, the accelerometer measures only gravity. If an axis is
# raised by an angle theta above horizontal, the part of gravity along it is
#
#     a = sin(theta)     (in g)        so        theta = arcsin(a)
#
# Mapping implemented by axis_speed():
#
#               { 0                                          if |a| <= d
#     v(a)  =   { sign(a) * Vmax * (|a| - d) / (1 - d)       if d < |a| < 1
#               { sign(a) * Vmax                             if |a| >= 1
#
#     With d = 0.20 and Vmax = 36:   v = sign(a) * 45 * (|a| - 0.20)  px/s
#
#     Shape of the curve:
#
#         speed
#         +36 |                         ________
#             |                       /
#             |                     /
#           0 |________......_____/
#             |      /       ^
#             |    /         dead zone, -0.2 .. +0.2
#         -36 |__/
#             +----+----+----+----+----+----+---- a (g)
#                 -1  -0.2   0   0.2   1
#
# Why (|a| - d) / (1 - d): it is the straight line through the two points
# (d, 0) and (1, Vmax). Subtracting d makes the speed begin at 0 at the edge of
# the dead zone -- no sudden jump -- and dividing by (1 - d) stretches the
# remaining range so the top speed is still reached at exactly 1 g.
#
# Worked values:
#
#     tilt angle     a = sin(theta)     speed
#       0.0 deg          0.000            0.0 px/s
#      11.5 deg          0.200            0.0 px/s   <- dead zone ends here,
#      20.0 deg          0.342            6.4 px/s      arcsin(0.20) = 11.54 deg
#      30.0 deg          0.500           13.5 px/s
#      45.0 deg          0.707           22.8 px/s
#      60.0 deg          0.866           30.0 px/s
#      90.0 deg          1.000           36.0 px/s   <- full speed
#
# Because a = sin(theta), equal steps in angle give smaller and smaller steps
# in a near 90 degrees. The control is therefore most sensitive for small,
# comfortable tilts and gentle near vertical, which suits a handheld device.
#
#
# M5. SPEED -> POSITION (integration and wrap-around)
# ---------------------------------------------------
# Position is the integral of velocity. Over one frame (forward Euler):
#
#     x_new = (x_old + v_x * dt) mod W
#     y_new = (y_old + v_y * dt) mod H
#
# Multiplying by the measured dt is what makes the speed frame-rate
# independent: a frame twice as long moves the text twice as far, so the
# on-screen speed in px/s is unchanged.
#
#     Largest step in a normal frame:   36 px/s * 0.033 s = 1.19 px
#     Largest step ever (dt clamped):   36 px/s * 0.100 s = 3.6  px
#
# So the text never jumps more than a few pixels in one frame, even after a
# long pause -- this is the purpose of clamping dt to 0.10 s.
#
# x and y are kept as floats on purpose. A step of 1.19 px would be rounded
# to 1 px if stored as an integer, and slow speeds (under 1 px per frame)
# would be rounded to 0 and never move at all. The fractional part is carried
# from frame to frame and only truncated at the moment of drawing.
#
# The mod keeps x in [0, W) and y in [0, H). Python's % returns a non-negative
# result for a positive modulus, so moving left past 0 lands just under W:
#
#     (-1.19) mod 312 = 310.81
#
#
# M6. THE PAGE SIZE
# -----------------
# The page is the rectangle that repeats. With n lines, the longest holding L
# characters, an 8 px font, and a 12 px row pitch:
#
#     W = max(128, 8 * L + SCROLL_GAP_PX)
#     H = max(32, 12 * (n - 1) + 8)
#
#     Width:  8 * L is the text itself; the gap is the blank stretch between
#             the end of the text and the start of its repeat, so the two do
#             not run together.
#     Height: the last row starts at 12 * (n - 1) and is 8 px tall.
#     The max(...) with the screen size is REQUIRED for correct wrapping, as
#     shown in M7.
#
#     Example, the summary of this program (n = 3). If the longest line is
#     "Location: Lon -73.9626, Lat 40.8075" (L = 35):
#
#         W = max(128, 8 * 35 + 32) = max(128, 312) = 312 px
#         H = max(32, 12 * 2 + 8)   = max(32, 32)   =  32 px
#
#     The page is 2.4 screens wide and exactly one screen tall. At full speed
#     a complete horizontal lap takes 312 / 36 = 8.7 s.
#
#
# M7. WHY FOUR COPIES ARE ALWAYS ENOUGH
# -------------------------------------
# Work along x first. After the mod, the page corner is at ox with 0 <= ox < W.
# Two copies are drawn:
#
#     copy A occupies  [ox,     ox + W)
#     copy B occupies  [ox - W, ox)
#
# They touch at ox, so together they cover [ox - W, ox + W) with no hole.
# The screen occupies [0, 128). It lies inside that range when
#
#     ox - W <= 0      true, because ox < W
#     ox + W >= 128    true, because ox >= 0 and W >= 128   <- needs M6's max()
#
# So every screen column is covered by copy A or copy B. The identical
# argument holds along y with H >= 32. Two choices in x times two in y gives
#
#     (ox, oy)   (ox - W, oy)   (ox, oy - H)   (ox - W, oy - H)
#
# which are exactly the four passes of the nested loops in draw_wrapped_text().
#
#     Example: W = 312, ox = 200. Copy A covers [200, 512) and copy B covers
#     [-112, 200). On screen, columns 0..127 all come from copy B and show page
#     columns 112..239: the middle of the text. Copy A is entirely off-screen
#     and is clipped by the driver.
#
# If W were smaller than the screen (say W = 64), two copies would cover at
# most 2 * 64 = 128 columns only in the best case and would leave gaps in
# general; three or more copies would be needed. Forcing W >= 128 is what lets
# the code get away with a fixed count of four.
#
#
# M8. OLED TEXT GEOMETRY
# ----------------------
#     Screen 128 x 32 px, font 8 x 8 px, row pitch 12 px.
#
#     Characters per row:  128 / 8 = 16
#     Row positions:       y = 0, 12, 24
#     Bottom of last row:  24 + 8 = 32  -> exactly fills the screen
#     Gap between rows:    12 - 8 = 4 px
#
#     A fourth row would start at y = 36, below the screen, which is why
#     show_lines() draws at most three.
#
#
# M9. THE AUTOMATIC MARQUEE IN show_weather()
# -------------------------------------------
# For a description of n characters, with speed s = TEXT_SPEED_PX_S = 16 px/s
# and t = elapsed_ms:
#
#     period = 8 * n + 16                  text width plus a 16 px blank gap
#     shift  = floor(t * s / 1000) mod period
#
#     copy 1 is drawn at x = -shift
#     copy 2 is drawn at x = period - shift
#
# The two copies are always exactly one period apart, so as copy 1 slides off
# the left edge, copy 2 arrives from the right. When shift wraps from
# period - 1 back to 0, copy 2 has reached the spot where copy 1 started, so
# the picture is identical and the loop has no visible seam.
#
# Two copies are sufficient because the text is wider than the screen in this
# branch: n > 16 gives period >= 8 * 17 + 16 = 152 > 128 (same reasoning as M7).
#
#     Example: "overcast clouds with light rain" (n = 31)
#         period   = 8 * 31 + 16 = 264 px
#         one loop = 264 / 16    = 16.5 s
#         at t = 5000 ms: shift = floor(5000 * 16 / 1000) mod 264 = 80
#                         copy 1 at x = -80, copy 2 at x = 184 (off-screen)
#
# The shift is a pure function of t; no position is stored between calls.
#
#
# M10. TIME, TIMESTAMPS AND OTHER SMALL CALCULATIONS
# --------------------------------------------------
# Local time of day (build_summary).
#
#     local = (utc_seconds + offset) mod 86400       86400 = 24 * 60 * 60
#     hours   = local div 3600
#     minutes = (local mod 3600) div 60
#     seconds = local mod 60
#
#     Example: UTC time of day 18:07:52 = 65272 s, offset = -14400 s (UTC-4)
#         local = (65272 - 14400) mod 86400 = 50872
#         hours   = 50872 div 3600        = 14
#         minutes = (50872 mod 3600) / 60 = 472 div 60 = 7
#         seconds = 50872 mod 60          = 52             -> "14:07:52"
#
#     Wrap past midnight: UTC 02:00:00 = 7200 s with offset -14400 s gives
#         (7200 - 14400) mod 86400 = (-7200) mod 86400 = 79200 s = 22:00:00
#     on the previous day, which is correct.
#
# Why the epoch does not matter. NTP counts seconds from 1900-01-01, Unix (and
# ntfy.sh) from 1970-01-01, and some MicroPython ports from 2000-01-01. All
# three start at midnight UTC, so they differ by whole days:
#
#     1900 -> 1970:  25567 days * 86400 = 2 208 988 800 s
#     1970 -> 2000:  10957 days * 86400 =   946 684 800 s
#
#     (25567 = 70 * 365 + 17 leap days;  10957 = 30 * 365 + 7 leap days)
#
# A multiple of 86400 vanishes under "mod 86400":
#
#     (T + k * 86400) mod 86400 = T mod 86400
#
# so the time of day comes out the same from any of these epochs. That is why
# an NTP timestamp and an ntfy timestamp can be passed to build_summary()
# interchangeably, with no conversion. (This would NOT work for the date.)
#
# The NTP request byte (ntp_utc_seconds).
#
#     0x1B = 0001 1011 = [00][011][011]
#                         LI  VN   Mode
#     LI   = 0  no leap-second warning
#     VN   = 3  protocol version 3
#     Mode = 3  client
#
#     In the 48-byte reply, the transmit timestamp is bytes 40..47:
#     bytes 40..43 are whole seconds (unsigned, big-endian) and bytes 44..47
#     are the fraction of a second, which this program ignores.
#
#         seconds = b40 * 2^24 + b41 * 2^16 + b42 * 2^8 + b43
#
# Frame timing (scroll_text).
#
#     frame rate = 1000 / FRAME_MS = 1000 / 33 = 30.3 frames per second
#     sleep      = 33 ms - (time spent reading, computing and drawing)
#
#     If a frame takes longer than 33 ms the sleep is skipped and the next
#     frame starts at once; dt grows to match, so the scroll speed stays right.
#
# Wi-Fi polling (wait_for_wifi).
#
#     WIFI_TIMEOUT_MS / poll interval = 30000 / 200 = 150 status checks at most.
#
# Coordinate precision (weather_url, "%.4f").
#
#     One degree of latitude is about 111 km, so 0.0001 degree is about 11 m.
#     Four decimals is far finer than IP geolocation can deliver (kilometres),
#     so nothing is lost by rounding.
#
# Percent-encoding (quote_query).
#
#     A byte b outside the unreserved set becomes "%" followed by b written as
#     two uppercase hexadecimal digits:
#
#         space = 32  = 0x20 -> %20
#         "&"   = 38  = 0x26 -> %26
#         "e" with acute accent = UTF-8 bytes 0xC3 0xA9 -> %C3%A9
#
# =============================================================================
