nextflow.enable.dsl = 2

String shellQuote(value) {
    "'" + value.toString().replace("'", "'\"'\"'") + "'"
}

List asFileList(value) {
    value instanceof Collection ? value.toList() : [value]
}

Integer positiveIntegerParameter(value, String parameterName) {
    try {
        def parsed = Integer.parseInt(value.toString())
        if (parsed < 1) throw new NumberFormatException()
        return parsed
    } catch (NumberFormatException ignored) {
        error "${parameterName} must be a positive integer."
    }
}

Double positiveFiniteParameter(value, String parameterName) {
    try {
        def parsed = Double.parseDouble(value.toString())
        if (!Double.isFinite(parsed) || parsed <= 0) throw new NumberFormatException()
        return parsed
    } catch (NumberFormatException ignored) {
        error "${parameterName} must be a positive finite number."
    }
}

process FASTQC_RAW {
    tag "${sample_id}"
    label 'fastqc'
    publishDir "${params.outdir}/qc/raw/fastqc", mode: 'copy', overwrite: true

    input:
    tuple val(sample_id), path(read1_files), path(read2_files)

    output:
    path "*_fastqc.html", emit: reports
    path "*_fastqc.zip", emit: archives

    script:
    def reads = asFileList(read1_files) + asFileList(read2_files)
    def read_args = reads.collect { shellQuote(it) }.join(' ')
    def isolated_read_args = reads.collect { shellQuote(it) }.join(' ')
    def fastqc_commands = task.attempt > 1
        ? """
          run_fastqc_with_native_retry() {
              local read="\$1"
              local max_attempts=2
              local attempt=1
              local fastqc_status=0

              while (( attempt <= max_attempts )); do
                  fastqc_status=0
                  fastqc --threads 1 --outdir . "\$read" || fastqc_status=\$?
                  if (( fastqc_status == 0 )); then
                      return 0
                  fi
                  if (( fastqc_status != 134 && fastqc_status != 139 )); then
                      return "\$fastqc_status"
                  fi
                  if (( attempt >= max_attempts )); then
                      return "\$fastqc_status"
                  fi
                  attempt=\$((attempt + 1))
              done
          }

          for read in ${isolated_read_args}; do
              run_fastqc_with_native_retry "\$read"
          done
          """.stripIndent().trim()
        : "fastqc --threads ${task.cpus} --outdir . ${read_args}"
    """
    ${fastqc_commands}
    """
}

process MULTIQC_RAW {
    label 'multiqc'
    publishDir "${params.outdir}/qc/raw", mode: 'copy', overwrite: true

    input:
    path archives

    output:
    path "raw_multiqc_report.html"
    path "raw_multiqc_report_data"

    script:
    """
    multiqc --force --filename raw_multiqc_report.html --outdir . .
    """
}

process CUTADAPT_PAIRED {
    tag "${sample_id}"
    label 'cutadapt'
    publishDir "${params.outdir}/trimmed", mode: 'copy', overwrite: true

    input:
    tuple val(sample_id), path(read1_files), path(read2_files)
    val adapter_r1
    val adapter_r2
    val trim_quality
    val trim_minimum_length

    output:
    tuple val(sample_id), path("${sample_id}_R1.trimmed.fastq.gz"), path("${sample_id}_R2.trimmed.fastq.gz"), emit: reads
    path "${sample_id}.cutadapt.log", emit: logs

    script:
    def r1_lanes = asFileList(read1_files)
    def r2_lanes = asFileList(read2_files)
    def r1_input = r1_lanes.size() == 1 ? shellQuote(r1_lanes[0]) : "${sample_id}_R1.merged.fastq.gz"
    def r2_input = r2_lanes.size() == 1 ? shellQuote(r2_lanes[0]) : "${sample_id}_R2.merged.fastq.gz"
    def merge_commands = []
    if (r1_lanes.size() > 1) {
        merge_commands << "cat ${r1_lanes.collect { shellQuote(it) }.join(' ')} > ${sample_id}_R1.merged.fastq.gz"
    }
    if (r2_lanes.size() > 1) {
        merge_commands << "cat ${r2_lanes.collect { shellQuote(it) }.join(' ')} > ${sample_id}_R2.merged.fastq.gz"
    }
    def merge_script = merge_commands.join('\n')
    """
    ${merge_script}
    cutadapt \
      --cores ${task.cpus} \
      --minimum-length ${trim_minimum_length} \
      --quality-cutoff ${trim_quality} \
      -a ${adapter_r1} \
      -A ${adapter_r2} \
      --output ${sample_id}_R1.trimmed.fastq.gz \
      --paired-output ${sample_id}_R2.trimmed.fastq.gz \
      ${r1_input} ${r2_input} \
      > ${sample_id}.cutadapt.log
    """
}

