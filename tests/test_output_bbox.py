from PIL import Image

from chandra.output import parse_chunks


def test_parse_chunks_accepts_comma_separated_bbox():
    image = Image.new("RGB", (200, 100), "white")
    html = '<div data-label="Text" data-bbox="[10, 20, 110, 70]">hello</div>'

    chunks = parse_chunks(html, image, bbox_scale=1000)

    assert chunks[0]["bbox"] == [2, 2, 22, 7]
