"""QR codes for the APK download link: an SVG for the web portal, text for the terminal."""

import os
import sys

import qrcode
import qrcode.image.svg


def write(url, svg_path):
    """Save url as an SVG QR code."""
    # Path-based SVG: one element, scales cleanly, no image library needed.
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    # Written next to it and swapped in whole: the portal may be sending the old one right now.
    img.save(svg_path + ".tmp")
    os.replace(svg_path + ".tmp", svg_path)


def show(url):
    """Print url as a QR code a phone camera can read off the terminal."""
    q = qrcode.QRCode(border=2)
    q.add_data(url)
    # Inverted so it reads on dark terminal themes too.
    q.print_ascii(out=sys.stdout, invert=True)


if __name__ == "__main__":
    # python3 -m opendmtq_tools.qr <url>
    show(sys.argv[1])
