# Review package input snapshot

After Download ZIP is extracted, run `python3 restore_inputs.py` from its root.
The binary parts in `data-parts/` restore all 47 row-oriented SCP inputs used in the BIP86
conversion checks. Their bytes are unchanged. Verify the input hashes using
BIP86/source_files.sha256 from inside BIP86/.

These third-party matrices retain attribution to Shunji Umetani and OR-Library /
J. E. Beasley, with RAIL data attributed to contributor Paolo Nobili. Original
paper and source links are retained in the README. No new data license is claimed.

Of these exact inputs, 43 yield feasible STP graphs, corresponding to 86 U/P
outputs. rail516, rail2586, rail4284 and rail4872 have respectively 14, 8, 5 and
8 components containing terminals. Their inputs are retained, but their 8 STP
outputs are quarantined by default and excluded from solver comparisons.

The RAIL inputs are the local row-format copies used in the experiment. This
package makes no independent equivalence claim against original column-format
RAIL downloads. See the README for the supported SCP format.

This package omits Git metadata, commit history, compiled Python caches and
links to the experiment authors' GitHub account. Generator source, configuration
parameters, seeds and all 47 numerical inputs are preserved.
