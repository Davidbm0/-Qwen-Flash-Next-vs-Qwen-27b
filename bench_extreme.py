# Bench "Extreme Suite" — Flash-Next (8080) vs Fable-27B (8083), 2 faze pe 5080.
# 2-phase run on one GPU:  python bench_extreme.py flash   apoi   python bench_extreme.py fable
#
# NOTE CRONOS (verificate cu implementare de referinta, extreme_ref.py):
#  - P1: assert-urile din suite sunt CORECTE (27 si 106, verificat cu Dijkstra pe state-space extins).
#  - P2: assert-urile suite-ului NU satisfac propriile formule: w=0.3547 mm -> Z0=53.2 Ohm, nu 50.
#        Referinta corecta pentru formulele date: w=0.3658 mm, w_mils=14.4017, eeff=3.2045, delay=5.9712 ps/mm.
#  - P3: assert corect sub semantica "SET in coada nu inregistreaza nimic cand e executat la deblocare"
#        (11 intrari pentru 12 ops). Deadlock: T2->T1->T2 cycle -> DEADLOCK_ABORT.
#  - P4: assert-urile suite-ului sunt fizic imposibile (min 4.71 mOhm sub ESR-ul de 5 mOhm al 10uF;
#        si 71.36 MHz nu e anti-rezonanta intre capurile date). Referinta din formulele date:
#        188.80 MHz / 2366.58 mOhm / min 5.00 mOhm.
#  - P5: documentul tau taie problema (fara asserturi) — exclusa din bench.

import json, re, subprocess, sys, time, urllib.request

SERVERS = {
    "flashnext": {"base": "http://127.0.0.1:8080/v1", "model": "qwen3.8-flash-next"},
    "fable27b":  {"base": "http://127.0.0.1:8083/v1", "model": "Qwen3.8-27B-UD-Q3_K_XL"},
}
TIMEBOX_CAP = 900          # secunde max per problema
MAX_ATTEMPTS = 4           # self-repair in buget

CODE_RULE = ("\n\nScrie o singura functie Python completa, doar cu standard library. "
             "Output: un singur bloc ```python ... ``` cu codul, fara explicatii.")

P1 = """Dat un graf orientat cu n noduri (0..n-1), fiecare muchie (u, v, weight, color).
Reguri de cost pentru un drum pornind din `start`:
1. Numarul de pas incepe de la 1 pentru prima muchie parcursa.
2. La pasi PAR (a 2-a, a 4-a muchie...), greutatea muchiei se inmulteste cu 2.
3. La pasi IMPAR (1, 3, 5...), greutatea normala (1x).
4. TURN PENALTY: daca parcurgi (u,v,w2,c2) imediat dupa (prev,u,w1,c1) si c1 != c2, platesti in plus abs(c1-c2)*3 (dupa inmultirea cu paritatea). Prima muchie nu are turn penalty.
5. CONSECUTIVE SAME-COLOR BAN: NU poti parcurge trei muchii la rand cu exact aceeasi culoare.
Scrie parity_turn_dijkstra(n: int, edges: list[tuple[int,int,int,int]], start: int, dst: int) -> int care intoarce costul minim start->dst sau -1 daca e unreachable.
Indicatie: simplul Dijkstra pe nod NU functioneaza — costul depinde de paritatea pasului, culoarea precedentului si numarul de muchii consecutive de aceeasi culoare.""" + CODE_RULE

P1_VERIFY = '''
assert parity_turn_dijkstra(5, [(0,1,5,1),(1,2,5,1),(2,3,5,1),(1,4,2,2),(4,2,2,2)], 0, 3) == 27
assert parity_turn_dijkstra(4, [(0,1,10,1),(1,2,100,1),(0,3,1,2),(3,1,1,1)], 0, 2) == 106
print("PASS")
'''

P2 = """Scrie solve_microstrip_width(z_target: float, h_mm: float, er: float, t_oz: float) -> dict folosind DOAR standard library (math).
Afla latimea fizica de urma w_mm care da impedanta caracteristica z_target pentru microstrip pe strat exterior, folosind exact ecuatia Hammerstad-Jensen cu corectia Wheeler pentru grosimea cuprului:
1. t_mm = t_oz * 0.034798
2. u = w/h_mm. Daca t_mm > 0:
   du1 = (t_mm/h_mm)/pi * ln(1 + (4e)/((t_mm/h_mm)*(1/tanh(sqrt(6.517*u)))^2))
   du_r = 0.5*du1*(1 + 1/cosh(sqrt(er-1)))
   u1 = u + du1, ur = u + du_r. Altfel u1 = ur = u.
3. a = 1 + (1/49)*ln((ur^4+(ur/52)^2)/(ur^4+0.432)) + (1/18.7)*ln(1+(ur/18.1)^3)
   b = 0.564*((er-0.9)/(er+3))^0.053
   eeff = (er+1)/2 + ((er-1)/2)*(1+10/ur)^(-a*b)
4. f(u) = 6 + (2*pi-6)*exp(-(30.666/u)^0.7528)
   Z0_freespace(u) = (376.730313668/(2*pi)) * ln(f(u)/u + sqrt(1+(2/u)^2))
   Z0(u) = Z0_freespace(ur)/sqrt(eeff)
Root-finding numeric (bisectie/Brent) pe w_mm in [0.01, 20.0], acuratete 1e-7.
Intoarce dict cu cheile rotunjite la 4 zecimale: 'w_mm', 'w_mils' (1 mm = 39.3700787 mils), 'eeff', 'delay_ps_per_mm' (ps per mm, c = 299792458 m/s).
Verificare: solve_microstrip_width(50.0, 0.2, 4.2, 1.0) trebuie dea w_mm≈0.3658, w_mils≈14.4017, eeff≈3.2045, delay_ps_per_mm≈5.9712.""" + CODE_RULE

