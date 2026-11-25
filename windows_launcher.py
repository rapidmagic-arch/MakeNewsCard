"""Double-click entry point for packaged Windows users; no installed Python required."""
import argparse
import os
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
from meditip.lifecycle import DesktopLifecycle
from meditip.managed_files import ManagedFiles

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

def show_message(message,title='MakeNewsCard',error=False):
    if os.name=='nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,message,title,0x10 if error else 0x40)
    elif sys.stderr is not None:
        print(message,file=sys.stderr)

def run_tray(lifecycle,home,port,open_browser=True):
    import pystray
    from PIL import Image,ImageDraw
    image=Image.new('RGBA',(64,64),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((3,3,61,61),radius=12,fill='#185e96')
    draw.rectangle((15,13,49,51),fill='white')
    for y in (23,31,39):draw.line((21,y,43,y),fill='#185e96',width=3)

    def open_editor(icon,item):
        webbrowser.open(f'http://127.0.0.1:{port}/')

    def open_files(icon,item):
        try:ManagedFiles(home).open_folder()
        except (OSError,ValueError):show_message('관리 폴더를 열 수 없습니다. 환경설정에서 경로를 확인하세요.',error=True)

    def exit_app(icon,item):
        if not lifecycle.request_stop():
            show_message('수집·GPT 분석 또는 요청 처리 중입니다. 작업 완료 후 다시 종료하세요.')

    icon=pystray.Icon('MakeNewsCard',image,'MakeNewsCard · 로컬 서버 실행 중',
                     menu=pystray.Menu(pystray.MenuItem('편집 화면 열기',open_editor,default=True),
                                       pystray.MenuItem('관리 폴더 열기',open_files),
                                       pystray.Menu.SEPARATOR,
                                       pystray.MenuItem('프로그램 종료',exit_app)))
    def monitor():
        lifecycle.finished.wait()
        icon.stop()

    def setup(tray):
        try:
            tray.visible=True
        except Exception:
            show_message('트레이 아이콘을 표시할 수 없어 프로그램을 종료합니다.',error=True)
            while not lifecycle.finished.is_set() and not lifecycle.request_stop():time.sleep(.2)
        threading.Thread(target=monitor,daemon=True).start()
        if open_browser and tray.visible and not lifecycle.finished.is_set():
            threading.Thread(target=launch_browser,args=(port,),daemon=True).start()
    icon.run(setup=setup)

def main():
    parser=argparse.ArgumentParser(description='MakeNewsCard local newsletter editor')
    parser.add_argument('--data-dir',type=Path,default=portable_root())
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--no-tray',action='store_true',help='Headless local server for development and automated checks')
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
    lifecycle=DesktopLifecycle()
    def worker():
        try:serve(db,ROOT/'templates'/'892_slots_original.html',ROOT/'editor.html',eid,args.port,workspace=home,lifecycle=lifecycle)
        except Exception as exc:lifecycle.complete(exc)
        else:lifecycle.complete()
    thread=threading.Thread(target=worker,name='local-http-server')
    thread.start()
    lifecycle.ready.wait()
    if lifecycle.error is not None:
        thread.join()
        raise RuntimeError('로컬 서버 시작 실패: '+str(lifecycle.error))
    try:
        if args.no_tray or os.name!='nt':
            if not args.no_browser:threading.Thread(target=launch_browser,args=(args.port,),daemon=True).start()
            lifecycle.finished.wait()
        else:
            run_tray(lifecycle,home,args.port,open_browser=not args.no_browser)
    finally:
        # If the tray loop stops unexpectedly, finish pending work before closing the server.
        while not lifecycle.finished.is_set() and not lifecycle.request_stop():
            lifecycle.finished.wait(.2)
        thread.join()
    if lifecycle.error is not None:raise RuntimeError('로컬 서버 오류: '+str(lifecycle.error))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        show_message(str(exc),error=True)
        sys.exit(1)
