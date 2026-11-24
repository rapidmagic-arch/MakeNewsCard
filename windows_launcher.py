"""Double-click entry point for packaged Windows users; no installed Python required."""
import argparse
from datetime import date, timedelta
import sys
import threading
import time
from pathlib import Path
import urllib.request
import webbrowser
from meditip.app_config import load_project_env
from meditip.db import connect,setup,ensure_edition
from meditip.server import serve

ROOT=Path(__file__).resolve().parent

def portable_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else ROOT

def launch_browser(port):
    url=f'http://127.0.0.1:{port}/'
    for _ in range(80):
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200:
                    webbrowser.open(url)
                    return
        except OSError:time.sleep(.25)

def main():
    parser=argparse.ArgumentParser(description='MakeNewsCard local newsletter editor')
    parser.add_argument('--data-dir',type=Path,default=portable_root())
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    home=args.data_dir.resolve()
    home.mkdir(parents=True,exist_ok=True)
    load_project_env(home)
    db=home/'data'/'newsletter.db'
    with connect(db) as con:
        setup(con)
        row=con.execute("SELECT id FROM editions ORDER BY (status='draft') DESC,created_at DESC,id DESC LIMIT 1").fetchone()
        if row:
            eid=row['id']
        else:
            today=date.today()
            end=today-timedelta(days=today.weekday()+1)
            start=end-timedelta(days=6)
            eid='edition-'+start.isoformat()+'-'+end.isoformat()
            ensure_edition(con,eid,start.isoformat(),end.isoformat())
    print('Local data:',db,flush=True)
    if not args.no_browser:
        threading.Thread(target=launch_browser,args=(args.port,),daemon=True).start()
    serve(db,ROOT/'templates'/'892_slots_original.html',ROOT/'editor.html',eid,args.port)

if __name__=='__main__':
    main()
