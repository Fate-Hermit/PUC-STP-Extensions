#!/usr/bin/env python3
"""Independent PUC CC-style Steiner tree benchmark generator v3 (Python 3.9+).

Exact Hamming H(n,q) graph, radius-1 covering-code terminal set, and original
PUC incidence-cost classes. Tabu exchange is a new approximation, NOT the
original Poggi & Souza (1999) tabu search or the official instance generator.
"""
import argparse
from array import array
import hashlib
import heapq
import json
from pathlib import Path
import random
import re
import sys
import time

MASK = (1 << 64) - 1


def qgraph_size(n, q):
    if n < 1 or q < 2:
        raise ValueError('Need n>=1 and q>=2')
    N = q ** n
    degree = n * (q - 1)
    return N, N * degree // 2, degree


def neighbor_ids(v, n, q, strides=None):
    if strides is None:
        strides = [q**j for j in range(n)]
    for step in strides:
        old = (v // step) % q
        v0 = v - old * step
        for x in range(q):
            if x != old:
                yield v0 + x * step


def splitmix64(z):
    z = (z + 0x9E3779B97F4A7C15) & MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
    return (z ^ (z >> 31)) & MASK


def edge_noise(u, v, seed):
    a, b = min(u, v), max(u, v)
    z = (seed ^ ((a + 1) * 0xD6E8FEB86659FD93) ^ ((b + 1) * 0xA5A3564E27FDF50D)) & MASK
    return splitmix64(z) % 11


def make_covering_greedy(n, q, seed, simplify=True):
    """Exact dominating property; incremental-gain greedy O(q*n*N) updates.

    This heuristic does NOT guarantee a minimum-size dominating set.
    """
    N, _, degree = qgraph_size(n, q)
    strides = [q**j for j in range(n)]
    # use unsigned short if possible: maximum gain=degree+1
    if degree + 1 < 65536:
        gain = array('H', [degree + 1]) * N
    else:
        gain = array('I', [degree + 1]) * N
    covered = bytearray(N)
    # random tie break deterministic per fixed seed
    rng = random.Random(seed)
    ties = list(range(N))
    rng.shuffle(ties)
    priority = array('I', [0]) * N
    for idx, v in enumerate(ties):
        priority[v] = idx
    del ties
    heap = [(-degree - 1, priority[v], v) for v in range(N)]
    heapq.heapify(heap)
    selected = []
    nleft = N
    t0 = time.monotonic()
    while nleft:
        while True:
            if not heap:
                raise RuntimeError('Heap exhausted without coverage')
            neg, tie, u = heapq.heappop(heap)
            if -neg == gain[u]:
                break
            # coverage gains only decrease, hence reinsertion is valid
            heapq.heappush(heap, (-int(gain[u]), tie, u))
        if not gain[u]:
            raise RuntimeError('Unable to cover vertex')
        selected.append(u)
        for v in (u, *neighbor_ids(u, n, q, strides)):
            if covered[v]:
                continue
            covered[v] = 1
            nleft -= 1
            gain[v] -= 1
            for z in neighbor_ids(v, n, q, strides):
                gain[z] -= 1
    del heap, gain, priority
    if simplify:
        # Every vertex must retain coverage count >=1 after deleting redundant codeword.
        # O(|C|*degree), and tested independently in validate_covering.
        cover_count = array('I', [0]) * N
        for u in selected:
            cover_count[u] += 1
            for v in neighbor_ids(u, n, q, strides):
                cover_count[v] += 1
        keep = []
        for u in reversed(selected):
            vicinity = [u, *neighbor_ids(u, n, q, strides)]
            if all(cover_count[v] >= 2 for v in vicinity):
                for v in vicinity:
                    cover_count[v] -= 1
            else:
                keep.append(u)
        selected = list(reversed(keep))
    selected.sort()
    return selected, time.monotonic() - t0



def make_covering_tabu(n, q, seed, steps=450, levels=8,
                       candidate_sample=5, removal_sample=24, restarts=3):
    """Approximate radius-1 covering code with reproducible tabu exchanges.

    Starts with a valid greedy covering code. At target cardinality K-1, uses
    1-for-1 exchanges to minimize uncovered vertices. Intermediate states are
    allowed to be infeasible, but the *returned* code is always feasible.
    This is a new implementation, NOT the original Poggi--Souza tabu search.
    Fixed iteration budgets, not wall-clock stops, provide reproducibility.
    """
    if min(steps, levels, candidate_sample, removal_sample, restarts) < 1:
        raise ValueError('Tabu budgets and sample sizes must be positive')
    t0 = time.monotonic()
    base, greedy_seconds = make_covering_greedy(n, q, seed)
    N, _, degree = qgraph_size(n, q)
    strides = [q**j for j in range(n)]
    rng = random.Random(seed ^ 0x5D6EF70A932BD1)
    neighbors_cache = None
    if N <= 5000:
        neighbors_cache = [tuple([v, *neighbor_ids(v, n, q, strides)])
                           for v in range(N)]
    def closed(u):
        return (neighbors_cache[u] if neighbors_cache is not None
                else (u, *neighbor_ids(u, n, q, strides)))
    best = list(base)
    visited = 0
    levels_done = 0
    for _ in range(levels):
        if len(best) <= 1:
            break
        success = None
        for restart in range(restarts):
            selected = set(best)
            counts = array('I', [0]) * N
            for u in selected:
                for v in closed(u):
                    counts[v] += 1
            uncovered = set()
            def remove(u):
                selected.remove(u)
                for v in closed(u):
                    counts[v] -= 1
                    if counts[v] == 0:
                        uncovered.add(v)
            def add(u):
                selected.add(u)
                for v in closed(u):
                    if counts[v] == 0:
                        uncovered.discard(v)
                    counts[v] += 1

            # Initial destruction: delete a near-redundant selected codeword.
            candidates = (sorted(selected) if len(selected) <= 160 else
                          rng.sample(sorted(selected), 160))
            scores = [(sum(counts[v] == 1 for v in closed(u)), rng.random(), u)
                      for u in candidates]
            scores.sort()
            dropped = scores[min(restart, len(scores)-1)][2]
            remove(dropped)
            tabu_add = {dropped: 0}
            tabu_remove = {}
            best_uncovered = len(uncovered)
            tenure = max(5, min(18, degree // 2 + 4))

            for iteration in range(steps):
                visited += 1
                if not uncovered:
                    success = sorted(selected)
                    break

                missing = sorted(uncovered)
                if len(missing) > candidate_sample:
                    missing = rng.sample(missing, candidate_sample)
                add_candidates = set()
                for v in missing:
                    add_candidates.update(closed(v))
                add_candidates.difference_update(selected)
                if not add_candidates:
                    break
                incoming = []
                for a in sorted(add_candidates):
                    na = closed(a)
                    gain = sum(counts[v] == 0 for v in na)
                    incoming.append((-gain, rng.random(), a, na))
                incoming.sort()
                incoming = incoming[:16]
                out_candidates = (sorted(selected) if len(selected) <= removal_sample
                                  else rng.sample(sorted(selected), removal_sample))

                best_move = None
                best_score = None
                for r in out_candidates:
                    nr = set(closed(r))
                    loss = sum(counts[v] == 1 for v in nr)
                    for minus_gain, _, a, na in incoming:
                        overlap = sum(counts[v] == 1 and v in nr for v in na)
                        missing_after = len(uncovered) + loss + minus_gain - overlap
                        taboo = (tabu_add.get(a, -tenure-1) + tenure > iteration or
                                 tabu_remove.get(r, -tenure-1) + tenure > iteration)
                        if taboo and missing_after >= best_uncovered:
                            continue
                        score = (missing_after, rng.random())
                        if best_score is None or score < best_score:
                            best_score, best_move = score, (r, a)
                if best_move is None:
                    # Diversification, also ensures a bounded search that cannot
                    # accidentally return an infeasible covering code.
                    best_move = (rng.choice(out_candidates), rng.choice(incoming)[2])
                r, a = best_move
                remove(r)
                add(a)
                tabu_add[r] = iteration
                tabu_remove[a] = iteration
                best_uncovered = min(best_uncovered, len(uncovered))
            if success is not None:
                break
        if success is None:
            break
        validate_covering(success, n, q)
        if len(success) != len(best) - 1:
            raise AssertionError('Unexpected covering cardinality change')
        best = success
        levels_done += 1
    return best, time.monotonic()-t0, dict(greedy_terminals=len(base),
          reduced_by=len(base)-len(best), successful_levels=levels_done,
          tabu_exchange_steps=visited, full_greedy_seconds=round(greedy_seconds, 3))

def make_covering_hamming(n, q, seed=42):
    """Construct a perfect radius-1 q-ary Hamming covering code.

    This algebraic method applies only when q is prime and n=(q**m-1)/(q-1)
    for integer m>=2. The returned parity-check code is a valid *minimum*
    dominating set in the complete Hamming graph H(n,q).

    Unlike the historical PUC CC generator, it does not use tabu search.
    Terminal locations are fixed by a canonical parity-check matrix and
    therefore do not depend on seed. p-variant edge weights still use seed.
    """
    t0 = time.monotonic()
    if q < 2 or any(q % p == 0 for p in range(2, int(q**0.5) + 1)):
        raise ValueError('--cover-method hamming requires a prime q (e.g. 2, 3, 5, 7)')
    m = None
    length = 1
    for k in range(2, 40):
        length += q ** (k - 1)
        if length == n:
            m = k
            break
        if length > n:
            break
    if m is None:
        raise ValueError(f'No perfect prime-q Hamming code exists for H({n},{q}); '
                         'require n=(q**m-1)//(q-1). '
                         'For million-scale graphs try --n 13 --q 3.')

    # Columns represent all one-dimensional subspaces of GF(q)^m.
    # Their first nonzero entry equals 1. This gives precisely n columns.
    cols = []
    for encoded in range(1, q ** m):
        vec = []
        w = encoded
        for _ in range(m):
            vec.append(w % q)
            w //= q
        pivot = next((x for x in vec if x), None)
        if pivot == 1:
            cols.append(vec)
        elif pivot is not None:
            inv = pow(pivot, -1, q)
            # Choose the canonical representative, not a duplicate.
            if inv == 1:
                cols.append(vec)
    cols.sort()
    if len(cols) != n:
        raise AssertionError(f'Incorrect parity-check column count: {len(cols)}, wanted {n}')

    N, _, degree = qgraph_size(n, q)
    terminals = []
    for node in range(N):
        digits = node
        sums = [0] * m
        for c in cols:
            x = digits % q
            digits //= q
            if x:
                for j in range(m):
                    sums[j] += x * c[j]
        if all(s % q == 0 for s in sums):
            terminals.append(node)
    expected = q ** (n - m)
    if len(terminals) != expected:
        raise AssertionError(f'Perfect-code size mismatch: {len(terminals)} != {expected}')
    # Each radius-1 ball has size 1+degree=q**m; disjoint linear-code balls
    # partition the N vertices. validate_covering checks all vertices.
    validate_covering(terminals, n, q)
    return terminals, time.monotonic() - t0, dict(
        construction='canonical q-ary Hamming linear code, parity-check matrix',
        q=q, n=n, parity_check_rows=m,
        covering_radius=1, perfectly_covers=True,
        proved_minimum_terminal_cardinality=expected,
        terminal_seed_dependency=False)


def make_covering_exact(n, q, seconds=60.0, max_nodes=500):
    """Solve minimum dominating set MILP with SciPy/HiGHS (small cases only).

    An optimal code need not coincide with the original published tabu-search code.
    """
    N, _, degree = qgraph_size(n, q)
    if N > max_nodes:
        raise ValueError(f'Exact covering MILP disabled for N={N}> {max_nodes}; use --cover-method greedy')
    try:
        import numpy as np
        from scipy.optimize import milp, Bounds, LinearConstraint
        from scipy.sparse import coo_matrix
    except ImportError as e:
        raise ValueError('Exact mode requires scipy and numpy; install with python3 -m pip install scipy') from e
    rows=[]; cols=[]
    for v in range(N):
        rows.append(v);cols.append(v)
        for u in neighbor_ids(v,n,q):
            rows.append(v);cols.append(u)
    A=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(N,N)).tocsr()
    t0=time.monotonic()
    res=milp(c=np.ones(N), integrality=np.ones(N),
             bounds=Bounds(np.zeros(N),np.ones(N)),
             constraints=[LinearConstraint(A,lb=np.ones(N),ub=np.full(N,np.inf))],
             options={'time_limit':float(seconds), 'disp':False})
    if res.x is None:
        raise ValueError(f'Covering MILP did not find an incumbent within {seconds}s; {res.message}')
    terminals=np.flatnonzero(res.x > .5).tolist()
    validate_covering(terminals,n,q)
    return terminals,time.monotonic()-t0, bool(res.success),float(getattr(res,'mip_gap',float('nan')))


def validate_covering(terminals, n, q):
    N, _, degree = qgraph_size(n, q)
    marks = bytearray(N)
    seen = set()
    for t in terminals:
        if t < 0 or t >= N or t in seen:
            raise ValueError(f'Invalid/duplicate terminal {t}')
        seen.add(t)
        marks[t] = 1
        for u in neighbor_ids(t, n, q):
            marks[u] = 1
    ncovered = sum(marks)
    if ncovered != N:
        example = next(i for i, x in enumerate(marks) if not x)
        raise ValueError(f'NOT a covering code: {ncovered}/{N}; uncovered vertex {example}')
    return dict(covering_valid=True, covered_vertices=ncovered, terminals=len(terminals),
                sphere_size=degree + 1, covering_cardinality_lower_bound=(N + degree) // (degree + 1))


def read_stp(path, require_edges=False):
    """Read SteinLib STP, return N, edge count, zero-based terminals, edges optional.
    Ignores coordinates/comments; accepts .stp UTF-8 or ASCII. Strict edge/terminal counts.
    """
    N = M = K = None
    terminals = []
    edges = {} if require_edges else None
    edge_count = 0
    section = ''
    with open(path, 'r', encoding='utf-8-sig') as src:
        for row in src:
            s = row.split('#', 1)[0].strip()
            if not s: continue
            cols = s.split()
            op = cols[0].lower()
            if op == 'section': section = cols[1].lower(); continue
            if op == 'end': section = ''; continue
            if op == 'eof': break
            if section == 'graph':
                if op == 'nodes': N = int(cols[1])
                elif op == 'edges': M = int(cols[1])
                elif op == 'e':
                    edge_count += 1
                    if require_edges:
                        a, b, w = int(cols[1])-1, int(cols[2])-1, int(cols[3])
                        key = (min(a,b), max(a,b))
                        if key in edges: raise ValueError(f'Parallel edge {key} in {path}')
                        edges[key] = w
            elif section == 'terminals':
                if op == 'terminals': K = int(cols[1])
                elif op == 't': terminals.append(int(cols[1])-1)
    if N is None or M is None or K is None:
        raise ValueError(f'Missing Graph/Terminals fields in {path}')
    if M != edge_count or K != len(terminals):
        raise ValueError(f'Header counts differ: M {M} vs {edge_count}; K {K} vs {len(terminals)}')
    if len(set(terminals)) != K or any(not 0 <= t < N for t in terminals):
        raise ValueError('Bad terminal IDs')
    return dict(N=N, M=M, K=K, terminals=sorted(terminals), edges=edges)


def verify_cc_stream(path, n, q):
    """Strong CC validity check in O(N+M) time and O(N+M/8) bytes memory.

    Checks every edge against its unique Hamming-edge index (no duplicates),
    verifies its incidence cost class, covers all nodes by the terminals.
    """
    N, M, degree = qgraph_size(n, q)
    src = read_stp(path, require_edges=False)
    if src['N'] != N or src['M'] != M:
        raise ValueError(f'Graph size mismatch: given N={src["N"]}, M={src["M"]}, expected N={N}, M={M}')
    cover = validate_covering(src['terminals'],n,q)
    tflags=bytearray(N)
    for v in src['terminals']: tflags[v] = 1
    strides=[q**j for j in range(n)]
    offset=array('Q',[0])*N
    cumulative=0
    for v in range(N):
        offset[v]=cumulative
        cumulative += sum(q-1-(v//stride)%q for stride in strides)
    if cumulative!=M: raise AssertionError('Edge-index sizing mismatch')
    seen=bytearray((M+7)//8)
    cat_counts=[0,0,0,0]
    variant=None
    read=0
    section=''
    with open(path,'r',encoding='utf-8-sig') as src_file:
        for line in src_file:
            parts=line.split('#',1)[0].split()
            if not parts: continue
            op=parts[0].lower()
            if op=='section':section=parts[1].lower();continue
            if op=='end':section='';continue
            if section!='graph' or op!='e':continue
            if len(parts)<4:raise ValueError(f'Malformed edge: {line.strip()}')
            a,b,w=(int(parts[1])-1,int(parts[2])-1,int(parts[3]))
            if a==b or min(a,b)<0 or max(a,b)>=N:
                raise ValueError(f'Invalid edge ({a+1},{b+1})')
            if a>b:a,b=b,a
            diffs=0; index=None; prior=0
            for j,stride in enumerate(strides):
                x=(a//stride)%q;y=(b//stride)%q
                if x!=y:
                    diffs+=1
                    if diffs>1: break
                    if x>y:break
                    index=int(offset[a])+prior+(y-x-1)
                prior += q-1-x
            if diffs!=1 or index is None:
                raise ValueError(f'Non-Hamming edge ({a+1},{b+1})')
            byte,bit=divmod(index,8)
            if seen[byte] & (1<<bit):raise ValueError(f'Duplicate edge ({a+1},{b+1})')
            seen[byte] |= 1<<bit
            cat=1+tflags[a]+tflags[b]
            cat_counts[cat]+=1
            if w==cat:cur='u'
            elif 100*cat<=w<=100*cat+10:cur='p'
            else:raise ValueError(f'Bad cost for edge ({a+1},{b+1}): {w} in category {cat}')
            if variant is None:variant=cur
            elif variant!=cur:raise ValueError('Mixed u and p edge weights')
            read+=1
    if read!=M:raise ValueError(f'Only {read} edges, expected {M}')
    return dict(verified=True,file=str(path),n=n,q=q,N=N,M=M,degree=degree,
                variant=variant,category_edges=cat_counts[1:],covering=cover,
                lower_bound=analytic_lb(len(src['terminals']),degree,variant))


def analytic_lb(t, degree, variant):
    # min tree cost >= 2t-1+ceil((t-2)/(Delta-2)), for t>=2 and Delta>=3.
    # Follows from sum of tree vertex degrees and CC incidence costs.
    if t <= 1:
        return 0
    if degree <= 2:
        # Conservative bound for deg<=2: at least t-1 edges, every selected terminal degree>=1.
        lb = 2*t - 1
    else:
        lb = 2*t-1 + (max(0,t-2)+degree-3)//(degree-2)
    return (100 if variant == 'p' else 1) * lb


def generate_file(n, q, terminals, variant, seed, destination,
                  noise_method='prng'):
    """Stream the complete Hamming graph as STP and certify a feasible-tree UB.

    prng: pseudorandom uniform integers 0..10 drawn ONCE per edge in a
          canonical, deterministic edge order; mathematically follows PUC's
          perturbation classes without reproducing its historical random stream.
    hash: reproduce the independent generator v1 perturbation exactly.
    """
    if variant not in ('u','p'):
        raise ValueError('variant must be u or p')
    if noise_method not in ('prng','hash'):
        raise ValueError('noise_method must be prng or hash')
    N, M, degree = qgraph_size(n, q)
    terminal_flags = bytearray(N)
    for u in terminals:
        if u < 0 or u >= N or terminal_flags[u]:
            raise ValueError(f'Invalid or repeated terminal: {u}')
        terminal_flags[u] = 1
    strides = [q**j for j in range(n)]
    rng = random.Random(seed)
    ub = 0
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(destination.name + '.partial')
    sha = hashlib.sha256()
    def emit(f, text):
        data = text.encode('ascii')
        f.write(data)
        sha.update(data)
    try:
        with open(tmp_path, 'wb', buffering=1024*1024) as f:
            emit(f, '33D32945 STP File, STP Format Version 1.0\n')
            emit(f, 'SECTION Comment\n')
            emit(f, f'Name "{destination.stem}"\n')
            emit(f, 'Creator "Independent PUC-CC structural generator v3"\n')
            emit(f, f'Remark "Hamming H({n},{q}), covering radius 1, seed={seed}, type={variant}, noise={noise_method}"\n')
            emit(f, 'END\n\nSECTION Graph\n')
            emit(f, f'Nodes {N}\nEdges {M}\n')
            m = 0
            for v in range(N):
                for stride in strides:
                    digit = (v // stride) % q
                    zeroed = v - digit * stride
                    for next_digit in range(digit+1, q):
                        w = zeroed + next_digit * stride
                        typ = 1 + terminal_flags[v] + terminal_flags[w]
                        if variant == 'u':
                            cost = typ
                        elif noise_method == 'prng':
                            cost = 100 * typ + rng.randint(0, 10)
                        else:
                            cost = 100 * typ + edge_noise(v, w, seed)
                        emit(f, f'E {v+1} {w+1} {cost}\n')
                        # A feasible spanning tree: each vertex w>0 is joined
                        # to the vertex obtained by zeroing its highest
                        # nonzero q-ary digit. Exactly those edges have v<stride.
                        if v < stride:
                            ub += cost
                        m += 1
            if m != M:
                raise AssertionError(f'Unexpected number of edges {m} != {M}')
            emit(f, 'END\n\nSECTION Terminals\n')
            emit(f, f'Terminals {len(terminals)}\n')
            for u in sorted(terminals):
                emit(f, f'T {u+1}\n')
            emit(f, 'END\nEOF\n')
        tmp_path.replace(destination)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return dict(file=str(destination), bytes=destination.stat().st_size,
                sha256=sha.hexdigest(), edges_written=M,
                analytical_lower_bound=analytic_lb(len(terminals), degree, variant),
                spanning_tree_upper_bound=ub)


def compare_files(path_a, path_b, n=None, q=None):
    a=read_stp(path_a,require_edges=True)
    b=read_stp(path_b,require_edges=True)
    ea=a.pop('edges'); eb=b.pop('edges')
    ea_set=set(ea); eb_set=set(eb)
    both=ea_set & eb_set
    weight_diffs=sum(ea[e] != eb[e] for e in both)
    term_a=set(a['terminals']); term_b=set(b['terminals'])
    report=dict(reference=str(path_a), generated=str(path_b),
        reference_vertices=a['N'],generated_vertices=b['N'],
        reference_edges=a['M'],generated_edges=b['M'],
        reference_terminals=a['K'],generated_terminals=b['K'],
        same_vertex_count=a['N']==b['N'],same_edge_count=a['M']==b['M'],
        same_terminal_set=term_a==term_b,
        terminals_only_in_reference=len(term_a-term_b),
        terminals_only_in_generated=len(term_b-term_a),
        same_edge_set=ea_set==eb_set,
        edges_only_in_reference=len(ea_set-eb_set),
        edges_only_in_generated=len(eb_set-ea_set),
        common_edge_weight_differences=weight_diffs,
        same_STP_problem=a['N']==b['N'] and term_a==term_b and ea==eb)
    if n is not None and q is not None:
        N,M,degree=qgraph_size(n,q)
        report['expected_hamming_graph']={'N':N,'M':M,'degree':degree}
        if a['N']==N:
            try:
                report['reference_covering']=validate_covering(a['terminals'],n,q)
            except ValueError as e:
                report['reference_covering_error']=str(e)
        if b['N']==N:
            try:
                report['generated_covering']=validate_covering(b['terminals'],n,q)
            except ValueError as e:
                report['generated_covering_error']=str(e)
        def hamming_edge(e):
            u,v=e
            return sum((u//(q**j))%q != (v//(q**j))%q for j in range(n))==1
        report['reference_non_hamming_edges']=sum(not hamming_edge(e) for e in ea)
        report['generated_non_hamming_edges']=sum(not hamming_edge(e) for e in eb)
    return report


def verify_generated_fast(path, n, q, seed=42, cover_method='hamming',
                          noise_method='prng', tabu_steps=450,
                          tabu_levels=8, tabu_restarts=3):
    """Linear-time canonical-file verifier for extremely large generated STPs.

    This verifies the full edge stream against the independently enumerated
    expected Hamming neighbors and cost classes in the generator's canonical
    order. Unlike `verify`, it does not support unordered STP edge records.
    It reconstructs terminals from the chosen deterministic covering algorithm
    and verifies the terminal list, edge weights, and all counts. O(N+M) operations.
    """
    if cover_method == 'hamming':
        terminals, _, _ = make_covering_hamming(n, q, seed)
    elif cover_method == 'greedy':
        terminals, _ = make_covering_greedy(n, q, seed)
    elif cover_method == 'tabu':
        terminals, _, _ = make_covering_tabu(n, q, seed, steps=tabu_steps,
                                            levels=tabu_levels, restarts=tabu_restarts)
    else:
        raise ValueError('Fast verification supports hamming, greedy and tabu only')
    validate_covering(terminals,n,q)
    N, M, degree = qgraph_size(n, q)
    terminal_flags = bytearray(N)
    for u in terminals:terminal_flags[u] = 1
    strides = [q**j for j in range(n)]
    rng = random.Random(seed)
    fpath = Path(path)
    with open(fpath, 'rb', buffering=1024*1024) as f:
        def next_significant():
            while True:
                line = f.readline()
                if not line:raise ValueError('Unexpected EOF')
                tokens = line.split()
                if tokens:return tokens
        # Skip header through the Graph section without reading the file twice.
        while True:
            tokens = next_significant()
            if tokens[0].lower() == b'section' and len(tokens)>1 and tokens[1].lower()==b'graph':break
        a=next_significant(); b=next_significant()
        if a != [b'Nodes',str(N).encode()] or b != [b'Edges',str(M).encode()]:
            raise ValueError(f'Bad Graph header: {a!r}, {b!r}')
        variant = None
        count = 0
        for v in range(N):
            for stride in strides:
                digit=(v//stride)%q
                zeroed=v-digit*stride
                for target_digit in range(digit+1,q):
                    w=zeroed+target_digit*stride
                    line=next_significant()
                    if len(line)!=4 or line[0] != b'E' or int(line[1]) != v+1 or int(line[2]) != w+1:
                        raise ValueError(f'Edge {count+1} mismatch: expected E {v+1} {w+1}, got {line!r}')
                    weight=int(line[3])
                    typ=1+terminal_flags[v]+terminal_flags[w]
                    if variant is None:
                        variant='u' if weight==typ else 'p'
                    if variant=='u':expected=typ
                    elif noise_method=='prng':expected=100*typ+rng.randint(0,10)
                    else:expected=100*typ+edge_noise(v,w,seed)
                    if weight!=expected:
                        raise ValueError(f'Edge {count+1} weight mismatch: got {weight}, expected {expected}')
                    count+=1
        if next_significant()!=[b'END'] or next_significant()!=[b'SECTION',b'Terminals']:
            raise ValueError('Missing Terminals section')
        if next_significant()!=[b'Terminals',str(len(terminals)).encode()]:
            raise ValueError('Wrong terminal count')
        for u in terminals:
            if next_significant()!=[b'T',str(u+1).encode()]:
                raise ValueError(f'Terminal mismatch at node {u+1}')
        if next_significant()!=[b'END'] or next_significant()!=[b'EOF']:
            raise ValueError('Bad terminal-section end')
        if f.read(1):
            raise ValueError('Unexpected trailing content')
    return dict(verified=True,file=str(path),n=n,q=q,N=N,M=M,terminals=len(terminals),
                variant=variant,seed=seed,cover_method=cover_method,noise_method=noise_method,
                full_canonical_edge_stream_checked=True,terminal_covering_verified=True)


def cli():
    ap = argparse.ArgumentParser(description='PUC-inspired CC / Hamming covering code STP generator v3')
    sub = ap.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan', help='Show theoretical graph size')
    for parser in [plan]:
        parser.add_argument('--n',type=int,required=True);parser.add_argument('--q',type=int,required=True)
    gen = sub.add_parser('generate', help='Generate STP (u/p/both)')
    gen.add_argument('--n',type=int,required=True);gen.add_argument('--q',type=int,required=True)
    gen.add_argument('--seed',type=int,default=42);gen.add_argument('--variant',choices=['u','p','both'],default='both')
    gen.add_argument('--outdir',default='instances');gen.add_argument('--meta-dir',default=None)
    gen.add_argument('--name',default=None,help='Base file name without u/p suffix')
    gen.add_argument('--terminals-from',help='Use terminal vertex IDs from an official reference STP (matching N)')
    gen.add_argument('--max-nodes',type=int,default=300000)
    gen.add_argument('--cover-method',choices=['tabu','greedy','exact','hamming'],default='tabu')
    gen.add_argument('--tabu-steps',type=int,default=450,
                     help='Fixed exchanges per tabu restart (reproducible)')
    gen.add_argument('--tabu-levels',type=int,default=8,
                     help='Maximum successive terminal removals')
    gen.add_argument('--tabu-restarts',type=int,default=3)
    gen.add_argument('--noise-method',choices=['prng','hash'],default='prng',
                     help='prng uses independent pseudorandom draws; hash preserves v1 weights')
    gen.add_argument('--verify-after-write',action='store_true',
                     help='Full O(N+M) semantic verification of each STP output')
    gen.add_argument('--exact-time-limit',type=float,default=60.0)
    cmp = sub.add_parser('compare',help='Compare STP semantics, not file byte layout')
    cmp.add_argument('reference');cmp.add_argument('candidate');cmp.add_argument('--n',type=int);cmp.add_argument('--q',type=int)
    val = sub.add_parser('verify', help='Check CC topology, terminals, weight categories; O(N+M)')
    val.add_argument('file');val.add_argument('--n',type=int,required=True);val.add_argument('--q',type=int,required=True)
    vf=sub.add_parser('verify-generated',help='Fast O(N+M) check of canonical Hamming-code outputs')
    vf.add_argument('file');vf.add_argument('--n',type=int,required=True);vf.add_argument('--q',type=int,required=True)
    vf.add_argument('--seed',type=int,default=42)
    vf.add_argument('--cover-method',choices=['hamming','greedy','tabu'],default='hamming')
    vf.add_argument('--tabu-steps',type=int,default=450)
    vf.add_argument('--tabu-levels',type=int,default=8)
    vf.add_argument('--tabu-restarts',type=int,default=3)
    vf.add_argument('--noise-method',choices=['prng','hash'],default='prng')
    args = ap.parse_args()
    if args.command=='verify-generated':
        report=verify_generated_fast(args.file,args.n,args.q,args.seed,cover_method=args.cover_method,
                   noise_method=args.noise_method,tabu_steps=args.tabu_steps,
                   tabu_levels=args.tabu_levels,tabu_restarts=args.tabu_restarts)
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return
    if args.command=='plan':
        N,M,degree=qgraph_size(args.n,args.q)
        print(json.dumps(dict(n=args.n,q=args.q,N=N,M=M,degree=degree,sphere_cover_size=degree+1,
                                  min_covering_vertices=(N+degree)//(degree+1)),indent=2))
        return
    if args.command=='compare':
        ret=compare_files(args.reference,args.candidate,args.n,args.q)
        print(json.dumps(ret,indent=2,ensure_ascii=False))
        return
    if args.command=='verify':
        report=verify_cc_stream(args.file,args.n,args.q)
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return
    if args.command=='generate':
        N,M,degree=qgraph_size(args.n,args.q)
        if N > args.max_nodes:
            ap.error(f'{N} vertices exceed --max-nodes={args.max_nodes}, override deliberately if needed')
        name=args.name or f'cc{args.n}-{args.q}_gen_s{args.seed}_'
        code_proved_minimal = None
        search_info = None
        if args.terminals_from:
            source=read_stp(args.terminals_from)
            if source['N'] != N:
                ap.error(f'Official source N={source["N"]} differs from H({args.n},{args.q}) N={N}')
            terminals=source['terminals']
            elapsed=0.0
            algorithm='imported_reference_terminals_not_independent_reproduction'
        elif args.cover_method == 'exact':
            print(f'Computing minimum dominating set by MILP for H({args.n},{args.q}), N={N} ...',flush=True)
            terminals,elapsed,code_proved_minimal,coverage_gap=make_covering_exact(
                args.n,args.q,args.exact_time_limit)
            algorithm='scipy_highs_milp_covering_code'
            print(f'  MILP covering code minimum proved: {code_proved_minimal}; gap={coverage_gap:.4g}',flush=True)
        elif args.cover_method == 'hamming':
            print(f'Computing perfect Hamming radius-1 code for H({args.n},{args.q}), N={N} ...',flush=True)
            terminals,elapsed,search_info=make_covering_hamming(args.n,args.q,args.seed)
            algorithm='perfect_q_ary_hamming_linear_covering_code'
            code_proved_minimal=True
            print(f'  verified perfect code: K={len(terminals)}; proof: one codeword per closed radius-1 ball',flush=True)
        elif args.cover_method == 'tabu':
            print(f'Computing tabu-improved covering code H({args.n},{args.q}), N={N},degree={degree} ...',flush=True)
            terminals,elapsed,search_info=make_covering_tabu(
                args.n,args.q,args.seed,steps=args.tabu_steps,
                levels=args.tabu_levels,restarts=args.tabu_restarts)
            algorithm='independent_greedy_plus_tabu_exchanges'
            print(f'  tabu improvement: {search_info}',flush=True)
        else:
            print(f'Computing verified greedy covering code H({args.n},{args.q}), N={N},degree={degree} ...',flush=True)
            terminals,elapsed=make_covering_greedy(args.n,args.q,args.seed)
            algorithm='incremental_gain_greedy_plus_redundancy_pruning'
        cover=validate_covering(terminals,args.n,args.q)
        print(f'Cover valid: |T|={len(terminals)}, cover_time={elapsed:.2f}s, cover_sphere_LB={cover["covering_cardinality_lower_bound"]}',flush=True)
        variants=['u','p'] if args.variant=='both' else [args.variant]
        outdir=Path(args.outdir)
        metadir=Path(args.meta_dir) if args.meta_dir else outdir
        metadir.mkdir(parents=True,exist_ok=True)
        for variant in variants:
            dest=outdir / (name+variant+'.stp')
            print(f'Writing {dest} ...',flush=True)
            gen_meta=generate_file(args.n,args.q,terminals,variant,args.seed,dest,
                                   noise_method=args.noise_method)
            if args.verify_after_write:
                checked=verify_cc_stream(dest,args.n,args.q)
                if checked['variant'] != variant:
                    raise AssertionError('Verification returned unexpected weight variant')
                print('  independent file verification: PASS',flush=True)
            metadata=dict(source='Independent CC generator based on Rosseti et al. (2001), Section 2.2',
                          not_original_PUC_generator=True,covering_method=algorithm,
                          reference_terminals_file=args.terminals_from,n=args.n,q=args.q,r=1,
                          N=N,M=M,average_degree=degree,seed=args.seed,variant=variant,
                          terminals=len(terminals),coverage=cover,covering_code_proved_minimal=code_proved_minimal,
                          tabu_search_information=search_info,
                          terminal_set_sha256=hashlib.sha256(
                              ','.join(str(i) for i in terminals).encode('ascii')).hexdigest(),
                          noise_method=(args.noise_method if variant=='p' else 'none'),
                          terminal_index_base='one-based STP',
                          edge_weight_rule='u:1/2/3, p:100..110 / 200..210 / 300..310',
                          lower_bound_explanation='Degree-count bound for incidence costs; not OPT',
                          generation_time_coverage_seconds=round(elapsed,3),**gen_meta)
            (metadir/(name+variant+'.json')).write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
            print(f'  N={N}, M={M}, K={len(terminals)}, LB={gen_meta["analytical_lower_bound"]}, UB={gen_meta["spanning_tree_upper_bound"]}, {gen_meta["bytes"]:,} bytes',flush=True)

if __name__=='__main__':
    try:cli()
    except (ValueError,FileNotFoundError) as e:
        print(f'ERROR: {e}',file=sys.stderr)
        sys.exit(2)
