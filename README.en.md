# PUC-style STP extension generators

[中文说明](README.md)

This repository contains independent generators for three extended Steiner Tree
Problem in Graphs (STP) benchmark families. They follow the HC, CC and BIP
construction rules described by Rosseti et al.; they are not the official PUC
generators or copies of the original SteinLib instances.

| Family | Configurations / inputs | Feasible U/P instances |
| --- | --- | ---: |
| MHC16 | Binary hypercubes of dimension 13–20 | 16 |
| MCC50 | 25 distinct Hamming-graph configurations | 50 |
| BIP86 | 43 feasible conversions among 47 SCP input matrices | 86 |
| Total | | 152 |

Each configuration produces one unperturbed (`u`) and one perturbed (`p`)
instance with identical topology and terminals. Output is SteinLib STP V1.0.

## Requirements and repository contents

Python 3.10 or newer is required. The three standard batch generators use only
the Python standard library. The optional `--cover-method exact` mode in
`MCC50/generate_cc.py` additionally requires NumPy/SciPy; the MCC50 batch driver
does not use this mode.

The repository contains generator source, configuration templates and source
verification records. Large generated STP files and third-party SCP matrices
are not included. Run the following commands from the repository root. On
Windows, replace `python3` with your Python interpreter as needed.

## MHC16: binary hypercubes

The graph has `2^d` vertices and `d * 2^(d-1)` edges. Vertices of even binary
Hamming weight are terminals. Unperturbed edge costs are 1; perturbed costs are
integers in `[100,110]`. Dimensions 13–20 give eight U/P pairs.

```bash
python3 MHC16/generate_hc13_20.py plan
python3 MHC16/generate_hc13_20.py generate --all \
  --outdir ./stp/MHC16 --meta-dir ./instance/MHC16
```

To generate only one pair, replace `--all` with `--dimension 13`.

## MCC50: covering codes on Hamming graphs

`H(n,q)` has `q^n` vertices and `n(q-1)q^n/2` edges. A deterministic greedy-seeded
tabu search constructs a radius-one covering code as the terminal set. It
verifies coverage but does not guarantee a minimum covering code. This is an
independent implementation, not the original PUC covering-code program.

An edge incident to `t` terminals has unperturbed cost `1+t`, for `t=0,1,2`.
Its perturbed cost is `100(1+t) + xi`, with integer `xi` in `[0,10]`. The 25
profiles and deterministic seed derivation are in `generate_MCC50_PUC.py`.
Default tabu settings are 120 steps, 4 levels and 2 restarts.

```bash
# Preview only.
python3 MCC50/generate_MCC50_PUC.py

# Generate all 25 U/P pairs, with verification enabled.
python3 MCC50/generate_MCC50_PUC.py --run \
  --stp-dir ./stp/MCC50 --meta-dir ./instance/MCC50
```

Add `--only cc13-2` for a smaller test. Keep `generate_cc.py` next to the batch
driver. Use a new output directory or `--overwrite` after changing tabu settings;
the resume check does not compare those settings. `MCC50_manifest.csv` is a
planning/RSS template for all 25 profiles, even with `--only`, not a list of
completed outputs. Per-instance JSON files contain output hashes.

## BIP86: bipartite graphs converted from SCP

**BIP86 is derived from existing set-covering problem (SCP) matrices.**
Each row becomes a terminal, each column becomes a nonterminal, and each matrix
nonzero becomes an undirected edge. Original SCP column costs are ignored.
No edges are added to force connectivity. Unperturbed edge costs are 1;
perturbed costs are integers in `[100,110]`.

Obtain the following source files from their original providers and put them
under `BIP86/scp/`:

- Umetani classes I–N: `scpi1.txt`–`scpn5.txt`, five per class (30 files).
- OR-Library NRG and NRH: five per class (10 files).
- OR-Library RAIL: `rail507`, `rail516`, `rail582`, `rail2536`, `rail2586`,
  `rail4284`, `rail4872` (7 files, with `.txt` extensions).

