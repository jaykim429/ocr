from chandra.review import build_review_text, strip_markdown_fence


def test_strip_markdown_fence():
    assert strip_markdown_fence("```markdown\n# Title\n```") == "# Title"
    assert strip_markdown_fence("plain text") == "plain text"


def test_build_review_text_trims_long_input():
    review_text = build_review_text("a" * 200, html="<p>hello</p>", max_input_chars=80)

    assert "OCR Markdown" in review_text
    assert "OCR HTML/layout reference" in review_text
    assert "middle omitted" in review_text
