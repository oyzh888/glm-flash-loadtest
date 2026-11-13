#!/usr/bin/env python3
"""bench_lock.py: hold the endpoint's test lock while a benchmark runs, so only one benchmark runs at a time.

  python3 bench_lock.py run --owner "acme-perf" --purpose "c1-c64 sweep" -- bash run_agent_c64.sh
  python3 bench_lock.py status

`run` takes the lock (waits in line if someone else holds it), exports the lease as $BENCH_LEASE for the command,
renews it in the background, and releases it when the command exits (also on Ctrl-C). If the lease is lost the
command is stopped, because its numbers would no longer be clean. Endpoints without a test lock (HTTP 404) are used
as is. Standard library only.
"""
import argparse, json, os, signal, subprocess, sys, threading, time, urllib.error, urllib.request

def call(url, path, body=None):
    req = urllib.request.Request(url.rstrip('/') + path, json.dumps(body).encode() if body is not None else None,
                                 {'Content-Type': 'application/json', 'User-Agent': 'bench-lock/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b'{}')
        except ValueError: return e.code, {}

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['run', 'status'])
    ap.add_argument('--url', default=os.environ.get('URL', 'https://glm-flash.aitist.ai'))
    ap.add_argument('--owner', default=os.environ.get('BENCH_OWNER', ''), help='who is testing (required for run; or $BENCH_OWNER)')
    ap.add_argument('--purpose', default=os.environ.get('BENCH_PURPOSE', ''))
    ap.add_argument('--duration', type=float, default=float(os.environ.get('BENCH_DURATION_S', 7200)), help='seconds to reserve (server caps it)')
    ap.add_argument('--wait', type=float, default=float(os.environ.get('BENCH_WAIT_S', 3600)), help='seconds to wait for the lock before giving up')
    argv = sys.argv[1:]; cmd = []
    if '--' in argv: i = argv.index('--'); argv, cmd = argv[:i], argv[i + 1:]
    A = ap.parse_args(argv)
    if A.cmd == 'status':
        s, j = call(A.url, '/api/bench/status'); print(json.dumps(j, indent=1, ensure_ascii=False)); return 0 if s == 200 else 1
    if not cmd: ap.error('run needs a command after --')
    if not A.owner: ap.error('--owner (or $BENCH_OWNER) is required: say who is testing')
    t_end = time.time() + A.wait; lease = None
    while True:
        s, j = call(A.url, '/api/bench/lock', {'owner': A.owner, 'purpose': A.purpose, 'duration_s': A.duration})
        if s == 200: lease = j['lease']; break
        if s == 404 and not j.get('held'):
            print('[bench-lock] this endpoint has no test lock; running without one', file=sys.stderr); break
        if s == 409 and time.time() < t_end:
            print(f"[bench-lock] lock held by {j.get('owner')!r} ({j.get('purpose')}) until about {j.get('expires')}; waiting...", file=sys.stderr)
            time.sleep(30); continue
        print(f'[bench-lock] could not take the lock: HTTP {s} {j}', file=sys.stderr); return 2
    env = dict(os.environ)
    if lease:
        env['BENCH_LEASE'] = lease
        print(f"[bench-lock] lock taken: lease {j.get('lease_id')}, owner {A.owner!r}, hard end {j.get('hard_end')}", file=sys.stderr)
    child = subprocess.Popen(cmd, env=env)
    lost = threading.Event()
    def renew():
        every = max(30, int(j.get('renew_every_s', 200))) if lease else 0
        while lease and child.poll() is None:
            time.sleep(every)
            if child.poll() is not None: break
            s2, j2 = call(A.url, '/api/bench/renew', {'lease': lease})
            if s2 != 200:
                print(f'[bench-lock] lease lost ({s2} {j2.get("error")}); stopping the benchmark, its numbers would not be clean', file=sys.stderr)
                lost.set(); child.terminate(); break
    threading.Thread(target=renew, daemon=True).start()
    def stop(sig, _):
        child.send_signal(sig)
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    rc = child.wait()
    if lease and not lost.is_set():
        s, r = call(A.url, '/api/bench/release', {'lease': lease})
        print(f"[bench-lock] released ({r.get('requests')} requests under the lease)" if s == 200 else f'[bench-lock] release: HTTP {s} {r}', file=sys.stderr)
    return 3 if lost.is_set() else rc

if __name__ == '__main__':
    sys.exit(main())
