nextflow.enable.dsl = 2

process FASTQC_RAW {
    tag "${sample_id}"
    label 'fastqc'
    publishDir "${params.outdir}/qc/raw/fastqc", mode: 'copy', overwrite: true

    input:
    tuple val(sample_id), path(read1), path(read2)

    output:
    path "*_fastqc.html", emit: reports
    path "*_fastqc.zip", emit: archives

    script:
    """
    fastqc --threads ${task.cpus} --outdir . ${read1} ${read2}
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
    tuple val(sample_id), path(read1), path(read2)

    output:
    tuple val(sample_id), path("${sample_id}_R1.trimmed.fastq.gz"), path("${sample_id}_R2.trimmed.fastq.gz"), emit: reads
    path "${sample_id}.cutadapt.log", emit: logs

    script:
    """
    cutadapt \
      --cores ${task.cpus} \
      --minimum-length 20 \
      --quality-cutoff 20 \
      -a AGATCGGAAGAGCACACGTCTGAACTCCAGTCA \
      -A AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT \
      --output ${sample_id}_R1.trimmed.fastq.gz \
      --paired-output ${sample_id}_R2.trimmed.fastq.gz \
      ${read1} ${read2} \
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
    """
    fastqc --threads ${task.cpus} --outdir . ${read1} ${read2}
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

    output:
    tuple val(sample_id), path("${sample_id}"), emit: quantifications

    script:
    """
    kallisto quant \
      --index ${kallisto_index} \
      --rf-stranded \
      --threads ${task.cpus} \
      --output-dir ${sample_id} \
      ${read1} ${read2}
    """
}

process FULL_HUMAN_ANALYSIS {
    label 'analysis'
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    tuple val(sample_ids), val(conditions), path(quantification_dirs)
    path biomart

    output:
    path "differential_expression"
    path "figures"
    path "tables"

    script:
    def rows = (0..<sample_ids.size()).collect { index ->
        "printf '%s\\t%s\\t%s\\n' '${sample_ids[index]}' '${conditions[index]}' '${quantification_dirs[index]}/abundance.tsv' >> samples.tsv"
    }.join('\n')
    """
    printf 'sample_id\tcondition\tabundance_tsv\n' > samples.tsv
    ${rows}

    full_human_analysis.R samples.tsv ${biomart} . OD1 H
    """
}

workflow {
    if (!params.manifest) {
        error "A validated project manifest is required (--manifest)."
    }

    manifest_file = file(params.manifest, checkIfExists: true)
    manifest_data = new groovy.json.JsonSlurper().parse(manifest_file.toFile())
    included_samples = manifest_data.samples.findAll { it.included }

    if (manifest_data.parameters.execution_mode != 'human-demo') {
        error "This workflow release is restricted to the validated human demo manifest."
    }
    if (manifest_data.parameters.differential_expression != true) {
        error "Differential expression must be enabled for the full human demo."
    }
    if (included_samples.size() != 8) {
        error "The full human demo requires exactly eight included samples."
    }
    if (manifest_data.comparisons.size() != 1 ||
        manifest_data.comparisons[0].numerator != 'OD1' ||
        manifest_data.comparisons[0].denominator != 'H') {
        error "The full human demo requires the OD1 versus H comparison."
    }
    if (!manifest_data.reference_resources.kallisto_index) {
        error "The manifest must define reference_resources.kallisto_index."
    }
    if (!manifest_data.reference_resources.biomart) {
        error "The manifest must define reference_resources.biomart."
    }

    condition_by_sample = included_samples.collectEntries { sample ->
        [(sample.sample_id as String): sample.condition as String]
    }
    condition_counts = included_samples.countBy { it.condition }
    if (condition_counts != [H: 4, OD1: 4]) {
        error "The full human demo requires four H and four OD1 samples."
    }

    sample_pairs = Channel
        .fromList(included_samples)
        .map { sample ->
            if (sample.r1_files.size() != 1 || sample.r2_files.size() != 1) {
                error "Demo sample ${sample.sample_id} must contain one R1 and one R2 file."
            }
            tuple(
                sample.sample_id as String,
                file(sample.r1_files[0] as String, checkIfExists: true),
                file(sample.r2_files[0] as String, checkIfExists: true)
            )
        }

    kallisto_index = Channel.value(
        file(manifest_data.reference_resources.kallisto_index as String, checkIfExists: true)
    )
    biomart = Channel.value(
        file(manifest_data.reference_resources.biomart as String, checkIfExists: true)
    )

    FASTQC_RAW(sample_pairs)
    MULTIQC_RAW(FASTQC_RAW.out.archives.flatten().collect())
    CUTADAPT_PAIRED(sample_pairs)
    FASTQC_CLEAN(CUTADAPT_PAIRED.out.reads)
    MULTIQC_CLEAN(FASTQC_CLEAN.out.archives.flatten().collect())
    KALLISTO_QUANT(CUTADAPT_PAIRED.out.reads, kallisto_index)
    analysis_input = KALLISTO_QUANT.out.quantifications
        .map { sample_id, quantification_dir ->
            tuple(sample_id, condition_by_sample[sample_id], quantification_dir)
        }
        .collect(flat: false)
        .map { rows ->
            def ordered = rows.sort { left, right -> left[0] <=> right[0] }
            tuple(
                ordered.collect { it[0] },
                ordered.collect { it[1] },
                ordered.collect { it[2] }
            )
        }
    FULL_HUMAN_ANALYSIS(analysis_input, biomart)
}