process FASTQC_CLEAN {
    tag "${sample_id}"
    label 'fastqc'
    publishDir "${params.outdir}/qc/clean/fastqc", mode: 'copy', overwrite: true

    input:
    tuple val(sample_id), path(read1), path(read2)

    output:
    path "*_fastqc.html", emit: reports
    path "*_fastqc.zip", emit: archives

    script:
    def reads = [read1, read2]
    def isolated_read_args = reads.collect { shellQuote(it) }.join(' ')
    def fastqc_commands = task.attempt > 1
        ? """
          run_fastqc_with_native_retry() {
              local read="\$1"
              local max_attempts=2
              local attempt=1
              local fastqc_status=0

              while (( attempt <= max_attempts )); do
                  fastqc_status=0
                  fastqc --threads 1 --outdir . "\$read" || fastqc_status=\$?
                  if (( fastqc_status == 0 )); then
                      return 0
                  fi
                  if (( fastqc_status != 134 && fastqc_status != 139 )); then
                      return "\$fastqc_status"
                  fi
                  if (( attempt >= max_attempts )); then
                      return "\$fastqc_status"
                  fi
                  attempt=\$((attempt + 1))
              done
          }

          for read in ${isolated_read_args}; do
              run_fastqc_with_native_retry "\$read"
          done
          """.stripIndent().trim()
        : "fastqc --threads ${task.cpus} --outdir . ${read1} ${read2}"
    """
    ${fastqc_commands}
    """
}

process MULTIQC_CLEAN {
    label 'multiqc'
    publishDir "${params.outdir}/qc/clean", mode: 'copy', overwrite: true

    input:
    path archives

    output:
    path "clean_multiqc_report.html"
    path "clean_multiqc_report_data"

    script:
    """
    multiqc --force --filename clean_multiqc_report.html --outdir . .
    """
}

process KALLISTO_QUANT {
    tag "${sample_id}"
    label 'kallisto'
    publishDir "${params.outdir}/counts/kallisto", mode: 'copy', overwrite: true

    input:
    tuple val(sample_id), path(read1), path(read2)
    path kallisto_index
    val strand_flag

    output:
    tuple val(sample_id), path("${sample_id}"), emit: quantifications

    script:
    def index_arg = shellQuote(kallisto_index)
    def read1_arg = shellQuote(read1)
    def read2_arg = shellQuote(read2)
    """
    run_with_timeout 7200 60 kallisto quant \
      --index ${index_arg} \
      ${strand_flag} \
      --threads ${task.cpus} \
      --output-dir ${sample_id} \
      ${read1_arg} ${read2_arg}
    """
}

