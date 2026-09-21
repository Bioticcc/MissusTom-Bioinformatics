#!/usr/bin/env python3
"""Run the five-stage, single-sample ONT modBAM workflow safely.

The manifest is deliberately the only source of input, reference, annotation,
and executable locations.  A resolved, shell-escaped environment is written to
the run directory so each stage is reproducible without inheriting machine
configuration from this repository.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES = tuple(ROOT / "stages" / f"{number:02d}_{name}.sh" for number, name in (
    (1, "align_modbam"), (2, "finalize_alignment"), (3, "ont_qc_and_coverage"),
    (4, "methylation_analysis"), (5, "methylation_exploration"),
))
DEFAULTS = {
    "alignment_threads": 4, "sort_threads": 4, "sort_memory_per_thread": "1G",
    "validation_threads": 2, "qc_threads": 4, "coverage_window_size": 100000,
    "coverage_thresholds": "1,5,10,20", "coverage_exclude_flags": 1796,
    "coverage_min_mapq": 0, "low_coverage_min_1x_breadth_percent": 80,
    "low_coverage_depth_threshold": 5, "modkit_threads": 4, "modkit_io_threads": 2,
    "modkit_bgzf_threads": 2, "modkit_sampling_threads": 2,
    "modkit_tag_check_reads": 50000, "modkit_sample_reads": 50000,
    "modkit_filter_percentile": 0.1, "modkit_max_depth": 60000,
    "methylation_window_size": 100000, "exploration_min_valid_coverage": 10,
    "exploration_min_feature_cpgs": 5, "exploration_top_window_count": 20,
    "exploration_plot_dpi": 300,
}
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MEMORY = re.compile(r"^[1-9][0-9]*[KMGTP]$")

class ManifestError(ValueError):
    pass

def path_value(value: object, base: Path, field: str, *, executable: bool = False) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{field} must be a non-empty path string")
    if "\r" in value or "\n" in value:
        raise ManifestError(f"{field} must not contain a line break")
    path = Path(value).expanduser()
    if not path.is_absolute(): path = base / path
    if path.is_symlink(): raise ManifestError(f"{field} must not be a symbolic link: {path}")
    path = path.resolve()
    if not path.is_file() or not os.access(path, os.R_OK): raise ManifestError(f"{field} is not a readable regular file: {path}")
    if executable and not os.access(path, os.X_OK): raise ManifestError(f"{field} is not executable: {path}")
    return path

def path_tool(name: str) -> str:
    """Resolve a declared local executable without accepting tool paths in manifests."""
    value = shutil.which(name)
    if value is None:
        raise ManifestError(f"required executable is not available on PATH: {name}")
    return str(Path(value).resolve())

def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"

def reject_symlink_components(path: Path, field: str) -> None:
    """Reject an existing symlink anywhere in a write target's spelling."""
    candidate = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts[1 if path.is_absolute() else 0:]:
        candidate /= part
        if candidate.is_symlink():
            raise ManifestError(f"{field} contains a symbolic-link component: {candidate}")

