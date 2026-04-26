from src.ingest.zh_normalize import to_simplified


def test_traditional_to_simplified():
    assert to_simplified("總收入") == "总收入"
    assert to_simplified("騰訊2025年度報告") == "腾讯2025年度报告"


def test_simplified_passthrough():
    assert to_simplified("总收入") == "总收入"


def test_empty_passthrough():
    assert to_simplified("") == ""


def test_mixed_with_ascii_and_numbers():
    out = to_simplified("Q3 營收 6,605 億")
    assert "营收" in out
    assert "6,605" in out
