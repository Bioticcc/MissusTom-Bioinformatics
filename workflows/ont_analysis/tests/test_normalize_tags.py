import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "lib/normalize_modbam_tags.py"
normalize_line = runpy.run_path(str(SOURCE))["normalize_line"]


class NormalizeTagTests(unittest.TestCase):
    def test_renames_only_tags_and_never_invents_mn(self):
        record = "r\t0\tchr1\t1\t60\t2M\t*\t0\t0\tCG\tII\tMm:Z:C+m,0;\tMl:B:C,204\n"
        result = normalize_line(record)
        self.assertEqual(result, record.replace("Mm:Z:", "MM:Z:").replace("Ml:B:", "ML:B:"))
        self.assertNotIn("MN:", result)
        self.assertEqual(normalize_line(result), result)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            normalize_line(record.rstrip() + "\tMM:Z:C+m,0;\n")

    def test_real_bam_normalization_retains_all_records_and_probabilities(self):
        samtools = os.environ.get("ONT_TEST_SAMTOOLS") or shutil.which("samtools")
        if not samtools:
            self.skipTest("Samtools is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [
                f"r{i}\t{flag}\tchr1\t1\t60\t2M\t*\t0\t0\tCG\tII\tMm:Z:C+m,0;\tMl:B:C,204"
                for i, flag in enumerate((0, 2048, 256))
            ]
            sam = "@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:2\n" + "\n".join(records) + "\n"
            bam = subprocess.run(
                [samtools, "view", "-b", "-"], input=sam.encode(), capture_output=True, check=True
            ).stdout
            output = root / "normalized.bam"
            subprocess.run(
                [sys.executable, str(SOURCE), "--samtools", samtools, "--output", str(output)],
                input=bam,
                capture_output=True,
                check=True,
            )
            result = subprocess.run(
                [samtools, "view", str(output)], capture_output=True, text=True, check=True
            ).stdout.splitlines()
            self.assertEqual(
                result,
                [record.replace("Mm:Z:", "MM:Z:").replace("Ml:B:", "ML:B:") for record in records],
            )
