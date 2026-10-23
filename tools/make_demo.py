#!/usr/bin/env python3
"""Generate an original, deterministic 4827 PNG using only Python stdlib."""
from pathlib import Path
import struct
import zlib


def png_bytes():
    width, height = 360, 120
    pixels = bytearray([255]) * (width * height)
    segments = {'4': 'bcfg', '8': 'abcdefg', '2': 'abdeg', '7': 'abc'}
    rectangles = {
        'a': (10, 0, 50, 9), 'b': (50, 9, 59, 44),
        'c': (50, 48, 59, 83), 'd': (10, 83, 50, 92),
        'e': (1, 48, 10, 83), 'f': (1, 9, 10, 44),
        'g': (10, 42, 50, 51),
    }
    for index, digit in enumerate('4827'):
        left, top = 30 + index * 80, 14
        for segment in segments[digit]:
            x1, y1, x2, y2 = rectangles[segment]
            for y in range(top + y1, top + y2):
                for x in range(left + x1, left + x2):
                    pixels[y * width + x] = 0

    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)

    rows = b''.join(b'\0' + pixels[y * width:(y + 1) * width] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / 'examples' / 'demo.png'
    destination.write_bytes(png_bytes())
    print('Generated synthetic demo.png: 4827, 360 x 120 pixels.')
