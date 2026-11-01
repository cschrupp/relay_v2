from pathlib import Path
from typing import Any

import pytest
import yaml

from relay.domain import LineEstimate, PacketError, WorkPacket, load_work_packet

FIXTURE = Path(__file__).with_name("packet.yaml")


def packet_data(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(FIXTURE.read_text())
    data.update(changes)
    return {key: value for key, value in data.items() if value is not ...}


def write_packet(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "packet.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_loads_the_fixture_packet() -> None:
    packet = load_work_packet(FIXTURE)

    assert packet.goal == "Add relay drift report"
    assert packet.base_sha == "988b8b9"
    assert packet.allowed_paths == ("src/relay/drift/**", "tests/drift/**")
    assert packet.expected_lines == LineEstimate(source=400, tests=300)
    assert (packet.role, packet.tier, packet.token_budget) == ("implementer", "cheap", 200000)


def test_round_trips_through_json_and_yaml(tmp_path: Path) -> None:
    packet = load_work_packet(FIXTURE)

    assert WorkPacket.model_validate_json(packet.model_dump_json()) == packet
    assert load_work_packet(write_packet(tmp_path, packet.model_dump(mode="json"))) == packet


def test_packets_are_immutable() -> None:
    packet = load_work_packet(FIXTURE)

    with pytest.raises(ValueError):
        packet.goal = "something else"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"goal": ...}, "goal"),
        ({"goal": "   "}, "goal"),
        ({"base_sha": "not-a-sha"}, "base_sha"),
        ({"base_sha": "ABCDEF1"}, "base_sha"),
        ({"base_sha": 1234567}, "quoted string"),
        ({"allowed_paths": []}, "allowed_paths"),
        ({"allowed_paths": ["/etc/passwd"]}, "must be relative"),
        ({"allowed_paths": ["src/../../x"]}, "must be relative"),
        ({"expected_lines": {"source": -1, "tests": 0}}, "expected_lines.source"),
        ({"expected_lines": 300}, "expected_lines"),
        ({"acceptance_commands": []}, "acceptance_commands"),
        ({"token_budget": 0}, "token_budget"),
        ({"role": "manager"}, "role"),
        ({"tier": "medium"}, "tier"),
        ({"surprise": True}, "surprise"),
    ],
)
def test_invalid_packets_are_rejected(
    tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    path = write_packet(tmp_path, packet_data(**changes))

    with pytest.raises(PacketError, match=message):
        load_work_packet(path)


@pytest.mark.parametrize("text", ["- a list\n", "just text\n", "key: [unclosed\n"])
def test_non_mapping_or_broken_yaml_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "packet.yaml"
    path.write_text(text)

    with pytest.raises(PacketError, match=str(path)):
        load_work_packet(path)


def test_missing_file_is_a_packet_error(tmp_path: Path) -> None:
    with pytest.raises(PacketError, match="cannot read"):
        load_work_packet(tmp_path / "missing.yaml")
