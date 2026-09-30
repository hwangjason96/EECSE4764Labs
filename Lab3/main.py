from machine import Pin, I2C
import ssd1306
# using default address 0x3C
i2c = I2C(sda=Pin(23), scl=Pin(22))
display = ssd1306.SSD1306_I2C(128, 32, i2c)
print([hex(a) for a in i2c.scan()])
# Print Hello World on the first line:
display.text('Hello, World!', 0, 0, 1)
display.show()