process BULK_RNASEQ_ANALYSIS {
    label 'analysis'
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    tuple val(sample_ids), val(conditions), val(interventions), path(abundance_files, stageAs: 'quantifications/??/*')
    path transcript_to_gene
    val comparisons
    val adjusted_p_value
    val absolute_log2_fold_change
    val minimum_group_size

    output:
    path "differential_expression"
    path "figures"
    path "tables"

    script:
    def rows = (0..<sample_ids.size()).collect { index ->
        "printf '%s\\t%s\\t%s\\t%s\\n' ${shellQuote(sample_ids[index])} ${shellQuote(conditions[index])} ${shellQuote(interventions[index])} ${shellQuote(abundance_files[index])} >> samples.tsv"
    }.join('\n')
    def comparison_rows = comparisons.collect { comparison ->
        "printf '%s\\t%s\\t%s\\t%s\\n' ${shellQuote(comparison.comparison_id)} ${shellQuote(comparison.numerator)} ${shellQuote(comparison.denominator)} ${shellQuote(comparison.intervention ?: '')} >> comparisons.tsv"
    }.join('\n')
    def mapping_arg = shellQuote(transcript_to_gene)
    """
    printf 'sample_id\tcondition\tintervention\tabundance_tsv\n' > samples.tsv
    ${rows}
    printf 'comparison_id\tnumerator\tdenominator\tintervention\n' > comparisons.tsv
    ${comparison_rows}

    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 RCPP_PARALLEL_NUM_THREADS=1 \
      bulk_rnaseq_analysis.R samples.tsv ${mapping_arg} . comparisons.tsv ${adjusted_p_value} ${absolute_log2_fold_change} ${minimum_group_size}
    """
}

