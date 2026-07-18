from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class MappingError(Exception):
    """Base exception for mapping errors."""


class MappingNotFoundError(MappingError):
    """No mapping section found in runinfo."""


class DuplicateMappingError(MappingError):
    """Duplicate pmt_id detected in mapping."""


class ChannelNotMappedError(MappingError):
    """A channel cannot be resolved to a pmt_id."""


@dataclass
class ChannelMapping:
    board_id: int
    channel_id: int
    pmt_id: str
    signal: str = ""


@dataclass
class MappingTable:
    entries: List[ChannelMapping] = field(default_factory=list)
    _by_key: Dict[Tuple[int, int], ChannelMapping] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for e in self.entries:
            self._by_key[(e.board_id, e.channel_id)] = e

    def lookup(self, board_id: int, channel_id: int) -> Optional[ChannelMapping]:
        return self._by_key.get((board_id, channel_id))

    def get_pmt_id(self, board_id: int, channel_id: int) -> Optional[str]:
        entry = self.lookup(board_id, channel_id)
        return entry.pmt_id if entry else None

    def all_pmt_ids(self) -> List[str]:
        return [e.pmt_id for e in self.entries]


def parse_mapping(raw_mapping: List[Dict[str, Any]]) -> MappingTable:
    """Parse the 'mapping' section from runinfo.json into a MappingTable.

    Supports two formats:
    - Nested: mapping[].channels[].ch + mapping[].channels[].pmt
    - Flat:   mapping[].channel_id[] + mapping[].pmt_id[]
    """
    if not raw_mapping:
        raise MappingNotFoundError("Mapping section is empty or missing")

    entries: List[ChannelMapping] = []

    for board_entry in raw_mapping:
        board_id = board_entry.get("board_id")
        if board_id is None:
            raise MappingError("board_id missing in mapping entry")
        board_id = int(board_id)

        signal = board_entry.get("signal", "")

        # Format 1: nested channels
        if "channels" in board_entry and isinstance(board_entry["channels"], list):
            for ch_obj in board_entry["channels"]:
                ch_id = ch_obj.get("ch")
                pmt = ch_obj.get("pmt")
                if ch_id is None or pmt is None:
                    raise MappingError(
                        f"Missing 'ch' or 'pmt' in board {board_id} channel entry"
                    )
                entries.append(ChannelMapping(
                    board_id=board_id,
                    channel_id=int(ch_id),
                    pmt_id=str(pmt),
                    signal=signal,
                ))

        # Format 2: parallel arrays
        elif "channel_id" in board_entry and "pmt_id" in board_entry:
            ch_ids = board_entry["channel_id"]
            pmt_ids = board_entry["pmt_id"]
            if len(ch_ids) != len(pmt_ids):
                raise MappingError(
                    f"channel_id/pmt_id length mismatch for board {board_id}: "
                    f"{len(ch_ids)} vs {len(pmt_ids)}"
                )
            for ch_id, pmt in zip(ch_ids, pmt_ids):
                entries.append(ChannelMapping(
                    board_id=board_id,
                    channel_id=int(ch_id),
                    pmt_id=str(pmt),
                    signal=signal,
                ))
        else:
            raise MappingError(
                f"Unrecognized mapping format for board {board_id}: "
                f"expected 'channels' or 'channel_id'+'pmt_id'"
            )

    return MappingTable(entries=entries)


def load_mapping_from_runinfo(runinfo_payload: Dict[str, Any]) -> MappingTable:
    """Extract and parse mapping from a runinfo.json payload dict."""
    raw = runinfo_payload.get("mapping")
    if raw is None:
        raise MappingNotFoundError("No 'mapping' key in runinfo payload")
    return parse_mapping(raw)
