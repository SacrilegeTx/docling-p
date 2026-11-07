from types import SimpleNamespace

from ocr_markdown import IMAGE_EXTENSIONS, document_markdown, image_markdown


class FakeDocument:
    """Mimics a DoclingDocument whose OCR text sits inside a detected picture."""

    def __init__(self):
        self.export_calls = []

    def export_to_markdown(self, **kwargs):
        self.export_calls.append(kwargs)
        if kwargs.get("traverse_pictures"):
            return "<!-- image -->\n\nCódigo de ubigeo"
        return "<!-- image -->"


class FakeConverter:
    def __init__(self):
        self.document = FakeDocument()
        self.converted = []

    def convert(self, source):
        self.converted.append(source)
        return SimpleNamespace(document=self.document)


def test_png_is_a_supported_image_extension():
    assert ".png" in IMAGE_EXTENSIONS


def test_image_markdown_keeps_the_text_found_inside_pictures(tmp_path):
    source = tmp_path / "tramos.png"
    converter = FakeConverter()

    markdown = image_markdown(converter, source)

    assert converter.converted == [str(source)]
    assert converter.document.export_calls == [{"traverse_pictures": True}]
    assert markdown == "<!-- image -->\n\nCódigo de ubigeo"


def test_document_markdown_keeps_picture_text_when_ocr_ran():
    document = FakeDocument()

    markdown = document_markdown(document, keep_picture_text=True)

    assert document.export_calls == [{"traverse_pictures": True}]
    assert markdown == "<!-- image -->\n\nCódigo de ubigeo"


def test_document_markdown_without_ocr_uses_the_default_export():
    document = FakeDocument()

    markdown = document_markdown(document, keep_picture_text=False)

    assert document.export_calls == [{}]
    assert markdown == "<!-- image -->"
