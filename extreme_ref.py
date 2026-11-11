# Referinta Cronos: verific SAU corectez assert-urile suite-ului inainte de bench.
import heapq, math

# ---------- P1: Dijkstra cu parity + turn penalty ----------
def parity_turn_dijkstra(n, edges, start, dst):
    adj = [[] for _ in range(n)]
    for u, v, w, c in edges:
        adj[u].append((v, w, c))
    # state: (node, step_parity(0=urmatorul edge e step 1/odd, 1=urmatorul e even), prev_color, run_len)
    INF = float("inf")
    dist = {}
    pq = [(0, start, 0, None, 0)]
    while pq:
        d, u, par, pc, run = heapq.heappop(pq)
        if (u, par, pc, run) in dist:
            continue
        dist[(u, par, pc, run)] = d
        if u == dst:
            return d
        for v, w, c in adj[u]:
            if pc is not None and c == pc:
                if run >= 2:
                    continue
                run2 = run + 1
            else:
                run2 = 1
            cost = 2 * w if par == 1 else w
            if pc is not None:
                cost += abs(pc - c) * 3
            npar = 0 if par == 1 else 1
            nd = d + cost
            key = (v, npar, c, run2)
            if key not in dist or nd < dist[key]:
                heapq.heappush(pq, (nd, v, npar, c, run2))
    return -1

# ---------- P2: Hammerstad-Jensen + Wheeler, solver bisection ----------
def solve_microstrip_width(z_target, h_mm, er, t_oz):
    t_mm = t_oz * 0.034798
    th = t_mm / h_mm
    def u1ur(u):
        if th <= 0:
            return u, u
        s = math.sqrt(6.517 * u)
        tanh_s = math.tanh(s)
        arg = (4.0 * math.e) / (th * (1.0 / tanh_s) ** 2) if tanh_s > 0 else 0.0
        du1 = th / math.pi * math.log(1.0 + arg)
        cr = math.sqrt(er - 1.0)
        du_r = 0.5 * du1 * (1.0 + 1.0 / math.cosh(min(cr, 350.0)))
        return u + du1, u + du_r
    def eeff(ur):
        a = (1.0 + (1.0/49.0)*math.log((ur**4 + (ur/52.0)**2)/(ur**4 + 0.432))
             + (1.0/18.7)*math.log(1.0 + (ur/18.1)**3))
        b = 0.564 * ((er - 0.9)/(er + 3.0))**0.053
        return (er+1.0)/2.0 + ((er-1.0)/2.0)*(1.0 + 10.0/ur)**(-a*b)
    def f_u(x):
        return 6.0 + (2.0*math.pi - 6.0)*math.exp(-(30.666/x)**0.7528)
    def z0_fs(x):
        return (376.730313668/(2.0*math.pi))*math.log(f_u(x)/x + math.sqrt(1.0 + (2.0/x)**2))
    def z0(w):
        u = w / h_mm
        _, ur = u1ur(u)
        return z0_fs(ur) / math.sqrt(eeff(ur))
    lo, hi = 0.01, 20.0
    zlo, zhi = z0(lo), z0(hi)
    if not (zhi <= z_target <= zlo):
        raise ValueError("tinta in afara intervalului")
    for _ in range(200):
        mid = 0.5*(lo+hi)
        if z0(mid) > z_target: lo = mid
        else: hi = mid
        if hi - lo < 1e-9: break
    w = 0.5*(lo+hi)
    _, ur = u1ur(w/h_mm)
    ee = eeff(ur)
    return {"w_mm": round(w, 4),
            "w_mils": round(w*39.3700787, 4),
            "eeff": round(ee, 4),
            "delay_ps_per_mm": round(1000.0/math.sqrt(ee)/299.792458, 4)}

# ---------- P4: PDN anti-resonanta ----------
def analyze_pdn_impedance(caps, f_start_hz, f_stop_hz, num_points):
    Z = []
    F = []
    for k in range(num_points):
        f = f_start_hz * (f_stop_hz/f_start_hz)**(k/(num_points-1))
        w = 2.0*math.pi*f
        Y = 0j
        for C, esr, esl in caps:
            Y += 1.0/(esr + 1j*(w*esl - 1.0/(w*C)))
        F.append(f)
        Z.append(1.0/abs(Y))
    peaks = [k for k in range(1, num_points-1) if Z[k] > Z[k-1] and Z[k] > Z[k+1]]
    if peaks:
        kp = max(peaks, key=lambda k: Z[k])
        fmax, zmax = F[kp], Z[kp]
    else:
        fmax = zmax = float("nan")
    return {"max_anti_res_freq_mhz": round(fmax/1e6, 2),
            "max_anti_res_z_mohm": round(zmax*1000.0, 2),
            "min_z_mohm": round(min(Z)*1000.0, 2)}

