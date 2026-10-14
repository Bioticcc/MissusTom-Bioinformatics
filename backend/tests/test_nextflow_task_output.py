from __future__ import annotations

from io import StringIO
from pathlib import Path

from missus_tom.services.nextflow_task_output import MAX_TASK_STREAM_BYTES, NextflowTaskOutput


def test_submitted_task_output_is_forwarded_once_with_provenance(tmp_path: Path) -> None:
    work = tmp_path / "work"
    task = work / "ab" / "cdef1234567890"
    task.mkdir(parents=True)
    (task / ".command.out").write_text("quantification complete\n", encoding="utf-8")
    (task / ".command.err").write_text("Running DESeq2 for treated\n", encoding="utf-8")
    run_log = tmp_path / "run.log"
    run_log.write_text("[ab/cdef12] Submitted process > BULK_RNASEQ_ANALYSIS\n", encoding="utf-8")
    destination = StringIO()
    forwarder = NextflowTaskOutput(work)

    assert forwarder.pump(run_log, destination) == "BULK_RNASEQ_ANALYSIS"
    assert "[Task out: BULK_RNASEQ_ANALYSIS]\nquantification complete" in destination.getvalue()
    assert "[Task err: BULK_RNASEQ_ANALYSIS]\nRunning DESeq2" in destination.getvalue()
    assert forwarder.pump(run_log, destination) is None
    assert destination.getvalue().count("Running DESeq2") == 1

    with (task / ".command.err").open("a", encoding="utf-8") as handle:
        handle.write("Analysis complete\n")
    forwarder.pump(run_log, destination)
    assert destination.getvalue().count("Analysis complete") == 1
    (task / ".exitcode").write_text("0\n", encoding="utf-8")
    forwarder.pump(run_log, destination)
    assert not forwarder.tasks


def test_task_output_is_bounded_and_does_not_follow_symlinks(tmp_path: Path) -> None:
    work = tmp_path / "work"
    task = work / "ab" / "cdef1234567890"
    task.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private data", encoding="utf-8")
    (task / ".command.out").symlink_to(outside)
    (task / ".command.err").write_bytes(b"x" * (MAX_TASK_STREAM_BYTES + 10))
    run_log = tmp_path / "run.log"
    run_log.write_text("[ab/cdef12] Submitted process > SAMPLE\n", encoding="utf-8")
    destination = StringIO()
    forwarder = NextflowTaskOutput(work)

    forwarder.pump(run_log, destination)
    forwarder.pump(run_log, destination)

    assert "private data" not in destination.getvalue()
    assert destination.getvalue().count("Task err preview limit reached") == 1
    assert len(destination.getvalue()) < MAX_TASK_STREAM_BYTES + 200
