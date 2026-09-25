from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPOSITORY_ROOT / "workflows" / "bulk_rnaseq" / "bin" / "run_with_timeout"
MAIN_NF = REPOSITORY_ROOT / "workflows" / "bulk_rnaseq" / "main.nf"


def _run_helper(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HELPER), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_run_with_timeout_preserves_successful_exit() -> None:
    started = time.monotonic()
    result = _run_helper("7200", "60", "true")
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert result.stderr == ""
    assert elapsed < 5


def test_run_with_timeout_preserves_command_failure_exit() -> None:
    result = _run_helper("7200", "60", "bash", "-c", "exit 42")
    assert result.returncode == 42
    assert "exceeded" not in result.stderr


def test_run_with_timeout_normalizes_elapsed_limit_to_240() -> None:
    result = _run_helper("1", "1", "sleep", "5")
    assert result.returncode == 240
    assert "exceeded 1s limit" in result.stderr


def test_run_with_timeout_rejects_non_positive_timeout_args() -> None:
    result = _run_helper("0", "60", "true")
    assert result.returncode == 2
    assert "positive integer" in result.stderr

    result = _run_helper("7200", "0", "true")
    assert result.returncode == 2
    assert "positive integer" in result.stderr


def test_kallisto_quant_script_has_no_background_watchdog() -> None:
    body = MAIN_NF.read_text(encoding="utf-8")
    process_block = re.search(
        r"process KALLISTO_QUANT \{(?P<body>.*?)^\}",
        body,
        re.MULTILINE | re.DOTALL,
    )
    assert process_block is not None
    script_body = process_block.group("body")
    assert "watchdog_pid" not in script_body
    assert ".kallisto_time_limit_exceeded" not in script_body
    assert "sleep 7200" not in script_body
    assert ") &" not in script_body
    assert re.search(r"run_with_timeout\s+7200\s+60\s+kallisto\s+quant", script_body)


@pytest.mark.skipif(shutil.which("nextflow") is None, reason="nextflow not installed")
def test_nextflow_serial_samples_complete_with_run_with_timeout(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "timeout-smoke"
    bin_dir = workflow_dir / "bin"
    bin_dir.mkdir(parents=True)
    shutil.copy2(HELPER, bin_dir / "run_with_timeout")
    (bin_dir / "run_with_timeout").chmod(0o755)

    main_nf = workflow_dir / "main.nf"
    main_nf.write_text(
        textwrap.dedent(
            '''
            nextflow.enable.dsl = 2

            process SAMPLE {
                tag "${sample_id}"

                input:
                val sample_id

                output:
                path "${sample_id}.done", emit: marker

                script:
                """
                run_with_timeout 7200 60 bash -c "echo ${sample_id} > ${sample_id}.done"
                """
            }

            process COLLECT {
                input:
                path markers, stageAs: 'markers/*'

                output:
                path 'summary.txt'

                script:
                """
                ls markers > summary.txt
                """
            }

            workflow {
                SAMPLE(Channel.of('sample_a', 'sample_b'))
                COLLECT(SAMPLE.out.marker.collect())
            }
            '''
        ).lstrip(),
        encoding="utf-8",
    )

    work_dir = tmp_path / "work"
    result = subprocess.run(
        [
            "nextflow",
            "run",
            str(main_nf),
            "-w",
            str(work_dir),
            "-with-trace",
            str(tmp_path / "trace.txt"),
        ],
        cwd=workflow_dir,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    summary_paths = list(work_dir.rglob("summary.txt"))
    assert summary_paths, "expected COLLECT to emit summary.txt"
    summary = summary_paths[0].read_text(encoding="utf-8")
    assert "sample_a.done" in summary
    assert "sample_b.done" in summary
