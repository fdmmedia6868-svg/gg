from app.srt_parser import merge_short_subtitles, parse_srt


def test_parse_srt_and_merge_short_lines():
    content = """1\n00:00:00,200 --> 00:00:01,000\nXin chao\n\n2\n00:00:01,100 --> 00:00:03,000\nNguoi que\n"""
    parsed = parse_srt(content)
    merged = merge_short_subtitles(parsed)
    assert len(parsed) == 2
    assert len(merged) == 1
    assert merged[0].start_ms == 200
    assert merged[0].end_ms == 3000
