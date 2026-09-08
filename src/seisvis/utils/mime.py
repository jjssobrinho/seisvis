from __future__ import annotations

# Payload format for catalog → canvas drags: newline-separated dataset ids,
# UTF-8. A private type (rather than text/uri-list) keeps these drags from
# being mistaken for the file drops MainWindow accepts, and keeps foreign
# drags out of the canvas.
DATASET_MIME_TYPE = "application/x-seisvis-dataset-ids"


def encode_dataset_ids(dataset_ids: list[str]) -> bytes:
    return "\n".join(dataset_ids).encode("utf-8")


def decode_dataset_ids(payload: bytes) -> list[str]:
    text = bytes(payload).decode("utf-8", errors="replace")
    return [line for line in text.split("\n") if line]


__all__ = ["DATASET_MIME_TYPE", "decode_dataset_ids", "encode_dataset_ids"]
