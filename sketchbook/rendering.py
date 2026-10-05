"""Side-effect-free renderer used by both the preview and the chat service."""
from io import BytesIO
from PIL import Image, ImageColor
from image_fit_paste import paste_image_auto
from text_fit_draw import draw_text_auto


def render(library, character, expression, text='', content=None):
    layout = library.validate_expression(character, expression)
    base = str(library.asset(character, expression['image']))
    overlay = str(library.asset(character, layout['overlay'])) if layout.get('overlay') else None
    font = str(library.asset(character, layout['font'])) if layout.get('font') else None
    x1, y1, x2, y2 = layout['region']

    def draw(source, region, top_overlay):
        a, b, c, d = region
        return draw_text_auto(source, (a, b), (c, d), text,
            color=ImageColor.getrgb(layout['color']), max_font_height=layout['max_font_size'],
            font_path=font, align=layout['align'], valign=layout['valign'],
            line_spacing=layout['line_spacing'], image_overlay=top_overlay,
            wrap_algorithm=layout.get('wrap_algorithm', 'original'))

    def paste(region, top_overlay):
        a, b, c, d = region
        padding = min(12, max(0, (min(c-a, d-b)-1)//4))
        return paste_image_auto(base, (a, b), (c, d), content, padding=padding,
                                allow_upscale=True, image_overlay=top_overlay)

    if content is None:
        if text:
            return draw(base, layout['region'], overlay)
        with Image.open(base) as image:
            image = image.convert('RGBA')
            if overlay:
                with Image.open(overlay) as layer:
                    image.alpha_composite(layer.convert('RGBA'))
            buffer = BytesIO()
            image.save(buffer, 'PNG')
            return buffer.getvalue()
    if not text:
        return paste(layout['region'], overlay)
    width, height = x2-x1, y2-y1
    if width < 4 or height < 4:
        raise ValueError('图文混排需要更大的区域')
    if content.height * width / height > content.width:
        spacing = min(10, width//4)
        split = x1 + (width-spacing)//2
        image_region, text_region = (x1,y1,split,y2), (split+spacing,y1,x2,y2)
    else:
        split = y2 - min(height//2,100)
        image_region, text_region = (x1,y1,x2,split), (x1,split,x2,y2)
    return draw(BytesIO(paste(image_region, None)), text_region, overlay)