workflow {
    positiveIntegerParameter(params.max_cpus, 'max_cpus')
    positiveFiniteParameter(params.max_memory_gb, 'max_memory_gb')
    positiveIntegerParameter(params.max_parallel_tasks, 'max_parallel_tasks')

    if (params.run_id != null && !(params.run_id as String ==~ /(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)) {
        error "run_id must be a canonical UUID when supplied."
    }

    if (!params.manifest) {
        error "A validated project manifest is required (--manifest)."
    }

    manifest_file = file(params.manifest, checkIfExists: true)
    manifest_data = new groovy.json.JsonSlurper().parse(manifest_file.toFile())
    included_samples = manifest_data.samples.findAll { it.included }
    start_stage = params.start_stage as String

    if (!(start_stage in ['quantification', 'analysis'])) {
        error "Unsupported start stage: ${start_stage}. Expected quantification or analysis."
    }

    if (!manifest_data.comparisons || manifest_data.comparisons.isEmpty()) {
        error "At least one manifest comparison is required."
    }
    if (!manifest_data.reference_resources.transcript_to_gene) {
        error "The manifest must define reference_resources.transcript_to_gene."
    }
    if (start_stage == 'quantification' && !manifest_data.reference_resources.kallisto_index) {
        error "The manifest must define reference_resources.kallisto_index."
    }
    if (start_stage == 'analysis' && manifest_data.reference_resources.kallisto_index) {
        log.warn "Analysis-only run: reference_resources.kallisto_index is present but will not be used."
    }

    condition_by_sample = included_samples.collectEntries { sample ->
        [(sample.sample_id as String): sample.condition as String]
    }
    intervention_by_sample = included_samples.collectEntries { sample ->
        [(sample.sample_id as String): (sample.covariates?.intervention ?: '') as String]
    }
    minimum_group_size = (
        manifest_data.parameters.containsKey('minimum_group_size')
            ? manifest_data.parameters.minimum_group_size
            : 2
    ) as Integer
    manifest_data.comparisons.each { comparison ->
        [comparison.numerator, comparison.denominator].each { group ->
            def matching_samples = included_samples.findAll { sample ->
                sample.condition == group && (
                    !comparison.intervention || sample.covariates?.intervention == comparison.intervention
                )
            }
            if (matching_samples.size() < minimum_group_size) {
                error "Comparison ${comparison.comparison_id} requires at least ${minimum_group_size} samples in ${group}."
            }
        }
    }

    adapter_r1 = (manifest_data.parameters.adapter_r1 ?: 'AGATCGGAAGAGCACACGTCTGAACTCCAGTCA') as String
    adapter_r2 = (manifest_data.parameters.adapter_r2 ?: 'AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT') as String
    trim_quality = (
        manifest_data.parameters.containsKey('trim_quality')
            ? manifest_data.parameters.trim_quality
            : 20
    ) as Integer
    trim_minimum_length = (
        manifest_data.parameters.containsKey('trim_minimum_length')
            ? manifest_data.parameters.trim_minimum_length
            : 20
    ) as Integer
    adjusted_p_value = (
        manifest_data.parameters.containsKey('adjusted_p_value')
            ? manifest_data.parameters.adjusted_p_value
            : 0.05
    ) as Double
    absolute_log2_fold_change = (
        manifest_data.parameters.containsKey('absolute_log2_fold_change')
            ? manifest_data.parameters.absolute_log2_fold_change
            : 0.30
    ) as Double
    transcript_to_gene = Channel.value(
        file(manifest_data.reference_resources.transcript_to_gene as String, checkIfExists: true)
    )

    if (start_stage == 'quantification') {
        strand_flag = [reverse: '--rf-stranded', forward: '--fr-stranded', unstranded: ''][manifest_data.strandedness]
        if (strand_flag == null) {
            error "Strandedness must be reverse, forward, or unstranded."
        }
        sample_pairs = Channel
            .fromList(included_samples)
            .map { sample ->
                if (!sample.r1_files || sample.r1_files.size() != sample.r2_files.size()) {
                    error "Sample ${sample.sample_id} must contain equal non-empty R1 and R2 lane lists."
                }
                tuple(
                    sample.sample_id as String,
                    sample.r1_files.collect { file(it as String, checkIfExists: true) },
                    sample.r2_files.collect { file(it as String, checkIfExists: true) }
                )
            }
        kallisto_index = Channel.value(
            file(manifest_data.reference_resources.kallisto_index as String, checkIfExists: true)
        )

        FASTQC_RAW(sample_pairs)
        MULTIQC_RAW(FASTQC_RAW.out.archives.flatten().collect())
        CUTADAPT_PAIRED(sample_pairs, adapter_r1, adapter_r2, trim_quality, trim_minimum_length)
        FASTQC_CLEAN(CUTADAPT_PAIRED.out.reads)
        MULTIQC_CLEAN(FASTQC_CLEAN.out.archives.flatten().collect())
        KALLISTO_QUANT(CUTADAPT_PAIRED.out.reads, kallisto_index, strand_flag)
        quantifications = KALLISTO_QUANT.out.quantifications.map { sample_id, quantification_dir ->
            tuple(
                sample_id,
                file("${quantification_dir}/abundance.tsv", checkIfExists: true)
            )
        }
    } else {
        quantifications = Channel
            .fromList(included_samples)
            .map { sample ->
                if (!sample.abundance_tsv) {
                    error "Analysis-only sample ${sample.sample_id} must define abundance_tsv."
                }
                def abundance_file = file(
                    sample.abundance_tsv as String,
                    checkIfExists: true
                )
                tuple(sample.sample_id as String, abundance_file)
            }
    }

    analysis_input = quantifications
        .map { sample_id, abundance_file ->
            tuple(
                sample_id,
                condition_by_sample[sample_id],
                intervention_by_sample[sample_id],
                abundance_file
            )
        }
        .collect(flat: false)
        .map { rows ->
            def ordered = rows.sort { left, right -> left[0] <=> right[0] }
            tuple(
                ordered.collect { it[0] },
                ordered.collect { it[1] },
                ordered.collect { it[2] },
                ordered.collect { it[3] }
            )
        }
    BULK_RNASEQ_ANALYSIS(
        analysis_input,
        transcript_to_gene,
        manifest_data.comparisons,
        adjusted_p_value,
        absolute_log2_fold_change,
        minimum_group_size
    )
}
