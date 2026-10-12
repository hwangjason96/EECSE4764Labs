#Part 2 Task 1: Connect your ESP32 to the internet.
from machine import Pin, I2C, RTC, SPI
import ssd1306, network, time

def do_connect():
    wlan = network.WLAN(network.WLAN.IF_STA)
    wlan.active(True)
    active_networks = wlan.scan()
    dec = 0
    for networks in active_networks:
        if networks[3] < -75 :
            continue
        for i in range (0,6):
            if i == 0:
                print(dec+1,": ssid:", networks[i])
            elif i == 1:
                print("bssid:", networks[i])
            elif i == 2:
                print("channel:", networks[i])
            elif i == 3:
                print("RSSI:", networks[i])
            elif i == 4:
                print("authmode:", networks[i])
            elif i == 5:
                print("hidden:", networks[i])
        print("\n")
        dec+=1
    
    try:
        user_decision = int(input("Choose among these networks: "))

    except ValueError:
        print("Not a number, try again!")
        return
    
    if (dec+1) - user_decision < 0 or user_decision < 1:
        print("Not a valid network in the list!")

    else:
        networkSSID = active_networks[(user_decision-1)][0]
        wlan.connect(networkSSID)
        if not wlan.isconnected():
            print('connecting to network...')
            print("Not able to connect to the network, something went wrong!")
        else:
            print("Connected to", wlan.config("ssid"))


def main():
    # wlan = network.WLAN(network.WLAN.IF_STA)
    # if wlan.isconnected():
    #     print("Already connected to the network: ", wlan.config("ssid"))
    # else:
    #     do_connect()
    from machine import Pin, SPI, I2C
    import time

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
    text_input = input("Enter a text:")
    padding_string = ""
    for i in range(len(text_input)-1):
        padding_string += " "
    text_string = ("\t" + padding_string + text_input + "\n" +
                    text_input + "\t" + text_input + "\t" + text_input + "\n\t" +
                        padding_string + text_input + "\n")
    
    while True:
        x, y, z = read_accel()
        display.fill(0)
        display.text(text_string,-x,y,z+1)
        time.sleep(0.1)

main()