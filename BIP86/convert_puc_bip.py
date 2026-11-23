#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Faithful, streaming PUC-BIP conversion of SCP incidence matrices to STP.

PUC Rosseti et al. 2001, Section 2.3:
  one terminal per SCP row; one nonterminal per SCP column;
  edge (row i, column j) iff A[i,j] = 1;
  u: unit edge weight; p: independent PRNG draws from discrete uniform [100,110].
  Original SCP column costs are intentionally ignored.

One u/p pair per original SCP file. No re-sampling of incidence matrices, no
synthetic bridges, no component filtering. Disconnected instances with terminals
in different components are converted but quarantined as INFEASIBLE_FOR_STP.

Python 3.9+, Linux/Mac/Windows. No third-party packages.
"""
from __future__ import annotations
import argparse
from array import array
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
import zipfile
import zlib

class DirectoryMember:
    """Directory source compatible with the few ZipInfo fields used below.

    The canonical member name deliberately starts with scp/ so that direct
    directory input produces the exact same STP bytes as an archive containing
    the same relative filenames.
    """
    def __init__(self, path: Path, root: Path):
        self.path = path
        self.filename = 'scp/' + path.relative_to(root).as_posix()
        self.file_size = path.stat().st_size
        self._crc = None

    @property
    def CRC(self):
        # Compute CRC32 lazily, streaming: detects changed input on resume
        # without requiring the original matrices to be re-archived.
        if self._crc is None:
            checksum = 0
            with self.path.open('rb', buffering=1024 * 1024) as src:
                while True:
                    block = src.read(4 * 1024 * 1024)
                    if not block:
                        break
                    checksum = zlib.crc32(block, checksum)
            self._crc = checksum & 0xFFFFFFFF
        return self._crc

    def is_dir(self):
        return False


class DirectoryArchive:
    """Read SCP matrices directly from a folder, without creating a ZIP."""
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir():
            raise NotADirectoryError(str(root))
        self._items = [DirectoryMember(p, self.root)
                       for p in self.root.rglob('*')
                       if p.is_file() and not p.is_symlink()
                       and p.suffix.lower() in ('.txt', '.dat', '.scp')]
        self._by_name = {item.filename: item for item in self._items}
        if len(self._by_name) != len(self._items):
            raise ValueError('Duplicate SCP relative paths')

    def infolist(self):
        return self._items

    def open(self, member, mode='r'):
        if mode != 'r':
            raise ValueError('Only reading SCP input is supported')
        if isinstance(member, DirectoryMember):
            member = member.filename
        return self._by_name[member].path.open('rb', buffering=1024 * 1024)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


DEFAULT_ZIP = 'scp.zip'
DEFAULT_OUTPUT = 'stp/BIP86'
DEFAULT_META = 'instance/BIP86'
SCHEMA = 'puc_bip_from_scp_v1'
RANDOM_MASTER_SEED = 20261023
PLACEHOLDER_WIDTH = 14


def source_name(path: str) -> str:
    stem = Path(path).stem.lower()
    return stem[3:] if stem.startswith('scp') else stem


def seed_for_source(key: str, master_seed: int) -> int:
    # Fixed and portable: no salted Python hash(). No seed repetitions.
    digest = hashlib.sha256((str(master_seed) + ':' + key).encode('ascii')).digest()
    return int.from_bytes(digest[:8], 'big')


def read_numbers(src):
    # PUC candidate archive stores header / column costs / per-row cardinality
    # and row incidence IDs as whitespace-delimited integers. Works across lines.
    for line in src:
        for piece in line.split():
            try:
                yield int(piece)
            except ValueError as exc:
                raise ValueError(f'Non-integer SCP token {piece[:80]!r}') from exc


def get_int(it, what):
    try:
        return next(it)
    except StopIteration as exc:
        raise ValueError(f'Truncated SCP source while reading {what}') from exc


class DisjointSet:
    def __init__(self, n):
        self.parent = array('I', range(n))
        self.size = array('I', [1]) * n

    def root(self, x):
        parent = self.parent
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(self, x, y):
        a, b = self.root(x), self.root(y)
        if a == b:
            return
        if self.size[a] < self.size[b]:
            a, b = b, a
        self.parent[b] = a
        self.size[a] += self.size[b]


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb', buffering=1024 * 1024) as f:
        while True:
            chunk = f.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def make_header(out, label, source, variant, m, n):
    # Edge count is unknown until all SCP incidence rows are scanned. Reserve a
    # fixed-width ASCII field, then patch it in place without a second SCP pass.
    out.write(b'33D32945 STP File, STP Format Version 1.0\n')
    out.write(b'SECTION Comment\n')
    out.write(('Name "' + label + '"\n').encode('ascii'))
    out.write(b'Creator "PUC BIP SCP incidence converter"\n')
    out.write(('Remark "PUC BIP construction; source=' + source + '; variant=' + variant + '"\n').encode('ascii'))
    out.write(b'END\n\nSECTION Graph\n')
    out.write(('Nodes %d\n' % (m + n)).encode('ascii'))
    out.write(b'Edges ')
    offset = out.tell()
    out.write((b'0' * PLACEHOLDER_WIDTH) + b'\n')
    return offset


def write_footer(out, m):
    out.write(b'END\n\nSECTION Terminals\n')
    out.write(('Terminals %d\n' % m).encode('ascii'))
    for i in range(1, m + 1):
        out.write(('T %d\n' % i).encode('ascii'))
    out.write(b'END\nEOF\n')


def patch_count(out, offset, cnt):
    value = str(cnt)
    if len(value) > PLACEHOLDER_WIDTH:
        raise ValueError('Edge count exceeds reserved header width')
    out.seek(offset)
    out.write(value.zfill(PLACEHOLDER_WIDTH).encode('ascii'))
    out.flush()


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.partial')
    try:
        with open(tmp, 'w', encoding='utf-8') as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write('\n')
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def load_row_generator(zf, member):
    # Parse via archive stream, not by extracting gigabyte source files to disk.
    # These 47 files have dimension header, n column costs, m incidence rows.
    with zf.open(member, 'r') as src:
        it = read_numbers(src)
        m = get_int(it, 'm rows')
        n = get_int(it, 'n columns')
        if not (m > 0 and n > 0 and m + n < (1 << 32)):
            raise ValueError(f'Invalid dimensions m={m}, n={n}')
        for _ in range(n):
            _ = get_int(it, 'SCP column cost')
        yield ('header', m, n)
        for r in range(m):
            count = get_int(it, f'row {r + 1} cardinality')
            if count <= 0 or count > n:
                raise ValueError(f'row {r+1}: invalid degree {count}')
            # Bounded to the largest row, never to whole SCP matrix.
            vals = [get_int(it, f'row {r + 1} element') for _ in range(count)]
            if any(j < 1 or j > n for j in vals):
                raise ValueError(f'row {r+1}: out-of-range column ID')
            if len(set(vals)) != count:
                raise ValueError(f'row {r+1}: repeated column ID; input not binary matrix')
            yield ('row', r + 1, vals)
        try:
            unexpected = next(it)
        except StopIteration:
            unexpected = None
        if unexpected is not None:
            raise ValueError(f'Unexpected extra numeric content after {m} rows: {unexpected}')


def convert_one(zf, member, output_dir, metadata_dir, master_seed, invalid_policy, overwrite=False):
    name = source_name(member.filename)
    if not name or not all(ch.isalnum() or ch in '-_' for ch in name):
        raise ValueError('Unsafe SCP base name: ' + name)
    label = 'bip' + name
    seed = seed_for_source(name, master_seed)
    # Stable metadata plus file hashes enable resume verification.
    expected_json = [metadata_dir / (label + v + '.json') for v in ('u', 'p')]
    done = True
    cached = []
    for v, jp in zip(('u', 'p'), expected_json):
        if not jp.exists():
            done = False
            break
        data = json.loads(jp.read_text(encoding='utf-8'))
        fp = Path(data.get('stp_path', ''))
        if not (data.get('schema') == SCHEMA and
                data.get('source_zip_crc32') == member.CRC and
                data.get('master_seed') == master_seed and
                data.get('weight_type') == v and
                fp.exists() and fp.stat().st_size == data.get('file_bytes') and
                hash_file(fp) == data.get('sha256')):
            done = False
            break
        cached.append(data)
    if done and not overwrite:
        return dict(source=member.filename, status='SKIPPED_VERIFIED',
                    nodes=cached[0]['nodes'], edges=cached[0]['edges'],
                    terminal_components=cached[0]['terminal_components'],
                    stp_status=cached[0]['stp_status'])

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    names = {v: output_dir / (label + v + '.stp') for v in ('u','p')}
    temps = {v: names[v].with_name(names[v].name + '.partial') for v in ('u','p')}
    for v in ('u','p'):
        if not overwrite and names[v].exists():
            raise FileExistsError(f'Existing output {names[v]} is not a complete verified pair; use --overwrite')
        if not overwrite and (output_dir / 'infeasible' / names[v].name).exists():
            raise FileExistsError(f'Existing quarantined output for {names[v].name}; use --overwrite')
    started = time.monotonic()
    edges = 0
    m = n = None
    rng = random.Random(seed)
    dsu = None
    out_u = out_p = None
    try:
        stream = load_row_generator(zf, member.filename)
        tag, m, n = next(stream)
        if tag != 'header':
            raise AssertionError('Expected SCP header')
        dsu = DisjointSet(m + n)
        out_u = open(temps['u'], 'wb', buffering=1024 * 1024)
        out_p = open(temps['p'], 'wb', buffering=1024 * 1024)
        off_u = make_header(out_u, label+'u', member.filename, 'u', m, n)
        off_p = make_header(out_p, label+'p', member.filename, 'p', m, n)
        column_ever_used = bytearray(n)
        rows_read = 0
        for tag, row, col_ids in stream:
            assert tag == 'row'
            rows_read += 1
            row0 = row - 1
            for c in col_ids:
                col0 = c - 1
                col_stp = m + c
                column_ever_used[col0] = 1
                dsu.union(row0, m + col0)
                out_u.write(f'E {row} {col_stp} 1\n'.encode('ascii'))
                w = rng.randint(100, 110)
                out_p.write(f'E {row} {col_stp} {w}\n'.encode('ascii'))
                edges += 1
        if rows_read != m:
            raise ValueError(f'Incomplete SCP: read {rows_read}/{m} rows')
        if edges < m:
            raise ValueError('Too few SCP incidences')
        for out, offset in ((out_u, off_u), (out_p, off_p)):
            write_footer(out, m)
            patch_count(out, offset, edges)
            out.close()
        out_u = out_p = None

        terminal_roots = set(dsu.root(i) for i in range(m))
        all_roots = set(dsu.root(i) for i in range(m+n))
        term_comps = len(terminal_roots)
        all_comps = len(all_roots)
        isolated_cols = n - column_ever_used.count(1)
        # If all terminals connected but isolated columns exist, SPG is still
        # feasible; record the source as disconnected and do not modify it.
        if term_comps > 1:
            stp_status = 'INFEASIBLE_FOR_STP'
        elif all_comps > 1:
            stp_status = 'DISCONNECTED_WITH_CONNECTED_TERMINALS'
        else:
            stp_status = 'FEASIBLE_GRAPH_TOPOLOGY'
        quarantine = stp_status != 'FEASIBLE_GRAPH_TOPOLOGY' and invalid_policy == 'quarantine'
        chosen = (output_dir / 'infeasible' if quarantine else output_dir)
        chosen.mkdir(parents=True, exist_ok=True)
        placed = {}
        for v in ('u','p'):
            dst = chosen / names[v].name
            if dst.exists() and not overwrite:
                raise FileExistsError(f'{dst} exists; use --overwrite')
            os.replace(temps[v], dst)
            placed[v] = dst
        for v in ('u','p'):
            dst = placed[v]
            data = dict(schema=SCHEMA,
                        source_zip_member=member.filename, source_zip_crc32=member.CRC,
                        source_zip_uncompressed_bytes=member.file_size,
                        source_id=name, name=label+v, weight_type=v,
                        master_seed=master_seed,
                        edge_weight_seed=(seed if v == 'p' else None),
                        edge_weight_rule=('constant 1' if v == 'u'
                                          else 'one seeded integer PRNG draw uniform in [100,110] per SCP matrix 1-entry'),
                        column_costs_ignored=True, incidence_matrix_unchanged=True,
                        pucreference='Rosseti et al. New Benchmark Instances for the Steiner Problem in Graphs, Sec. 2.3',
                        rows=m, columns=n, nodes=m+n, terminals=m, edges=edges,
                        bipartition_terminal_nodes='1..m',
                        bipartition_nonterminal_nodes='m+1..m+n',
                        all_graph_components=all_comps, terminal_components=term_comps,
                        unused_columns=isolated_cols,
                        stp_status=stp_status,
                        quarantined=quarantine,
                        algorithm_peak_rss_gib=None,
                        algorithm_memory_status='NOT_MEASURED',
                        graph_storage_lower_bound_gib=round(48*edges/(1024**3), 6),
                        note=('NOT an STP-feasible benchmark; terminals in separate components'
                              if term_comps > 1 else
                              'SCP bipartite graph disconnected; original PUC assumes connected underlying graph'
                              if all_comps > 1 else
                              'Feasible connected topology only; TJ RSS <4 GiB not yet measured'),
                        stp_path=str(dst),
                        file_bytes=dst.stat().st_size,
                        sha256=hash_file(dst),
                        elapsed_seconds=round(time.monotonic()-started, 3))
            write_json_atomic(metadata_dir / (label+v+'.json'), data)
        return dict(source=member.filename, status='GENERATED',
                    nodes=m+n, edges=edges, terminal_components=term_comps,
                    stp_status=stp_status, quarantined=quarantine,
                    seconds=round(time.monotonic()-started,2))
    finally:
        if out_u and not out_u.closed: out_u.close()
        if out_p and not out_p.closed: out_p.close()
        for p in temps.values():
            try: p.unlink()
            except FileNotFoundError: pass


def inspect_one(zf, member):
    """Parse every SCP coefficient, count edges and terminal components, no STP output."""
    gen = load_row_generator(zf, member.filename)
    _, m, n = next(gen)
    dsu = DisjointSet(m+n)
    edges = 0
    used = bytearray(n)
    for tag, row, cols in gen:
        if tag != 'row': raise AssertionError('Bad row token')
        for c in cols:
            dsu.union(row-1, m+c-1)
            used[c-1] = 1
            edges += 1
    return dict(source=member.filename, id=source_name(member.filename),
                rows=m, columns=n, nodes=m+n, terminals=m, edges=edges,
                terminal_components=len({dsu.root(i) for i in range(m)}),
                all_components=len({dsu.root(i) for i in range(m+n)}),
                isolated_columns=n-used.count(1))


def verify_file(path):
    """Independent streaming validation of produced STP; no original SCP needed."""
    import re
    fp = Path(path)
    section = ''
    n = m = k = None
    read_edges = 0
    terminals = 0
    types = set()
    dsu = None
    previous_row = 0
    used_in_row = set()
    seen_nonterm = None
    degree_row = 0
    with open(fp, 'rt', encoding='ascii') as f:
        for linenum, line in enumerate(f, 1):
            a = line.strip().split()
            if not a: continue
            cmd = a[0].lower()
            if cmd == 'section':
                section = a[1].lower()
                continue
            if cmd == 'end':
                section = ''
                continue
            if section == 'graph':
                if cmd == 'nodes':
                    n = int(a[1]); dsu = DisjointSet(n)
                elif cmd == 'edges':
                    m = int(a[1])
                elif cmd == 'e':
                    u,v,w = int(a[1]), int(a[2]), int(a[3])
                    if n is None or m is None: raise ValueError('Missing Nodes / Edges before E')
                    if not (1 <= u < v <= n): raise ValueError(f'Invalid edge on {linenum}')
                    if k is not None: raise ValueError('Unexpected graph order')
                    # A terminal/non-terminal partition is identified by the
                    # subsequent Terminals field, so just validate ordering now.
                    if u < previous_row: raise ValueError(f'Not grouped by SCP row: line {linenum}')
                    if u != previous_row: used_in_row.clear(); previous_row = u
                    if v in used_in_row: raise ValueError(f'Duplicate incidence: line {linenum}')
                    used_in_row.add(v)
                    if w == 1: types.add('u')
                    elif 100 <= w <= 110: types.add('p')
                    else: raise ValueError(f'Unexpected BIP edge weight {w}: {linenum}')
                    dsu.union(u-1,v-1)
                    read_edges += 1
            elif section == 'terminals':
                if cmd == 'terminals': k = int(a[1])
                elif cmd == 't':
                    terminals += 1
                    if int(a[1]) != terminals: raise ValueError('Terminal list not 1..m')
    if n is None or m is None or k is None or terminals != k or read_edges != m:
        raise ValueError('STP header, edge or terminal counts mismatch')
    if len(types) != 1: raise ValueError('Mixed u/p variants')
    # Rescan to enforce strict bipartite edge endpoints (T rows, non-T cols).
    with open(fp, 'rt', encoding='ascii') as f:
        section = ''
        for line in f:
            a = line.split()
            if not a: continue
            cmd = a[0].lower()
            if cmd == 'section': section = a[1].lower(); continue
            if cmd == 'end': section = ''; continue
            if section == 'graph' and cmd == 'e':
                if not (1 <= int(a[1]) <= k < int(a[2]) <= n):
                    raise ValueError('Not an SCP-incidence bipartite graph')
    comps = len(set(dsu.root(t) for t in range(k)))
    all_comps = len(set(dsu.root(t) for t in range(n)))
    return dict(verified=True, file=str(path), nodes=n, edges=m,
                terminals=k, weight_variant=next(iter(types)),
                terminal_components=comps, all_graph_components=all_comps,
                feasible_for_stp=(comps == 1),
                meets_puc_connected_graph_requirement=(all_comps == 1),
                sha256=hash_file(fp))


def cli():
    p = argparse.ArgumentParser(description='Convert 47 user-supplied OR-Library SCP matrices into faithful PUC-style BIP u/p STP pairs')
    p.add_argument('--zip', default=DEFAULT_ZIP, help='Path to SCP ZIP archive, or directly to SCP folder')
    p.add_argument('--scp-dir', default=None, help='Read SCP .txt/.dat/.scp files directly from this folder (no ZIP needed)')
    p.add_argument('--outdir', default=DEFAULT_OUTPUT)
    p.add_argument('--meta-dir', default=DEFAULT_META)
    p.add_argument('--seed', type=int, default=RANDOM_MASTER_SEED)
    p.add_argument('--only', nargs='*', default=None, help='Subset source IDs e.g. i1 rail507')
    p.add_argument('--list', action='store_true', help='List matching files; do not generate')
    p.add_argument('--scan-only', action='store_true', help='Read all matrix entries and check terminal connectivity; generate nothing')
    p.add_argument('--overwrite', action='store_true', help='Replace existing outputs and metadata')
    p.add_argument('--invalid-policy', choices=['quarantine','keep'], default='quarantine',
                   help='Disconnected (terminals in multiple components): store in infeasible/ by default')
    p.add_argument('--verify-after-write', action='store_true', help='Independently rescan every STP and verify graph/weights/counts')
    p.add_argument('--verify', nargs='*', help='Only verify existing STP files')
    args = p.parse_args()
    if args.verify is not None:
        for filename in args.verify:
            print(json.dumps(verify_file(filename), ensure_ascii=False, indent=2),flush=True)
        return
    source = Path(args.scp_dir) if args.scp_dir else Path(args.zip)
    if not source.exists(): raise FileNotFoundError(source)
    reader = DirectoryArchive(source) if source.is_dir() else zipfile.ZipFile(source)
    with reader as zf:
        members = sorted([x for x in zf.infolist() if (not x.is_dir() and
                Path(x.filename).suffix.lower() in ('.txt','.dat','.scp'))], key=lambda x: x.filename)
        if args.only:
            selected = set(map(str.lower, args.only))
            members = [m for m in members if source_name(m.filename) in selected or Path(m.filename).stem.lower() in selected]
            unmatched = selected - set(source_name(x.filename) for x in members) - set(Path(x.filename).stem.lower() for x in members)
            if unmatched: raise ValueError('No matching SCP sources: '+','.join(sorted(unmatched)))
        if not members: raise ValueError('No SCP files found')
        if args.scan_only:
            rows=[]
            for i,member in enumerate(members,1):
                print(f'[{i}/{len(members)}] inspecting {member.filename} ...',flush=True)
                rec=inspect_one(zf,member)
                rows.append(rec)
                print('  ',rec,flush=True)
            dest=Path(args.meta_dir)
            dest.mkdir(parents=True,exist_ok=True)
            write_json_atomic(dest/'source_scan.json',rows)
            with open(dest/'source_scan.csv','w',encoding='utf-8',newline='') as f:
                fields=['source','id','rows','columns','nodes','terminals','edges','terminal_components','all_components','isolated_columns']
                w=csv.DictWriter(f,fieldnames=fields)
                w.writeheader();w.writerows(rows)
            print('Scan complete: ',dest/'source_scan.csv',flush=True)
            return
        if args.list:
            for x in members:print(f'{source_name(x.filename):12} {x.filename:27} {x.file_size:>12,} bytes')
            print(f'{len(members)} source matrices -> {2*len(members)} STP files')
            return
        report=[]
        for i, member in enumerate(members, 1):
            print(f'[{i}/{len(members)}] {member.filename} ...', flush=True)
            try:
                summary=convert_one(zf,member,Path(args.outdir),Path(args.meta_dir),
                                    args.seed,args.invalid_policy,overwrite=args.overwrite)
                if args.verify_after_write and summary['status'] == 'GENERATED':
                    base = 'bip' + source_name(member.filename)
                    for v in ('u','p'):
                        meta=json.loads((Path(args.meta_dir)/(base+v+'.json')).read_text(encoding='utf-8'))
                        res=verify_file(meta['stp_path'])
                        if (res['terminals'] != meta['terminals'] or res['edges'] != meta['edges'] or
                            res['terminal_components'] != meta['terminal_components'] or
                            res['all_graph_components'] != meta['all_graph_components']):
                            raise AssertionError('Independent STP verification mismatch')
                report.append(summary)
                print('  ',summary,flush=True)
            except Exception as exc:
                report.append(dict(source=member.filename,status='FAILED',error=str(exc)))
                print('  ERROR:',exc,file=sys.stderr,flush=True)
        Path(args.meta_dir).mkdir(parents=True,exist_ok=True)
        summary_file=Path(args.meta_dir)/'conversion_summary.json'
        write_json_atomic(summary_file,dict(schema=SCHEMA,source_archive=str(source),
                 source_type=('directory' if source.is_dir() else 'zip'),
                 source_count=len(members),expected_pairs=2*len(members),
                 output_dir=args.outdir, metadata_dir=args.meta_dir,
                 records=report))
        fields=['source','status','nodes','edges','terminal_components','stp_status','quarantined','seconds','error']
        with open(Path(args.meta_dir)/'conversion_summary.csv','w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
            writer.writeheader();writer.writerows(report)
        failed=[r for r in report if r['status']=='FAILED']
        print(f'FINISHED: processed {len(report)}, failures {len(failed)}; summary {summary_file}',flush=True)
        if failed:sys.exit(1)


if __name__=='__main__':
    try:cli()
    except (OSError,ValueError,zipfile.BadZipFile) as e:
        print('ERROR:',e,file=sys.stderr)
        sys.exit(2)
