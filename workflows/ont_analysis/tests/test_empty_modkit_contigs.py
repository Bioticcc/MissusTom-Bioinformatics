"""Omitted Modkit stats rows require absence of every bedMethyl coordinate."""

import runpy
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

HELPER = runpy.run_path(
    str(Path(__file__).parents[1] / "lib/summarize_cpg_bedmethyl.py")
)


class EmptyModkitContigTests(unittest.TestCase):
    def test_only_contigs_without_bedmethyl_rows_may_be_omitted(self):
        for mode in ("5mc_only", "5mc_5hmc"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                stats = Path(temporary) / "stats.tsv"
                stats.write_text(
                    "#chrom\tstart\tend\tcount_m\tcount_valid_m\tcount_h\tcount_valid_h\n"
                    "chr1\t0\t4\t1\t2\t0\t2\n"
                )
                contigs = OrderedDict(chr1=4, empty=4)
                counts = {name: HELPER["empty_counts"]() for name in contigs}
                counts["chr1"].update(covered_cpg_sites=1, mod_m=1, valid=2)
                counts["empty"]["reference_cpg_sites"] = 2
                validate = HELPER["validate_modkit_stats"]
                validate(stats, contigs, counts, mode)
                # Even a zero-valid-call row must have its own stats row.
                counts["empty"]["covered_cpg_sites"] = 1
                with self.assertRaisesRegex(
                    ValueError, "missing chromosome row: empty"
                ):
                    validate(stats, contigs, counts, mode)
                counts["empty"]["covered_cpg_sites"] = 0
                stats.write_text(
                    stats.read_text().replace("\t1\t2\t0\t2", "\t0\t2\t0\t2")
                )
                with self.assertRaisesRegex(ValueError, "disagree"):
                    validate(stats, contigs, counts, mode)
