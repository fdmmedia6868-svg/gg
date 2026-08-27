import re
from dataclasses import dataclass


@dataclass
class Subtitle:
    start_ms: int
    end_ms: int
    text: str


def time_to_ms(value: str) -> int:
    hours, minutes, seconds, millis = map(int, re.split(r"[:,]", value.strip()))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_srt(content: str) -> list[Subtitle]:
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    subtitles: list[Subtitle] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (part.strip() for part in lines[1].split("-->", 1))
        subtitles.append(Subtitle(time_to_ms(start), time_to_ms(end), " ".join(lines[2:]).strip()))
    return subtitles


def merge_short_subtitles(subtitles: list[Subtitle], threshold_ms: int = 2000, target_ms: int = 6000) -> list[Subtitle]:
    merged: list[Subtitle] = []
    for subtitle in subtitles:
        if merged and subtitle.end_ms - merged[-1].start_ms <= target_ms and subtitle.start_ms - merged[-1].end_ms <= 500:
            merged[-1].end_ms = subtitle.end_ms
            merged[-1].text = f"{merged[-1].text} {subtitle.text}".strip()
        elif subtitle.end_ms - subtitle.start_ms < threshold_ms and merged:
            merged[-1].end_ms = subtitle.end_ms
            merged[-1].text = f"{merged[-1].text} {subtitle.text}".strip()
        else:
            merged.append(Subtitle(subtitle.start_ms, subtitle.end_ms, subtitle.text))
    return merged
