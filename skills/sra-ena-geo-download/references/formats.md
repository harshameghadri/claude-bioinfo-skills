# Table formats and exit codes

## files.tsv (tab-separated, header row)

| column | meaning |
|---|---|
| run | run accession (GEO rows: the GSE/GSM accession) |
| dest_dir | directory the file is written to (created by `fetch`) |
| filename | file name on disk |
| url | download URL (ENA scheme-less URLs get `--scheme`, default `http`) |
| md5 | published md5, empty when unavailable |
| bytes | published size in bytes, empty when unavailable |
| source | `ena`, `sdl-source`, `sdl-sra`, `geo` |
| note | flags, for example `md5_unavailable`, `kept_original_names:<reason>`, `no_md5_published` |

## unresolved.tsv

`accession`, `dest`, `reason` (`empty_fastq_ftp ...`, `not_in_ena`, `lookup_failed: ...`). The file is a valid `--manifest` for the next lookup rung.

## manifest.tsv (input to lookup/jobs)

Header required. Column `run` (aliases `srr`, `accession`); optional `dest` (relative sub-directory, no `..`); `jobs` also reads an optional `spots` column for the spot-count check. `resolve` writes this format.

## verify_report.tsv statuses

`ok`, `missing`, `size_mismatch`, `md5_mismatch`, `incomplete` (`.aria2` sidecar present), `no_md5_size_ok`, `no_md5_no_size` (nothing to check against; not an error, but not a verification either).

## Exit codes

0 ok, 1 error (download failed, unexpected exception), 2 usage error (bad accession, unsafe pueue argument, missing aria2c), 3 some accessions unresolved, 4 verification failures.

## Other notes

- md5 of the whole file is computed in 4 MiB chunks, in parallel threads (`verify --jobs`). `--no-md5` checks sizes only and will not detect same-size corruption.
- GEO supplementary directories do not publish md5. `verify --write-sha256` writes `SHA256SUMS` beside the files so later checks can detect changes.
- Accessions are validated (letters followed by digits) before they are placed in URLs.