P2_VERIFY = '''
r = solve_microstrip_width(50.0, 0.2, 4.2, 1.0)
assert abs(r['w_mm'] - 0.3658) < 0.002, r
assert abs(r['w_mils'] - 14.4017) < 0.08, r
assert abs(r['eeff'] - 3.2045) < 0.01, r
assert abs(r['delay_ps_per_mm'] - 5.9712) < 0.02, r
print("PASS")
'''

P3 = """Scrie run_tx_engine(ops: list[tuple]) -> list care simuleaza un store key-value transactional in memorie cu exclusive locks pessimiste si savepoints.
Operatii:
- ("BEGIN", tx_id): activeaza tranzactia. Inregistreaza "OK".
- ("SET", tx_id, key, val): cere lock exclusiv pe key.
  - Daca key e neincuiat sau deja incuiat de tx_id: scrie val (necomandat, in write-set-ul tranzactiei) si inregistreaza "OK".
  - Daca e incuiat de alta tranzactie activa tx_other: verifica daca adaugarea muchiei tx_id -> tx_other in Wait-For Graph creeaza ciclu.
    - DEADLOCK: aborteaza tx_id imediat (elibereaza toate lock-urile lui, arunca scrierile necomittate), deblocheaza in ordine FIFO tranzactiile care asteptau pe tx_id, inregistreaza "DEADLOCK_ABORT".
    - Altfel: tx_id intra in stare de asteptare, operatia e pusa in coada pe key, inregistreaza "WAITING". Cand lock-ul se elibereaza ulterior, operatia din coada se executa FARA a inregistra ceva in plus.
- ("SAVEPOINT", tx_id, sp_name): salveaza snapshot al scrierilor si lock-urilor curente. Inregistreaza "OK".
- ("ROLLBACK_TO", tx_id, sp_name): anuleaza scrierile facute dupa sp_name si elibereaza lock-urile dobandite dupa sp_name (deblocand coada FIFO). Inregistreaza "OK".
- ("COMMIT", tx_id): aplica scrierile in store-ul global, elibereaza toate lock-urile (deblocand coada FIFO). Inregistreaza "COMMITTED".
- ("GET", key): intoarce ultima valoare COMMITTED (sau None) si o inregistreaza in output.
Intoarce lista rezultatelor inregistrate, in ordinea operatiilor.
Semantica importanta: un SET care a inregistrat "WAITING" nu inregistreaza nimic cand e executat mai tarziu din coada.
Verificare: run_tx_engine([("BEGIN","T1"),("BEGIN","T2"),("SET","T1","A",10),("SAVEPOINT","T1","sp1"),("SET","T1","B",20),("SET","T2","B",99),("ROLLBACK_TO","T1","sp1"),("SET","T1","B",30),("SET","T2","A",88),("COMMIT","T1"),("GET","A"),("GET","B")]) == ["OK","OK","OK","OK","WAITING","OK","WAITING","DEADLOCK_ABORT","COMMITTED",10,30]""" + CODE_RULE

P3_VERIFY = '''
ops = [("BEGIN","T1"),("BEGIN","T2"),("SET","T1","A",10),("SAVEPOINT","T1","sp1"),
       ("SET","T1","B",20),("SET","T2","B",99),("ROLLBACK_TO","T1","sp1"),
       ("SET","T1","B",30),("SET","T2","A",88),("COMMIT","T1"),("GET","A"),("GET","B")]
got = run_tx_engine(ops)
assert got == ["OK","OK","OK","OK","WAITING","OK","WAITING","DEADLOCK_ABORT","COMMITTED",10,30], got
print("PASS")
'''

P4 = """Scrie analyze_pdn_impedance(caps: list[tuple[float,float,float]], f_start_hz: float, f_stop_hz: float, num_points: int) -> dict.
Fiecare condensator (C_farads, ESR_ohms, ESL_henries) e in paralel intre VDD si GND.
Frecvente logaritmic echidistante incluziv: f_k = f_start*(f_stop/f_start)^(k/(num_points-1)), k=0..num_points-1.
Admitanta totala: Y(w) = sum_i 1/(ESR_i + j*(w*ESL_i - 1/(w*C_i))), Z = 1/|Y|.
Identifica varfurile de anti-rezonanta (puncte strict interioare 0<k<num_points-1 cu |Z[k]| > |Z[k-1]| si |Z[k]| > |Z[k+1]|).
Intoarce dict cu cheile rotunjite la 2 zecimale: 'max_anti_res_freq_mhz' (frecventa in MHz a celui mai inalt varf de anti-rezonanta), 'max_anti_res_z_mohm' (magnitudinea impedantei in milliohmi la acel varf), 'min_z_mohm' (minimul global al impedantei in milliohmi pe sweep).
Verificare: analyze_pdn_impedance([(10e-6,0.005,800e-12),(100e-9,0.015,500e-12),(1e-9,0.050,400e-12)], 1e5, 1e9, 4001) trebuie dea max_anti_res_freq_mhz≈188.80, max_anti_res_z_mohm≈2366.58, min_z_mohm≈5.00.""" + CODE_RULE

