from PIL import Image
import re

# Configuration
IMAGE_PATH = "ascii-art (1).jpg"
WIDTH = 130  # Matches the horizontal layout scale of your templates
ASCII_CHARS = " .:-=+*#%@"

def image_to_ascii(image_path):
    img = Image.open(image_path).convert("L")
    # Aspect ratio correction for terminal/mono fonts
    aspect_ratio = img.height / img.width
    new_height = int(WIDTH * aspect_ratio * 0.55)
    img = img.resize((WIDTH, new_height))
    
    pixels = img.getdata()
    chars = "".join([ASCII_CHARS[pixel * len(ASCII_CHARS) // 256] for pixel in pixels])
    
    # Split into lines
    lines = [chars[i:i + WIDTH] for i in range(0, len(chars), WIDTH)]
    return lines

def update_svg_template(template_path, ascii_lines):
    with open(template_path, "r", encoding="utf-8") as f:
        svg_content = f.read()
    
    # Target the text rows inside the SVG <g> blocks
    pattern = r'(<text x="24" y="[\d\.]+" textLength="260" lengthAdjust="spacingAndGlyphs" font-family="[^"]+" font-size="4" fill="[^"]+" xml:space="preserve">)(.*?)(</text>)'
    
    matches = list(re.finditer(pattern, svg_content))
    
    if not matches:
        print(f"No matching text lines found in {template_path}")
        return

    new_svg_content = svg_content
    for i, match in enumerate(matches):
        if i < len(ascii_lines):
            line_content = ascii_lines[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            replacement = match.group(1) + line_content + match.group(3)
            new_svg_content = new_svg_content.replace(match.group(0), replacement, 1)
        else:
            replacement = match.group(1) + (" " * 50) + match.group(3)
            new_svg_content = new_svg_content.replace(match.group(0), replacement, 1)
            
    with open(template_path, "w", encoding="utf-8") as f:
        f.write(new_svg_content)
    print(f"Successfully updated {template_path}")

if __name__ == "__main__":
    ascii_art_lines = image_to_ascii(IMAGE_PATH)
    update_svg_template("templates/overview_dark.svg", ascii_art_lines)
    update_svg_template("templates/overview_light.svg", ascii_art_lines)