def positive_int(value: object, field: str, *, maximum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or (maximum is not None and value > maximum):
        suffix = f" no greater than {maximum}" if maximum is not None else ""
        raise ManifestError(f"{field} must be a positive integer{suffix}")
    return value

def validate_settings(settings: dict[str, object], cpus: int, memory_gb: float) -> dict[str, object]:
    merged: dict[str, object] = {**DEFAULTS, **settings}
    thread_keys = ("alignment_threads", "sort_threads", "validation_threads", "qc_threads", "modkit_threads", "modkit_io_threads", "modkit_bgzf_threads", "modkit_sampling_threads")
    for key in thread_keys:
        value = positive_int(merged[key], f"parameters.{key}")
        if value > cpus: raise ManifestError(f"parameters.{key} must not exceed resource_profile.cpus ({cpus})")
        merged[key] = value
    if not isinstance(merged["sort_memory_per_thread"], str) or not MEMORY.fullmatch(merged["sort_memory_per_thread"]):
        raise ManifestError("parameters.sort_memory_per_thread must look like 2G")
    memory_units = {"K": 1 / (1024 * 1024), "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 * 1024}
    requested_sort_gb = int(merged["sort_memory_per_thread"][:-1]) * memory_units[merged["sort_memory_per_thread"][-1]] * (merged["sort_threads"] + 1)
    if requested_sort_gb > memory_gb * 0.8:
        raise ManifestError("sort memory (including the main thread) must leave at least 20% of resource_profile.memory_gb available")
    for key in ("coverage_window_size", "low_coverage_depth_threshold", "modkit_tag_check_reads", "modkit_sample_reads", "methylation_window_size", "exploration_min_valid_coverage", "exploration_min_feature_cpgs", "exploration_top_window_count", "exploration_plot_dpi"):
        merged[key] = positive_int(merged[key], f"parameters.{key}")
    if merged["low_coverage_depth_threshold"] < 2: raise ManifestError("parameters.low_coverage_depth_threshold must be at least 2")
    if merged["exploration_plot_dpi"] < 72: raise ManifestError("parameters.exploration_plot_dpi must be at least 72")
    if merged["coverage_window_size"] != merged["methylation_window_size"]:
        raise ManifestError("coverage_window_size and methylation_window_size must match for coordinate-joined exploration")
    for key, maximum in (("coverage_exclude_flags", None), ("coverage_min_mapq", 255), ("modkit_max_depth", 60000)):
        value = merged[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or (maximum is not None and value > maximum):
            raise ManifestError(f"parameters.{key} is outside its supported range")
    if merged["modkit_max_depth"] < 1: raise ManifestError("parameters.modkit_max_depth must be positive")
    for key in ("low_coverage_min_1x_breadth_percent", "modkit_filter_percentile"):
        value = merged[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool): raise ManifestError(f"parameters.{key} must be numeric")
        merged[key] = float(value)
    if not 0 <= merged["low_coverage_min_1x_breadth_percent"] <= 100: raise ManifestError("parameters.low_coverage_min_1x_breadth_percent must be 0..100")
    if not 0 <= merged["modkit_filter_percentile"] < 1: raise ManifestError("parameters.modkit_filter_percentile must be >=0 and <1")
    thresholds = merged["coverage_thresholds"]
    if isinstance(thresholds, list): thresholds = ",".join(str(item) for item in thresholds)
    if not isinstance(thresholds, str): raise ManifestError("parameters.coverage_thresholds must be comma-delimited integers")
    try: parsed = [int(item) for item in thresholds.split(",")]
    except ValueError as exc: raise ManifestError("parameters.coverage_thresholds must be comma-delimited integers") from exc
    if parsed != sorted(set(parsed)) or any(item < 1 for item in parsed) or not {1, 5, 10, 20}.issubset(parsed):
        raise ManifestError("parameters.coverage_thresholds must be ascending and include 1,5,10,20")
    merged["coverage_thresholds"] = thresholds
    return merged

def load_manifest(path: Path, outdir: Path, run_id: str) -> dict[str, str]:
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ManifestError(f"cannot read JSON manifest: {exc}") from exc
    if not isinstance(data, dict): raise ManifestError("manifest must be a JSON object")
    if data.get("schema_version") != "1.0.0": raise ManifestError("schema_version must be '1.0.0'")
    if data.get("pipeline_identifier") != "ont-analysis" or data.get("pipeline_version") != "0.1.0":
        raise ManifestError("ONT runner requires pipeline_identifier 'ont-analysis' and pipeline_version '0.1.0'")
    if data.get("organism") != "Mus musculus" or data.get("reference_genome") != "GRCm38p6":
        raise ManifestError("ONT runner supports only Mus musculus GRCm38p6")
    if data.get("execution_profile") != "local": raise ManifestError("ONT runner supports only the local execution profile")
    resources = data.get("reference_resources")
    samples = data.get("samples")
    parameters = data.get("parameters", {})
    profile = data.get("resource_profile")
    input_directory = data.get("input_directory")
    if not isinstance(resources, dict) or not isinstance(samples, list) or not isinstance(parameters, dict) or not isinstance(profile, dict):
        raise ManifestError("reference_resources, samples, parameters, and resource_profile must be objects/arrays")
    if not isinstance(input_directory, str): raise ManifestError("input_directory must be a path string")
    input_root = Path(input_directory).resolve()
    if not input_root.is_dir(): raise ManifestError(f"input_directory is not a directory: {input_root}")
    reference_name = data.get("reference_genome")
    if not isinstance(reference_name, str) or not reference_name.strip():
        raise ManifestError("reference_genome must be a non-empty string")
    included = [item for item in samples if isinstance(item, dict) and item.get("included") is True]
    if len(included) != 1: raise ManifestError("ONT execution requires exactly one included sample")
    if data.get("comparisons"):
        raise ManifestError("ONT single-sample execution does not accept comparisons")
    sample = included[0]
    sample_id = sample.get("sample_id")
    bam_files = sample.get("ont_bam_files")
    if not isinstance(sample_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sample_id):
        raise ManifestError("included sample.sample_id must be a safe identifier")
    if not isinstance(bam_files, list) or not bam_files: raise ManifestError("included sample.ont_bam_files must be a non-empty list")
    base = path.parent.resolve()
    bams = [path_value(item, base, f"sample.ont_bam_files[{index}]") for index, item in enumerate(bam_files)]
    for requested, bam in zip(bam_files, bams, strict=True):
        if Path(requested).is_symlink() or bam.suffix.lower() != ".bam" or not bam.is_relative_to(input_root):
            raise ManifestError(f"ONT BAM must be a regular .bam under input_directory: {bam}")
    if len(set(bams)) != len(bams): raise ManifestError("sample.ont_bam_files contains duplicate paths")
    names = [bam.name for bam in bams]
    if len(set(names)) != len(names): raise ManifestError("sample.ont_bam_files contains duplicate BAM basenames")
    expected_count = parameters.get("expected_pass_bam_count", len(bams))
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count <= 0
        or expected_count != len(bams)
    ):
        raise ManifestError(
            "parameters.expected_pass_bam_count must match the assigned ONT BAM count"
        )
    ref = path_value(resources.get("reference_fasta"), base, "resources.reference_fasta")
    mmi = path_value(resources.get("minimap2_index"), base, "resources.minimap2_index")
    reference_fai = path_value(resources.get("reference_fai"), base, "resources.reference_fai")
    annotation_keys = ("gencode_gff3", "cpg_islands", "ccre_table", "intergenic_bed")
    supplied_annotations = [key for key in annotation_keys if key in resources]
    if supplied_annotations and len(supplied_annotations) != len(annotation_keys):
        missing_annotations = sorted(set(annotation_keys) - set(supplied_annotations))
        raise ManifestError(
            "annotation exploration resources must be supplied as a complete group; missing: "
            + ", ".join(missing_annotations)
        )
    annotations = {
        key: path_value(resources[key], base, f"resources.{key}")
        for key in supplied_annotations
    }
    instrument_report = (
        path_value(resources["ont_instrument_report"], base, "resources.ont_instrument_report")
        if "ont_instrument_report" in resources
        else None
    )
    cpus = positive_int(profile.get("cpus"), "resource_profile.cpus")
    memory_gb = profile.get("memory_gb")
    if not isinstance(memory_gb, (int, float)) or isinstance(memory_gb, bool) or not math.isfinite(memory_gb) or memory_gb <= 0:
        raise ManifestError("resource_profile.memory_gb must be positive")
    settings = {key: value for key, value in parameters.items() if key in DEFAULTS}
    for key in ("alignment_threads", "sort_threads", "validation_threads", "qc_threads", "modkit_threads", "modkit_io_threads", "modkit_bgzf_threads", "modkit_sampling_threads"):
        if key not in settings: settings[key] = min(int(DEFAULTS[key]), cpus)
    if "sort_memory_per_thread" not in settings:
        per_thread_mb = max(1, min(1024, int(float(memory_gb) * 0.8 * 1024 / (settings["sort_threads"] + 1))))
        settings["sort_memory_per_thread"] = f"{per_thread_mb}M"
    merged = validate_settings(settings, cpus, float(memory_gb))
    output = outdir.resolve()
    if output.is_relative_to(input_root) or input_root.is_relative_to(output):
        raise ManifestError("outdir must be separate from and outside input_directory")
    values = {
        "WORKFLOW_ROOT": str(ROOT), "RUN_ID": run_id, "SAMPLE_ID": sample_id, "REFERENCE_NAME": reference_name.strip(),
        "SAMPLE_OUTPUT": str(output), "REFERENCE_FASTA": str(ref), "REFERENCE_FAI": str(reference_fai), "REFERENCE_MMI": str(mmi),
        "ANNOTATION_EXPLORATION_ENABLED": "1" if annotations else "0",
        "METHYLATION_GENCODE_GFF3": str(annotations.get("gencode_gff3", "")),
        "METHYLATION_CPG_ISLANDS_JSON": str(annotations.get("cpg_islands", "")),
        "METHYLATION_CCRE_TABLE": str(annotations.get("ccre_table", "")),
        "METHYLATION_INTERGENIC_BED": str(annotations.get("intergenic_bed", "")),
        "ONT_INSTRUMENT_REPORT": str(instrument_report or ""),
        "SAMTOOLS_BIN": path_tool("samtools"), "DORADO_BIN": path_tool("dorado"),
        "MOSDEPTH_BIN": path_tool("mosdepth"), "MODKIT_BIN": path_tool("modkit"),
        "BGZIP_BIN": path_tool("bgzip"), "TABIX_BIN": path_tool("tabix"),
        "RSCRIPT_BIN": path_tool("Rscript"),
        "INPUT_BAM_LIST": str(output / "config" / "ont_bam_files.list"),
        "PIPELINE_SETTINGS_FILE": str(output / "config" / "pipeline-settings.env"),
    }
    values.update({key.upper(): str(value) for key, value in merged.items()})
    values["EXPECTED_PASS_BAM_COUNT"] = str(expected_count)
    values["MANIFEST_PATH"] = str(path.resolve())
    values["BAM_FILES"] = "\n".join(str(item) for item in bams) + "\n"
    return values

def write_config(values: dict[str, str], output: Path) -> Path:
    reject_symlink_components(output, "outdir")
    if output.exists():
        for directory, dirs, files in os.walk(output, followlinks=False):
            for name in dirs + files:
                target = Path(directory) / name
                if target.is_symlink():
                    raise ManifestError(f"generated output contains a symbolic link: {target}")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ManifestError(f"outdir must be a real directory, not a symlink or file: {output}")
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(output, 0o700)
    config = output / "config"
    if config.is_symlink() or (config.exists() and not config.is_dir()):
        raise ManifestError(f"generated config directory is unsafe: {config}")
    config.mkdir(mode=0o700, exist_ok=True); os.chmod(config, 0o700)
    def write_stable(path: Path, content: str) -> None:
        temporary = path.with_name(path.name + ".partial")
        if path.is_symlink() or temporary.is_symlink():
            raise ManifestError(f"generated file target is unsafe: {path}")
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            temporary.write_text(content, encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(path)

    bam_list = config / "ont_bam_files.list"
    bam_content = values["BAM_FILES"]
    write_stable(bam_list, bam_content)
    env_path = config / "project.env"
    lines = ["# Generated by workflows/ont_analysis/run_pipeline.py; do not edit."]
    lines += [f"{key}={shell_quote(value)}" for key, value in sorted(values.items()) if key != "BAM_FILES"]
    env_content = "\n".join(lines) + "\n"
    write_stable(env_path, env_content)
    settings_path = Path(values["PIPELINE_SETTINGS_FILE"])
    settings_lines = ["# Stable stage-invalidation inputs; generated by run_pipeline.py."]
    settings_lines += [f"{key}={shell_quote(value)}" for key, value in sorted(values.items()) if key not in {"RUN_ID", "BAM_FILES", "MANIFEST_PATH", "PIPELINE_SETTINGS_FILE"}]
    write_stable(settings_path, "\n".join(settings_lines) + "\n")
    manifest_copy = config / "manifest.json"
    manifest_temporary = manifest_copy.with_suffix(".json.partial")
    if manifest_copy.is_symlink() or manifest_temporary.is_symlink():
        raise ManifestError("generated manifest target is unsafe")
    shutil.copy2(values["MANIFEST_PATH"], manifest_temporary)
    os.chmod(manifest_temporary, 0o600)
    manifest_temporary.replace(manifest_copy)
    return env_path

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not RUN_ID.fullmatch(args.run_id): parser.error("--run-id may contain only letters, numbers, dot, underscore, and hyphen")
    try:
        if not args.manifest.is_file(): raise ManifestError(f"manifest not found: {args.manifest}")
        requested_output = args.outdir.expanduser()
        reject_symlink_components(requested_output, "outdir")
        output = requested_output.resolve()
        values = load_manifest(args.manifest.resolve(), output, args.run_id)
        env_path = write_config(values, output)
        if args.check_only:
            print(f"CHECK-ONLY: manifest, contained BAM paths, resources, PATH tools, and generated config validate: {env_path}")
            return 0
        for stage in STAGES:
            command = ["bash", str(stage)]
            print("RUN:", " ".join(command), flush=True)
            environment = os.environ | {"PIPELINE_ENV": str(env_path)}
            subprocess.run(command, check=True, env=environment)  # fixed argv; never a shell
    except (ManifestError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 1
    return 0
if __name__ == "__main__": raise SystemExit(main())
