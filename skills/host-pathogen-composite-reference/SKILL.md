---
name: host-pathogen-composite-reference
description: Build, validate and use a host plus pathogen (for example human plus EBV/viral) composite reference for STAR/STARsolo single-cell and bulk RNA-seq. Merges FASTA/GTF with collision checks, converts viral GFF3 to a per-gene GTF so CDS-only genes are counted, handles genomes with features crossing the circular origin, computes genomeSAindexNbases and sjdbOverhang, and pre-flights the barcode whitelist. Use for viral or bacterial reads in scRNA-seq, EBV-positive cell detection, 'host+virus index', GFF3 to GTF, STARsolo chemistry/whitelist questions, viral genes with zero counts.
---

# Host + pathogen composite reference (STAR / STARsolo)

Aligning against the host genome alone silently discards every pathogen read. A composite reference (host contigs plus the pathogen contig, one FASTA, one GTF, one index) fixes that, but three failures are easy to miss and cost hours or produce wrong biology: contig-name or gene-id collisions, pathogen genes without exon rows (never counted), and a barcode whitelist that does not match the chemistry. This skill covers all three with scripts that are tested offline.

Requirements: `python3` (>= 3.8, standard library only) for all scripts; STAR for the index and alignment steps. Run any script with `--help`. Paths are relative to this skill folder.

## Procedure

1. **Collect inputs and decide names.** Host FASTA + GTF (same release, e.g. GENCODE primary assembly), pathogen FASTA + GFF3 (e.g. an NCBI RefSeq record). Record accession, version and download date. The pathogen contig name in the FASTA must equal the first column of its annotation and must not collide with any host contig.
2. **Convert the pathogen GFF3 to a per-gene GTF.**
   `python3 scripts/viral_quant_annotation.py --gff virus.gff3 --contig NC_XXXXXX.X --fasta virus.fa --out-gtf virus.gtf [--strip-prefix LOCUSPREFIX_]`
   Every gene gets exon rows: from its exons, else its CDS rows, else the gene row. Read the stderr summary (how many genes were exon-defined, CDS-defined, gene-row only). Features crossing the circular origin are listed in `virus_wrapped.tsv`: open it and check each placement. `--wrap split` (default) makes two blocks; `cap` truncates at the contig end; `error` stops.
   For 5' or 3' libraries, extension of the footprint into the UTR is optional (`--upstream-ext N` for 5' chemistry, `--downstream-ext N` for 3' chemistry, `--ext-for cds_only|all`). Use 0 for the index build; use extension only for a separate quantification annotation. The 300 bp starter value is not validated: choose it from the observed 5' (or 3') read pile-up and re-check the `new_overlap_ids_after_ext` column in `virus_genes.tsv`, which lists neighbours that start to overlap only because of the extension.
3. **Merge.**
   `python3 scripts/composite_ref.py build --host-fasta host.fa.gz --host-gtf host.gtf.gz --virus-fasta virus.fa --virus-gtf virus.gtf --out-fasta composite.fa --out-gtf composite.gtf`
   Refuses duplicate contig names, pathogen annotation on unknown contigs, host annotation on the pathogen contig and gene_ids present in both. A host FASTA without a final newline cannot swallow the pathogen header.
4. **Check before indexing.**
   `python3 scripts/composite_ref.py check --fasta composite.fa --gtf composite.gtf --pathogen-contig NC_XXXXXX.X --strict`
   Errors (exit 1): GTF contig absent from the FASTA, coordinates outside a contig, exon/CDS rows without gene_id or transcript_id, a transcript_id shared by several genes. Warning: genes with a gene row but no exon rows. Resolve every message; do not start a multi-hour index build on a reference that fails.
5. **Compute index parameters and build.**
   `python3 scripts/composite_ref.py star-params --fasta composite.fa --gtf composite.gtf --read-length 150 --threads 16 --limit-ram-gb 45`
   prints a complete `STAR --runMode genomeGenerate` command. `--genomeSAindexNbases` follows the TOTAL genome length (min(14, log2(length)/2 - 1), rounded down): a human + virus composite stays at 14. Lowering it because the virus contig is small is a common mistake; use the small values only for indexes of a small genome alone. `--sjdbOverhang` is the longest read length minus 1 (the cDNA read for 10x data). The step needs tens of GB of RAM for human; cap it with `--limitGenomeGenerateRAM`. Run it detached and say so before starting.
6. **Pre-flight the whitelist before every STARsolo run.**
   `python3 scripts/whitelist_preflight.py --r1 sample_R1.fastq.gz --whitelist candidate.txt [other.txt ...] --cb-start 1 --cb-len 16`
   Exit 3 means fewer than 90% of cell barcodes are in the whitelist: wrong chemistry/whitelist, wrong read order, or wrong `--cb-start`. Details and the chemistry table: `references/starsolo-parameters.md`.
7. **Align and quantify** with the parameters in `references/starsolo-parameters.md`, then check the STARsolo summary ("Reads With Valid Barcodes" should be high, typically well above 0.7) and that the pathogen contig appears among mapped reads. Keep a record: reference build command, `composite.fa.contigs.tsv`, `virus_genes.tsv`, whitelist file name and the pre-flight output.

## Rules that prevent known failures

- A gene with only gene/CDS rows in the GTF is not counted by STAR and does not even appear in `ReadsPerGene`. The check warns about it; the annotation step fixes it.
- Gene names are not unique in viral genomes (repeat families share a name). `gene_id` comes from the locus tag (unique), `gene_name` from the name; do not collapse by name before quantification unless that is the intent. The `same_name_other_loci` column lists the sharing loci.
- Overlapping, same-strand viral genes make read-to-gene assignment ambiguous; antisense overlaps are reported separately. Report these limitations with any viral-expression result.
- Do not mix GTF releases between host FASTA and GTF.
- Keep pathogen-contig reads out of host-based QC statistics (for example the mitochondrial/ribosomal fractions) unless that is intended.
- `--wrap` choices are not validated against real data in the tests; the wrapped-features table exists so a person confirms them.

## Outputs

`virus.gtf`, `virus_genes.tsv` (per-gene footprint, source, overlaps), `virus_overlaps.tsv`, `virus_wrapped.tsv` (if any), `composite.fa`, `composite.fa.contigs.tsv`, `composite.gtf`, the STAR index directory, whitelist pre-flight output.

## Testing

`bash tests/run.sh` (16 tests). Highlights: the annotation output is identical to the output of the original R implementation (GenomicRanges/rtracklayer) on a synthetic viral GFF3 for two parameter sets (golden files in `tests/fixtures/expected/`); circular-origin cases; a real STAR index of a tiny host+virus composite, where a CDS-only viral gene is counted after the annotation step and is absent from STAR's output without it. The STAR test is skipped when STAR is not installed.
