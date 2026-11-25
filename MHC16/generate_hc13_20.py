#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate 16 standard PUC-style HC STP instances: hc13u/p ... hc20u/p.

Standard hypercube topology only; no rewiring. Memory usage O(1) in graph size.
Every even-parity vertex is a terminal. u: edge weights 1; p: uniformly
sampled integer weights 100..110, with a recorded deterministic seed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import os
import time
from pathlib import Path

MIN_DIM, MAX_DIM = 13, 20
BASE_SEED = 20261010


def bound(d: int, variant: str) -> int:
    t = 1 << (d - 1)
    # Any tree containing all t terminals requires at least
    # s=ceil((t-1)/(d-1)) nonterminals, hence t+s-1 edges.
    s = (t - 1 + d - 2) // (d - 1)
    return (t + s - 1) * (100 if variant == 'p' else 1)


def sizes(d):
    return (1 << d, d * (1 << (d - 1)), 1 << (d - 1))


def seed_for(d, variant):
    return BASE_SEED + 1000 * d if variant == 'p' else None


def generate_one(d: int, variant: str, outdir: Path, meta_dir: Path,
                 overwrite: bool = False, skip_existing: bool = False):
    if not MIN_DIM <= d <= MAX_DIM:
        raise ValueError(f'd must be within {MIN_DIM}..{MAX_DIM}')
    n, m, t = sizes(d)
    name = f'hc{d}{variant}'
    outdir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    target = outdir / f'{name}.stp'
    meta = meta_dir / f'{name}.json'
    if not overwrite and (target.exists() or meta.exists()):
        if skip_existing and target.exists() and meta.exists():
            print(f'SKIP: {name} (both STP and JSON already exist)', flush=True)
            return
        raise FileExistsError(f'{name}: output exists/partial; verify it or use --overwrite')
    # Write to *.part first to avoid treating interrupted jobs as complete.
    tmp = outdir / f'{name}.stp.part'
    tm = time.monotonic()
    rng = random.Random(seed_for(d, variant)) if variant == 'p' else None
    fixed_tree_ub = 0
    fixed_tree_edges = 0
    digest = hashlib.sha256()
    try:
        with tmp.open('w', encoding='ascii', buffering=1024 * 1024, newline='\n') as f:
            f.write('33D32945 STP File, STP Format Version 1.0\n')
            f.write('SECTION Comment\n')
            f.write(f'Name "{name}"\n')
            f.write('Creator "Independent HC13-HC20 PUC-style generator"\n')
            f.write('Remark "Standard binary hypercube; even Hamming parity terminals"\n')
            f.write(f'Remark "Proven analytical LB: {bound(d, variant)} (not OPT)"\n')
            f.write('END\nSECTION Graph\n')
            f.write(f'Nodes {n}\nEdges {m}\n')
            written = 0
            # Enumerate precisely one endpoint of each hypercube edge.
            for v in range(n):
                if v.bit_count() & 1:
                    continue
                for b in range(d):
                    u = v ^ (1 << b)
                    w = 1 if rng is None else rng.randint(100, 110)
                    f.write(f'E {v + 1} {u + 1} {w}\n')
                    written += 1
                    # Parent(v) = v with its lowest set bit cleared.
                    # All N-1 parent edges form a fixed spanning tree.
                    if (u & (u - 1)) == v or (v != 0 and (v & (v - 1)) == u):
                        fixed_tree_ub += w
                        fixed_tree_edges += 1
            f.write('END\nSECTION Terminals\n')
            f.write(f'Terminals {t}\n')
            for v in range(n):
                if (v.bit_count() & 1) == 0:
                    f.write(f'T {v + 1}\n')
            f.write('END\nEOF\n')
        if written != m or fixed_tree_edges != n - 1:
            raise AssertionError(f'Internal error: edges {written}/{m}, tree {fixed_tree_edges}/{n-1}')
        with tmp.open('rb') as fp:
            while block := fp.read(4 * 1024 * 1024):
                digest.update(block)
        if overwrite:
            os.replace(tmp, target)
        else:
            tmp.rename(target)
        result = {
            'source': 'Independent PUC-HC-style extension, not official PUC generator',
            'topology': 'standard_binary_hypercube',
            'dimension': d,
            'N': n,
            'M': m,
            'terminals': t,
            'average_degree': d,
            'variant': variant,
            'terminal_rule': 'even_binary_Hamming_weight',
            'weight_rule': 'u: all 1; p: uniformly sampled integers 100..110',
            'seed': seed_for(d, variant),
            'analytical_lower_bound': bound(d, variant),
            'lower_bound_status': 'proven_valid_not_necessarily_optimal',
            'fixed_spanning_tree_upper_bound': fixed_tree_ub,
            'upper_bound_status': 'valid_feasible_tree_not_best_known',
            'spanning_tree_edge_count': fixed_tree_edges,
            'generation_seconds': round(time.monotonic() - tm, 3),
            'file': str(target),
            'bytes': target.stat().st_size,
            'sha256': digest.hexdigest()
        }
        temp_meta = meta.with_suffix('.json.part')
        temp_meta.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp_meta, meta)
        print(f'OK {name}: V={n:,}, E={m:,}, T={t:,}, LB={bound(d, variant):,}, '
              f'UB={fixed_tree_ub:,}, size={target.stat().st_size:,} bytes, '
              f'time={result["generation_seconds"]}s', flush=True)
        return result
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def verify_one(path: Path, dimension: int | None):
    # Standalone verification, reading edges sequentially with O(V) bits.
    n = m = k = None
    sec = None
    written = 0
    terminals = 0
    last_v = -1
    last_seen_mask = 0
    parent_edges = 0
    seen_terminals = None
    expected_variant = path.stem[-1] if path.stem[-1] in ('u', 'p') else None
    for line in path.open('r', encoding='ascii'):
        text = line.strip()
        if text.startswith('SECTION '):
            sec = text.split(' ', 1)[1]
            continue
        if text == 'END':
            sec = None
            continue
        v = text.split()
        if not v:
            continue
        if sec == 'Graph':
            if v[0] == 'Nodes': n = int(v[1]); seen_terminals = bytearray(n); continue
            if v[0] == 'Edges': m = int(v[1]); continue
            if v[0] != 'E': continue
            a, b, w = map(int, v[1:]); a -= 1; b -= 1
            if not (0 <= a < n and 0 <= b < n):
                raise ValueError('Invalid vertex in edge')
            if (a.bit_count() & 1) or ((b.bit_count() & 1) != 1):
                raise ValueError('Invalid HC bipartition')
            bit = a ^ b
            if bit == 0 or bit & (bit - 1):
                raise ValueError('Not a hypercube edge')
            if a != last_v:
                if last_v >= 0 and last_seen_mask != (1 << (n.bit_length() - 1)) - 1:
                    raise ValueError('Previous terminal missing neighbor')
                if last_v >= 0 and a <= last_v:
                    raise ValueError('Edge ordering error')
                last_v = a
                last_seen_mask = 0
            pos = bit.bit_length() - 1
            if last_seen_mask & (1 << pos):
                raise ValueError('Duplicate edge')
            last_seen_mask |= 1 << pos
            if (expected_variant == 'u' and w != 1) or (expected_variant == 'p' and not 100 <= w <= 110) or (w != 1 and not 100 <= w <= 110):
                raise ValueError('Incorrect weight')
            if (b & (b - 1)) == a or (a != 0 and (a & (a - 1)) == b):
                parent_edges += 1
            written += 1
        elif sec == 'Terminals':
            if v[0] == 'Terminals': k = int(v[1]); continue
            if v[0] == 'T':
                vertex = int(v[1]) - 1
                if vertex < 0 or vertex >= n or (vertex.bit_count() & 1):
                    raise ValueError('Invalid terminal')
                if seen_terminals[vertex]:
                    raise ValueError('Duplicate terminal')
                seen_terminals[vertex] = 1
                terminals += 1
    if n is None or m is None or k is None:
        raise ValueError('Missing STP sections')
    d = n.bit_length() - 1
    if dimension is not None and d != dimension:
        raise ValueError('Unexpected dimension')
    if n != 1 << d or m != d * (n // 2) or written != m or k != n // 2 or terminals != k:
        raise ValueError('Wrong counts')
    if parent_edges != n - 1:
        raise ValueError('No fixed spanning tree')
    if last_seen_mask != (1 << d) - 1:
        raise ValueError('Last vertex missing neighbor')
    print(json.dumps({'valid': True, 'dimension': d, 'N': n, 'M': m, 'terminals': k,
                      'parent_tree_edges': parent_edges}, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Generate 16 standard HC instances, HC13..HC20 u/p')
    sub = parser.add_subparsers(dest='command', required=True)
    pp = sub.add_parser('plan')
    g = sub.add_parser('generate')
    group = g.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true')
    group.add_argument('--dimension', type=int)
    g.add_argument('--variant', choices=['u', 'p', 'both'], default='both')
    g.add_argument('--outdir', type=Path, default=Path('instances'))
    g.add_argument('--meta-dir', type=Path, default=Path('instance'))
    g.add_argument('--overwrite', action='store_true')
    g.add_argument('--skip-existing', action='store_true')
    v = sub.add_parser('verify')
    v.add_argument('file', type=Path)
    v.add_argument('--dimension', type=int, default=None)
    args = parser.parse_args()
    if args.command == 'plan':
        for d in range(MIN_DIM, MAX_DIM+1):
            n,m,t = sizes(d)
            print(f'HC{d}: V={n:,}, E={m:,}, T={t:,}, '
                  f'uLB={bound(d,"u"):,}, pLB={bound(d,"p"):,}')
    elif args.command == 'generate':
        dims = range(MIN_DIM, MAX_DIM+1) if args.all else [args.dimension]
        modes = ('u', 'p') if args.variant == 'both' else (args.variant,)
        for d in dims:
            for mode in modes:
                generate_one(d, mode, args.outdir, args.meta_dir, args.overwrite, args.skip_existing)
    elif args.command == 'verify':
        verify_one(args.file, args.dimension)


if __name__ == '__main__':
    main()