P4_VERIFY = '''
r = analyze_pdn_impedance([(10e-6,0.005,800e-12),(100e-9,0.015,500e-12),(1e-9,0.050,400e-12)], 1e5, 1e9, 4001)
assert abs(r['max_anti_res_freq_mhz'] - 188.80) < 1.5, r
assert abs(r['max_anti_res_z_mohm'] - 2366.58) < 150.0, r
assert abs(r['min_z_mohm'] - 5.00) < 0.15, r
print("PASS")
'''

PROBLEMS = [
    ("p1_dijkstra", P1, P1_VERIFY),
    ("p2_microstrip", P2, P2_VERIFY),
    ("p3_txengine", P3, P3_VERIFY),
    ("p4_pdn", P4, P4_VERIFY),
]

def ask(server, prompt, max_tokens=8000):
    body = json.dumps({
        "model": server["model"], "max_tokens": max_tokens, "temperature": 0.3,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(server["base"] + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as resp:
        d = json.loads(resp.read())
    msg = d["choices"][0]["message"]
    text = (msg.get("content") or "") + "\n" + (msg.get("reasoning_content") or "")
    return text, time.time() - t0

def extract_blocks(text):
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S)
    return blocks if blocks else [text]

def verify(code, verifier):
    src = code + "\n\n" + verifier
    with open("_attempt.py", "w", encoding="utf-8") as f:
        f.write(src)
    try:
        p = subprocess.run([sys.executable, "_attempt.py"], capture_output=True, timeout=120)
        ok = p.returncode == 0 and b"PASS" in p.stdout
        err = "" if ok else p.stderr.decode(errors="replace")[-300:]
        return ok, err
    except subprocess.TimeoutExpired:
        return False, "exec timeout (120s)"

def preflight(arm):
    srv = SERVERS[arm]
    try:
        urllib.request.urlopen(srv["base"].replace("/v1", "") + "/health", timeout=10).read()
    except Exception as e:
        print(f"PREFLIGHT ESUAT: {arm} ({srv['base']}) nu raspunde: {e}")
        print("Nu masuram nimic — porneste serverul si reia.")
        return False
    return True

def run_phase(arm, budget_file=None):
    if not preflight(arm):
        return
    saved = {}
    if budget_file:
        try:
            rows = json.load(open(budget_file))
            saved = {r["id"]: r["flashnext"]["t"] for r in rows
                     if r.get("flashnext", {}).get("t", 0) > 5}
        except Exception:
            print(f"Nu gasesc {budget_file} — rulez cu bugetul fix {TIMEBOX_CAP}")
    results = []
    for pid, prompt0, verifier in PROBLEMS:
        row = {"id": pid}
        srv = SERVERS[arm]
        budget = min(saved.get(pid, TIMEBOX_CAP) if budget_file else TIMEBOX_CAP, TIMEBOX_CAP)
        t_total, ok, attempts, last_err = 0.0, False, 0, ""
        t_start = time.time()
        cur_prompt = prompt0
        while attempts < MAX_ATTEMPTS and time.time() - t_start < budget:
            attempts += 1
            try:
                ans, dt = ask(srv, cur_prompt)
                t_total += dt
                for block in extract_blocks(ans):
                    ok, last_err = verify(block, verifier)
                    if ok:
                        break
                if ok:
                    break
                cur_prompt = prompt0 + f"\n\n(Codul anterior a ESUAT la verificare: {last_err[:400]} Reia si corecteaza.)"
            except Exception as e:
                t_total = time.time() - t_start
                row["err"] = str(e)[:80]
                break
        row[arm] = {"ok": ok, "t": round(t_total, 1), "attempts": attempts}
        results.append(row)
        print(json.dumps(row), flush=True)
    n_ok = sum(1 for r in results if r[arm]["ok"])
    print(f"\n=== {arm}: {n_ok}/{len(PROBLEMS)} in {sum(r[arm]['t'] for r in results):.0f}s ===")
    out = "extreme_flash.json" if arm == "flashnext" else "extreme_fable.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Salvat: {out}")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "flash":
        run_phase("flashnext")
    elif mode == "fable":
        run_phase("fable27b", budget_file="extreme_flash.json")
    else:
        print("Folosire (2 faze, pe rand pe 5080):")
        print("  1) python bench_extreme.py flash   (Fable NU trebuie sa fie pornit)")
        print("  2) swap: Cronos descarca Flash + porneste Fable pe 8083, apoi python bench_extreme.py fable")