# ---------- P3: motorul TX (interpretare literala) ----------
def run_tx_engine(ops):
    out = []
    store = {}
    lock_owner = {}
    active = set()
    writes = {}
    locks_order = {}
    savepoints = {}
    waiting = {}
    def release(tx, keys):
        freed = []
        for k in keys:
            if lock_owner.get(k) == tx:
                del lock_owner[k]
                freed.append(k)
        return freed
    def pump(keys):
        progressed = True
        while progressed:
            progressed = False
            for k in list(keys):
                if k in lock_owner:
                    continue
                for tx in list(waiting.get(k, [])):
                    if tx not in active:
                        waiting[k].remove(tx)
                        continue
                    _, key, val = waiting[k].pop(0)
                    if not waiting[k]:
                        del waiting[k]
                    lock_owner[key] = tx
                    writes[tx].append((key, val))
                    if key not in locks_order[tx]:
                        locks_order[tx].append(key)
                    out.append("OK")
                    progressed = True
                    break
    for op in ops:
        tag = op[0]
        if tag == "BEGIN":
            tx = op[1]
            active.add(tx)
            writes[tx] = []
            locks_order[tx] = []
            savepoints[tx] = []
            out.append("OK")
        elif tag == "SET":
            tx, key, val = op[1], op[2], op[3]
            owner = lock_owner.get(key)
            if owner is None or owner == tx:
                lock_owner[key] = tx
                writes[tx].append((key, val))
                if key not in locks_order[tx]:
                    locks_order[tx].append(key)
                out.append("OK")
            else:
                if key in waiting.get(tx, {}):
                    pass
                waiting.setdefault(key, []).append((tx, key, val))
                out.append("WAITING")
                pump([key])
        elif tag == "SAVEPOINT":
            tx, sp = op[1], op[2]
            savepoints[tx].append((sp, len(writes[tx]), list(locks_order[tx])))
            out.append("OK")
        elif tag == "ROLLBACK_TO":
            tx, sp = op[1], op[2]
            entry = None
            for e in savepoints[tx]:
                if e[0] == sp:
                    entry = e
            if entry is not None:
                _, wl, ll = entry
                for (k, v) in reversed(writes[tx][wl:]):
                    if lock_owner.get(k) == tx:
                        del lock_owner[k]
                writes[tx] = writes[tx][:wl]
                locks_order[tx] = ll
                savepoints[tx] = [e for e in savepoints[tx] if e[0] != sp]
                pump(list(lock_owner.keys()) + [k for k in waiting if k not in lock_owner])
            out.append("OK")
        elif tag == "COMMIT":
            tx = op[1]
            for (k, v) in writes[tx]:
                store[k] = v
            freed = release(tx, list(locks_order[tx]))
            active.discard(tx)
            writes[tx] = []
            locks_order[tx] = []
            out.append("COMMITTED")
            pump(freed)
        elif tag == "GET":
            out.append(store.get(op[1]))
    return out

# ================ VERIFICAREA ASSERT-URILOR ================
print("=== P1 ===")
edges1 = [(0,1,5,1),(1,2,5,1),(2,3,5,1),(1,4,2,2),(4,2,2,2)]
print("test1 (asteptat 27):", parity_turn_dijkstra(5, edges1, 0, 3))
edges3 = [(0,1,10,1),(1,2,100,1),(0,3,1,2),(3,1,1,1)]
print("test2 (asteptat 106):", parity_turn_dijkstra(4, edges3, 0, 2))

print("=== P2 ===")
res = solve_microstrip_width(50.0, 0.2, 4.2, 1.0)
print("asteptat w_mm~0.3547 w_mils~13.9645 eeff~3.1973 delay~5.9631")
print("calculat:", res)

print("=== P4 ===")
caps = [(10e-6,0.005,800e-12),(100e-9,0.015,500e-12),(1e-9,0.050,400e-12)]
res4 = analyze_pdn_impedance(caps, 1e5, 1e9, 4001)
print("asteptat 71.36 MHz / 1712.82 mOhm / min 4.71 mOhm")
print("calculat:", res4)

print("=== P3 ===")
ops = [
    ("BEGIN","T1"),("BEGIN","T2"),
    ("SET","T1","A",10),
    ("SAVEPOINT","T1","sp1"),
    ("SET","T1","B",20),
    ("SET","T2","B",99),
    ("ROLLBACK_TO","T1","sp1"),
    ("SET","T1","B",30),
    ("SET","T2","A",88),
    ("COMMIT","T1"),
    ("GET","A"),("GET","B"),
]
got = run_tx_engine(ops)
exp = ["OK","OK","OK","OK","WAITING","OK","WAITING","DEADLOCK_ABORT","COMMITTED",10,30]
print("got:", got)
print("exp:", exp)
print("match:", got == exp)
