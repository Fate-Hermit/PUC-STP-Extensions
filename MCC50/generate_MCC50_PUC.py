#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate 25 unique PUC-CC-style configurations, one u/p pair each.

The batch driver always uses a deterministic greedy-seeded tabu covering-code
search, Hamming graph H(n,q), covering radius r=1, and the PUC incidence-cost
rules. It does not use the algebraic Hamming-code or syndrome generator.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_STP_DIR = Path('stp/MCC50')
DEFAULT_META_DIR = Path('instance/MCC50')
MAX_NODES = 262_144
MAX_EDGES = 4_100_000
VERSION = 'MCC50-PUC-CC-v2'

# 25 distinct (n,q) configurations; each produces exactly one u and one p.
# The 13 original PUC configurations are intentionally excluded, so these are
# new parameter configurations rather than replacements for official files.
PROFILES = [
    (11, 3), (9, 4), (5, 11), (5, 10), (6, 7),
    (4, 18), (4, 17), (4, 16), (4, 15), (5, 9),
    (7, 5), (10, 3), (8, 4), (6, 6), (4, 14),
    (4, 13), (4, 12), (4, 11), (5, 8), (5, 7),
    (17, 2), (16, 2), (15, 2), (14, 2), (13, 2),
]

# Previously reported TJ peak RSS for reference configurations only.
# These are reference measurements, not guarantees for the new terminal sets.
REFERENCE_RSS_GIB = {
    (11, 3): 1.04,
    (5, 11): 1.13,
    (9, 4): 2.21,
}

# Smaller reserve configurations if a target-server RSS test rejects a profile.
# They are not generated unless manually substituted for a rejected profile.
BACKUP_PROFILES = [(4, 10), (4, 9), (4, 8), (5, 6), (4, 6), (5, 5), (4, 5), (3, 12)]


def graph_size(n: int, q: int):
    N = q ** n
    degree = n * (q - 1)
    M = N * degree // 2
    return N, M, degree


def stable_seed(n: int, q: int) -> int:
    raw = f'{VERSION}|n={n}|q={q}|terminal-and-weight-seed'.encode('ascii')
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def pair_is_complete(stp_dir: Path, meta_dir: Path, n: int, q: int) -> bool:
    base = f'cc{n}-{q}'
    for v in ('u', 'p'):
        stp = stp_dir / f'{base}{v}.stp'
        meta = meta_dir / f'{base}{v}.json'
        if not stp.is_file() or not meta.is_file():
            return False
        try:
            data = json.loads(meta.read_text(encoding='utf-8'))
            if data.get('n') != n or data.get('q') != q or data.get('variant') != v:
                return False
            if data.get('sha256') != sha256_file(stp):
                return False
        except (OSError, ValueError, json.JSONDecodeError):
            return False
    return True


def nearest_existing(path: Path) -> Path:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def write_manifest(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        'instance_base', 'n', 'q', 'N', 'M', 'degree',
        'covering_cardinality_lower_bound', 'prior_reference_TJ_peak_RSS_GiB',
        'candidate_envelope', 'target_TJ_peak_RSS_GiB', 'actual_TJ_peak_RSS_GiB',
        'memory_status',
    ]
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for n, q in PROFILES:
            N, M, d = graph_size(n, q)
            w.writerow({
                'instance_base': f'cc{n}-{q}', 'n': n, 'q': q, 'N': N, 'M': M,
                'degree': d,
                'covering_cardinality_lower_bound': (N + d) // (d + 1),
                'prior_reference_TJ_peak_RSS_GiB': REFERENCE_RSS_GIB.get((n, q), ''),
                'candidate_envelope': f'N<={MAX_NODES}; M<={MAX_EDGES}',
                'target_TJ_peak_RSS_GiB': 3.2,
                'actual_TJ_peak_RSS_GiB': '',
                'memory_status': 'PENDING_TARGET_TJ_RSS_PROFILE',
            })