The converter requires **row-oriented sparse SCP text**: `m n`, then `n`
column costs, followed by each row's cardinality and 1-based column indices.
All 47 checked local inputs use this format. The original RAIL downloads from
OR-Library are **column-oriented** and cannot be passed to this parser directly;
they must first be reformatted without changing the incidence matrix. Umetani's
data page links to an [SCP archive](https://drive.google.com/file/d/17im3dxfYdiGO2bUtJxX08kuyimIdsJ7d/view).
Use the source hashes to check that your files match the inputs verified here.
The connectivity counts below refer to those exact local row-format inputs.
This repository does not include the RAIL preprocessing step or an independent
matrix-equivalence check against the original column-format downloads.

The 47 source matrices have all been parsed and checked. Four RAIL matrices
convert to graphs whose terminals lie in multiple connected components:

| Source | Connected components containing terminals | Status |
| --- | ---: | --- |
| `rail516` | 14 | Infeasible STP |
| `rail2586` | 8 | Infeasible STP |
| `rail4284` | 5 | Infeasible STP |
| `rail4872` | 8 | Infeasible STP |

These files **can be parsed and converted**; they cannot yield feasible STP
instances under the unchanged incidence-graph construction. The default
`--invalid-policy quarantine` puts their eight U/P outputs in `infeasible/`.
Exclude them from solver comparisons. Thus 47 sources produce 94 files, of
which **86 are feasible**. This is a topology issue, not a converter format error
or a solver failure.

For additional inputs, the default quarantine policy also excludes graphs with
isolated nonterminals even if all terminals are connected. None of the 47
checked inputs has this additional case.

```bash
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp --list

# Check every input without producing STP files.
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp \
  --meta-dir ./instance/BIP86 --scan-only

# Convert and verify. Infeasible results are quarantined by default.
python3 BIP86/convert_puc_bip.py --scp-dir ./BIP86/scp \
  --outdir ./stp/BIP86 --meta-dir ./instance/BIP86 --verify-after-write
```

Add `--only i1` for one source; `--zip ./scp.zip` may replace `--scp-dir`.
See [`source_connectivity.csv`](BIP86/source_connectivity.csv) for all 47 results
and [`source_files.sha256`](BIP86/source_files.sha256) for the exact input hashes.

## Reproducibility and verification

Default seeds, profile ordering and construction logic are preserved from the
original local generators. Publication changes make MCC/BIP output paths
relative and explicitly decode BIP JSON as UTF-8 on Windows; they do not change
graph topology, terminals or random weights.

- HC13 U/P generation and independent verification passed; hashes match the
  existing reference metadata.
- MCC `cc13-2` passed semantic verification and repeated-generation hash checks
  with default batch settings.
- All 47 SCP matrices passed parsing; connectivity results are listed above.
- BIP synthetic-matrix tests: `python3 BIP86/test_converter.py`.

These checks do not mean all 152 large outputs were regenerated for this
publication. Solver peak memory must be measured separately; graph-size limits
and successful generation are not solver-memory guarantees.

## Original construction rules and source data

1. I. Rosseti, M. Poggi de Aragão, C. C. Ribeiro, E. Uchoa, and R. F. Werneck.
   *New Benchmark Instances for the Steiner Problem in Graphs*. Research report,
   PUC-Rio, 2001. [Report](https://optimization-online.org/2001/09/374/).
2. S. Umetani. *Exploiting variable associations to configure efficient local
   search algorithms in large-scale binary integer programs*. European Journal
   of Operational Research, 263(1), 72–81, 2017.
   [Paper](https://doi.org/10.1016/j.ejor.2017.05.025).
   [SCP classes I–N](https://sites.google.com/view/umepon/benchmark).
3. J. E. Beasley. *OR-Library: Distributing test problems by electronic mail*.
   Journal of the Operational Research Society, 41(11), 1069–1072, 1990.
   [NRG/NRH and RAIL data and format descriptions](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/scpinfo.html).

The original data providers retain attribution for the source matrices. This
repository provides independent PUC-style extensions and makes no claim that
their optima or difficulty match the original PUC benchmark.
