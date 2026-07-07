from PIL import Image, ImageDraw, ImageFont
import textwrap

W, H = 1280, 720
img = Image.new("RGB", (W, H), (10, 22, 40))
draw = ImageDraw.Draw(img)

for y in range(H):
    r = int(10 + (y / H) * 30)
    g = int(22 + (y / H) * 20)
    b = int(40 + (y / H) * 25)
    draw.line([(0, y), (W, y)], fill=(r, g, b))

top_bar = Image.new("RGBA", (W, 4), (60, 120, 60, 60))
img.paste(top_bar, (0, 0), top_bar)

bottom_bar = Image.new("RGBA", (W, 180), (0, 0, 0, 140))
img.paste(bottom_bar, (0, H - 180), bottom_bar)

decorative = Image.new("RGBA", (W, 2), (180, 220, 180, 80))
img.paste(decorative, (0, H - 185), decorative)

try:
    font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 72)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
except:
    font_large = ImageFont.load_default()
    font_small = font_large

line1 = "﷽"
bbox1 = draw.textbbox((0, 0), line1, font=font_large)
draw.text(((W - bbox1[2]) // 2, 80), line1, fill=(200, 200, 180), font=font_large)

line2 = "Quran Live"
bbox2 = draw.textbbox((0, 0), line2, font=font_large)
draw.text(((W - bbox2[2]) // 2, H // 2 - 40), line2, fill=(220, 230, 210), font=font_large)

line3 = "24/7 Recitation"
bbox3 = draw.textbbox((0, 0), line3, font=font_small)
draw.text(((W - bbox3[2]) // 2, H // 2 + 30), line3, fill=(160, 180, 150), font=font_small)

line4 = "SoundCloud → YouTube"
bbox4 = draw.textbbox((0, 0), line4, font=font_small)
draw.text(((W - bbox4[2]) // 2, H - 100), line4, fill=(120, 140, 120), font=font_small)

img.save("/tmp/thumbnail.png", "PNG")
print("Thumbnail saved: /tmp/thumbnail.png")
