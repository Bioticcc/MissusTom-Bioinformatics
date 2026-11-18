#!/usr/bin/env nextflow
// Pipeline orchestrator: stage validated inputs, run R, retain execution reports.
nextflow.enable.dsl = 2

process SINGLECELL_ANALYSIS {
    label 'analysis'
    cache 'deep'
    publishDir params.outdir, mode: 'copy', overwrite: false

    input:
    path manifest_file, stageAs: 'prepared_manifest.json'
    path matrix_dirs, stageAs: 'matrix????'
    path analysis_script, stageAs: 'singlecell_analysis.R'
    path import_script, stageAs: 'import_qc.R'

    output:
    path 'qc'
    path 'tables'
    path 'figures'
    path 'objects'

    script:
    """
    export OMP_NUM_THREADS=${task.cpus}
    export OPENBLAS_NUM_THREADS=${task.cpus}
    export MKL_NUM_THREADS=${task.cpus}
    Rscript --vanilla singlecell_analysis.R prepared_manifest.json ${task.cpus}
    """
}

workflow {
    if (!params.prepared_manifest) error 'Use run_pipeline.py --manifest INPUT --run-dir NEW_DIRECTORY'
    def manifest_path = file(params.prepared_manifest, checkIfExists: true)
    def manifest = new groovy.json.JsonSlurper().parseText(manifest_path.text)
    def matrices = manifest.samples.collect { file(it.matrix_dir, checkIfExists: true) }
    SINGLECELL_ANALYSIS(Channel.value(manifest_path), Channel.value(matrices),
        Channel.value(file("${projectDir}/bin/singlecell_analysis.R", checkIfExists: true)),
        Channel.value(file("${projectDir}/bin/import_qc.R", checkIfExists: true)))
}
