
'use strict';const TOKEN=document.querySelector('meta[name="local-token"]').content;let db=null;let reviewGroups=[],editingReviewGroupId=null;let queueKind="recommended", detailItemId=null, detailDirty=false, aiReady=false;const selectedIds=new Set();const $=id=>document.getElementById(id);const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sec=['mfds.guides','mfds.regulations','mfds.press','mfds.notices','industry.policy','industry.market','industry.global','industry.rnd','industry.unclassified','company.news','clinical.approval','clinical.treatment','drug.approvals'];
const sectionLabel={'mfds.guides':'식약처 지침·안내서','mfds.regulations':'식약처 고시·법령','mfds.press':'식약처 보도자료','mfds.notices':'식약처 공지·공고','industry.policy':'정책','industry.market':'시장','industry.global':'글로벌','industry.rnd':'연구개발','industry.unclassified':'미분류','company.news':'회사 소식','clinical.approval':'임상시험 승인','clinical.treatment':'치료목적 사용승인','drug.approvals':'의약품 허가'};
const sourceLabel={'guides_staff':'공무원지침서','guides_citizen':'민원인안내서','preannouncements':'입법·행정예고','enacted_notices':'제·개정고시','laws':'법령','press':'보도자료','notice':'공지','announcement':'공고','dailypharm':'데일리팜','medisobizanews':'메디소비자뉴스','medicaltimes':'메디칼타임즈','kpanews':'약사공론','yakup':'약업신문','company_manual':'메디팁 등록 자료','official_csv_clinical':'임상시험 CSV','official_csv_treatment':'치료목적 CSV','official_csv_drug':'품목허가 CSV','official_live_clinical':'임상시험 공식 조회','official_live_treatment':'치료목적 공식 조회','official_live_drug':'품목허가 공식 조회'};
let pageIndex=0,cardIndex=0,cardMode=false,libraryPageNumber=1;let publicationDirty=false,lastApprovalMarker='';const PAGE_SIZE=12;const LIBRARY_PAGE_SIZE=12;
async function fileBase64(file){const bytes=new Uint8Array(await file.arrayBuffer());let raw='';for(let i=0;i<bytes.length;i+=16384)raw+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(raw)}
function fileDropStatus(input,message,error=false){const zone=input.closest('[data-drop-input]');if(!zone)return;const status=zone.querySelector('.drop-filename');status.textContent=message;zone.classList.toggle('file-error',error);zone.classList.toggle('has-file',!!input.files.length&&!error);}
function fileError(input,file){if(!file)return '파일을 선택하세요.';const name=file.name.toLowerCase();const isCsv=input.id==='approvalFile',isJson=input.id==='aiJsonFile';const valid=isCsv?name.endsWith('.csv'):isJson?name.endsWith('.json'):['image/png','image/jpeg'].includes(file.type)||/\.(png|jpe?g)$/.test(name);const limit=isCsv?2500000:1000000;return !valid?'지원하지 않는 파일 형식입니다.':file.size<1||file.size>limit?'허용 파일 크기를 확인하세요.':''}
function clearDrop(id){const input=$(id);input.value='';const zone=input.closest('[data-drop-input]');fileDropStatus(input,zone?.dataset.emptyLabel||'파일 미선택')}
for(const zone of document.querySelectorAll('[data-drop-input]')){
 const input=$(zone.dataset.dropInput);zone.dataset.emptyLabel=zone.querySelector('.drop-filename').textContent;
 input.addEventListener('change',()=>{const file=input.files[0];if(!file){clearDrop(input.id);return}const err=fileError(input,file);if(err){input.value='';fileDropStatus(input,err,true);return}fileDropStatus(input,file.name+' · '+Math.max(1,Math.round(file.size/1024))+'KB')});
 zone.addEventListener('dragover',e=>{e.preventDefault();if(!input.disabled)zone.classList.add('is-dragover');e.dataTransfer.dropEffect=input.disabled?'none':'copy'});
 zone.addEventListener('dragleave',()=>zone.classList.remove('is-dragover'));
 zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('is-dragover');if(input.disabled)return;const files=e.dataTransfer.files;if(files.length!==1){fileDropStatus(input,'한 개의 파일만 등록하세요.',true);return}const err=fileError(input,files[0]);if(err){fileDropStatus(input,err,true);return}const transfer=new DataTransfer();transfer.items.add(files[0]);input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}))});
}
for(const id of ['issueNumber','publicationDate'])$(id).addEventListener('input',()=>{publicationDirty=true});
async function api(path,payload){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':TOKEN},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok)throw Error(j.error||'저장 실패');return j}
async function load(){const r=await fetch('/api/edition');if(!r.ok)throw Error('회차 정보를 읽을 수 없어');db=await r.json();render();setEditionFields();await loadEditionPicker()}
async function loadEditionPicker(){const r=await fetch('/api/editions');if(!r.ok)return;const x=await r.json();
 $('editionPicker').innerHTML=x.editions.map(e=>'<option value="'+esc(e.id)+'" '+(e.id===x.active?'selected':'')+'>'+esc((e.issue_number?'제'+e.issue_number+'호 · ':'')+e.title+' · '+(e.status==='confirmed'?'확정':'초안'))+'</option>').join('')}

async function loadLibrary(){
 const q=$('librarySearch').value.trim(),status=$('libraryStatus').value;
 $('libraryMessage').textContent='보관함 조회 중';
 try{
  const params=new URLSearchParams({status,q,page:String(libraryPageNumber)});
  const res=await fetch('/api/library?'+params.toString());const data=await res.json();
  if(!res.ok)throw Error(data.error||'도서관을 불러올 수 없어');
  $('libraryMessage').textContent=data.total+'개 회차 · '+(status==='confirmed'?'확정본':status==='draft'?'초안':'전체');
  $('libraryPageInfo').textContent=data.page+' / '+data.pages+' 페이지';
  $('libraryPrev').disabled=data.page<=1;$('libraryNext').disabled=data.page>=data.pages;
  $('libraryGrid').innerHTML=data.items.map(e=>{
   const badge=e.status==='confirmed'?'확정본':'작업 중';
   const caption=e.issue_number?'제'+esc(e.issue_number)+'호':esc(e.title);
   const htmlUrl='/api/library/html?edition_id='+encodeURIComponent(e.id);
   const open=e.status==='confirmed'?'<a class="button primary" target="_blank" rel="noopener noreferrer" href="'+htmlUrl+'">확정본 보기</a><a class="button" href="'+htmlUrl+'&download=1">HTML 받기</a>':
       '<button type="button" data-resume-edition="'+esc(e.id)+'">이어서 편집</button>';
   return '<article class="library-card"><div class="library-cover"><span class="library-icon">▤</span><strong>'+caption+'</strong><small>'+esc(badge)+'</small></div>'+
    '<div class="library-card-info"><h4>'+esc(e.title)+'</h4>'+
    ''+
    '<div class="actions">'+open+'</div></div></article>';
  }).join('')||'<p class="muted library-empty">해당 조건의 뉴스레터가 없어.</p>';
 }catch(err){$('libraryMessage').textContent='도서관 조회 오류: '+err.message;$('libraryGrid').innerHTML=''}
}
async function switchToEdition(id){
 if(!id||!db||id===db.edition.id)return true;
 if(detailDirty&&!confirm('저장하지 않은 기사 편집이 있어. 회차를 변경할까?'))return false;
 await api('/api/edition/select',{edition_id:id});
 detailDirty=false;detailItemId=null;selectedIds.clear();pageIndex=0;cardIndex=0;publicationDirty=false;lastApprovalMarker='';clearDrop('approvalFile');clearDrop('aiJsonFile');$('approvalStatus').textContent='';
 $('colStart').value='';$('colEnd').value='';await load();refreshPreview();return true;
}
$('librarySearchButton').addEventListener('click',()=>{libraryPageNumber=1;loadLibrary()});
$('librarySearch').addEventListener('keydown',e=>{if(e.key==='Enter'){libraryPageNumber=1;loadLibrary()}});
$('libraryStatus').addEventListener('change',()=>{libraryPageNumber=1;loadLibrary()});
$('libraryPrev').addEventListener('click',()=>{if(libraryPageNumber>1){libraryPageNumber--;loadLibrary()}});
$('libraryNext').addEventListener('click',()=>{libraryPageNumber++;loadLibrary()});
$('libraryGrid').addEventListener('click',async e=>{const btn=e.target.closest('[data-resume-edition]');if(!btn)return;
 try{if(await switchToEdition(btn.dataset.resumeEdition))openView('edit')}catch(err){$('libraryMessage').textContent=err.message}});
$('openEditionDialog').addEventListener('click',()=>{$('editionDialog').showModal()});
$('closeEditionDialog').addEventListener('click',()=>{$('editionDialog').close()});
$('applyEditionSwitch').addEventListener('click',async()=>{
 try{if(await switchToEdition($('editionPicker').value)){$('editionDialog').close();loadLibrary()}}catch(err){alert(err.message)}
});

let collectionRunning=false, collectionWasActive=false, pollBusy=false, collectionError='', collectionSubmitting=false;
let sourceCatalog=new Map();
function setEditionFields(){
 if(!publicationDirty){$('publicationDate').value=db.edition.publication_date||'';$('issueNumber').value=db.edition.issue_number||'';}
 const start=db.edition.period_start,end=db.edition.period_end;$('approvalRange').textContent=start+' ~ '+end;
 for(const [kind,id] of [['clinical','approvalClinicalLink'],['treatment','approvalTreatmentLink'],['drug','approvalDrugLink']]){const url=db.approval_links?.[kind];if(url)$(id).href=url;}
 $('activeEdition').textContent='현재 회차: '+db.edition.title+' ('+db.edition.period_start+' ~ '+db.edition.period_end+')';
 updateDashboard();
 // Preserve dates entered by the operator except on first load or edition switch.
 if(!$('colStart').value)$('colStart').value=db.edition.period_start;
 if(!$('colEnd').value)$('colEnd').value=db.edition.period_end;
}
async function loadSources(){
 const r=await fetch('/api/sources');if(!r.ok)throw Error('수집 사이트 설정 오류');
 const {sources}=await r.json();
 let saved=null;try{saved=JSON.parse(localStorage.getItem('meditip.source-selection.v1')||'null')}catch(e){};const remember=saved?.remember!==false;$('rememberSources').checked=remember;const remembered=remember&&Array.isArray(saved?.keys)?new Set(saved.keys):null;
 sourceCatalog=new Map(sources.map(x=>[x.key,x]));
 $('sourceList').innerHTML=sources.map(x=>'<label><input type="checkbox" data-source="'+esc(x.key)+'" '+((remembered?remembered.has(x.key):x.key==='press')?'checked':'')+'> '+esc((x.group==='mfds'?'식약처 · ':'언론 · ')+(sourceLabel[x.key]||x.key))+'</label>').join('');
 updateSourceToggles();
}
function rememberSourceSelection(){try{localStorage.setItem('meditip.source-selection.v1',JSON.stringify({remember:$('rememberSources').checked,keys:$('rememberSources').checked?collectSelected():[]}))}catch(e){}}
$('rememberSources').addEventListener('change',rememberSourceSelection);
function collectSelected(){return [...document.querySelectorAll('[data-source]:checked')].map(x=>x.dataset.source)}
function sourceBoxes(group){return [...document.querySelectorAll('#sourceList [data-source]')].filter(x=>sourceCatalog.get(x.dataset.source)?.group===group)}
function updateSourceToggles(){
 for(const [group,id,label] of [['mfds','toggleMFDS','식약처'],['industry','toggleMedia','언론']]){
  const boxes=sourceBoxes(group),selected=boxes.filter(x=>x.checked).length,all=boxes.length>0&&selected===boxes.length;
  const b=$(id);b.textContent=label+(all?' 선택 해제':' 전체 선택')+' ('+selected+'/'+boxes.length+')';
  b.setAttribute('aria-pressed',String(all));b.disabled=boxes.length===0||collectionRunning;
 }
}
function toggleSourceGroup(group){const boxes=sourceBoxes(group),all=boxes.length>0&&boxes.every(x=>x.checked);
 boxes.forEach(x=>x.checked=!all);updateSourceToggles();rememberSourceSelection();}
$('sourceList').addEventListener('change',e=>{if(e.target.matches('[data-source]')){updateSourceToggles();rememberSourceSelection()}});
$('toggleMFDS').addEventListener('click',()=>toggleSourceGroup('mfds'));
$('toggleMedia').addEventListener('click',()=>toggleSourceGroup('industry'));
function collectError(message){
 collectionError=message;
 $('collectionState').textContent='수집 요청 확인 필요';
 $('collectionResults').hidden=false;
 $('collectionResults').innerHTML='<p class="error" role="alert">'+esc(message)+'</p>';
}
function collectInputError(keys,start,end,mode,maxPages){
 if(!keys.length)return '수집할 사이트를 하나 이상 선택해.';
 if(!db?.edition)return '회차 정보를 읽지 못했어. 화면을 새로고침해.';
 if(!start||!end||start>end)return '시작일과 종료일을 올바르게 지정해.';
 if(start!==db.edition.period_start||end!==db.edition.period_end)
  return '선택한 수집 기간('+start+' ~ '+end+')이 현재 회차 기간('+db.edition.period_start+' ~ '+db.edition.period_end+')과 달라. 먼저 [이 기간으로 회차 생성·전환]을 눌러줘.';
 if(mode==='rss'){
  const unsupported=keys.filter(k=>!sourceCatalog.get(k)?.rss_available||sourceCatalog.get(k)?.group!=='mfds');
  if(unsupported.length)return 'RSS가 설정되지 않은 사이트: '+unsupported.join(', ')+'. [공개 목록] 방식으로 변경하거나 RSS 가능한 식약처 사이트만 선택해.';
 }
 if(!Number.isInteger(maxPages)||maxPages<1||maxPages>10)return '최대 조회 페이지는 1~10 사이의 정수로 지정해.';
 if(keys.some(k=>sourceCatalog.get(k)?.group==='industry')&&!$('mediaRights').checked)
  return '언론사 수집 전에 사이트 이용 조건 확인 체크박스를 선택해.';
 return '';
}
function syncApprovalButtons(){const locked=db?.edition?.status==='confirmed',busy=collectionRunning||collectionSubmitting||lastAi==='running';for(const id of ['collectApproval','collectAllApprovals','importApproval','approvalFile'])$(id).disabled=!db||locked||busy;const zone=$('approvalFile').closest('[data-drop-input]');zone?.classList.toggle('disabled',!!$('approvalFile').disabled)}
async function startApprovalCollection(kind){if(!db||collectionRunning||collectionSubmitting)return;collectionSubmitting=true;collectionError='';lastApprovalMarker='';syncApprovalButtons();$('approvalStatus').textContent='공식 목록 조회 중';try{showCollection(await api('/api/approval/collect',{kind}))}catch(err){collectError('자동 수집 실패: '+err.message);$('approvalStatus').textContent='자동 수집 실패: '+err.message}finally{collectionSubmitting=false;syncApprovalButtons()}}
$('collectApproval').addEventListener('click',()=>startApprovalCollection($('approvalKind').value));
$('collectAllApprovals').addEventListener('click',()=>startApprovalCollection('all'));
function showCollection(j){
 // Never present results from a different edition after creating/switching weeks.
 if(db?.edition && j.edition_id && j.edition_id!==db.edition.id){collectionWasActive=false;j={state:'idle',processed:0,total:0,results:[]}}
 const isRunning=j.state==='running';collectionRunning=isRunning;syncApprovalButtons();
 if(j.approval_kind){const marker=[j.edition_id,j.started_at,j.state,j.finished_at].join('|');if(marker!==lastApprovalMarker){lastApprovalMarker=marker;const outs=j.results||[],out=outs[0];$('approvalStatus').textContent=j.state==='running'?'공식 목록 조회 중':j.state==='failed'?'자동 수집 실패: '+(j.error||'조회 실패'):j.approval_kind==='all'?'공식 수집 '+outs.length+'개 유형 · 성공 '+outs.filter(x=>x.status==='success').length+' · 실패 '+outs.filter(x=>x.status==='failed').length:out?'공식 조회 '+out.official_total+'건 · 등록 '+out.records+'건 · 신규 '+(out.save_counts?.new??0)+'건 · 기존 '+(out.save_counts?.unchanged??0)+'건 · 변경 '+(out.save_counts?.changed??0)+'건'+(out.cancelled_only?' · 취소/취하만 해당 '+out.cancelled_only+'건 제외':''):'';}}
 $('startCollection').disabled=isRunning||collectionSubmitting||db?.edition?.status==='confirmed';
 $('newEdition').disabled=isRunning||collectionSubmitting;
 updateSourceToggles();
 const totalRecords=(j.results||[]).reduce((sum,x)=>sum+Number(x.records||0),0);
 const summary=j.state==='finished'?' · 발견 '+totalRecords+'건'+(j.new_edition_links==null?'':' · 회차 신규 연결 '+j.new_edition_links+'건'):'';
 $('collectionState').textContent=collectionError?'수집 요청 확인 필요':({idle:'대기',running:'수집 중',finished:'수집 작업 종료',failed:'수집 작업 오류'}[j.state]||j.state)+' ('+(j.processed||0)+'/'+(j.total||0)+')'+summary;
 $('collectionProgress').max=Math.max(1,j.total||1);$('collectionProgress').value=j.processed||0;
 let html=collectionError?'<p class="error" role="alert">'+esc(collectionError)+'</p>':'';
 if(j.error)html+='<p class="error" role="alert">'+esc(j.error)+'</p>';
 for(const x of j.results||[]){
  const critical=(x.issues||[]).filter(y=>/error|exception|timeout|denied|forbidden|http\s*\d{3}|no article links parsed|selector needs validation|invalid|failed|refused|connection|not found|blocked/i.test(String(y)));
  if(x.save_counts)html+='<p>'+esc(sourceLabel[x.source]||x.source)+' · 발견 '+Number(x.records||0)+' · 신규 '+Number(x.save_counts.new||0)+' · 기존 동일 '+Number(x.save_counts.unchanged||0)+' · 변경 '+Number(x.save_counts.changed||0)+'</p>';
  if(x.official_total!=null)html+='<p>'+esc(sourceLabel[x.source]||x.source)+' · 공식 조회 '+x.official_total+'건 · 등록 '+x.records+'건'+(x.cancelled_only?' · 취소/취하만 해당 '+x.cancelled_only+'건 제외':'')+'</p>';if(x.status==='success'&&!critical.length)continue;
  if(Number(x.records||0)!==0 && x.status!=='failed' && !critical.length)continue;
  html+='<div class="collection-problem"><b>'+esc(sourceLabel[x.source]||x.source)+'</b> · '+(x.status==='failed'?'오류':Number(x.records||0)===0?'0건':'확인 필요')+' · '+Number(x.records||0)+'건</div>';
  if(critical.length)html+='<ul>'+critical.map(y=>'<li>'+esc(String(y).replace(/No article links parsed on page (\d+); selector needs validation/i,'$1페이지: 기사 링크 미확인 · 마지막 페이지인지 구조 변경인지 확인 필요'))+'</li>').join('')+'</ul>';
 }
 $('collectionResults').hidden=!html;
 $('collectionResults').innerHTML=html;
 if(isRunning)collectionWasActive=true;
 if(!isRunning&&collectionWasActive){collectionWasActive=false;load().catch(e=>{$('feedback').textContent=e.message})}
}
async function pollCollection(){if(pollBusy)return;pollBusy=true;try{const r=await fetch('/api/collection');if(r.ok)showCollection(await r.json())}catch(err){$('collectionState').textContent='상태 조회 오류: '+err.message}finally{pollBusy=false}}
$('startCollection').addEventListener('click',async()=>{
 if(collectionSubmitting||collectionRunning)return;
 const keys=collectSelected(),start=$('colStart').value,end=$('colEnd').value;
 const method=$('colMethod').value,maxPages=Number($('colPages').value);
 const invalid=collectInputError(keys,start,end,method,maxPages);
 if(invalid){collectError(invalid);if(db?.edition&&(start!==db.edition.period_start||end!==db.edition.period_end))$('newEdition').focus();return}
 collectionError='';collectionSubmitting=true;
 $('startCollection').disabled=true;$('newEdition').disabled=true;
 $('collectionResults').textContent='';$('collectionResults').hidden=true;$('collectionState').textContent='수집 요청 전송 중';
 try{const result=await api('/api/collect',{sources:keys,start,end,method,max_pages:maxPages,rights_acknowledged:$('mediaRights').checked});showCollection(result)}
 catch(err){collectError('실행 오류: '+err.message)}
 finally{collectionSubmitting=false;$('startCollection').disabled=collectionRunning;$('newEdition').disabled=collectionRunning}
});
$('newEdition').addEventListener('click',async()=>{
 const status=$('editionSetupStatus'),start=$('colStart').value,end=$('colEnd').value,id=$('newEditionId').value.trim();
 status.textContent='';if(!start||!end||end<start){status.textContent='시작일과 종료일을 올바르게 지정하세요.';return}if(id&&!/^[0-9A-Za-z_-]{4,72}$/.test(id)){status.textContent='회차 ID는 영문·숫자·-·_ 4~72자만 가능합니다. 회차 제목에는 한글을 사용할 수 있습니다.';return}
 try{const r=await api('/api/edition/new',{start:$('colStart').value,end:$('colEnd').value,target:4,edition_id:$('newEditionId').value.trim()||undefined,title:$('newEditionTitle').value.trim()||undefined});
 detailDirty=false;detailItemId=null;selectedIds.clear();pageIndex=0;cardIndex=0;publicationDirty=false;lastApprovalMarker='';clearDrop('approvalFile');clearDrop('aiJsonFile');$('approvalStatus').textContent='';
 $('colStart').value='';$('colEnd').value='';collectionError='';await load();await pollCollection();$('editionSetupStatus').textContent='회차 전환 완료: '+r.edition_id}
 catch(err){$('editionSetupStatus').textContent='회차 오류: '+err.message}
});
function sourceDisplay(x){if(x.source_group==='company'){try{return JSON.parse(x.original_metadata||'{}').publisher||sourceLabel[x.source_key]||x.source_key}catch(e){}}return sourceLabel[x.source_key]||x.source_key}
function titleNeedsReview(x){return x.verification==='needs_title_review'||!String(x.title||'').trim()||(x.title||'').length>190||(x.source_key==='medicaltimes'&&/\[\s*메디칼타임즈\s*=|\[제목 확인 필요\]|20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/.test(x.title||''))}
function proposedSection(x){return x.source_group==='industry'&&titleNeedsReview(x)?'industry.unclassified':x.ai_section||x.rule_section||x.section}
function qualityMatch(x,key){if(key==='all')return true;if(key==='title')return titleNeedsReview(x);if(key==='date')return !x.published_at;if(key==='period')return Boolean(x.published_at&&(x.published_at<db.edition.period_start||x.published_at>db.edition.period_end));if(key==='proposal')return x.source_group==='industry'&&proposedSection(x)==='industry.unclassified';if(key==='publication')return x.source_group==='industry'&&(x.section_override||x.section)==='industry.unclassified';if(key==='medicaltimes')return x.source_key==='medicaltimes'&&['title','date','period','proposal','publication'].some(k=>qualityMatch(x,k));return false}
function originalUrl(x){const url=x.original_url??x.url;return /^https?:\/\//i.test(url||'')?url:null}
function originalLinkLabel(x){return x.original_link_kind==='search'?'원문 조건 검색':x.original_link_kind==='source'?'공식 조회 페이지':'원문 확인'}
function safeOriginalLink(x){const url=originalUrl(x);return url?'<a class="button original-link" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+originalLinkLabel(x)+' ↗</a>':''}
function candidateSection(x){return x.section_override||proposedSection(x)}
function hasAi(x){return x.ai_score!=null||x.ai_reason!=null||x.ai_section!=null||Boolean(x.ai_summary)}
function isSuggested(x){if(titleNeedsReview(x))return false;return hasAi(x)?Boolean(x.ai_recommended):Boolean(x.rule_recommended)}
function industryRows(){return db.items.filter(x=>x.source_group==='industry')}
function groupLabel(id){return reviewGroups.find(g=>g.id===id)?.label||'그룹 미지정'}
function scopeIndustry(){const s=$('industrySection').value;return industryRows().filter(x=>s==='all'||candidateSection(x)===s)}
function ordered(){return db.items.filter(x=>x.top_selected).sort((a,b)=>(a.top_rank??9999)-(b.top_rank??9999)|| (a.id<b.id?-1:a.id>b.id?1:0))}
function reviewStatus(x){
 if(x.source_group!=='industry')return 'institutional';
 if(isSuggested(x))return 'recommended';
 return hasAi(x)&&x.ai_relevance==='irrelevant'?'other':'review';
}
function queueMatch(x){if(queueKind==='top')return Boolean(x.top_selected);if(queueKind==='company')return x.source_group==='company'||Boolean(x.company_selected);return queueKind==='all'||(queueKind==='included'?Boolean(x.include_detail):reviewStatus(x)===queueKind)}
function sectionSelectOptions(x){return sec.filter(y=>x.source_group==='mfds'?y.startsWith('mfds.'):x.source_group==='industry'?y.startsWith('industry.'):x.source_group==='company'?y.startsWith('company.'):x.source_group==='clinical'?y==='clinical.approval':x.source_group==='treatment'?y==='clinical.treatment':x.source_group==='drug'?y==='drug.approvals':false)}
let currentPageRows=[];
function articleTags(x){const ai=hasAi(x),suggested=isSuggested(x),rank=ordered().findIndex(y=>y.id===x.id)+1;const top=Array.isArray(db.top_output_ids)?(db.top_output_ids.includes(x.id)?' · 출력':' · 예비'):'';return '<span class="tag '+(x.include_detail?'selected':'tag-neutral')+'">'+(x.include_detail?'수록':'미수록')+'</span><span class="tag '+(ai?'tag-ai':suggested?'tag-rule':x.source_group==='industry'?'tag-review':'tag-neutral')+'">'+(ai?(suggested?'GPT 추천':'GPT 검토'):suggested?'규칙 추천':x.source_group==='industry'?'추가 검토':'기관 자료')+'</span>'+(x.top_selected?'<span class="tag tag-top">TOP '+rank+esc(top)+'</span>':'')+(x.company_selected||x.source_group==='company'?'<span class="tag tag-rule">회사 소식 '+(companyRows().findIndex(y=>y.id===x.id)+1)+'</span>':'')+(titleNeedsReview(x)?'<span class="tag warn">제목 확인</span>':'')+(qualityMatch(x,'period')?'<span class="tag warn">기간 밖</span>':'');}
function renderCardGallery(view){
 const gallery=$('cardGallery'),locked=db.edition.status==='confirmed';gallery.hidden=!cardMode;$('items').hidden=cardMode;
 $('viewModeToggle').textContent=cardMode?'목록 보기':'추천 카드 보기';$('viewModeToggle').setAttribute('aria-pressed',String(cardMode));
 $('prevItems').hidden=cardMode;$('nextItems').hidden=cardMode;$('pageInfo').hidden=cardMode;
 if(!cardMode)return;
 cardIndex=Math.max(0,Math.min(cardIndex,view.length-1));const x=view[cardIndex];
 $('cardPrev').disabled=cardIndex===0;$('cardNext').disabled=cardIndex>=view.length-1;
 $('cardStatus').textContent=view.length?(cardIndex+1)+' / '+view.length:'0 / 0';
 if(!x){$('featuredArticle').innerHTML='<p class="empty-results">추천 기사 또는 현재 조건에 맞는 후보가 없어.</p>';return}
 const safeLink=originalUrl(x);
 const flag=titleNeedsReview(x);
 const info=flag?' · 제목 확인 필요':(!x.published_at?' · 날짜 확인 필요':'');
 $('featuredArticle').innerHTML='<article class="candidate-card" data-id="'+esc(x.id)+'">'+
  '<div class="candidate-card-top"><span class="pill">'+esc(sourceDisplay(x))+'</span><span class="card-status-tags">'+articleTags(x)+'</span></div>'+
  '<h4>'+esc(x.title)+'</h4>'+
  '<p class="candidate-card-reason">'+esc(hasAi(x)?x.ai_reason||'GPT 분석 근거 없음':x.rule_reason||'추천 근거 없음')+'</p>'+
  '<div class="actions">'+(x.source_group==='industry'?'<label><input type="checkbox" data-card-select="'+esc(x.id)+'" '+(selectedIds.has(x.id)?'checked':'')+(locked?' disabled':'')+'> 일괄 선택</label>':'')+
  '<button type="button" class="primary" data-open-id="'+esc(x.id)+'">상세 검토</button>'+
  (safeLink?'<a class="button" href="'+esc(safeLink)+'" rel="noopener noreferrer" target="_blank">'+originalLinkLabel(x)+'</a>':'')+'</div></article>';
}
function openCandidate(id){if(detailItemId!==id&&detailDirty&&!confirm('저장하지 않은 편집 내용을 버리고 다른 기사를 열까?'))return;
 detailDirty=false;detailItemId=id;render();$('detailPanel').scrollTop=0;if(window.matchMedia('(max-width: 1060px)').matches)$('closeDetail')?.focus()}
$('viewModeToggle').addEventListener('click',()=>{cardMode=!cardMode;if(cardMode)cardIndex=pageIndex*PAGE_SIZE;render()});
$('cardPrev').addEventListener('click',()=>{cardIndex=Math.max(0,cardIndex-1);render()});
$('cardNext').addEventListener('click',()=>{cardIndex++;render()});
$('cardGallery').addEventListener('click',e=>{const btn=e.target.closest('[data-open-id]');if(btn)openCandidate(btn.dataset.openId)});
$('cardGallery').addEventListener('change',e=>{const box=e.target.closest('[data-card-select]');if(!box||box.disabled||db?.edition?.status==='confirmed')return;
 if(box.checked)selectedIds.add(box.dataset.cardSelect);else selectedIds.delete(box.dataset.cardSelect);render()});
function showRankQueue(kind){queueKind=kind;selectedIds.clear();pageIndex=0;cardIndex=0;cardMode=false;for(const id of ['group','industrySection','actualSection','reviewGroup','qualityFilter'])$(id).value='all';$('search').value='';}
function companyRows(){return (db?.items||[]).filter(x=>x.source_group==='company'||x.company_selected).sort((a,b)=>(a.company_rank??999999)-(b.company_rank??999999)||a.id.localeCompare(b.id))}
function renderCompany(){
 const rows=companyRows(),locked=db.edition.status==='confirmed';
 $('companyList').innerHTML=rows.map((x,i)=>'<div class="rankrow"><b class="num">'+(i+1)+'</b><button class="company-open" data-company-open="'+esc(x.id)+'">'+esc(x.title_override??x.title)+'</button><span class="tag '+((x.source_group==='company'?x.include_detail:x.company_selected)?'selected':'tag-neutral')+'">'+((x.source_group==='company'?x.include_detail:x.company_selected)?'수록':'미수록')+'</span><button data-company-move="-1" data-id="'+esc(x.id)+'" '+(locked||i===0?'disabled':'')+' aria-label="위로">↑</button><button data-company-move="1" data-id="'+esc(x.id)+'" '+(locked||i===rows.length-1?'disabled':'')+' aria-label="아래로">↓</button></div>').join('');
 $('saveCompany').disabled=locked;syncApprovalButtons();
 for(const id of ['companyTitle','companyPublisher','companyUrl','companyDate','companySummary'])$(id).disabled=locked;
 $('savePublication').disabled=locked;$('publicationDate').disabled=locked;
}
$('companyList').addEventListener('click',async e=>{const open=e.target.closest('[data-company-open]');if(open){openCandidate(open.dataset.companyOpen);$('detailPanel').scrollIntoView({block:'nearest'});return}const btn=e.target.closest('[data-company-move]');if(!btn)return;const ids=companyRows().map(x=>x.id),i=ids.indexOf(btn.dataset.id),j=i+Number(btn.dataset.companyMove);if(i<0||j<0||j>=ids.length)return;[ids[i],ids[j]]=[ids[j],ids[i]];try{await api('/api/company/order',{ids});showRankQueue('company');await load()}catch(err){$('companyStatus').textContent=err.message}});
$('saveCompany').addEventListener('click',async()=>{try{const result=await api('/api/company/register',{title:$('companyTitle').value,publisher:$('companyPublisher').value,url:$('companyUrl').value,published_at:$('companyDate').value,summary:$('companySummary').value});for(const id of ['companyTitle','companyPublisher','companyUrl','companyDate','companySummary'])$(id).value='';await load();$('companyStatus').textContent='등록 완료';}catch(err){$('companyStatus').textContent=err.message}});
$('importApproval').addEventListener('click',async()=>{const file=$('approvalFile').files[0];if(!file||fileError($('approvalFile'),file)){$('approvalStatus').textContent='2.5MB 이하 CSV를 선택하세요.';return}try{const result=await api('/api/approval/import',{kind:$('approvalKind').value,filename:file.name,content:await fileBase64(file)});await load();clearDrop('approvalFile');$('approvalStatus').textContent='등록 '+result.imported+'건 · 제외 '+result.skipped.length+'건'+(result.skipped.length?' · '+result.skipped.slice(0,5).map(x=>x.line+'행: '+x.reason).join(' / '):'')+(result.managed_file?' · 원본 보관 완료':'');}catch(err){$('approvalStatus').textContent=err.message}});
async function savePublication(){await api('/api/edition/publication',{issue_number:$('issueNumber').value.trim(),publication_date:$('publicationDate').value});publicationDirty=false;await load();refreshPreview()}
$('savePublication').addEventListener('click',async()=>{try{await savePublication();$('confirmMessage').textContent='발행 정보 저장 완료'}catch(err){$('confirmMessage').textContent=err.message}});
function render(){
 if(!db)return;
 renderCompany();
 const locked=db.edition.status==='confirmed';if(locked)selectedIds.clear();
 const all=db.items, top=ordered(), q=$('search').value.trim().toLowerCase(),g=$('group').value,sf=$('industrySection').value,af=$('actualSection').value,rg=$('reviewGroup').value,quality=$('qualityFilter').value;
 for(const id of [...selectedIds])if(!all.some(x=>x.id===id&&x.source_group==='industry'))selectedIds.delete(id);
 $('stats').innerHTML='<div class="stat"><b>'+all.length+'</b><small>전체 자료</small></div><div class="stat"><b>'+all.filter(x=>x.include_detail).length+'</b><small>수록 자료</small></div><div class="stat"><b>'+top.length+'</b><small>TOP 후보</small></div>';
 $('collectionSummary').textContent='식약처 연결 자료 '+all.filter(x=>x.source_group==='mfds').length+'건 · 수집 기록 '+(db.run_total??db.runs.length)+'회';
 $('editionScope').textContent='날짜 미확인 '+(db.undated_count||0)+'건 · 기간 밖 '+(db.out_of_period_count||0)+'건';$('editionScope').hidden=!(db.undated_count||db.out_of_period_count);
 $('target').value=db.edition.top_target;
 const outputIds=new Set(db.top_output_ids||[]), outputKnown=Array.isArray(db.top_output_ids);
 $('previewTopState').textContent=outputKnown?'주요 뉴스 '+outputIds.size+'건 출력 · 후보 '+top.length+'건 · 상한 '+db.edition.top_target+'건':'이전 확정본 · TOP 건수 미확인';
 const media=all.filter(x=>x.source_group==='industry'), analysed=media.filter(hasAi);
 $('aiCounts').textContent='언론기사 '+media.length+'건 · GPT 분석 '+analysed.length+'건 · GPT 추천 '+analysed.filter(isSuggested).length+'건 · 미분석 '+(media.length-analysed.length)+'건';
 $('targetHint').textContent='후보 '+top.length+'건 · 실제 출력 '+outputIds.size+'건 · 예비 '+(top.length-outputIds.size)+'건 / 출력 상한 '+db.edition.top_target+'건';
 if(!outputKnown)$('targetHint').textContent='이전 확정본 · 실제 출력은 보존된 HTML에서 확인해.';
 const counts={recommended:all.filter(x=>reviewStatus(x)==='recommended').length,review:all.filter(x=>reviewStatus(x)==='review').length,other:all.filter(x=>reviewStatus(x)==='other').length,institutional:all.filter(x=>reviewStatus(x)==='institutional').length,company:companyRows().length,top:top.length,included:all.filter(x=>x.include_detail).length,all:all.length};
 for(const button of document.querySelectorAll('[data-queue]')){
   const key=button.dataset.queue;button.setAttribute('aria-selected',String(queueKind===key));
   button.textContent={recommended:'추천 후보',review:'추가 검토',other:'기타 언론기사',institutional:'기관·기타 자료',company:'회사 소식',top:'TOP 후보',included:'수록 목록',all:'전체'}[key]+' '+counts[key];
 }
 const labels={medicaltimes:'메디칼타임즈 확인 필요',title:'제목 확인',date:'날짜 미확인',period:'기간 밖',proposal:'추천 미분류',publication:'발행 미분류'};
 for(const opt of $('qualityFilter').options)if(labels[opt.value])opt.textContent=labels[opt.value]+' '+all.filter(x=>qualityMatch(x,opt.value)).length+'건';
 let view=all.filter(x=>queueMatch(x)&&qualityMatch(x,quality)&&(g==='all'||x.source_group===g)
   &&(sf==='all'||(x.source_group==='industry'&&proposedSection(x)===sf))
    &&(af==='all'||(x.source_group==='industry'&&(x.section_override||x.section)===af))
    &&(rg==='all'||(x.source_group==='industry'&&x.rule_group_id===rg))
   &&(!q||(x.title+' '+(x.summary_source||'')+' '+x.source_key).toLowerCase().includes(q)));
 if(queueKind==='company'||queueKind==='top'){const ranks=new Map((queueKind==='company'?companyRows():top).map((x,i)=>[x.id,i]));view.sort((a,b)=>(ranks.get(a.id)??999999)-(ranks.get(b.id)??999999));}
 const pages=Math.max(1,Math.ceil(view.length/PAGE_SIZE));pageIndex=Math.max(0,Math.min(pageIndex,pages-1));
 if(cardMode){cardIndex=Math.max(0,Math.min(cardIndex,view.length-1));const cardPage=Math.floor(cardIndex/PAGE_SIZE);if(cardPage!==pageIndex){selectedIds.clear();pageIndex=cardPage;}}
 currentPageRows=view.slice(pageIndex*PAGE_SIZE,(pageIndex+1)*PAGE_SIZE);
 $('pageInfo').textContent=view.length+'건 중 '+(currentPageRows.length?((pageIndex*PAGE_SIZE)+1):0)+'~'+Math.min((pageIndex+1)*PAGE_SIZE,view.length)+'건';
 $('queueTotal').textContent='현재 조건 '+view.length+'건';
 $('prevItems').disabled=pageIndex===0;$('nextItems').disabled=pageIndex>=pages-1;
 $('items').innerHTML=currentPageRows.map(x=>{
   const proposal=x.source_group==='industry'?proposedSection(x):x.section;
   const actual=x.section_override||x.section;
   const proposalLabel=sectionLabel[proposal]||proposal;
   const summary=x.summary_source||'';
   return '<article class="queue-row'+(detailItemId===x.id?' active':'')+'" data-id="'+esc(x.id)+'">'+
    '<label class="queue-select" title="'+(locked?'확정 회차 · 읽기 전용':x.source_group!=='industry'?'일괄 편집은 언론기사만 지원':'일괄 작업에 포함')+'"><input type="checkbox" data-queue-check="1" '+(selectedIds.has(x.id)?'checked':'')+(locked||x.source_group!=='industry'?' disabled':'')+' aria-label="기사 선택"></label>'+
    '<button class="queue-open" data-open-id="'+esc(x.id)+'" type="button" title="'+esc(x.title)+'"><strong class="queue-headline">'+esc(x.title)+'</strong><small>'+esc(x.published_at||'날짜 확인 필요')+' · '+esc(sourceDisplay(x))+' · 제안 '+esc(proposalLabel)+' / 발행 '+esc(sectionLabel[actual]||actual)+'</small><span class="queue-reason">'+esc(((hasAi(x)?x.ai_reason:x.rule_reason)||'').slice(0,150))+'</span></button>'+
    '<div class="queue-chips">'+articleTags(x)+'</div></article>'
 }).join('')||'<p class="empty-results">조건에 맞는 기사가 없어. 다른 탭이나 전체 목록을 확인해.</p>';
 renderCardGallery(view);
 const pageSelectable=currentPageRows.filter(x=>x.source_group==='industry');
 $('selectVisible').checked=pageSelectable.length>0&&pageSelectable.every(x=>selectedIds.has(x.id));
 $('selectVisible').indeterminate=!$('selectVisible').checked&&pageSelectable.some(x=>selectedIds.has(x.id));
 $('selectVisible').disabled=db.edition.status==='confirmed'||!currentPageRows.some(x=>x.source_group==='industry');
 $('selectedCount').textContent='선택 '+selectedIds.size+'건';
 for(const id of ['importAi','aiJsonFile','bulkIncludeSelected','bulkExcludeSelected','saveTarget'])$(id).disabled=locked;$('aiJsonFile').closest('[data-drop-input]')?.classList.toggle('disabled',locked);
 $('runAi').disabled=locked||!aiReady||lastAi==='running';
 $('target').disabled=locked;
 $('bulkIncludeSelected').disabled=locked||!selectedIds.size;
 $('bulkExcludeSelected').disabled=locked||!selectedIds.size;
 const chosen=all.filter(x=>selectedIds.has(x.id));
 $('bulkIncludeSelected').setAttribute('aria-pressed',String(chosen.length>0&&chosen.every(x=>x.include_detail)));
 $('bulkExcludeSelected').setAttribute('aria-pressed',String(chosen.length>0&&chosen.every(x=>!x.include_detail)));
 $('top').innerHTML=top.map((x,i)=>'<div class="rankrow"><b class="num">'+(i+1)+'</b><span>'+esc(x.title_override??x.title)+' <small>'+ (!outputKnown?'확정 당시 후보':outputIds.has(x.id)?'출력':'예비')+'</small></span><button data-move="-1" data-id="'+esc(x.id)+'" '+(i===0||locked?'disabled':'')+' aria-label="위로 이동">↑</button><button data-move="1" data-id="'+esc(x.id)+'" '+(i===top.length-1||locked?'disabled':'')+' aria-label="아래로 이동">↓</button><button data-remove-top="1" data-id="'+esc(x.id)+'" '+(locked?'disabled':'')+' aria-label="TOP 후보 해제">×</button></div>').join('')||'<p class="status">담당자가 선정한 TOP 기사가 없어.</p>';
 $('runs').innerHTML=db.runs.slice(0,20).map(r=>'<div style="margin:6px 0">'+esc(r.source_key)+' · '+esc(r.status)+' · '+r.records_seen+'건</div>').join('')||'이 회차에 귀속된 수집 이력이 없어. 기존 기록은 임의로 귀속하지 않았어.';
 renderDetail();updateDashboard();
}
function renderDetail(){
 const x=db?.items.find(x=>x.id===detailItemId),target=$('detailPanel');
  target.classList.toggle('is-open',Boolean(x));$('detailBackdrop').hidden=!x;
  const asDrawer=Boolean(x)&&window.matchMedia('(max-width: 1060px)').matches;
  target.setAttribute('role',asDrawer?'dialog':'complementary');
  if(asDrawer)target.setAttribute('aria-modal','true');else target.removeAttribute('aria-modal');
  document.body.classList.toggle('drawer-open',asDrawer);
 const draft=detailDirty&&target.dataset.itemId===detailItemId&&$('detailTitle')&&$('detailSummary')?
       {title:$('detailTitle').value,summary:$('detailSummary').value}:null;
 target.dataset.itemId=x?.id||'';
 if(!x){target.innerHTML='<div class="detail-empty"><h3>3. 기사 상세 편집</h3><p>기사를 선택하세요.</p></div>';return;}
 const confirmed=db.edition.status==='confirmed',locked=confirmed?'disabled':'';
 const proposed=proposedSection(x),actual=x.section_override||x.section;
 const attrs=sectionSelectOptions(x).map(key=>'<option value="'+esc(key)+'" '+(key===actual?'selected':'')+'>'+esc(sectionLabel[key]||key)+'</option>').join('');
 const suggestedSummary=hasAi(x)?x.ai_summary||'':null;
 target.innerHTML='<div class="detail-content"><div class="detail-title"><h3>3. 기사 상세 편집</h3><div class="detail-title-actions">'+safeOriginalLink(x)+'<button id="closeDetail" type="button" aria-label="상세 편집 닫기">닫기</button></div></div>'+
  '<div class="detail-form"><h4>최종 편집·발행 내용</h4>'+(confirmed?'<p class="readonly-note">확정된 회차 · 읽기 전용</p>':x.mandatory?'<p class="readonly-note">필수 수록 자료 · 본문 제외 불가</p>':'')+'<label class="checkline"><input id="detailInclude" type="checkbox" '+(x.include_detail?'checked':'')+(x.mandatory||confirmed?' disabled':'')+'> 본문에 수록</label><label class="checkline"><input id="detailTop" type="checkbox" '+(x.top_selected?'checked ':'')+locked+'> TOP 후보</label>'+(x.source_group==='industry'?'<label class="checkline"><input id="detailCompany" type="checkbox" '+(x.company_selected?'checked ':'')+locked+'> 메디팁 주요 소식</label>':'')+
  '<label class="field" for="detailSection">발행 분야</label><select id="detailSection" '+locked+'>'+attrs+'</select>'+
  '<label class="field" for="detailTitle">발행 제목</label><input id="detailTitle" '+locked+' value="'+esc(x.title_override??x.title)+'" maxlength="2000">'+
  '<label class="field" for="detailSummary">발행 요약</label><textarea id="detailSummary" '+locked+' maxlength="2000">'+esc(x.summary_override??x.summary_source??'')+'</textarea>'+
  '<div id="detailSummaryLength" class="small-label"></div><div class="actions">'+(suggestedSummary&&!confirmed?'<button id="applyAiSummary">GPT 요약을 편집란으로 복사</button>':'')+'<button id="saveDetailText" class="primary" '+locked+'>저장</button></div><p class="muted" id="detailStatus"></p></div>'+ '<div class="proposal-box"><p class="small-label">분석 제안 (승인 전)</p><p><strong>추천 그룹:</strong> '+esc(groupLabel(x.rule_group_id))+' · <strong>발행 분야:</strong> '+esc(sectionLabel[proposed]||proposed)+' · <strong>수록 추천:</strong> '+(isSuggested(x)?'추천':'미추천')+'</p><p>'+esc(hasAi(x)?x.ai_reason||'':x.rule_reason||'규칙 추천 없음')+'</p>'+(suggestedSummary?'<p><strong>요약 제안:</strong> '+esc(suggestedSummary)+'</p>':'')+'</div>' + '<section class="original-article">'+ '<div class="original-heading"><h4>원본 기사</h4>'+safeOriginalLink(x)+'</div>'+(titleNeedsReview(x)?'<p class="notice">제목 추출 확인 필요</p>':'')+(qualityMatch(x,'period')?'<p class="notice">발행일이 회차 수집 기간 밖입니다.</p>':'')+'<p class="source-title">'+esc(x.title)+'</p><p class="muted">'+esc(x.published_at||'날짜 미확인')+' · '+esc(sourceDisplay(x))+'</p>'+(!confirmed&&x.source_key==='medicaltimes'?'<button id="recheckMetadata" type="button">원문 제목·발행일 재확인</button><p id="recheckStatus" class="status" role="status"></p>':'') + '</section></div>';
 if(draft){$('detailTitle').value=draft.title;$('detailSummary').value=draft.summary;}
 $('detailTitle').addEventListener('input',()=>{detailDirty=true});
 const counter=()=>{const n=$('detailSummary').value.length;$('detailSummaryLength').textContent=n+'/220자'+(n>220?' (권장 초과)':'')};counter();$('detailSummary').addEventListener('input',()=>{detailDirty=true;counter()});
 $('closeDetail').addEventListener('click',()=>{if(detailDirty&&!confirm('저장하지 않은 편집 내용을 닫을까?'))return;const oldId=detailItemId;detailDirty=false;detailItemId=null;render();[...document.querySelectorAll('[data-open-id]')].find(el=>el.dataset.openId===oldId)?.focus()});
 if(confirmed)return;
 if($('recheckMetadata'))$('recheckMetadata').addEventListener('click',async()=>{const button=$('recheckMetadata');button.disabled=true;$('recheckStatus').textContent='원문 확인 중';try{const result=await api('/api/article/recheck',{item_id:x.id});await load();if(detailItemId===x.id&&$('recheckStatus'))$('recheckStatus').textContent=(result.changed?'원본 메타데이터 갱신 · 기존 발행 편집값 유지 · GPT 제안 재분석 필요':'원문 메타데이터 확인 완료')+(result.out_of_period?' · 수집 기간 밖':'')}catch(e){if(detailItemId===x.id&&$('recheckStatus'))$('recheckStatus').textContent=e.message}finally{if(detailItemId===x.id&&$('recheckMetadata'))$('recheckMetadata').disabled=false}});
 if(suggestedSummary)$('applyAiSummary').addEventListener('click',()=>{$('detailSummary').value=suggestedSummary;detailDirty=true;counter();$('detailStatus').textContent='GPT 요약을 복사했어. 확인 후 저장을 눌러야 반영돼.'});
 $('detailInclude').addEventListener('change',e=>act(()=>api('/api/decision',{item_id:x.id,changes:{include_detail:e.target.checked}})));
 if($('detailCompany'))$('detailCompany').addEventListener('change',e=>act(()=>api('/api/decision',{item_id:x.id,changes:{company_selected:e.target.checked}})));
 $('detailTop').addEventListener('change',e=>{const ids=ordered().map(y=>y.id).filter(id=>id!==x.id);if(e.target.checked)ids.push(x.id);act(()=>api('/api/top-order',{ids}))});
 $('detailSection').addEventListener('change',e=>act(()=>api('/api/decision',{item_id:x.id,changes:{section_override:e.target.value}})));
 $('saveDetailText').addEventListener('click',async()=>{
  const title=$('detailTitle').value,summary=$('detailSummary').value;
  if(await act(()=>api('/api/decision',{item_id:x.id,changes:{title_override:title,summary_override:summary}}))){detailDirty=false;renderDetail();}
 });
}
async function act(fn){try{await fn();await load();$('feedback').textContent='변경 내용 저장 완료';return true;}catch(e){$('feedback').textContent=e.message;return false}}
function selectedIndustryIds(){return [...selectedIds].filter(id=>db.items.some(x=>x.id===id&&x.source_group==='industry'))}
async function bulkSelected(mode,value){
 const ids=selectedIndustryIds();if(!ids.length){$('industryFeedback').textContent='먼저 언론기사를 선택해.';return}
 const label=mode==='apply_sections'?'추천 분야 적용':value?'본문 수록':'본문 제외';
 if(!confirm('선택한 '+ids.length+'건에 '+label+'을(를) 적용할까? 기존 개별 수정을 바꾸는 명시적인 선택이야.'))return;
 try{const out=await api('/api/industry/bulk',{mode,ids,...(mode==='set_inclusion'?{value}: {})});
  $('industryFeedback').textContent='처리 '+out.updated+'건 · 기존 승인 보호 '+out.protected+'건 · 제안 없음 '+out.not_recommended+'건';selectedIds.clear();await load();}
 catch(e){$('industryFeedback').textContent=e.message}
}
$('bulkIncludeSelected').addEventListener('click',()=>bulkSelected('set_inclusion',true));
$('bulkExcludeSelected').addEventListener('click',()=>bulkSelected('set_inclusion',false));
$('selectVisible').addEventListener('change',e=>{for(const x of currentPageRows.filter(x=>x.source_group==='industry')){if(e.target.checked)selectedIds.add(x.id);else selectedIds.delete(x.id)}render()});
$('items').addEventListener('change',e=>{if(!e.target.matches('[data-queue-check]')||e.target.disabled||db?.edition?.status==='confirmed')return;const id=e.target.closest('[data-id]').dataset.id;if(e.target.checked)selectedIds.add(id);else selectedIds.delete(id);render()});
$('items').addEventListener('click',e=>{const btn=e.target.closest('[data-open-id]');if(btn)openCandidate(btn.dataset.openId)});
$('detailBackdrop').addEventListener('click',()=>$('closeDetail')?.click());
document.addEventListener('keydown',e=>{
 if($('detailBackdrop').hidden||!window.matchMedia('(max-width: 1060px)').matches)return;
 if(e.key==='Escape'){$('closeDetail')?.click();return}
 if(e.key==='Tab'){
  const nodes=[...$('detailPanel').querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])')];
  if(!nodes.length)return;
  const first=nodes[0],last=nodes[nodes.length-1];
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
 }
});
$('queueTabs').addEventListener('click',e=>{const btn=e.target.closest('[data-queue]');if(!btn)return;queueKind=btn.dataset.queue;selectedIds.clear();pageIndex=0;cardIndex=0;render()});
$('top').addEventListener('click',e=>{const btn=e.target.closest('[data-move],[data-remove-top]');if(!btn)return;const ids=ordered().map(x=>x.id),i=ids.indexOf(btn.dataset.id);if(i<0)return;if(btn.hasAttribute('data-remove-top')){ids.splice(i,1);act(()=>api('/api/top-order',{ids}));return;}const j=i+Number(btn.dataset.move);if(j<0||j>=ids.length)return;[ids[i],ids[j]]=[ids[j],ids[i]];act(async()=>{await api('/api/top-order',{ids});showRankQueue('top')})});
$('saveTarget').addEventListener('click',()=>act(()=>api('/api/target',{count:Number($('target').value)})));
[['search','input'],['group','change'],['industrySection','change'],['actualSection','change'],['reviewGroup','change']].forEach(([id,ev])=>$(id).addEventListener(ev,()=>{selectedIds.clear();pageIndex=0;cardIndex=0;render()}));
$('qualityFilter').addEventListener('change',()=>{if($('qualityFilter').value!=='all')queueKind='all';selectedIds.clear();pageIndex=0;cardIndex=0;render()});
$('prevItems').addEventListener('click',()=>{selectedIds.clear();pageIndex=Math.max(0,pageIndex-1);render()});
$('nextItems').addEventListener('click',()=>{selectedIds.clear();pageIndex++;render()});
$('importAi').addEventListener('click',async()=>{const file=$('aiJsonFile').files[0];if(!file||fileError($('aiJsonFile'),file)){$('industryFeedback').textContent='GPT 분석 결과 JSON을 먼저 선택해.';return}
 try{const result=JSON.parse(await file.text());if(!Array.isArray(result.items))throw Error('items 배열 필요');
  const r=await api('/api/ai/import',{filename:file.name,content:await fileBase64(file)});$('industryFeedback').textContent='GPT 제안 '+r.analysed+'건 등록 · 사용자가 수록 버튼을 눌러야 적용돼'+(r.managed_file?' · 원본 보관 완료':'');await load();clearDrop('aiJsonFile');}
 catch(e){$('industryFeedback').textContent='GPT JSON 오류: '+e.message}
});
const titles={dashboard:'뉴스레터 도서관',collect:'자료 수집',edit:'기사 검토·편집',preview:'미리보기·확정',settings:'환경설정'};
function openView(name){if(!titles[name])return;
 if(name!=='edit'&&detailDirty&&!confirm('저장하지 않은 기사 편집 내용이 있어. 이동할까?'))return;
 if(name!=='edit'){detailDirty=false;detailItemId=null;document.body.classList.remove('drawer-open');$('detailBackdrop').hidden=true;$('detailPanel').classList.remove('is-open');}
 document.querySelectorAll('.view-panel').forEach(x=>x.hidden=x.id!=='view-'+name);
 document.querySelectorAll('.nav-item').forEach(x=>x.setAttribute('aria-current',x.dataset.view===name?'page':'false'));
 $('pageHeading').textContent=titles[name];
 $('headerEdition').hidden=!(db&&['collect','edit','preview'].includes(name));$('openEditionDialog').hidden=!(name==='edit'||name==='preview');$('openDraftSetup').hidden=!(db?.edition?.status==='confirmed'&&['edit','preview'].includes(name));if(name==='dashboard')loadLibrary();
 if(name==='edit'&&db)render();if(name==='preview')refreshPreview();if(name==='settings')loadSettings().catch(e=>{$('settingAi').textContent=e.message});}
document.querySelectorAll('[data-view],[data-go]').forEach(x=>x.addEventListener('click',()=>openView(x.dataset.view||x.dataset.go)));

function updateDashboard(){if(!db)return;const ed=db.edition;
 const activeView=document.querySelector('.nav-item[aria-current="page"]')?.dataset.view;
 const locked=ed.status==='confirmed';const idLabel=ed.issue_number?'제'+ed.issue_number+'호':ed.title;
 $('headerEdition').textContent=idLabel+' · '+(locked?'확정 · 읽기 전용':'편집 가능 · 초안');$('headerEdition').classList.toggle('locked-edition',locked);$('headerEdition').hidden=!['collect','edit','preview'].includes(activeView);$('openDraftSetup').hidden=!(locked&&['edit','preview'].includes(activeView));
 $('finalState').textContent=ed.status==='confirmed'?'확정본 · '+(ed.confirmed_at||''):'초안';
 $('templateChoice').value=ed.template_id||'classic';
 $('templateChoice').disabled=ed.status==='confirmed';
 $('templateMessage').textContent=ed.status==='confirmed'?'확정된 템플릿 · 변경 불가':'';
 $('confirmIssue').disabled=ed.status==='confirmed';$('runAi').disabled=ed.status==='confirmed'||!aiReady||lastAi==='running';$('issueNumber').disabled=ed.status==='confirmed';
 $('startCollection').disabled=ed.status==='confirmed'||collectionRunning;updateSourceToggles();
 $('newEdition').disabled=collectionRunning;
 $('confirmedBy').disabled=locked;$('finalAck').disabled=locked;if(locked)$('confirmedBy').value=ed.confirmed_by||'';
}
$('openDraftSetup').addEventListener('click',()=>{if(!db)return;openView('collect');$('colStart').value=db.edition.period_start;$('colEnd').value=db.edition.period_end;$('newEditionId').value='draft-'+Date.now();$('newEditionTitle').value='';$('newEditionId').focus()});
function refreshPreview(){$('newsletterPreview').src='/preview/html?refresh='+Date.now()}
$('reloadPreview').addEventListener('click',refreshPreview);
$('templateChoice').addEventListener('change',async()=>{
 const chosen=$('templateChoice').value;
 if(!db||db.edition.status==='confirmed')return;
 try{await api('/api/edition/template',{template_id:chosen});
     db.edition.template_id=chosen;
     $('templateMessage').textContent='템플릿 변경 저장됨 · 미리보기 갱신 완료';
     refreshPreview();}
 catch(err){$('templateChoice').value=db.edition.template_id||'classic';
     $('templateMessage').textContent='변경 실패: '+err.message;}
});
$('confirmIssue').addEventListener('click',async()=>{if(!db||db.edition.status==='confirmed')return;
 if(!$('finalAck').checked){$('confirmMessage').textContent='수집·내용·미연결 항목 검토 확인을 선택해.';return}
 if(!confirm('이 회차를 확정하면 수정할 수 없어. 현재 HTML과 원본 스냅샷을 고정할까?'))return;
 try{const result=await api('/api/confirm',{confirmed_by:$('confirmedBy').value.trim(),issue_number:$('issueNumber').value.trim(),publication_date:$('publicationDate').value,acknowledged:true});
 publicationDirty=false;$('confirmMessage').textContent='확정 완료 · SHA256 '+result.html_sha256.slice(0,12);await load();refreshPreview();}
 catch(e){$('confirmMessage').textContent='확정 오류: '+e.message;}});
function renderReviewGroups(){
 $('reviewGroupList').innerHTML=reviewGroups.map(g=>'<div class="review-group-row"><div><strong>'+esc(g.label)+'</strong><small>발행 분야 '+esc(sectionLabel[g.target_section]||g.target_section)+' · '+(g.recommend?'추천 후보':'추가 검토')+'</small><p>'+esc(g.keywords.join(', '))+'</p></div><div class="actions"><button data-group-edit="'+esc(g.id)+'">수정</button><button data-group-delete="'+esc(g.id)+'">삭제</button></div></div>').join('')||'';
 const chosen=$('reviewGroup').value;
 $('reviewGroup').innerHTML='<option value="all">전체 그룹</option>'+reviewGroups.map(g=>'<option value="'+esc(g.id)+'">'+esc(g.label)+'</option>').join('');
 $('reviewGroup').value=reviewGroups.some(g=>g.id===chosen)?chosen:'all';
 if(db)render();
}
function clearReviewGroupForm(){editingReviewGroupId=null;$('reviewGroupFormHeading').textContent='추천 그룹 추가';$('reviewGroupName').value='';$('reviewGroupTerms').value='';$('reviewGroupSection').value='industry.policy';$('reviewGroupRecommend').checked=true}
$('cancelReviewGroup').addEventListener('click',clearReviewGroupForm);
$('reviewGroupList').addEventListener('click',async e=>{
 const edit=e.target.closest('[data-group-edit]'),del=e.target.closest('[data-group-delete]');if(!edit&&!del)return;
 const id=(edit||del).dataset[edit?'groupEdit':'groupDelete'],group=reviewGroups.find(g=>g.id===id);if(!group)return;
 if(edit){editingReviewGroupId=id;$('reviewGroupFormHeading').textContent='추천 그룹 수정';$('reviewGroupName').value=group.label;$('reviewGroupTerms').value=group.keywords.join(', ');$('reviewGroupSection').value=group.target_section;$('reviewGroupRecommend').checked=group.recommend;$('reviewGroupName').focus();return}
 if(!confirm('추천 그룹 '+group.label+'을 삭제할까? 저장된 원본·사용자 선택은 유지되며, 재분류 후 새 규칙이 적용돼.'))return;
 try{const r=await api('/api/review-groups/delete',{id});reviewGroups=r.groups;renderReviewGroups();clearReviewGroupForm();$('reviewGroupStatus').textContent='그룹 삭제 완료 · 현재 회차 반영은 재분류 후';}catch(err){$('reviewGroupStatus').textContent=err.message}
});
$('saveReviewGroup').addEventListener('click',async()=>{
 const terms=$('reviewGroupTerms').value.split(/[,\n]+/).map(x=>x.trim()).filter(Boolean);
 try{const r=await api('/api/review-groups/save',{...(editingReviewGroupId?{id:editingReviewGroupId}:{}),label:$('reviewGroupName').value.trim(),target_section:$('reviewGroupSection').value,keywords:terms,recommend:$('reviewGroupRecommend').checked});reviewGroups=r.groups;renderReviewGroups();clearReviewGroupForm();$('reviewGroupStatus').textContent='그룹 저장 완료 · 현재 회차 반영은 재분류 후';}catch(err){$('reviewGroupStatus').textContent=err.message}
});
$('refreshReviewGroups').addEventListener('click',async()=>{
 if(!db||db.edition.status==='confirmed'){$('reviewGroupStatus').textContent='확정된 회차는 재분류할 수 없어.';return}
 try{const r=await api('/api/review-groups/recalculate',{});$('reviewGroupStatus').textContent='규칙 제안 '+r.candidates+'건 재계산 · 기존 수록/수동 편집 유지';await load();}catch(err){$('reviewGroupStatus').textContent=err.message}
});
const brandFields={contact_name:'brandContact',phone:'brandPhone',email:'brandEmail',address:'brandAddress',website:'brandWebsite'};
let brandingDirty=false,defaultContact=null;
for(const id of Object.values(brandFields))$(id).addEventListener('input',()=>{brandingDirty=true});
function showBranding(data){if(data.default_contact||data.sample_contact)defaultContact=data.default_contact||data.sample_contact;$('restoreSampleContact').disabled=!defaultContact;if(!brandingDirty)for(const [key,id] of Object.entries(brandFields))$(id).value=data[key]||'';$('brandingImages').textContent='로고: '+(data.logo_custom?'사용자 이미지':'기본 텍스트')+' · 상단 배너: '+(data.banner_custom?'사용자 이미지':'MVP 이미지')+' · 하단 배너: '+(data.footer_custom?'사용자 이미지':'MVP 이미지')}
$('restoreSampleContact').addEventListener('click',()=>{if(!defaultContact)return;for(const [key,id] of Object.entries(brandFields))$(id).value=defaultContact[key]||'';brandingDirty=true;$('brandingStatus').textContent='기본 연락처 불러옴 · 발행 환경 저장 시 적용'});
$('saveDefaultContact').addEventListener('click',async()=>{const button=$('saveDefaultContact');button.disabled=true;try{const payload=Object.fromEntries(Object.entries(brandFields).map(([k,id])=>[k,$(id).value.trim()]));const r=await api('/api/branding/default-contact',payload);defaultContact=r.default_contact;$('brandingStatus').textContent='기본 연락처 저장 완료 · 발행 설정은 별도 저장'}catch(e){$('brandingStatus').textContent=e.message}finally{button.disabled=false}});
function readBrandImage(file){return new Promise((resolve,reject)=>{if(!file||file.size>1000000){reject(Error('1MB 이하 PNG/JPEG 이미지를 선택하세요.'));return}const mime=/\.png$/i.test(file.name)?'image/png':/\.jpe?g$/i.test(file.name)?'image/jpeg':file.type;if(!['image/jpeg','image/png'].includes(mime)){reject(Error('PNG/JPEG만 등록할 수 있습니다.'));return}const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('이미지 읽기 실패'));reader.readAsDataURL(new Blob([file],{type:mime}))})}
$('saveBranding').addEventListener('click',async()=>{$('saveBranding').disabled=true;$('brandingStatus').textContent='저장 중';try{const payload=Object.fromEntries(Object.entries(brandFields).map(([k,id])=>[k,$(id).value.trim()]));for(const [key,fileId,resetId] of [['logo','brandLogo','resetLogo'],['banner','brandBanner','resetBanner'],['footer','brandFooter','resetFooter']]){if($(resetId).checked&&$(fileId).files.length)throw Error('이미지 선택과 기본 복원을 동시에 지정할 수 없습니다.');if($(resetId).checked)payload[key]='';else if($(fileId).files.length)payload[key]=await readBrandImage($(fileId).files[0])}const res=await api('/api/branding/save',payload);brandingDirty=false;showBranding(res.branding);for(const id of ['brandLogo','brandBanner','brandFooter'])clearDrop(id);for(const id of ['resetLogo','resetBanner','resetFooter'])$(id).checked=false;$('brandingStatus').textContent='저장 완료 · 새 초안 출력에 적용'}catch(err){$('brandingStatus').textContent=err.message}finally{$('saveBranding').disabled=false}});
$('openManagedFiles').addEventListener('click',async()=>{try{await api('/api/files/open',{});$('managedFilesStatus').textContent='탐색기 실행 요청 완료 · 창이 보이지 않으면 경로를 복사해 직접 열어 주세요.'}catch(e){$('managedFilesStatus').textContent=e.message}});
$('copyManagedPath').addEventListener('click',async()=>{const path=$('managedFilesPath').textContent;try{await navigator.clipboard.writeText(path);$('managedFilesStatus').textContent='경로 복사 완료 · 탐색기 주소창에 붙여넣으세요.'}catch(e){const range=document.createRange();range.selectNodeContents($('managedFilesPath'));window.getSelection().removeAllRanges();window.getSelection().addRange(range);$('managedFilesStatus').textContent='경로 선택 완료 · Ctrl+C로 복사하세요.'}});
async function loadSettings(){const r=await fetch('/api/settings');if(!r.ok)throw Error('설정 조회 실패');const j=await r.json();
 $('settingSources').innerHTML=j.sources.map(s=>'<div>'+esc(s.group==='mfds'?'식약처':'언론')+' · '+esc(s.key)+' <span class="muted">'+esc(s.url)+'</span></div>').join('');
 reviewGroups=j.review_groups||[];renderReviewGroups();showBranding(j.branding||{});
 $('managedFilesPath').textContent=j.managed_files?.root||'관리 경로 미확인';$('openManagedFiles').disabled=!j.managed_files?.can_open;$('copyManagedPath').disabled=!j.managed_files?.root;
 aiReady=Boolean(j.ai_api_available);
 $('runAi').disabled=!aiReady||db?.edition?.status==='confirmed'||lastAi==='running';
 $('settingAi').textContent=aiReady?'OPENAI_API_KEY 연결됨 · 유료 API 분석 가능':'OPENAI_API_KEY 미설정';
 if(!aiReady)$('aiJobStatus').textContent='API 미연결';}

$('runAi').addEventListener('click',async()=>{const ids=industryRows().map(x=>x.id);
 if(!ids.length){$('aiJobStatus').textContent='후보가 없어.';return}
 if(!confirm(ids.length+'건을 OpenAI API에 보내 분류 제안을 받을까? API 비용이 발생할 수 있어.'))return;
 try{await api('/api/ai/review',{ids});lastAi='running';$('runAi').disabled=true;$('aiJobStatus').textContent='GPT 분석 중 · '+ids.length+'건'}
 catch(e){$('aiJobStatus').textContent=e.message}});
let lastAi='idle';async function pollAiJob(){try{const r=await fetch('/api/ai/job');if(!r.ok)return;let j=await r.json();
 if(db?.edition&&j.edition_id&&j.edition_id!==db.edition.id)j={state:'idle'};
 $('aiJobStatus').textContent=j.state==='running'?'GPT 분석 진행 중 · '+j.total+'건':j.state==='failed'?'GPT 분석 실패 · '+j.error:j.state==='finished'?'GPT 제안 '+j.processed+'건 저장':(!aiReady?'API 미연결':'분석 대기');
 if(lastAi!==j.state&&j.state==='finished')await load();lastAi=j.state;$('runAi').disabled=!aiReady||db?.edition?.status==='confirmed'||j.state==='running';syncApprovalButtons();}catch(e){}}
setInterval(pollAiJob,2500);
Promise.all([loadSources(),load(),loadSettings(),pollCollection(),pollAiJob(),loadLibrary()]).catch(e=>{$('feedback').textContent=e.message});setInterval(pollCollection,1800);
