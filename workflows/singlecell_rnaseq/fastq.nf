#!/usr/bin/env nextflow
// FASTQ graph: build one shared reference, then quantify each independent library.
nextflow.enable.dsl = 2

process STAR_INDEX {
    label 'quantification'
    cache 'deep'
    publishDir "${params.outdir}/reference", mode: 'copy', pattern: 'index_provenance.json'
    input:
    path manifest_file, stageAs: 'prepared_fastq_manifest.json'
    path fasta, stageAs: 'reference.fa'
    path gtf, stageAs: 'genes.gtf'
    path helper, stageAs: 'fastq_stage.py'
    output:
    path 'star_index', emit: index
    path 'index_provenance.json'
    script:
    """
    python3 fastq_stage.py index prepared_fastq_manifest.json ${task.cpus} ${params.max_memory_gb}
    """
}

process STARSOLO {
    label 'quantification'
    cache 'deep'
    publishDir { "${params.outdir}/quantification/${sample_id}" }, mode: 'copy', overwrite: false
    input:
    tuple val(sample_id), path(sample_file, stageAs: 'sample.json'),
        path(reads, stageAs: 'read????.fastq.gz'), path(whitelist, stageAs: 'whitelist.txt')
    path genome, stageAs: 'star_index'
    path helper, stageAs: 'fastq_stage.py'
    output:
    path 'Solo.out'
    path 'matrix'
    path 'quantification_provenance.json'
    path 'fastq_validation.json'
    path 'Log.final.out'
    path 'Log.out'
    script:
    """
    python3 fastq_stage.py quant sample.json ${task.cpus} ${params.max_memory_gb}
    """
}

workflow {
    if (!params.prepared_manifest) error 'Use run_fastq.py with a FASTQ manifest'
    def manifest_path = file(params.prepared_manifest, checkIfExists: true)
    def manifest = new groovy.json.JsonSlurper().parseText(manifest_path.text)
    def helper = Channel.value(file("${projectDir}/bin/fastq_stage.py", checkIfExists: true))
    STAR_INDEX(Channel.value(manifest_path),
        Channel.value(file(manifest.reference.fasta, checkIfExists: true)),
        Channel.value(file(manifest.reference.gtf, checkIfExists: true)), helper)
    def samples = Channel.fromList(manifest.samples).map { sample ->
        def reads = sample.lanes.collectMany { lane ->
            [file(lane.r1, checkIfExists: true), file(lane.r2, checkIfExists: true)]
        }
        tuple(sample.sample_id,
            file("${manifest_path.parent}/${sample.sample_id}.json", checkIfExists: true),
            reads, file(sample.barcode_whitelist, checkIfExists: true))
    }
    STARSOLO(samples, STAR_INDEX.out.index.first(), helper)
}
