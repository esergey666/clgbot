"""Small printer-style 5 x 7 decimal alphabet used below EAN bars.

Draw whole square cells, without antialiasing. A zero has a diagonal;
this affects only the human-readable legend, never encoded barcode data.
"""
from PIL import ImageDraw

DIGITS = {
    '0': ('01110','10001','10011','10101','11001','10001','01110'),
    '1': ('00100','01100','00100','00100','00100','00100','01110'),
    '2': ('01110','10001','00001','00110','01000','10000','11111'),
    '3': ('11110','00001','00001','01110','00001','00001','11110'),
    '4': ('00010','00110','01010','10010','11111','00010','00010'),
    '5': ('11111','10000','11110','00001','00001','10001','01110'),
    '6': ('00110','01000','10000','11110','10001','10001','01110'),
    '7': ('11111','00001','00001','00010','00100','00100','00100'),
    '8': ('01110','10001','10001','01110','10001','10001','01110'),
    '9': ('01110','10001','10001','01111','00001','00010','01100'),
}


def draw_digits(image, value, x, y, cell=5):
    draw = ImageDraw.Draw(image)
    for index, char in enumerate(value):
        for row, bits in enumerate(DIGITS[char]):
            for column, bit in enumerate(bits):
                if bit == '1':
                    left, top = x + (index * 6 + column) * cell, y + row * cell
                    draw.rectangle((left, top, left + cell - 1, top + cell - 1), fill='black')
