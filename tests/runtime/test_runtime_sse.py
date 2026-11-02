from relay.runtime.sse import SseFrame, parse_sse


def test_frames_split_on_blank_lines_with_fields_and_comments() -> None:
    lines = [
        ": keep-alive",
        "id: 7",
        "event: message",
        'data: {"a":',
        "data:  1}",
        "",
        "data: tail",
    ]

    assert list(parse_sse(lines)) == [
        SseFrame("7", "message", '{"a":\n 1}'),
        SseFrame(None, None, "tail"),
    ]


def test_blocks_without_data_are_skipped() -> None:
    assert list(parse_sse(["event: ping", "", "", "id: 3", ""])) == []
