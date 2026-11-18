"""Native regression oracles for ambiguous bases and retained downstream calls."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MODKIT = os.environ.get("ONT_TEST_MODKIT")
SAMTOOLS = os.environ.get("ONT_TEST_SAMTOOLS")


@unittest.skipUnless(MODKIT and SAMTOOLS, "native Modkit/Samtools required")
class ModkitAmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_tool(self, tool, *args):
        result = subprocess.run(
            [tool, *map(str, args)], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def bam(self, sequences, records):
        sam = self.root / "input.sam"
        ref = self.root / "ref.fa"
        ref.write_text("".join(f">{name}\n{seq}\n" for name, seq in sequences))
        sam.write_text(
            "@HD\tVN:1.6\tSO:coordinate\n"
            + "".join(f"@SQ\tSN:{name}\tLN:{len(seq)}\n" for name, seq in sequences)
            + "\n".join(records)
            + "\n"
        )
        bam = self.root / "input.bam"
        self.run_tool(SAMTOOLS, "view", "-b", "-o", bam, sam)
        self.run_tool(SAMTOOLS, "index", bam)
        self.run_tool(SAMTOOLS, "faidx", ref)
        return bam, ref

    def pileup(self, bam, ref, optimized):
        bed = self.root / "calls.bed"
        bed.unlink(missing_ok=True)
        args = ["--modified-bases", "C:m"] if optimized else []
        self.run_tool(
            MODKIT,
            "pileup",
            bam,
            bed,
            "--ref",
            ref,
            "--no-filtering",
            "--threads",
            "1",
            *args,
        )
        return [line.split("\t") for line in bed.read_text().splitlines()]

    def test_leading_and_softclip_ambiguity_retain_downstream_call_in_both_workers(
        self,
    ):
        for softclip in (False, True):
            sequence = "CNCTGTACTT" if softclip else "NCTGTACTTN"
            cigar = "1S9M" if softclip else "10M"
            mm = "0,0" if softclip else "0"
            ml = "255,255" if softclip else "255"
            bam, ref = self.bam(
                [("chr1", "CCTGTACTTC")],
                [
                    (
                        f"r\t0\tchr1\t1\t60\t{cigar}\t*\t0\t0\t{sequence}\tIIIIIIIIII"
                        f"\tMM:Z:C+m?,{mm};\tML:B:C,{ml}\tMN:i:10"
                    )
                ],
            )
            for optimized in (False, True):
                with self.subTest(softclip=softclip, optimized=optimized):
                    rows = self.pileup(bam, ref, optimized)
                    self.assertEqual(
                        rows,
                        [
                            [
                                "chr1",
                                "1",
                                "2",
                                "m",
                                "1",
                                "+",
                                "1",
                                "2",
                                "255,0,0",
                                "1",
                                "100.00",
                                "1",
                                "0",
                                "0",
                                "0",
                                "0",
                                "0",
                                "0",
                            ]
                        ],
                    )

    def test_forward_reverse_iupac_summary_and_exact_calls(self):
        for symbol in "NRYMKSWBDHV":
            with self.subTest(symbol=symbol):
                bam, ref = self.bam(
                    [("chrF", "CAN"), ("chrR", "NTG")],
                    [
                        (
                            f"f\t0\tchrF\t1\t60\t3M\t*\t0\t0\tCA{symbol}\tIII"
                            "\tMM:Z:C+m?,0;\tML:B:C,255\tMN:i:3"
                        ),
                        (
                            f"r\t16\tchrR\t1\t60\t3M\t*\t0\t0\t{symbol}TG\tIII"
                            "\tMM:Z:C+m?,0;\tML:B:C,255\tMN:i:3"
                        ),
                    ],
                )
                summary = self.run_tool(
                    MODKIT,
                    "summary",
                    bam,
                    "--tsv",
                    "--threads",
                    "1",
                    "--io-threads",
                    "1",
                    "--num-reads",
                    "2",
                )
                self.assertIn("C", summary)
                for optimized in (False, True):
                    rows = self.pileup(bam, ref, optimized)
                    self.assertEqual(
                        [r[:6] for r in rows],
                        [
                            ["chrF", "0", "1", "m", "1", "+"],
                            ["chrR", "2", "3", "m", "1", "-"],
                        ],
                    )
                    self.assertTrue(
                        all(r[9:14] == ["1", "100.00", "1", "0", "0"] for r in rows)
                    )

    @unittest.skipUnless(
        os.environ.get("ONT_TEST_BASELINE_MODKIT"), "stock Modkit comparison"
    )
    def test_canonical_joint_calls_match_stock_modkit(self):
        bam, ref = self.bam(
            [("chrF", "CGACG"), ("chrR", "CGACG")],
            [
                (
                    "f\t0\tchrF\t1\t60\t5M\t*\t0\t0\tCGACG\tIIIII"
                    "\tMM:Z:C+mh,0,0;\tML:B:C,255,0,0,255\tMN:i:5"
                ),
                (
                    "r\t16\tchrR\t1\t60\t5M\t*\t0\t0\tCGACG\tIIIII"
                    "\tMM:Z:C+mh,0,0;\tML:B:C,255,0,0,255\tMN:i:5"
                ),
            ],
        )
        for optimized in (False, True):
            extra = ["--modified-bases", "C:m", "C:h"] if optimized else []
            outputs = []
            for tool in (os.environ["ONT_TEST_BASELINE_MODKIT"], MODKIT):
                bed = self.root / "canonical.bed"
                bed.unlink(missing_ok=True)
                self.run_tool(
                    tool,
                    "pileup",
                    bam,
                    bed,
                    "--ref",
                    ref,
                    "--no-filtering",
                    "--threads",
                    "1",
                    *extra,
                )
                outputs.append(bed.read_bytes())
            self.assertTrue(outputs[0])
            self.assertEqual(outputs[0], outputs[1])
