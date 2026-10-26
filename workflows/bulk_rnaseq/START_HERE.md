# Start here: Bulk RNA-seq

> Pipeline guide: This introductory file comes first in Learn and Modify. It
> explains how the executable source files fit together; it is not executed.

This pipeline turns paired RNA sequencing reads into gene counts, comparisons,
tables, and figures.

## How the files connect

1. `main.nf` is the map of the pipeline. It decides which steps run and in
   what order.
2. `nextflow.config` sets general Nextflow behavior, reports, and run profiles.
3. `conf/resources.config` sets CPU, memory, retry, and container limits for
   each step.
4. `bin/run_with_timeout` starts individual commands and stops them when their
   allowed time is exceeded.
5. `bin/bulk_rnaseq_analysis.R` reads the count data and creates the statistical
   results, tables, and figures.

`main.nf` connects all of these files. A run must use matching copies from the
same saved pipeline revision.

## Reading the appendices

Each executable source file has numbered appendix references beside its major
functions or blocks. If a piece of code is difficult to follow, find its
appendix number and look at the appendix at the bottom of that same file. The
appendix gives a plain-English pseudocode version of the existing behavior; it
does not change how the pipeline runs.

## Before changing a file

- Start with one small change and keep notes about why you made it.
- Names passed between `main.nf` and the R script must continue to match.
- Output file names are used by Missus Tom to decide whether a run succeeded.
- CPU and memory limits protect the computer, but they do not make custom code
  safe for files that your user account can access.
- A script can run without errors and still produce scientifically incorrect
  results. Review custom results carefully.

Missus Tom keeps the official pipeline unchanged. You can restore it from this
page if a custom version does not work.
