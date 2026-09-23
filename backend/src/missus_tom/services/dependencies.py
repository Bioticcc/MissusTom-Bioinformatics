"""Local, fixed-catalogue workflow dependency management.

This module deliberately knows no pipeline adapters: adapters consume the small
runtime helpers below, while the API owns installation/status presentation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Final
from uuid import UUID, uuid4

from missus_tom.config import settings
from missus_tom.models.dependencies import (
    DependencyInstallJob,
    DependencyInstallStatus,
    DependencyRequirement,
    DependencyStatus,
)

ONT_R_PACKAGES: Final[tuple[str, ...]] = (
    "data.table",
    "ggplot2",
    "ggrepel",
    "scales",
    "patchwork",
    "GenomicRanges",
    "IRanges",
    "GenomeInfoDb",
    "rtracklayer",
    "jsonlite",
)
BULK_R_PACKAGES: Final[tuple[str, ...]] = ("DESeq2", "tximport", "ggplot2")
_PACKAGE_CATALOG: Final[dict[str, tuple[str, ...]]] = {
    "bulk-rnaseq": (
        "nextflow=24.04.4",
        "openjdk=17",
        "fastqc=0.12.1",
        "multiqc=1.33",
        "cutadapt=5.2",
        "kallisto=0.52.0",
        "r-base",
    ),
    "ont-analysis": (
        "samtools",
        "htslib",
        "mosdepth=0.3.14",
        "ont-modkit=0.6.4",
        "minimap2=2.31",
        "python=3",
        "r-base",
    ),
}
_TOOL_CATALOG: Final[dict[str, tuple[str, ...]]] = {
    "bulk-rnaseq": (
        "nextflow",
        "java",
        "fastqc",
        "multiqc",
        "cutadapt",
        "kallisto",
        "Rscript",
    ),
    "ont-analysis": (
        "dorado",
        "samtools",
        "bgzip",
        "tabix",
        "mosdepth",
        "modkit",
        "minimap2",
        "python3",
        "Rscript",
    ),
}
_PIPELINES: Final[frozenset[str]] = frozenset(_PACKAGE_CATALOG)
_MICROMAMBA_VERSION: Final = "2.3.2-0"
_MICROMAMBA_URL: Final = (
    "https://github.com/mamba-org/micromamba-releases/releases/download/"
    f"{_MICROMAMBA_VERSION}/micromamba-linux-64.tar.bz2"
)
# The release publishes this sidecar beside the immutable versioned archive.
_MICROMAMBA_SHA_URL: Final = f"{_MICROMAMBA_URL}.sha256"
_MICROMAMBA_SHA256: Final = "ffc3cb8d52d4d6b354bdbb979c407719c485392b74e462cbd50811aa88e58f85"
_MICROMAMBA_ARCHIVE_SHA256: Final = (
    "5512233cdd8564a671626081026dc861537a963baa06706baab08fac6f3bb9d2"
)
_DORADO_VERSION: Final = "2.1.2"
_DORADO_ARCHIVE_ROOT: Final = f"dorado-{_DORADO_VERSION}-linux-x64"
_DORADO_ARCHIVE_SIZE_BYTES: Final = 3_466_666_099
_DORADO_CUDNN_VERSION: Final = "9.8.0"
_DORADO_CUDNN_COMPONENTS: Final = (
    "",
    "_graph",
    "_engines_runtime_compiled",
    "_adv",
    "_engines_precompiled",
    "_ops",
    "_heuristic",
    "_cnn",
)
_DORADO_URL: Final = (
    "https://cdn.oxfordnanoportal.com/software/analysis/dorado-2.1.2-linux-x64.tar.gz"
)
# Verified from the official 2.1.2 CDN archive. Never replace this with an
# unverified locally observed value.
_DORADO_ARCHIVE_SHA256: Final = "f4ed83acfb75cf07ffe8a0fc78e26828fc911fcfc8177920be6104e1d0e02485"
_DOCKER_IMAGES: Final[tuple[str, ...]] = (
    "quay.io/biocontainers/fastqc@sha256:e194048df39c3145d9b4e0a14f4da20b59d59250465b6f2a9cb698445fd45900",
    "quay.io/biocontainers/multiqc@sha256:dfd9fde2c48b896b884e79a71ddc16c72c97a0ee5c5c8e45aaba50f55d07d263",
    "quay.io/biocontainers/cutadapt@sha256:c96a44c18f58660e853652c7efb303b3f426aa12f1ee7af007d03a54c39b87a5",
    "quay.io/biocontainers/kallisto@sha256:7615f563aa2948fd087f7e4a666e252f275c60b2070729bc9a3804c8873527e5",
)
_ACTIVE = {DependencyInstallStatus.RUNNING}


def _managed_root(pipeline_identifier: str) -> Path:
    if pipeline_identifier not in _PIPELINES:
        raise ValueError(f"unsupported pipeline identifier: {pipeline_identifier}")
    return settings.state_directory / "dependencies" / pipeline_identifier


def _managed_bin(pipeline_identifier: str) -> Path:
    root = _managed_root(pipeline_identifier)
    active = root / "active.json"
    try:
        selected = json.loads(active.read_text(encoding="utf-8"))["environment"]
        if not isinstance(selected, str):
            raise ValueError("invalid active environment pointer")
        candidate = (root / selected).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_dir():
            return candidate / "bin"
    except (OSError, ValueError, KeyError):
        pass
    return root / "environment" / "bin"  # legacy/incomplete installs are not active


def runtime_environment(pipeline_identifier: str) -> dict[str, str]:
    """Return an isolated env suitable for controlled runner subprocesses."""
    return _environment_for_prefix(pipeline_identifier, _managed_bin(pipeline_identifier).parent)


def _version_arguments(tool: str) -> list[str]:
    if tool == "kallisto":
        return ["version"]
    return ["-version"] if tool in {"nextflow", "java"} else ["--version"]


def _environment_for_prefix(pipeline_identifier: str, prefix: Path) -> dict[str, str]:
    managed_bin = prefix / "bin"
    environment = os.environ.copy()
    for key in tuple(environment):
        if key == "JAVA_HOME" or key.startswith(("R_", "PYTHON", "CONDA_", "LD_")):
            environment.pop(key, None)
    path_entries = [str(managed_bin)]
    if pipeline_identifier == "bulk-rnaseq":
        docker = runtime_tool("docker", pipeline_identifier)
        if docker:
            path_entries.append(str(Path(docker).parent))
    path_entries.extend(("/usr/bin", "/bin"))
    environment["PATH"] = os.pathsep.join(dict.fromkeys(path_entries))
    environment["MAMBA_ROOT_PREFIX"] = str(_managed_root(pipeline_identifier) / "micromamba-root")
    environment["PYTHONNOUSERSITE"] = "1"
    environment["R_LIBS_USER"] = str(prefix / "lib" / "R" / "library")
    environment["R_LIBS_SITE"] = str(prefix / "lib" / "R" / "site-library")
    environment["R_ENVIRON_USER"] = os.devnull
    environment["R_PROFILE_USER"] = os.devnull
    environment["R_ENVIRON_SITE"] = os.devnull
    environment["R_PROFILE_SITE"] = os.devnull
    library_paths = [str(prefix / "lib")]
    dorado = managed_bin / "dorado"
    if dorado.exists():
        dorado_library = dorado.resolve().parent.parent / "lib"
        if dorado_library.is_dir() and dorado_library.is_relative_to(
            _managed_root(pipeline_identifier)
        ):
            library_paths.append(str(dorado_library))
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(library_paths)
    if (managed_bin / "java").is_file():
        environment["JAVA_HOME"] = str(managed_bin.parent)
    if pipeline_identifier == "bulk-rnaseq" and (managed_bin / "nextflow").is_file():
        # Keep the Nextflow home and engine cache inside the managed root so
        # install-time warmup survives and offline runs do not depend on ~/.nextflow.
        nextflow_home = _managed_root(pipeline_identifier) / "nextflow-home"
        with suppress(OSError):
            nextflow_home.mkdir(parents=True, exist_ok=True)
        environment["NXF_HOME"] = str(nextflow_home)
        environment["NXF_VER"] = "24.04.4"
        environment["NXF_OFFLINE"] = "true"
    return environment


def runtime_tool(name: str, pipeline_identifier: str) -> str | None:
    managed_bin = _managed_bin(pipeline_identifier)
    if name == "docker" and pipeline_identifier == "bulk-rnaseq":
        return shutil.which("docker")  # optional system tool for the regression profile
    if name not in _TOOL_CATALOG[pipeline_identifier]:
        return None
    executable = shutil.which(name, path=str(managed_bin))
    if executable is None:
        return None
    resolved = Path(executable).resolve()
    if not resolved.is_relative_to(_managed_root(pipeline_identifier).resolve()):
        return None
    return executable


class DependencyInstaller:
    """Persistent job metadata with a process-local single installer lock."""

    def __init__(self, *, state_directory: Path | None = None) -> None:
        self.state_directory = state_directory or settings.state_directory / "dependencies"
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._run_lock_descriptors: dict[str, int] = {}
        self._jobs: dict[str, DependencyInstallJob] = {}
        self._probe_cache: dict[str, tuple[float, list[DependencyRequirement]]] = {}
        self._recover_jobs()

    def status(self, pipeline_identifier: str) -> DependencyStatus:
        requirements = self._requirements(pipeline_identifier)
        missing = [item.name for item in requirements if not item.installed]
        dorado_verified = (
            pipeline_identifier != "ont-analysis" or _DORADO_ARCHIVE_SHA256 is not None
        )
        manual_requirements = (
            [
                "Managed ONT installation is disabled until the Dorado archive has "
                "an authoritative pinned SHA-256 digest."
            ]
            if pipeline_identifier == "ont-analysis" and not dorado_verified
            else []
        )
        return DependencyStatus(
            pipeline_identifier=pipeline_identifier,
            requirements=requirements,
            missing=missing,
            installable=self._supported_platform() and dorado_verified,
            manual_requirements=manual_requirements,
            job=self._job_for_pipeline(pipeline_identifier),
        )

    def install(self, pipeline_identifier: str) -> DependencyInstallJob:
        self._validate_pipeline(pipeline_identifier)
        if not self._supported_platform():
            raise ValueError(
                "automated dependency installation currently supports Linux x86_64 only"
            )
        if pipeline_identifier == "ont-analysis" and _DORADO_ARCHIVE_SHA256 is None:
            raise ValueError(
                "managed ONT installation is disabled until the Dorado archive "
                "has an authoritative pinned SHA-256 digest"
            )
        with self._lock:
            active = self._job_for_pipeline(pipeline_identifier)
            if active and active.status in _ACTIVE:
                raise ValueError("dependency installation is already running for this pipeline")
            if any(job.status in _ACTIVE for job in self._jobs.values()):
                raise ValueError("another dependency installation is already running")
            job = DependencyInstallJob(
                job_identifier=str(uuid4()),
                pipeline_identifier=pipeline_identifier,
                status=DependencyInstallStatus.RUNNING,
                message="Preparing local environment",
            )
            lock_descriptor = self._acquire_run_lock(job.job_identifier)
            self._jobs[job.job_identifier] = job
            try:
                self._run_lock_descriptors[job.job_identifier] = lock_descriptor
                self._persist(job)
                thread = threading.Thread(
                    target=self._install_worker, args=(job.job_identifier,), daemon=True
                )
                self._threads[job.job_identifier] = thread
                thread.start()
            except Exception:
                self._jobs.pop(job.job_identifier, None)
                self._threads.pop(job.job_identifier, None)
                self._release_run_lock(job.job_identifier)
                raise
            return job.model_copy(deep=True)

    def _validate_pipeline(self, pipeline_identifier: str) -> None:
        if pipeline_identifier not in _PIPELINES:
            raise ValueError(f"unsupported pipeline identifier: {pipeline_identifier}")

    @staticmethod
    def _supported_platform() -> bool:
        return platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}

    def _requirements(self, pipeline_identifier: str) -> list[DependencyRequirement]:
        self._validate_pipeline(pipeline_identifier)
        cached = self._probe_cache.get(pipeline_identifier)
        if cached and time.monotonic() - cached[0] < 5:
            return [requirement.model_copy(deep=True) for requirement in cached[1]]
        managed = _managed_bin(pipeline_identifier).is_dir()
        with ThreadPoolExecutor(max_workers=len(_TOOL_CATALOG[pipeline_identifier])) as pool:
            items = list(
                pool.map(
                    lambda tool: self._tool_requirement(tool, pipeline_identifier, managed),
                    _TOOL_CATALOG[pipeline_identifier],
                )
            )
        if pipeline_identifier == "ont-analysis":
            items.append(
                self._r_requirement(pipeline_identifier, managed, ONT_R_PACKAGES, "ONT R packages")
            )
        elif pipeline_identifier == "bulk-rnaseq":
            items.append(
                self._r_requirement(
                    pipeline_identifier, managed, BULK_R_PACKAGES, "Bulk R packages"
                )
            )
        self._probe_cache[pipeline_identifier] = (time.monotonic(), items)
        return [requirement.model_copy(deep=True) for requirement in items]

    def _tool_requirement(
        self, name: str, pipeline_identifier: str, managed: bool
    ) -> DependencyRequirement:
        executable = runtime_tool(name, pipeline_identifier)
        available = False
        detail = "not found"
        if executable:
            # Nextflow/Java cold starts and first-time engine probes need more than
            # a one-second budget; keep CLI tools short so the status panel stays snappy.
            probe_timeout = 8 if name in {"nextflow", "java"} else 3
            try:
                completed = subprocess.run(
                    [executable, *_version_arguments(name)],
                    capture_output=True,
                    text=True,
                    timeout=probe_timeout,
                    check=False,
                    env=runtime_environment(pipeline_identifier),
                )
                available = completed.returncode == 0
                detail = executable if available else f"{executable} did not run successfully"
            except (OSError, subprocess.TimeoutExpired):
                detail = f"{executable} could not be executed"
        return DependencyRequirement(
            name=name,
            installed=available,
            managed=managed
            and executable is not None
            and str(_managed_bin(pipeline_identifier)) in executable,
            detail=detail,
        )

    def _r_requirement(
        self,
        pipeline_identifier: str,
        managed: bool,
        packages: tuple[str, ...],
        requirement_name: str,
    ) -> DependencyRequirement:
        rscript = runtime_tool("Rscript", pipeline_identifier)
        expression = (
            "p<-c("
            + ",".join(repr(item) for item in packages)
            + "); m<-p[!vapply(p,requireNamespace,logical(1),quietly=TRUE)]; "
            "cat(paste(m,collapse=', ')); quit(status=if(length(m)) 1 else 0)"
        )
        available = False
        detail = "Rscript not found"
        if rscript:
            # Bioconductor namespaces (especially DESeq2) can exceed a few seconds
            # on cold disk cache; keep this above the tool-probe budget.
            try:
                result = subprocess.run(
                    [rscript, "--vanilla", "-e", expression],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                    env=runtime_environment(pipeline_identifier),
                )
                available = result.returncode == 0
                detail = (
                    "all required R and Bioconductor packages available"
                    if available
                    else "missing R packages: " + (result.stdout.strip() or ", ".join(packages))
                )
            except (OSError, subprocess.TimeoutExpired):
                detail = "R package check could not complete"
        return DependencyRequirement(
            name=requirement_name,
            installed=available,
            managed=managed
            and rscript is not None
            and str(_managed_bin(pipeline_identifier)) in rscript,
            detail=detail,
        )

    def _docker_requirement(self, managed: bool) -> DependencyRequirement:
        docker = shutil.which("docker")
        available = False
        detail = "Docker CLI not found"
        if docker:
            try:
                result = subprocess.run(
                    [docker, "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                available = result.returncode == 0 and bool(result.stdout.strip())
                detail = "Docker daemon available" if available else "Docker daemon is unavailable"
            except (OSError, subprocess.TimeoutExpired):
                detail = "Docker daemon check timed out"
        return DependencyRequirement(
            name="Docker daemon", installed=available, managed=False, detail=detail
        )

    def _analysis_image_requirement(self, managed: bool) -> DependencyRequirement:
        docker = shutil.which("docker")
        if not docker:
            return DependencyRequirement(
                name="Bulk analysis image",
                installed=False,
                managed=False,
                detail="Docker CLI not found",
            )
        try:
            result = subprocess.run(
                [docker, "image", "inspect", "missus-tom/rnaseq-analysis:0.3.0", *_DOCKER_IMAGES],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            available = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            available = False
        return DependencyRequirement(
            name="Bulk analysis image",
            installed=available,
            managed=False,
            detail="available" if available else "build with the fixed project build script",
        )

    def _install_worker(self, job_identifier: str) -> None:
        with self._lock:
            job = self._jobs[job_identifier]
        try:
            self._log(job, "Starting dependency installation.")
            self._install_environment(job)
            self._probe_cache.pop(job.pipeline_identifier, None)
            job.status = DependencyInstallStatus.SUCCEEDED
            job.message = "Local dependencies verified"
            self._log(job, "Dependency installation completed and was verified.")
        except Exception as exc:
            job.status = DependencyInstallStatus.FAILED
            job.message = str(exc)
            self._log(job, f"Installation failed: {exc}")
        finally:
            try:
                self._persist(job)
            finally:
                self._release_run_lock(job.job_identifier)

    def _install_environment(self, job: DependencyInstallJob) -> None:
        root = _managed_root(job.pipeline_identifier)
        self._safe_directory(root.parent)
        self._safe_directory(root)
        self._safe_directory(root / "staging")
        staging = Path(mkdtemp(prefix=f".{job.pipeline_identifier}-", dir=root / "staging"))
        environment = root / "environments" / job.job_identifier / "environment"
        try:
            # Native Bulk now includes R/Bioconductor as well as the scientific CLI tools.
            minimum_free = (
                20 * 1024**3 if job.pipeline_identifier == "ont-analysis" else 15 * 1024**3
            )
            if shutil.disk_usage(root).free < minimum_free:
                raise RuntimeError(
                    f"installation needs at least {minimum_free // 1024**3} GiB free "
                    "on the dependency filesystem"
                )
            mamba = self._ensure_micromamba(staging, job)
            self._safe_directory(environment.parent)
            packages = self._packages_for(job.pipeline_identifier)
            self._run(
                job,
                [
                    str(mamba),
                    "create",
                    "--yes",
                    "--no-rc",
                    "--strict-channel-priority",
                    "--prefix",
                    str(environment),
                    "--override-channels",
                    "--channel",
                    "conda-forge",
                    "--channel",
                    "bioconda",
                    *packages,
                ],
                environment=self._mamba_environment(job.pipeline_identifier),
            )
            if job.pipeline_identifier == "ont-analysis":
                self._install_r_packages(job, mamba, environment)
                self._install_dorado(job, environment.parent)
            elif job.pipeline_identifier == "bulk-rnaseq":
                self._install_bulk_r_packages(job, mamba, environment)
            self._verify_environment(job, environment)
            self._activate(root, environment)
            shutil.rmtree(staging, ignore_errors=True)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _verify_environment(self, job: DependencyInstallJob, prefix: Path) -> None:
        """Verify an inactive prefix before switching away from a working install."""
        environment = _environment_for_prefix(job.pipeline_identifier, prefix)
        tools = _TOOL_CATALOG[job.pipeline_identifier]
        if job.pipeline_identifier == "bulk-rnaseq":
            nextflow_home = _managed_root(job.pipeline_identifier) / "nextflow-home"
            self._safe_directory(nextflow_home)
            environment["NXF_HOME"] = str(nextflow_home)
            environment["NXF_OFFLINE"] = (
                "false"  # warm up the pinned engine while installation permits networking
            )
        for tool in tools:
            executable = prefix / "bin" / tool
            if not executable.is_file():
                raise RuntimeError(f"new environment is missing {tool}")
            if not executable.resolve().is_relative_to(prefix.parent.resolve()):
                raise RuntimeError(f"new environment tool escapes its private location: {tool}")
            self._run(
                job,
                [str(executable), *_version_arguments(tool)],
                environment=environment,
            )
        r_packages = (
            ONT_R_PACKAGES
            if job.pipeline_identifier == "ont-analysis"
            else BULK_R_PACKAGES
            if job.pipeline_identifier == "bulk-rnaseq"
            else ()
        )
        if r_packages:
            packages = ",".join(json.dumps(name) for name in r_packages)
            expression = (
                f"stopifnot(all(vapply(c({packages}),requireNamespace,logical(1),quietly=TRUE)))"
            )
            self._run(
                job,
                [str(prefix / "bin" / "Rscript"), "--vanilla", "-e", expression],
                environment=environment,
            )

    @staticmethod
    def _packages_for(pipeline_identifier: str) -> list[str]:
        return list(_PACKAGE_CATALOG[pipeline_identifier])

    def _install_r_packages(
        self, job: DependencyInstallJob, mamba: Path, environment: Path
    ) -> None:
        packages = [
            "r-data.table",
            "r-ggplot2",
            "r-ggrepel",
            "r-scales",
            "r-patchwork",
            "bioconductor-genomicranges",
            "bioconductor-iranges",
            "bioconductor-genomeinfodb",
            "bioconductor-rtracklayer",
            "r-jsonlite",
        ]
        self._run(
            job,
            [
                str(mamba),
                "install",
                "--yes",
                "--no-rc",
                "--strict-channel-priority",
                "--prefix",
                str(environment),
                "--override-channels",
                "--channel",
                "conda-forge",
                "--channel",
                "bioconda",
                *packages,
            ],
            environment=self._mamba_environment(job.pipeline_identifier),
        )

    def _install_bulk_r_packages(
        self, job: DependencyInstallJob, mamba: Path, environment: Path
    ) -> None:
        self._run(
            job,
            [
                str(mamba),
                "install",
                "--yes",
                "--no-rc",
                "--strict-channel-priority",
                "--prefix",
                str(environment),
                "--override-channels",
                "--channel",
                "conda-forge",
                "--channel",
                "bioconda",
                "bioconductor-deseq2",
                "bioconductor-tximport",
                "r-ggplot2",
            ],
            environment=self._mamba_environment(job.pipeline_identifier),
        )

    def _install_bulk_images(self, job: DependencyInstallJob) -> None:
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError(
                "Docker must be installed and its daemon started before bulk installation"
            )
        for image in _DOCKER_IMAGES:
            self._run(job, [docker, "pull", image])
        script = settings.resource_root / "scripts" / "build-analysis-image.sh"
        self._run(job, ["bash", str(script)])

    def _ensure_micromamba(self, staging: Path, job: DependencyInstallJob) -> Path:
        archive = staging / "micromamba.tar.bz2"
        checksum = self._download_text(_MICROMAMBA_SHA_URL).split()[0].lower()
        self._download(_MICROMAMBA_URL, archive)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        # Upstream's tar sidecar describes the extracted binary, not the archive.
        # Both hashes are pinned from the official release's asset metadata.
        if (
            len(checksum) != 64
            or checksum != _MICROMAMBA_SHA256
            or actual != _MICROMAMBA_ARCHIVE_SHA256
        ):
            raise RuntimeError("micromamba archive checksum verification failed")
        with tarfile.open(archive, "r:bz2") as bundle:
            member = bundle.getmember("bin/micromamba")
            if not member.isfile():
                raise RuntimeError("micromamba archive executable is not a regular file")
            source = bundle.extractfile(member)
            if source is None or hashlib.sha256(source.read()).hexdigest() != checksum:
                raise RuntimeError("micromamba binary checksum verification failed")
            bundle.extract(member, path=staging)
        binary = staging / "bin" / "micromamba"
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        self._log(job, f"Verified micromamba {_MICROMAMBA_VERSION} release archive.")
        return binary

    def _install_dorado(self, job: DependencyInstallJob, destination_root: Path) -> None:
        expected_digest = _DORADO_ARCHIVE_SHA256
        if expected_digest is None:
            raise RuntimeError(
                "Dorado installation is disabled until its archive SHA-256 is pinned"
            )
        staging = destination_root
        archive = staging / "dorado.tar.gz"
        self._log(
            job,
            f"Downloading Dorado 2.1.2 ({_DORADO_ARCHIVE_SIZE_BYTES:,} bytes; "
            "approximately 3.23 GiB compressed); "
            "extraction needs additional space.",
        )
        self._download(
            _DORADO_URL,
            archive,
            expected_size_bytes=_DORADO_ARCHIVE_SIZE_BYTES,
        )
        with archive.open("rb") as archive_stream:
            actual_digest = hashlib.file_digest(archive_stream, "sha256").hexdigest()
        if actual_digest != expected_digest:
            raise RuntimeError("Dorado archive checksum verification failed")
        destination = staging / "dorado"
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            self._localize_dorado_library_links(job, members)
            for member in members:
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise RuntimeError("Dorado archive contains an unsafe path")
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("Dorado archive contains an unsafe path")
                if member.issym() or member.islnk():
                    if Path(member.linkname).is_absolute():
                        raise RuntimeError("Dorado archive contains an unsafe link")
                    base = target.parent if member.issym() else destination
                    lexical = Path(os.path.normpath(base / member.linkname))
                    if not lexical.is_relative_to(destination.resolve()):
                        raise RuntimeError("Dorado archive contains an unsafe link")
                    if not lexical.resolve().is_relative_to(destination.resolve()):
                        raise RuntimeError("Dorado archive contains an unsafe link")
            # Python 3.11 predates tarfile's data filter. Validate again in extraction
            # order so earlier links cannot redirect later members outside the root.
            for member in members:
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("Dorado archive link redirects an extraction path")
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise RuntimeError("Dorado archive contains a special file")
                if member.issym() or member.islnk():
                    base = target.parent if member.issym() else destination
                    if not (base / member.linkname).resolve().is_relative_to(destination.resolve()):
                        raise RuntimeError("Dorado archive contains an unsafe chained link")
                bundle.extract(member, destination)
                if member.isfile():
                    target.chmod(member.mode & 0o777)
        candidates = [path for path in destination.rglob("dorado") if path.is_file()]
        if len(candidates) != 1 or not candidates[0].is_file():
            raise RuntimeError("Dorado archive did not contain one executable")
        bin_dir = staging / "environment" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        candidates[0].chmod(candidates[0].stat().st_mode | stat.S_IXUSR)
        (bin_dir / "dorado").symlink_to(os.path.relpath(candidates[0], bin_dir))
        archive.unlink()  # only our downloaded archive; retain the complete library distribution
        self._log(job, f"Installed Dorado {_DORADO_VERSION} from the official CDN archive.")

    def _localize_dorado_library_links(
        self, job: DependencyInstallJob, members: list[tarfile.TarInfo]
    ) -> None:
        """Repair only the reviewed 2.1.2 host aliases using regular bundled files.

        Never stat, open, or copy the upstream host link's target. Unrecognized
        external links still fail the ordinary archive containment checks.
        """
        archive_lib = f"{_DORADO_ARCHIVE_ROOT}/lib"
        entries = {member.name: member for member in members}
        for component in _DORADO_CUDNN_COMPONENTS:
            name = f"libcudnn{component}.so"
            member = entries.get(f"{archive_lib}/{name}")
            if member is None or not member.issym():
                continue
            expected_external = f"/etc/alternatives/{name.replace('.', '_')}"
            if member.linkname != expected_external:
                continue
            private_name = f"{name}.{_DORADO_CUDNN_VERSION}"
            bundled = entries.get(f"{archive_lib}/{private_name}")
            if bundled is None or not bundled.isfile():
                raise RuntimeError(
                    f"Dorado archive is missing required private library {private_name}"
                )
            member.linkname = private_name
            self._log(job, f"Using bundled private library: {name} -> {private_name}")

    def _run(
        self,
        job: DependencyInstallJob,
        command: list[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> None:
        self._log(job, "Running: " + " ".join(command[:3]) + " …")
        descriptor = self._run_lock_descriptors.get(job.job_identifier)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            shell=False,
            env=environment,
            pass_fds=(() if descriptor is None else (descriptor,)),
            start_new_session=True,
        )
        deadline = time.monotonic() + 1800
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        pending = b""
        try:
            while selector.get_map() or process.poll() is None:
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(command, 1800)
                for key, _ in selector.select(timeout=1):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    pending += chunk
                    while b"\n" in pending or len(pending) >= 4096:
                        if b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                        else:
                            line, pending = pending[:4096], pending[4096:]
                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        self._append_command_log(job, decoded)
                        self._log(job, decoded[:2000])
            if pending:
                decoded = pending.decode("utf-8", errors="replace").rstrip()
                self._append_command_log(job, decoded)
                self._log(job, decoded[:2000])
            process.wait()
        except Exception as exc:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            if isinstance(exc, subprocess.TimeoutExpired):
                raise RuntimeError("installer command timed out and was stopped") from None
            raise
        finally:
            selector.close()
            with suppress(OSError):
                process.stdout.close()
        if process.returncode:
            raise RuntimeError(f"installer command failed with exit code {process.returncode}")

    @staticmethod
    def _download_text(url: str) -> str:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed HTTPS URL
            payload: bytes = response.read(512)
            return payload.decode("utf-8")

    @staticmethod
    def _download(url: str, destination: Path, *, expected_size_bytes: int | None = None) -> None:
        """Download a fixed HTTPS artifact, optionally enforcing its exact size."""
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed HTTPS URL
                if expected_size_bytes is not None:
                    try:
                        content_length = int(response.headers["Content-Length"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise RuntimeError(
                            "download response is missing a valid Content-Length"
                        ) from exc
                    if content_length != expected_size_bytes:
                        raise RuntimeError(
                            "download response Content-Length does not match expected size"
                        )

                with destination.open("wb") as output:
                    transferred = 0
                    while True:
                        read_size = 1024 * 1024
                        if expected_size_bytes is not None:
                            # Read at most one byte beyond the pinned size. This detects an
                            # oversized or never-ending response without growing the archive.
                            read_size = min(read_size, expected_size_bytes + 1 - transferred)
                        chunk = response.read(read_size)
                        if not chunk:
                            break
                        transferred += len(chunk)
                        if expected_size_bytes is not None and transferred > expected_size_bytes:
                            raise RuntimeError("download exceeded expected size")
                        output.write(chunk)
                    if expected_size_bytes is not None and transferred != expected_size_bytes:
                        raise RuntimeError("download size does not match expected size")
        except Exception:
            with suppress(FileNotFoundError):
                destination.unlink()
            raise

    @staticmethod
    def _safe_directory(directory: Path) -> None:
        target = directory.absolute()
        current = Path(target.anchor)
        for component in target.parts[1:]:
            current /= component
            try:
                info = current.lstat()
            except FileNotFoundError:
                current.mkdir(mode=0o700)
                info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise RuntimeError("dependency state directory must not contain symlinks")

    @staticmethod
    def _mamba_environment(pipeline_identifier: str) -> dict[str, str]:
        environment = _environment_for_prefix(
            pipeline_identifier, _managed_root(pipeline_identifier) / "installer"
        )
        environment["MAMBA_ROOT_PREFIX"] = str(
            _managed_root(pipeline_identifier) / "micromamba-root"
        )
        return environment

    @staticmethod
    def _activate(root: Path, environment: Path) -> None:
        """Atomically select a verified immutable conda prefix; never rename it."""
        relative = environment.relative_to(root)
        temporary = root / ".active.tmp"
        active = root / "active.json"
        if active.is_symlink():
            raise RuntimeError("active environment pointer must not be a symbolic link")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(json.dumps({"environment": str(relative)}))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(root / "active.json")

    def _job_for_pipeline(self, pipeline_identifier: str) -> DependencyInstallJob | None:
        with self._lock:
            jobs = [
                item
                for item in self._jobs.values()
                if item.pipeline_identifier == pipeline_identifier
            ]
            if not jobs:
                return None
            return max(jobs, key=lambda item: item.created_at).model_copy(deep=True)

    def _job_path(self, job_identifier: str) -> Path:
        return self.state_directory / "jobs" / f"{job_identifier}.json"

    def _acquire_run_lock(self, job_identifier: str) -> int:
        """Use the same flock RunManager holds, including across installer children."""
        path = settings.state_directory / "runs" / ".active-run.lock"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, job_identifier.encode("ascii"))
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in {11, 35}:
                raise ValueError("a workflow run is active or requires recovery") from exc
            raise

    def _release_run_lock(self, job_identifier: str) -> None:
        descriptor = self._run_lock_descriptors.pop(job_identifier, None)
        if descriptor is not None:
            with suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _persist(self, job: DependencyInstallJob) -> None:
        self._safe_directory(self.state_directory / "jobs")
        path = self._job_path(job.job_identifier)
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(
            temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, job.model_dump_json().encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        temporary.replace(path)

    def _recover_jobs(self) -> None:
        jobs = self.state_directory / "jobs"
        if not jobs.is_dir() or jobs.is_symlink():
            return
        for path in jobs.glob("*.json"):
            with suppress(OSError, ValueError):
                UUID(path.stem)
                if path.is_symlink():
                    continue
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    payload = os.read(descriptor, 1_000_000).decode("utf-8")
                finally:
                    os.close(descriptor)
                job = DependencyInstallJob.model_validate_json(payload)
                if job.status == DependencyInstallStatus.RUNNING:
                    job.status = DependencyInstallStatus.FAILED
                    job.message = "backend restarted before dependency installation completed"
                    self._persist(job)
                self._jobs[job.job_identifier] = job

    def _log(self, job: DependencyInstallJob, line: str) -> None:
        stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        job.log_tail = [*job.log_tail, f"{stamp} {line}"][-80:]
        self._persist(job)

    def _append_command_log(self, job: DependencyInstallJob, line: str) -> None:
        path = self.state_directory / "jobs" / f"{job.job_identifier}.install.log"
        descriptor = os.open(
            path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, (line + "\n").encode("utf-8", errors="replace"))
        finally:
            os.close(descriptor)


dependency_installer = DependencyInstaller()
