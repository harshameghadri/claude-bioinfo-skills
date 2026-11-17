# Queueing, load and portability notes

## pueue

- pueue re-tokenises commands. `pueue add -- bash -c "long string with quotes"` breaks. Either pass each argument as its own token (what `fetch --runner pueue` does) or write a job script and queue `bash /absolute/path/job.sh` (what `jobs --runner pueue` does).
- Set parallelism outside the generating tool: `pueue parallel N -g <group>`. Re-queue failures: `pueue restart --failed-in-group <group>`.
- `--gate` queues the first job alone and makes every other job depend on it (`pueue add --after <id>`), so a mistake in paths, credentials or free space fails once, not hundreds of times.

## Load on the source

- ENA: 3 parallel downloads x 16 connections each was stable; 6 parallel downloads gave "Connection refused". The source project's NCBI `.sra` downloads used 8 connections per file with 2 jobs in parallel.
- Lookups to NCBI: keep about one query per second (`resolve --sleep`); the tool retries transient errors with increasing delays (set `SRA_DL_RETRY_SLEEP=0` in tests).

## Disk

`fasterq-dump` needs scratch space several times the `.sra` size. Put `--temp` on fast local storage with enough free space and check free space before queueing (the source project refused to start a job below 300 GB free on its scratch disk).

## Portability

- The tool uses Python's hashlib and `Path.stat`, so it does not depend on GNU `md5sum` or `stat -c`, which differ on macOS.
- Generated job scripts use only bash, coreutils and the SRA Toolkit; they pick `sha256sum` or `shasum -a 256` when the script is generated.
- If you extend the bash around this tool: a bare `(( n++ ))` returns status 1 when `n` is 0 and kills a `set -e` script; use `n=$((n + 1))`.
