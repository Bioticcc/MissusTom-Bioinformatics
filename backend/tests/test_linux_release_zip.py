from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path


def test_linux_release_zip_contains_only_the_deb_checksum_and_instructions(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_deb = tmp_path / "fake-package.deb"
    source_deb.write_bytes(b"not a real Debian package; release ZIP tests use a fixture")
    output_directory = tmp_path / "release-artifacts"

    subprocess.run(
        [
            "bash",
            str(repository_root / "scripts" / "create-linux-release-zip.sh"),
            "--version",
            "1.2.3-rc.1",
            "--deb",
            source_deb.name,
            "--output-dir",
            output_directory.name,
        ],
        check=True,
        cwd=tmp_path,
    )

    deb_name = "missus-tom_1.2.3-rc.1_linux-x86_64.deb"
    zip_path = output_directory / "ver1.2.3-rc.1_Linux-x86_64_Ubuntu-Debian.zip"
    assert sorted(path.name for path in output_directory.iterdir()) == [zip_path.name]

    with zipfile.ZipFile(zip_path) as release_zip:
        assert sorted(release_zip.namelist()) == ["SHA256SUMS", "installation.md", deb_name]
        deb_contents = release_zip.read(deb_name)
        assert deb_contents == source_deb.read_bytes()
        assert release_zip.read("SHA256SUMS").decode() == (
            f"{hashlib.sha256(deb_contents).hexdigest()}  {deb_name}\n"
        )
        instructions = release_zip.read("installation.md").decode()

    assert "sha256sum --check SHA256SUMS" in instructions
    assert f"sudo apt install ./{deb_name}" in instructions


def test_linux_release_zip_rejects_invalid_version_and_existing_zip(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    source_deb = tmp_path / "fake-package.deb"
    source_deb.write_bytes(b"fixture")
    output_directory = tmp_path / "release-artifacts"

    invalid = subprocess.run(
        [
            "bash",
            str(repository_root / "scripts" / "create-linux-release-zip.sh"),
            "--version",
            "../unsafe",
            "--deb",
            str(source_deb),
            "--output-dir",
            str(output_directory),
        ],
        capture_output=True,
        text=True,
    )
    assert invalid.returncode == 2
    assert "Release version" in invalid.stderr

    output_directory.mkdir()
    (output_directory / "old.zip").write_bytes(b"old artifact")
    existing = subprocess.run(
        [
            "bash",
            str(repository_root / "scripts" / "create-linux-release-zip.sh"),
            "--version",
            "1.2.3",
            "--deb",
            str(source_deb),
            "--output-dir",
            str(output_directory),
        ],
        capture_output=True,
        text=True,
    )
    assert existing.returncode == 2
    assert "must not already contain a ZIP" in existing.stderr
