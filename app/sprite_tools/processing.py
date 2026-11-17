"""Independent CPU image operations; Pillow is imported only on a call."""
import os,hashlib
from typing import Optional,Dict,Any

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _parse_hex_color(color_str: str) -> tuple:
    s = color_str.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        raise ValueError(f"Invalid hex color: {color_str!r}, expected #RRGGBB")
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        raise ValueError(f"Invalid hex color: {color_str!r}")
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        raise ValueError(f"Color channel out of range: {color_str!r}")
    return (r, g, b)

def pixelize(
    input_path: str,
    work_root: str,
    grid_width: int,
    grid_height: int,
    palette_colors: int,
    export_scale: int,
    remove_background: bool,
    background_color: Optional[str],
    result_dir: Optional[str] = None,
) -> Dict[str, Any]:
    from PIL import Image

    with Image.open(input_path) as source:
        img = source.convert("RGBA")

    if remove_background:
        if background_color is None:
            raise ValueError("background_color required when remove_background is true")
        bg = _parse_hex_color(background_color)
        data = list(img.getdata())
        new_data = []
        for r, g, b, a in data:
            if a > 0:
                dist = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
                if dist <= 80:
                    new_data.append((0, 0, 0, 0))
                else:
                    new_data.append((r, g, b, a))
            else:
                new_data.append((0, 0, 0, 0))
        img.putdata(new_data)

    ratio = min(grid_width / img.width, grid_height / img.height)
    size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    fitted = img.resize(size, Image.Resampling.BOX)
    small = Image.new("RGBA", (grid_width, grid_height), (0, 0, 0, 0))
    small.paste(fitted, ((grid_width-size[0])//2, (grid_height-size[1])//2))
    small_data = list(small.getdata())
    thresholded = []
    for r, g, b, a in small_data:
        if a > 128:
            thresholded.append((r, g, b, 255))
        else:
            thresholded.append((0, 0, 0, 0))
    small.putdata(thresholded)

    opaque_indices = []
    opaque_colors = []
    for i, (r, g, b, a) in enumerate(small.getdata()):
        if a == 255:
            opaque_indices.append(i)
            opaque_colors.append((r, g, b))

    if opaque_colors:
        rgb_img = Image.new("RGB", (grid_width, grid_height), (0, 0, 0))
        rgb_data = list(rgb_img.getdata())
        for idx, (r, g, b) in zip(opaque_indices, opaque_colors):
            rgb_data[idx] = (r, g, b)
        rgb_img.putdata(rgb_data)
        n_colors = min(palette_colors, 256)
        quantized = rgb_img.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q_rgb = quantized.convert("RGB")
        q_data = list(q_rgb.getdata())
        final_data = list(small.getdata())
        for idx in opaque_indices:
            r, g, b = q_data[idx]
            final_data[idx] = (r, g, b, 255)
        small.putdata(final_data)

    actual_colors = set()
    for r, g, b, a in small.getdata():
        if a == 255:
            actual_colors.add((r, g, b))
    actual_palette = ["#{:02X}{:02X}{:02X}".format(r, g, b) for r, g, b in sorted(actual_colors)]

    if result_dir is None:
        raise ValueError("An explicit output directory is required")
    os.makedirs(result_dir, exist_ok=True)
    sprite_path = os.path.join(result_dir, f"sprite_{grid_width}x{grid_height}.png")
    small.save(sprite_path, "PNG")
    sprite_sha = _sha256_file(sprite_path)
    sprite_bytes = os.path.getsize(sprite_path)

    export_w = grid_width * export_scale
    export_h = grid_height * export_scale
    export_img = small.resize((export_w, export_h), Image.Resampling.NEAREST)
    export_path = os.path.join(result_dir, f"sprite_{grid_width}x{grid_height}_x{export_scale}.png")
    export_img.save(export_path, "PNG")
    export_sha = _sha256_file(export_path)
    export_bytes = os.path.getsize(export_path)

    alpha_values = sorted(set(a for r, g, b, a in small.getdata()))

    return {
        "sprite_path": os.path.relpath(sprite_path, work_root),
        "sprite_sha256": sprite_sha,
        "sprite_bytes": sprite_bytes,
        "sprite_width": grid_width,
        "sprite_height": grid_height,
        "export_path": os.path.relpath(export_path, work_root),
        "export_sha256": export_sha,
        "export_bytes": export_bytes,
        "export_width": export_w,
        "export_height": export_h,
        "actual_palette_colors": len(actual_palette),
        "palette": actual_palette,
        "alpha_values": alpha_values,
    }

def inspect_image(path: str) -> dict:
    from PIL import Image
    with Image.open(path) as source:
        mode = source.mode
        image = source.convert('RGBA')
    alpha = image.getchannel('A')
    histogram = alpha.histogram()
    total = image.width * image.height
    return {'mode': mode, 'width': image.width, 'height': image.height,
            'alpha_min': alpha.getextrema()[0], 'alpha_max': alpha.getextrema()[1],
            'transparent_pixels': histogram[0], 'opaque_pixels': histogram[255],
            'transparency_fraction': histogram[0] / total,
            'has_transparent_background_candidate': histogram[0] > 0 and histogram[255] > 0,
            'fully_opaque': histogram[255] == total,
            'semantic_acceptance': 'not_reviewed'}



def observation_preview(input_path: str, work_root: str) -> dict:
    """Derived nearest-neighbor view on light/dark backgrounds; preserve source."""
    from pathlib import Path
    from PIL import Image
    import io
    source = Path(input_path)
    source_sha = _sha256_file(str(source))
    with Image.open(source) as loaded:
        image = loaded.convert('RGBA')
    scale = 4 if max(image.size) <= 256 else 1
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    canvas = Image.new('RGB', (image.width * 2, image.height), '#eeeeee')
    canvas.paste(Image.new('RGB', image.size, '#303030'), (image.width, 0))
    canvas.paste(image, (0, 0), image)
    canvas.paste(image, (image.width, 0), image)
    output = io.BytesIO(); canvas.save(output, format='PNG')
    data = output.getvalue()
    import hashlib
    digest = hashlib.sha256(data).hexdigest()
    relative = Path('results/observations') / (digest + '.png')
    destination = Path(work_root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('xb') as handle:
            handle.write(data)
    except FileExistsError:
        if _sha256_file(str(destination)) != digest:
            raise ValueError('Existing observation preview SHA mismatch')
    return {'path': str(relative), 'sha256': digest,
            'label': f'DERIVED PREVIEW, nearest-neighbor x{scale}; left light background, right dark. Source SHA256 {source_sha}. Not a new generation.'}
