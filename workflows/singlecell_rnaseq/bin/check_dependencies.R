#!/usr/bin/env Rscript
# Report all missing/incompatible packages together; never install at run time.
required <- c(Seurat = "5.3.0", SeuratObject = "5.0.0", Matrix = "1.6.0",
              ggplot2 = "3.5.0", jsonlite = "1.8.0", future = "1.34.0")
problems <- character()
if (getRversion() < "4.4.0") problems <- c(problems, "R >= 4.4.0 is required")
for (package in names(required)) {
    if (!requireNamespace(package, quietly = TRUE)) {
        problems <- c(problems, paste(package, "is missing"))
    } else {
        version <- packageVersion(package)
        cat(package, as.character(version), "\n")
        if (version < required[[package]]) {
            problems <- c(problems, paste(package, "requires >=", required[[package]]))
        }
        if (package %in% c("Seurat", "SeuratObject") && version >= "6.0.0") {
            problems <- c(problems, paste(package, "v6 is not validated"))
        }
        if (package == "SeuratObject" && !"JoinLayers" %in% getNamespaceExports(package)) {
            problems <- c(problems, "SeuratObject must export JoinLayers to read split v5 layers")
        }
    }
}
if (length(problems)) stop(paste(problems, collapse = "; "), call. = FALSE)
cat("SingleCell runtime dependencies available.\n")
