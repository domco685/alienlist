#!/usr/bin/env python3
"""Download all PDF/image/thumb files from the war.gov UAP catalog into assets/."""
import json, os, subprocess, concurrent.futures, time, random, urllib.parse, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')
PDFS = os.path.join(ASSETS, 'pdf')
THUMBS = os.path.join(ASSETS, 'thumb')
LOG = os.path.join(ROOT, 'download.log')
os.makedirs(PDFS, exist_ok=True)
os.makedirs(THUMBS, exist_ok=True)

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'

def safe_name(url):
    # Use the last path segment, decode percents, replace separators.
    name = urllib.parse.unquote(url.split('/')[-1])
    return name

def encoded_url(url):
    # Re-encode the path component (handles spaces, brackets, special chars)
    p = urllib.parse.urlsplit(url)
    path = '/'.join(urllib.parse.quote(seg, safe='') for seg in p.path.split('/'))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, p.query, p.fragment))

def download(url, dest_dir, retries=4):
    name = safe_name(url)
    # Avoid filesystem issues with brackets/spaces
    name = name.replace(' ', '_').replace('[','').replace(']','')
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return ('skip', url, dest, os.path.getsize(dest))
    fetch_url = encoded_url(url)
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(0.05, 0.4))
            r = subprocess.run(
                ['curl','-sSL','--http2','--retry','2','--max-time','600',
                 '-A', UA,
                 '-H','Accept: application/pdf,image/*,*/*',
                 '-H','Accept-Language: en-US,en;q=0.9',
                 '-H','Sec-Fetch-Dest: document',
                 '-H','Sec-Fetch-Mode: navigate',
                 '-H','Sec-Fetch-Site: none',
                 '-H','Sec-Fetch-User: ?1',
                 '-H','Upgrade-Insecure-Requests: 1',
                 '-H','Referer: https://www.war.gov/UFO/',
                 '-w','%{http_code}',
                 '-o', dest,
                 fetch_url],
                capture_output=True, text=True, timeout=620
            )
            code = r.stdout.strip().splitlines()[-1] if r.stdout else ''
            if code == '200' and os.path.exists(dest) and os.path.getsize(dest) > 1000:
                return ('ok', url, dest, os.path.getsize(dest))
            # backoff on rate-limit
            time.sleep(2 + attempt*1.5 + random.random())
        except Exception as e:
            time.sleep(1 + attempt)
    if os.path.exists(dest):
        try: os.remove(dest)
        except: pass
    return ('fail', url, dest, code if 'code' in dir() else 'ERR')

def main():
    urls = [u.strip() for u in open(os.path.join(ROOT,'urls.txt')) if u.strip()]
    thumbs = [u.strip() for u in open(os.path.join(ROOT,'thumbs.txt')) if u.strip()]
    jobs = [(u, PDFS) for u in urls] + [(u, THUMBS) for u in thumbs]
    print(f'jobs: {len(jobs)} ({len(urls)} files + {len(thumbs)} thumbs)')
    start = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(download, u, d) for u,d in jobs]
        done_count = 0
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            results.append(r)
            done_count += 1
            status, url, dest, info = r
            if done_count % 10 == 0 or status == 'fail':
                elapsed = time.time()-start
                ok = sum(1 for x in results if x[0] in ('ok','skip'))
                fail = sum(1 for x in results if x[0]=='fail')
                print(f'[{done_count}/{len(jobs)}] elapsed={elapsed:.0f}s ok={ok} fail={fail} last={status} {os.path.basename(dest)}', flush=True)
    elapsed = time.time()-start
    ok = [r for r in results if r[0] in ('ok','skip')]
    fail = [r for r in results if r[0]=='fail']
    print(f'\nDONE in {elapsed:.0f}s: {len(ok)}/{len(jobs)} ok, {len(fail)} failed')
    with open(LOG, 'w') as o:
        for s,u,d,i in results:
            o.write(f'{s}\t{i}\t{u}\t{d}\n')
    if fail:
        print('\nFAILURES:')
        for s,u,d,i in fail[:20]:
            print(f'  [{i}] {u}')

if __name__ == '__main__':
    main()
