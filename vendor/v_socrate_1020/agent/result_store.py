"""Per-question selection result storage.

Layout:
    <run_dir>/<dataset>/<question_id>.json

Each file contains one JSON object and is written via atomic replace. A rerun scans
the directory automatically: successful questions are skipped; failed questions are
run again and their files are overwritten.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

RESULT_SCHEMA_VERSION = 2


def result_succeeded(row: Dict[str, Any]) -> bool:
    """Only complete Select→Reflect→Answer v2 records are resumable successes."""
    if row.get("result_schema_version") != RESULT_SCHEMA_VERSION:
        return False
    if row.get("status") != "success":
        return False
    answer = row.get("answer")
    final_reflection = row.get("final_reflection")
    evidence = row.get("evidence_frame_ids")
    actual = row.get("actual_frame_ids")
    return bool(
        isinstance(answer, dict)
        and isinstance(answer.get("choice"), str)
        and answer.get("choice")
        and isinstance(answer.get("text"), str)
        and answer.get("text")
        and isinstance(final_reflection, dict)
        and final_reflection.get("status") in ("CONFIRM", "BEST_GUESS")
        and isinstance(evidence, list)
        and evidence
        and actual == evidence
    )


def build_result_record(
    *,
    base: Dict[str, Any],
    status: str,
    failed_type: str,
    submitted_frame_ids: List[int],
    final_reflection: Dict[str, Any],
    reflection_history: List[Dict[str, Any]],
    elapsed_sec: float,
    conversation: List[Dict[str, Any]],
    process: Optional[Dict[str, Any]] = None,
    error: str = "",
) -> Dict[str, Any]:
    reflection = dict(final_reflection or {})
    evidence = [int(x) for x in reflection.get("evidence_frame_ids", [])]
    answer = dict(reflection.get("answer") or {})
    final_output = str(reflection.pop("final_output", ""))
    row = {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        **base,
        "num_frames": len(evidence),
        "selected_num_frames": len(submitted_frame_ids),
        "selected_frame_ids": list(submitted_frame_ids),
        "evidence_frame_ids": evidence,
        "actual_frame_ids": evidence,
        "answer": answer,
        "final_reflection": reflection,
        "reflection_history": list(reflection_history),
        "final_output": final_output,
        "status": status,
        "failed_type": failed_type,
        "error": error,   # exception text for input_data_error (empty otherwise)
        "elapsed_sec": round(elapsed_sec, 1),
        "conversation": conversation,
        # Trajectory (MMDR-PLANNER style): process.selector = message_meta / calls / tool_stats
        # for `conversation`; process.reflector = one exchange per Reflect, linked by
        # selector_tool_call_id.
        "process": process or {},
    }
    if status != "success":
        row["answer"] = {}
        row["final_reflection"] = {}
        row["evidence_frame_ids"] = []
        row["actual_frame_ids"] = []
        row["num_frames"] = 0
        row["final_output"] = ""
    return row


def dataset_result_dir(run_dir: str, dataset: str) -> str:
    path = os.path.join(os.path.abspath(run_dir), dataset)
    os.makedirs(path, exist_ok=True)
    return path


def _qid_filename(question_id: Any) -> str:
    qid = str(question_id)
    if not qid:
        raise ValueError("question_id must not be empty")
    # Preserve normal benchmark IDs exactly; escape only path separators and other
    # characters that cannot safely be a single filename component.
    return quote(qid, safe="@._-") + ".json"


def result_path(run_dir: str, dataset: str, question_id: Any) -> str:
    return os.path.join(dataset_result_dir(run_dir, dataset), _qid_filename(question_id))


def write_result(run_dir: str, dataset: str, record: Dict[str, Any]) -> str:
    path = result_path(run_dir, dataset, record["question_id"])
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def load_results(run_dir: str, dataset: str) -> List[Dict[str, Any]]:
    directory = dataset_result_dir(run_dir, dataset)
    rows: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                row = json.load(f)
            if isinstance(row, dict) and row.get("question_id") is not None:
                rows.append(row)
        except (OSError, json.JSONDecodeError):
            # Atomic writes prevent partial files in normal operation. If an old or
            # manually-created file is corrupt, leave it for inspection and rerun qid.
            continue
    return rows


def successful_by_qid(
    run_dir: str,
    dataset: str,
    succeeded,
) -> Dict[str, Dict[str, Any]]:
    return {
        str(row["question_id"]): row
        for row in load_results(run_dir, dataset)
        if succeeded(row)
    }


def write_many(run_dir: str, dataset: str, records: Iterable[Dict[str, Any]]) -> None:
    for record in records:
        write_result(run_dir, dataset, record)
