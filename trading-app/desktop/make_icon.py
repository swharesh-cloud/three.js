"""Draws the 1024x1024 app icon (a rising price line on a teal tile)."""
import sys

from PIL import Image, ImageDraw

out = sys.argv[1] if len(sys.argv) > 1 else "icon.png"
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((80, 80, S - 80, S - 80), radius=190, fill=(15, 118, 110, 255))
pts = [(220, 700), (360, 560), (460, 620), (600, 420), (700, 480), (820, 280)]
d.line(pts, fill=(255, 255, 255, 255), width=56, joint="curve")
for x, y in (pts[0], pts[-1]):
    d.ellipse((x - 40, y - 40, x + 40, y + 40), fill=(255, 255, 255, 255))
img.save(out)
