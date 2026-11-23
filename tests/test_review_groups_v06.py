"""User-defined suggestion groups preserve source data and human review decisions."""
from meditip.db import connect, setup, ensure_edition, save_item, edition_rows
from meditip.edition import prepare
from meditip.review_groups import init_groups, list_groups, save_group, delete_group, with_groups

DEFAULTS={'industry.policy':['약가'],'industry.market':['시장'],'industry.global':['FDA'],'industry.rnd':['신약']}


def test_groups_crud_and_delete_last_does_not_reseed(tmp_path):
    with connect(tmp_path/'groups.db') as con:
        setup(con);init_groups(con,DEFAULTS)
        assert len(list_groups(con))==4
        gid=save_group(con,{'label':'보험·약가','target_section':'industry.policy','keywords':['보험급여','약가'], 'recommend':True})
        assert any(x['id']==gid for x in list_groups(con))
        save_group(con,{'id':gid,'label':'보험·약가','target_section':'industry.market','keywords':['보험급여'], 'recommend':False})
        assert [x for x in list_groups(con) if x['id']==gid][0]['recommend'] is False
        for group in list_groups(con):delete_group(con,group['id'])
        init_groups(con,DEFAULTS)
        assert list_groups(con)==[]


def test_group_reclassification_does_not_overwrite_editorial_decision(tmp_path):
    with connect(tmp_path/'groups.db') as con:
        setup(con);init_groups(con,DEFAULTS)
        ensure_edition(con,'issue','2026-11-16','2026-11-22')
        iid=save_item(con,{'source_key':'dailypharm','source_group':'industry','section':'industry.unclassified',
                            'title':'보험급여 신청 관련 법령', 'published_at':'2026-11-19',
                            'url':'https://www.dailypharm.com/user/news/60099'})
        con.commit()
        gid=save_group(con,{'label':'보험급여','target_section':'industry.policy','keywords':['보험급여'], 'recommend':True})
        prepare(con,'issue',with_groups(con,{}));row=edition_rows(con,'issue')[0]
        assert row['rule_group_id']==gid and row['rule_recommended']==1
        assert row['include_detail']==0
        con.execute('UPDATE decisions SET include_detail=1,detail_reviewed=1,section_override=?,section_reviewed=1 WHERE edition_id=? AND item_id=?',('industry.global','issue',iid));con.commit()
        save_group(con,{'id':gid,'label':'보험급여','target_section':'industry.market','keywords':['보험급여'], 'recommend':False})
        prepare(con,'issue',with_groups(con,{}));row=edition_rows(con,'issue')[0]
        assert row['rule_group_id']==gid and row['rule_recommended']==0
        assert row['rule_section']=='industry.market'
        assert row['include_detail']==1 and row['section_override']=='industry.global'
        assert con.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1


def test_market_signal_beats_glp1_rnd_keyword(tmp_path):
    with connect(tmp_path/'groups.db') as con:
        setup(con);init_groups(con,{'industry.market':['시장'],'industry.rnd':['GLP-1']})
        ensure_edition(con,'issue','2026-11-16','2026-11-22')
        save_item(con,{'source_key':'dailypharm','source_group':'industry','section':'industry.unclassified',
                        'title':'GLP-1 치료제 시장 동향', 'published_at':'2026-11-17',
                        'url':'https://www.dailypharm.com/user/news/60100'})
        con.commit();prepare(con,'issue',with_groups(con,{}))
        row=edition_rows(con,'issue')[0]
        assert row['rule_section']=='industry.market'


def test_explicit_custom_group_beats_generic_default_group(tmp_path):
    with connect(tmp_path/'groups.db') as con:
        setup(con);init_groups(con,{'industry.policy':['법령']})
        ensure_edition(con,'issue','2026-11-16','2026-11-22')
        gid=save_group(con,{'label':'보험급여','target_section':'industry.market',
                            'keywords':['보험급여'],'recommend':True})
        save_item(con,{'source_key':'dailypharm','source_group':'industry',
                       'section':'industry.unclassified','title':'보험급여 신청 관련 법령 변경',
                       'published_at':'2026-11-17','url':'https://www.dailypharm.com/user/news/90000'})
        con.commit();prepare(con,'issue',with_groups(con,{}))
        row=edition_rows(con,'issue')[0]
        assert row['rule_group_id']==gid and row['rule_section']=='industry.market'
