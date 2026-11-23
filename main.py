"""MEDiTIP standalone collection/editor MVP — runs locally without any AI API.
Examples:
  python main.py init
  python main.py seed-demo
  python main.py serve
  python main.py collect --source press --method rss --start 2026-11-16 --end 2026-11-22
"""
import argparse
import json
import sys
from pathlib import Path
import yaml
from meditip.db import connect,setup,ensure_edition,edition_rows,get_edition
from meditip.collect import source_specs,collect_source,import_snapshot,import_approval_csv
from meditip.edition import prepare,import_ai
from meditip.render import render
from meditip.server import serve

ROOT=Path(__file__).resolve().parent
DEFAULT_DB=ROOT/'data'/'newsletter.db'

def read_config():return yaml.safe_load((ROOT/'config'/'sources.yaml').read_text(encoding='utf8'))

def read_editorial():return yaml.safe_load((ROOT/'config'/'editorial.yaml').read_text(encoding='utf8'))

def main():
    p=argparse.ArgumentParser(description='MEDiTIP standalone newsletter MVP (never sends email)')
    p.add_argument('--db',default=str(DEFAULT_DB),help='SQLite path')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='Create local SQLite database')
    sub.add_parser('seed-demo',help='Import the provided 7-item historical fixture (not a live crawl)')
    edt=sub.add_parser('edition',help='Create a weekly/quarterly/custom edition')
    edt.add_argument('id');edt.add_argument('--start',required=True);edt.add_argument('--end',required=True);edt.add_argument('--title');edt.add_argument('--target',type=int,default=4)
    prep=sub.add_parser('prepare',help='Apply deterministic first-pass ranking and populate editor')
    prep.add_argument('id')
    collector=sub.add_parser('collect',help='Attempt permitted public RSS / list metadata crawl')
    collector.add_argument('--source',required=True,help='One source key in config/sources.yaml')
    collector.add_argument('--method',choices=['rss','board'],default='board')
    collector.add_argument('--start',required=True);collector.add_argument('--end',required=True)
    collector.add_argument('--max-pages',type=int,default=2)
    imp=sub.add_parser('import-json',help='Import JSON object with records[]; imported evidence not reverified')
    imp.add_argument('path');imp.add_argument('--source',default='provided_json')
    appr=sub.add_parser('import-approval-csv',help='Import manually exported approval CSV without claiming official API coverage')
    appr.add_argument('path');appr.add_argument('--kind',choices=['clinical','treatment','drug'],default='clinical')
    exp=sub.add_parser('export-html',help='Render actual 892-derived email template to a local file')
    exp.add_argument('id');exp.add_argument('--out')
    export_ai=sub.add_parser('export-ai',help='Export candidate items for external GPT analysis')
    export_ai.add_argument('id');export_ai.add_argument('--out')
    ai=sub.add_parser('import-ai',help='Import AI proposals; preserve human decisions')
    ai.add_argument('id');ai.add_argument('path')
    app=sub.add_parser('serve',help='Launch local-only editorial UI')
    app.add_argument('--edition',default='demo-2026-11-16-22');app.add_argument('--port',type=int,default=8765)
    args=p.parse_args()
    if args.command=='serve':
        with connect(args.db) as con:setup(con);get_edition(con,args.edition)
        return serve(args.db,ROOT/'templates'/'892_slots_original.html',ROOT/'editor.html',args.edition,args.port)
    with connect(args.db) as con:
        setup(con)
        if args.command=='init':print('SQLite initialized:',args.db)
        elif args.command=='seed-demo':
            fixture=json.loads((ROOT/'fixtures'/'mfds_2026-11-16_22_partial.json').read_text(encoding='utf8'))
            n=import_snapshot(con,fixture,'mfds_sample_2026w47')
            id='demo-2026-11-16-22'
            ensure_edition(con,id,'2026-11-16','2026-11-22','2026-11-16~22 2차 테스트 재현',4)
            m=prepare(con,id,read_editorial())
            print(f'Historical test fixture imported: {n} records / editor items: {m}; not live fetched')
            print('Run: python main.py serve')
        elif args.command=='edition':
            if args.start>args.end:raise ValueError('Start date must precede end date')
            if not 0<=args.target<=100:raise ValueError('target must be 0..100')
            ensure_edition(con,args.id,args.start,args.end,args.title,args.target)
            print('Created or found edition:',args.id)
        elif args.command=='prepare':print('Prepared edition:',args.id,'items',prepare(con,args.id,read_editorial()))
        elif args.command=='collect':
            if args.start>args.end:raise ValueError('Invalid date range')
            sources={s['key']:s for s in source_specs(read_config())}
            if args.source not in sources:raise ValueError('Unknown source key (see config/sources.yaml): '+args.source)
            spec=sources[args.source]
            if spec['group']=='industry' and args.method=='rss':raise ValueError('RSS endpoint for this media site is unverified')
            # Actual website conditions must be checked by the operator before live media crawling.
            print(json.dumps(collect_source(con,spec,args.start,args.end,args.method,args.max_pages),ensure_ascii=False,indent=2))
        elif args.command=='import-json':
            payload=json.loads(Path(args.path).read_text(encoding='utf8'))
            print('Imported',import_snapshot(con,payload,args.source),'records (original source not rechecked)')
        elif args.command=='import-approval-csv':
            print(json.dumps(import_approval_csv(con,args.path,args.kind),ensure_ascii=False,indent=2))
        elif args.command=='export-html':
            html=render(con,args.id,ROOT/'templates'/'892_slots_original.html')
            out=Path(args.out) if args.out else ROOT/'output'/f'newsletter_{args.id}.html'
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(html,encoding='utf8')
            print('Rendered draft:',out,'bytes:',len(html.encode('utf8')))
        elif args.command=='export-ai':
            e=get_edition(con,args.id);rows=edition_rows(con,args.id)
            payload={'schema_version':'meditip-ai-candidate-0.1','edition':e,
                     'instruction':'Return JSON items[] with id, section, summary, reason, recommended, score 0..100. Do not invent or overwrite source information.',
                     'items':[{'id':x['id'],'title':x['title'],'url':x['url'],'published_at':x['published_at'],
                               'source_key':x['source_key'],'section':x['section'],
                               'verification':x['verification'],'summary_source':x['summary_source']} for x in rows]}
            out=Path(args.out) if args.out else ROOT/'output'/f'candidates_{args.id}.json'
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8');print('AI input saved:',out)
        elif args.command=='import-ai':
            payload=json.loads(Path(args.path).read_text(encoding='utf8'))
            print('AI proposals imported:',import_ai(con,args.id,payload),'(no human override modified)')

if __name__=='__main__':
    try:main()
    except Exception as exc:print(f'ERROR: {exc}',file=sys.stderr);sys.exit(1)
