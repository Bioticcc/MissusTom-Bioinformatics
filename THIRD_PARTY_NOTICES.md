# Third-party notices

Missus Tom release packages bundle the application frontend, Rust host, Python
backend sidecars, and repository workflow/resource files needed by those
components. The applicable notices and license terms for bundled dependencies
remain those supplied by their respective upstream projects and package
metadata. This document does not assign a license where upstream terms have not
been independently reviewed.

The application can later download or build optional runtime dependencies only
after an operator requests installation. Those post-install downloads are not
bundled in the GitHub release and may include:

- Micromamba;
- Bioconda and conda-forge packages, including ONT tools and R packages;
- Oxford Nanopore Dorado distributions;
- BioContainers images used by the bulk RNA-seq workflow; and
- the locally built bulk RNA-seq analysis image and its upstream base image.

Each downloaded package, image, or archive remains subject to its upstream
license, notices, redistribution conditions, and any hardware or service terms.
Operators are responsible for reviewing those terms before installation or use.

No restricted human demo inputs, ONT inputs, reference genomes or annotations,
managed dependency environments, Docker image layers, generated results,
workflow work directories, logs, provenance maps, credentials, or runtime
state are included in release artifacts.

The ONT runtime also uses a repaired Modkit 0.6.4 build. Sidecar builds include
this native tool and its upstream `LICENCE.txt`, Cargo dependency lock, and
build manifest. Source revision and archive checksums are recorded in
`backend/src/missus_tom/resources/modkit-repair/recipe.json`; the complete
corresponding upstream source is available at
https://github.com/SuhasSrinivasan/modkit/tree/bb20328778b2a5e3f0f815b36af2ae09c1df7ae7.
The ambiguity repair originates from nanoporetech/modkit PR #714. Modkit remains
subject to the Oxford Nanopore Technologies PLC Public License Version 1.0;
its Rust dependencies retain their own upstream licenses.
