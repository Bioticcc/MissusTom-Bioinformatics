import importlib.util
import tempfile
import time
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "lib/check_modbam_tags.py"
spec = importlib.util.spec_from_file_location("tag_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TagProbeTests(unittest.TestCase):
    def test_combined_tags_after_uncalled_read_and_bounded_producer(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "samtools"
            tool.write_text(
                "#!/usr/bin/env python3\nimport time\nprint('untagged', flush=True)\n"
                "print('r\\t0\\tchr1\\t1\\t60\\t1M\\t*\\t0\\t0\\tC\\tI"
                "\\tMM:Z:C+mh,0;\\tML:B:C,204,26\\tMN:i:1', flush=True)\n"
                "time.sleep(30)\n"
            )
            tool.chmod(0o700)
            started = time.monotonic()
            self.assertTrue(probe.check_tags(str(tool), "stub.bam"))
            self.assertLess(time.monotonic() - started, 5)

    def test_missing_tags_fail_instead_of_scanning_every_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "samtools"
            tool.write_text("#!/usr/bin/env python3\nwhile True: print('untagged', flush=True)\n")
            tool.chmod(0o700)
            self.assertFalse(probe.check_tags(str(tool), "stub.bam", max_records=5))

    def test_legacy_tags_without_mn_are_accepted_on_primary_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "samtools"
            tool.write_text(
                "#!/usr/bin/env python3\nprint('r\\t0\\tchr1\\t1\\t60\\t1M\\t*\\t0\\t0\\tC\\tI"
                "\\tMm:Z:C+m,0;\\tMl:B:C,204')\n"
            )
            tool.chmod(0o700)
            valid, message = probe.inspect_tags(str(tool), "legacy.bam")
            self.assertTrue(valid)
            self.assertIn("primary mapped read", message)

    def test_existing_mn_must_match_sequence_length(self):
        with tempfile.TemporaryDirectory() as temporary:
            tool = Path(temporary) / "samtools"
            record = "r\t0\tchr1\t1\t60\t1M\t*\t0\t0\tC\tI\tMM:Z:C+m,0;\tML:B:C,204\tMN:i:2"
            tool.write_text(f"#!/usr/bin/env python3\nprint({record!r})\n")
            tool.chmod(0o700)
            valid, message = probe.inspect_tags(str(tool), "invalid.bam")
            self.assertFalse(valid)
            self.assertIn("sequence length", message)
