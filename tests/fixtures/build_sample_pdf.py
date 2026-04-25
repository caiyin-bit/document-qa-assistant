"""Run once to create tests/fixtures/sample_zh.pdf and sample_empty.pdf for unit tests."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

FIXTURES = Path(__file__).parent


def build_zh():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    out = FIXTURES / "sample_zh.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setFont("STSong-Light", 14)

    pages = [
        "第一页：腾讯 2025 年总营业收入为 6,605 亿元，同比增长 10.2%。",
        "第二页：本页空白用于测试空页跳过。",
        "第三页：金融科技及企业服务业务收入达到 2,134 亿元。",
    ]
    for text in pages:
        c.drawString(80, 750, text)
        c.showPage()
    c.save()
    return out


def build_empty():
    """A syntactically valid PDF with 0 pages."""
    out = FIXTURES / "sample_empty.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    # no showPage → 0 pages
    c.save()
    return out


if __name__ == "__main__":
    print("Built", build_zh())
    print("Built", build_empty())