def main():
    ap = argparse.ArgumentParser(description='MCC50 PUC-CC strict-structure batch generator')
    ap.add_argument('--run', action='store_true', help='Actually generate files; without this flag only print the plan')
    ap.add_argument('--stp-dir', type=Path, default=DEFAULT_STP_DIR)
    ap.add_argument('--meta-dir', type=Path, default=DEFAULT_META_DIR)
    ap.add_argument('--only', action='append', default=[], help='Generate selected config(s), e.g. --only cc9-4; may repeat')
    ap.add_argument('--overwrite', action='store_true', help='Regenerate even when a valid pair already exists')
    ap.add_argument('--max-nodes', type=int, default=MAX_NODES)
    ap.add_argument('--max-edges', type=int, default=MAX_EDGES)
    ap.add_argument('--tabu-steps', type=int, default=120)
    ap.add_argument('--tabu-levels', type=int, default=4)
    ap.add_argument('--tabu-restarts', type=int, default=2)
    ap.add_argument('--no-verify', action='store_true', help='Skip full STP semantic verification (not recommended)')
    ap.add_argument('--generator', type=Path, default=Path(__file__).with_name('generate_cc.py'))
    ap.add_argument('--manifest', type=Path, default=None)
    args = ap.parse_args()

    known = {f'cc{n}-{q}': (n, q) for n, q in PROFILES}
    if args.only:
        unknown = [x for x in args.only if x not in known]
        if unknown:
            ap.error('Unknown config(s): ' + ', '.join(unknown))
        selected = [known[x] for x in args.only]
        # Preserve the canonical profile order and avoid duplicate --only arguments.
        selected_set = set(selected)
        selected = [p for p in PROFILES if p in selected_set]
    else:
        selected = list(PROFILES)

    if len(PROFILES) != 25 or len(set(PROFILES)) != 25:
        raise RuntimeError('Configuration list must contain 25 unique pairs')
    if len(PROFILES) * 2 != 50:
        raise RuntimeError('MCC50 must contain exactly 50 STP files')

    total_edges = 0
    maxN = maxM = 0
    print(f'{VERSION}: {len(selected)} configurations / {len(selected)*2} STP files')
    print('Construction: Hamming graph H(n,q), r=1 covering terminals from deterministic tabu search, PUC incidence weights.')
    print('No repeated configurations or extra random-seed replicas; each configuration yields one u/p pair.')
    print('-' * 92)
    print(f'{"config":<12} {"N":>10} {"M":>12} {"degree":>8} {"K lower bound":>15} {"prior RSS GiB":>14}')
    for n, q in selected:
        N, M, d = graph_size(n, q)
        total_edges += M
        maxN, maxM = max(maxN, N), max(maxM, M)
        ref = REFERENCE_RSS_GIB.get((n, q), None)
        print(f'cc{n}-{q:<8} {N:>10,} {M:>12,} {d:>8,} {(N+d)//(d+1):>15,} {ref if ref is not None else "—":>14}')
        if N > args.max_nodes or M > args.max_edges:
            ap.error(f'cc{n}-{q} exceeds safety envelope N<={args.max_nodes}, M<={args.max_edges}')
    estimated_pair_bytes = total_edges * 2 * 24  # conservative text-size planning estimate
    print('-' * 92)
    print(f'Profile max: N={maxN:,}; M={maxM:,}; total M across selected configs={total_edges:,}')
    print(f'Approximate u/p STP storage for selected configs: {estimated_pair_bytes / (1024**3):.2f} GiB')
    print('RSS policy: target <=3.2 GiB per TJ process; 4 GiB is the hard ceiling.')
    print('The graph-size envelope is a conservative screen, not a substitute for target-binary peak-RSS measurement.')

    manifest = args.manifest or (args.meta_dir / 'MCC50_manifest.csv')
    if not args.run:
        print('\nDry run only. Add --run to generate the files.')
        return 0

    if not args.generator.is_file():
        ap.error(f'Generator source not found: {args.generator}')
    stp_root = nearest_existing(args.stp_dir)
    free = shutil.disk_usage(stp_root).free
    required = int(estimated_pair_bytes * 1.25)
    if free < required:
        ap.error(f'Insufficient free disk space: {free/(1024**3):.2f} GiB available; '
                 f'about {required/(1024**3):.2f} GiB recommended for this selection')

    args.stp_dir.mkdir(parents=True, exist_ok=True)
    args.meta_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(manifest)

    for idx, (n, q) in enumerate(selected, 1):
        base = f'cc{n}-{q}'
        out_paths = [args.stp_dir / f'{base}{v}.stp' for v in ('u', 'p')]
        meta_paths = [args.meta_dir / f'{base}{v}.json' for v in ('u', 'p')]
        if not args.overwrite and pair_is_complete(args.stp_dir, args.meta_dir, n, q):
            print(f'[{idx}/{len(selected)}] SKIP verified pair {base}', flush=True)
            continue
        existing = [p for p in out_paths + meta_paths if p.exists()]
        if existing and not args.overwrite:
            ap.error(f'Partial/stale files exist for {base}; inspect them or rerun with --overwrite')

        seed = stable_seed(n, q)
        cmd = [
            sys.executable, str(args.generator), 'generate',
            '--n', str(n), '--q', str(q), '--seed', str(seed),
            '--variant', 'both', '--outdir', str(args.stp_dir), '--meta-dir', str(args.meta_dir),
            '--name', base, '--max-nodes', str(args.max_nodes),
            '--cover-method', 'tabu', '--tabu-steps', str(args.tabu_steps),
            '--tabu-levels', str(args.tabu_levels), '--tabu-restarts', str(args.tabu_restarts),
            '--noise-method', 'prng',
        ]
        if not args.no_verify:
            cmd.append('--verify-after-write')
        print(f'\n[{idx}/{len(selected)}] GENERATE {base}; seed={seed}', flush=True)
        print(' '.join(cmd), flush=True)
        subprocess.run(cmd, check=True)
        # Annotate metadata with the batch-level provenance and memory caveat.
        for v in ('u', 'p'):
            mp = args.meta_dir / f'{base}{v}.json'
            md = json.loads(mp.read_text(encoding='utf-8'))
            md['batch_profile_version'] = VERSION
            md['one_pair_per_configuration'] = True
            md['same_terminal_set_for_u_p'] = True
            md['tabu_steps'] = args.tabu_steps
            md['tabu_levels'] = args.tabu_levels
            md['tabu_restarts'] = args.tabu_restarts
            md['generator_source_sha256'] = sha256_file(args.generator)
            md['puc_construction_note'] = (
                'H(n,q) with Hamming-distance-one edges, radius-1 covering terminals, and PUC incidence weights. '
                'Terminal search is a deterministic independent greedy-seeded tabu implementation; it is not '
                'the original Poggi-de Aragao/de Souza 1999 source code and does not reproduce official terminal positions.'
            )
            md['tj_peak_rss_status'] = 'PENDING_PROFILE_ON_TARGET_TJ_BINARY'
            md['target_rss_gib'] = 3.2
            mp.write_text(json.dumps(md, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        if not pair_is_complete(args.stp_dir, args.meta_dir, n, q):
            raise RuntimeError(f'Post-generation SHA256/metadata check failed for {base}')
        print(f'[{idx}/{len(selected)}] PASS generated and hash-checked {base}u/{base}p', flush=True)

    print(f'\nDone. STP dir: {args.stp_dir}\nJSON/manifest dir: {args.meta_dir}\nManifest: {manifest}')
    print('Before treating all profiles as approved, measure peak RSS with the exact TJ binary on the target server.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
