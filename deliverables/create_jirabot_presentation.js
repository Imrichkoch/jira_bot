const pptxgen = require('pptxgenjs');
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Imrich Koch';
pptx.company = 'Raizenko';
pptx.subject = 'JiraBot project presentation';
pptx.title = 'JiraBot - AI assistant for Jira and Assets';
pptx.lang = 'sk-SK';
pptx.theme = {
  headFontFace: 'Aptos Display',
  bodyFontFace: 'Aptos',
  lang: 'sk-SK'
};
pptx.defineLayout({ name:'CUSTOM_WIDE', width:13.333, height:7.5 });
pptx.layout = 'CUSTOM_WIDE';
pptx.margin = 0;
pptx.layout = 'LAYOUT_WIDE';
pptx.defineSlideMaster({
  title:'MASTER', background:{color:'081C35'},
  objects:[
    { rect:{ x:0, y:0, w:13.333, h:0.12, fill:{color:'1685F8'}, line:{color:'1685F8'} } },
    { text:{ text:'JiraBot', options:{ x:0.55, y:7.05, w:1.1, h:0.18, fontFace:'Aptos', fontSize:9, color:'7F9AB8', margin:0 } } },
    { text:{ text:'AI assistant for Jira & Assets', options:{ x:10.3, y:7.05, w:2.45, h:0.18, fontFace:'Aptos', fontSize:9, color:'7F9AB8', align:'right', margin:0 } } }
  ],
  slideNumber:{ x:12.85, y:7.02, color:'7F9AB8', fontFace:'Aptos', fontSize:9 }
});

const C={navy:'081C35', panel:'102946', panel2:'143252', blue:'1685F8', teal:'00C2A8', gold:'FFB548', coral:'FF6B6B', white:'F4F8FF', muted:'9CB3CC', line:'24496E', pale:'DCEBFA', ink:'12243A', paper:'F7FAFD', gray:'E7EEF6'};
const S=pptx.ShapeType;
function rect(slide,x,y,w,h,fill,opts={}){ slide.addShape(opts.shape||S.roundRect,{x,y,w,h,rectRadius:opts.radius||0.08,fill:{color:fill,transparency:opts.transparency||0},line:{color:opts.line||fill,transparency:opts.lineTransparency||100,width:opts.lineWidth||0},shadow:opts.shadow?{type:'outer',color:'000000',opacity:0.18,blur:2,offset:1,angle:45}:undefined}); }
function text(slide,t,x,y,w,h,opts={}){ slide.addText(t,{x,y,w,h,fontFace:opts.fontFace||'Aptos',fontSize:opts.fontSize||16,color:opts.color||C.white,bold:opts.bold||false,italic:opts.italic||false,align:opts.align||'left',valign:opts.valign||'mid',margin:opts.margin===undefined?0:opts.margin,breakLine:opts.breakLine,fit:'shrink',paraSpaceAfterPt:opts.paraSpaceAfterPt||0,bullet:opts.bullet,transparency:opts.transparency}); }
function title(slide,kicker,heading,sub=''){ text(slide,kicker.toUpperCase(),0.7,0.5,3.5,0.24,{fontSize:10,color:C.teal,bold:true}); text(slide,heading,0.7,0.82,11.7,0.55,{fontSize:29,bold:true}); if(sub) text(slide,sub,0.72,1.45,11.4,0.32,{fontSize:13,color:C.muted}); }
function icon(slide,label,x,y,color){ slide.addShape(S.ellipse,{x,y,w:0.52,h:0.52,fill:{color},line:{color,transparency:100}}); text(slide,label,x,y+0.015,0.52,0.47,{fontSize:14,bold:true,align:'center'}); }
function card(slide,x,y,w,h,head,body,accent=C.blue){ rect(slide,x,y,w,h,C.panel,{line:C.line,lineTransparency:0,shadow:true}); rect(slide,x,y,0.09,h,accent,{shape:S.rect}); text(slide,head,x+0.28,y+0.22,w-0.5,0.32,{fontSize:16,bold:true}); text(slide,body,x+0.28,y+0.68,w-0.52,h-0.85,{fontSize:12.5,color:C.muted,valign:'top'}); }
function bulletLines(slide,items,x,y,w,h,color=C.white,size=14){ const runs=[]; items.forEach((it,i)=>runs.push({text:it,options:{bullet:{indent:15},breakLine:i<items.length-1,indent:15, hanging:3}})); slide.addText(runs,{x,y,w,h,fontFace:'Aptos',fontSize:size,color,margin:0,breakLine:true,paraSpaceAfterPt:7,fit:'shrink'}); }

// 1. Title
{
 const s=pptx.addSlide('MASTER');
 s.background={color:C.navy};
 s.addShape(S.arc,{x:8.25,y:-1.5,w:6.3,h:6.3,adjustPoint:0.25,line:{color:C.blue,transparency:35,width:2},rotate:23});
 s.addShape(S.arc,{x:9.2,y:-0.5,w:4.3,h:4.3,adjustPoint:0.25,line:{color:C.teal,transparency:10,width:1.5},rotate:23});
 text(s,'JiraBot',0.72,1.45,6.5,0.82,{fontSize:46,bold:true});
 text(s,'AI asistent pre Jira, Assets a IT procesy',0.74,2.43,6.8,0.45,{fontSize:21,color:C.pale});
 text(s,'Od prirodzenej otázky až po ticket, priradenie zariadenia a pripravený protokol.',0.76,3.12,6.35,0.6,{fontSize:15,color:C.muted,valign:'top'});
 const stats=[['JIRA','tickety a používatelia'],['ASSETS','notebooky a evidencia'],['AI','chat v slovenčine']];
 stats.forEach((a,i)=>{const x=0.75+i*2.26; rect(s,x,4.55,2.0,1.02,C.panel,{line:C.line,lineTransparency:0}); text(s,a[0],x+0.18,4.72,1.65,0.26,{fontSize:13,bold:true,color:i===0?C.blue:i===1?C.teal:C.gold}); text(s,a[1],x+0.18,5.05,1.65,0.26,{fontSize:10.3,color:C.muted});});
 text(s,'Projektová prezentácia | Imrich Koch',0.76,6.4,5.5,0.3,{fontSize:12,color:C.muted});
}

// 2. Problem / answer
{
 const s=pptx.addSlide('MASTER'); title(s,'Prečo tento projekt','IT agenda je roztrúsená. JiraBot ju spája do jedného rozhovoru.');
 card(s,0.75,2.05,3.75,3.8,'Dnes: veľa kontextových prepnutí','Ticket v Jira. Zariadenie v Assets. Informácie v komentároch. Protokol v súbore. Každý krok je samostatná manuálna úloha.',C.coral);
 card(s,4.8,2.05,3.75,3.8,'JiraBot: jedna požiadavka','Používateľ napíše bežnú vetu. Bot rozpozná zámer, načíta kontext a vykoná bezpečnú akciu alebo sa dopyta.',C.blue);
 card(s,8.85,2.05,3.75,3.8,'Výsledok: riadený proces','Menej klikov, menej prepisovania dát a jasnejší onboarding či offboarding zariadení.',C.teal);
 text(s,'Cieľ nie je nahradiť Jira. Cieľ je spraviť Jira použiteľnejšou v každodennej práci.',0.78,6.25,11.8,0.35,{fontSize:16,color:C.pale,italic:true});
}

// 3. Capabilities
{
 const s=pptx.addSlide('MASTER'); title(s,'Funkcie','Čo vie používateľ vybaviť priamo cez chat');
 const items=[
  ['01','Ticket intelligence','Vyhľadanie, zoznam, stav a súhrn ticketu vrátane komentárov.',C.blue],
  ['02','Akcie v Jira','Vytvorenie, priradenie a uzavretie ticketu s kontrolou kontextu.',C.teal],
  ['03','Assets lookup','Zistí, aké zariadenia má konkrétny používateľ priradené.',C.gold],
  ['04','Dokumenty','Onboarding/offboarding PDF alebo DOCX z administrátorskej šablóny.',C.coral],
  ['05','Používatelia','Rozpozná prihláseného Jira používateľa a frázu „mne“.',C.blue],
  ['06','Admin riadenie','Skupiny, práva, model, systémový prompt a skills.md.',C.teal]
 ];
 items.forEach((it,i)=>{const col=i%3,row=Math.floor(i/3),x=0.76+col*4.12,y=2.05+row*2.02; rect(s,x,y,3.72,1.55,C.panel,{line:C.line,lineTransparency:0}); icon(s,it[0],x+0.28,y+0.28,it[3]); text(s,it[1],x+0.95,y+0.27,2.5,0.28,{fontSize:15,bold:true}); text(s,it[2],x+0.28,y+0.8,3.1,0.5,{fontSize:11.2,color:C.muted,valign:'top'}); });
}

// 4. Demo
{
 const s=pptx.addSlide('MASTER'); title(s,'Demo scenár','Od otázky po výsledok za pár sekúnd');
 const steps=[
  ['1','Otvor ticket','„Zhrň tiket KAN-4“',C.blue],
  ['2','AI načíta kontext','Popis, stav, priorita, riešiteľ a komentáre.',C.teal],
  ['3','Bot vytvorí odpoveď','TL;DR, riziká a odporúčaný ďalší krok.',C.gold],
  ['4','Používateľ rozhodne','Pokračuje, priradí ticket alebo vytvorí ďalšiu akciu.',C.coral]
 ];
 steps.forEach((a,i)=>{const x=0.72+i*3.18; rect(s,x,2.05,2.72,2.82,C.panel,{line:C.line,lineTransparency:0,shadow:true}); icon(s,a[0],x+0.25,2.33,a[3]); text(s,a[1],x+0.27,3.08,2.1,0.3,{fontSize:16,bold:true}); text(s,a[2],x+0.27,3.6,2.16,0.68,{fontSize:12.3,color:C.muted,valign:'top'}); if(i<3){s.addShape(S.chevron,{x:x+2.82,y:3.08,w:0.34,h:0.55,fill:{color:C.line},line:{color:C.line}});} });
 rect(s,0.76,5.5,11.8,0.68,C.panel2,{line:C.line,lineTransparency:0}); text(s,'Dôležité: rizikové akcie sa nepotvrdzujú automaticky. Pri hromadnom priradení bot najprv vyžiada „áno“.',1.02,5.68,11.25,0.28,{fontSize:14,color:C.pale,bold:true,align:'center'});
}

// 5 documents
{
 const s=pptx.addSlide('MASTER'); title(s,'Onboarding & offboarding','Assets a dokumentácia sú jeden riadený tok');
 // device panel
 rect(s,0.75,2.0,3.4,3.95,C.panel,{line:C.line,lineTransparency:0,shadow:true}); text(s,'Jira Assets',1.03,2.35,2.5,0.35,{fontSize:20,bold:true});
 const deviceRows=[['Laptop Dell Latitude 7440','CDX-4'],['Owner','Imrich Koch'],['Serial number','DL7440-2026-001']];
 deviceRows.forEach((r,i)=>{text(s,r[0],1.04,3.05+i*0.7,1.7,0.24,{fontSize:10.5,color:C.muted}); text(s,r[1],2.5,3.05+i*0.7,1.25,0.24,{fontSize:11.4,bold:true,align:'right'}); s.addShape(S.line,{x:1.02,y:3.38+i*0.7,w:2.75,h:0,line:{color:C.line,width:1}});});
 // arrows and doc
 s.addShape(S.chevron,{x:4.55,y:3.43,w:0.62,h:0.62,fill:{color:C.blue},line:{color:C.blue}});
 rect(s,5.55,1.9,3.0,4.1,C.paper,{line:C.gray,lineTransparency:0,shadow:true}); text(s,'PREBERACÍ\nPROTOKOL',5.9,2.35,2.3,0.65,{fontSize:18,bold:true,color:C.ink,align:'center'}); text(s,'Meno: Imrich Koch\n\nZariadenie: Dell Latitude 7440\n\nSériové číslo: DL7440-2026-001',5.9,3.45,2.2,1.35,{fontSize:11.5,color:'334B66',valign:'top'}); s.addShape(S.line,{x:5.92,y:5.24,w:2.2,h:0,line:{color:'B4C4D5',width:1}}); text(s,'Podpis: __________________',5.9,5.45,2.25,0.22,{fontSize:10,color:'617895'});
 s.addShape(S.chevron,{x:8.95,y:3.43,w:0.62,h:0.62,fill:{color:C.teal},line:{color:C.teal}});
 card(s,9.92,2.35,2.55,3.2,'Kontrolovaný výsledok','1. Používateľ vyberie zariadenie.\n\n2. Bot vytvorí dokument.\n\n3. Assets sa priradí alebo odoberie.',C.teal);
}

// 6 arch
{
 const s=pptx.addSlide('MASTER'); title(s,'Technická architektúra','Oddelené rozhranie, logika, integrácie a dáta');
 const cols=[
  ['Jira Cloud','Forge issue panel\nAktuálny ticket\nIdentita používateľa',C.blue],
  ['JiraBot API','FastAPI backend\nKlasifikácia zámeru\nBezpečné workflow',C.teal],
  ['Integrácie','Jira REST API\nJira Assets API\nAI provider',C.gold],
  ['Dáta','SQLite: admin a práva\nŠablóny dokumentov\nPodpísané downloady',C.coral]
 ];
 cols.forEach((a,i)=>{const x=0.73+i*3.18; rect(s,x,2.2,2.72,3.55,C.panel,{line:C.line,lineTransparency:0,shadow:true}); rect(s,x,2.2,2.72,0.18,a[2],{shape:S.rect}); text(s,a[0],x+0.24,2.67,2.15,0.35,{fontSize:17,bold:true}); text(s,a[1],x+0.24,3.45,2.15,1.3,{fontSize:12.6,color:C.muted,valign:'top'}); if(i<3){s.addShape(S.chevron,{x:x+2.78,y:3.62,w:0.3,h:0.45,fill:{color:C.line},line:{color:C.line}});} });
 text(s,'Forge prenáša iba potrebný kontext. Backend vykonáva integrácie a rozhoduje podľa práv používateľa.',0.78,6.25,11.7,0.32,{fontSize:14.5,color:C.pale,align:'center'});
}

// 7 security
{
 const s=pptx.addSlide('MASTER'); title(s,'Bezpečnosť a kontrola','AI nerobí zápisy bez jasného oprávnenia a kontextu');
 const layers=[
  ['1','Práva používateľa','Skupiny určujú, kto môže čítať tickety, pracovať s Assets alebo generovať dokumenty.',C.blue],
  ['2','Forge + widget secret','Panel a backend komunikujú cez overenú integračnú cestu.',C.teal],
  ['3','Podpísané workflow','Rozpracované akcie majú HMAC podpis; klient ich nemôže podvrhnúť.',C.gold],
  ['4','Bezpečné potvrdenie','Hromadné priradenie čaká na samostatné potvrdenie „áno“.',C.coral],
  ['5','Dokumenty','Súbory používajú časovo obmedzené podpísané URL.',C.blue]
 ];
 layers.forEach((a,i)=>{const y=1.95+i*0.85; rect(s,0.8,y,11.7,0.62,C.panel,{line:C.line,lineTransparency:0}); icon(s,a[0],1.02,y+0.05,a[3]); text(s,a[1],1.78,y+0.12,2.6,0.24,{fontSize:14.5,bold:true}); text(s,a[2],4.15,y+0.12,7.8,0.24,{fontSize:12.2,color:C.muted});});
}

// 8 testing
{
 const s=pptx.addSlide('MASTER'); title(s,'Overené scenáre','Testovanie bolo súčasťou implementácie, nie až posledný krok');
 const tests=[['Chat v slovenčine','Preklepy, vágne otázky, otázky mimo kontextu a bezpečné fallbacky.',C.blue],['Jira actions','Vyhľadanie, súhrn, priradenie, uzavretie a práca s kontextom ticketu.',C.teal],['Assets','Vyhľadanie notebookov používateľa a kontrola priradenia/odobratia.',C.gold],['Dokumenty','Upload DOCX/PDF, polia, render, overenie obsahu a cleanup šablón.',C.coral]];
 tests.forEach((a,i)=>{const x=i%2?6.77:0.77,y=i<2?2.0:4.1; rect(s,x,y,5.78,1.5,C.panel,{line:C.line,lineTransparency:0,shadow:true}); icon(s,String(i+1).padStart(2,'0'),x+0.27,y+0.28,a[2]); text(s,a[0],x+1.0,y+0.25,4.3,0.28,{fontSize:16,bold:true}); text(s,a[1],x+1.0,y+0.73,4.2,0.48,{fontSize:11.8,color:C.muted,valign:'top'});});
 text(s,'Princíp testovania: najprv bezpečné čítanie, potom potvrdený zápis, následne kontrola výsledného stavu.',0.82,6.32,11.6,0.3,{fontSize:14.5,color:C.pale,align:'center'});
}

// 9 status roadmap
{
 const s=pptx.addSlide('MASTER'); title(s,'Stav a ďalší rozvoj','Funkčný základ je hotový. Ďalší krok je produkčné spevnenie.');
 const left=['Hotovo','Forge panel v Jira','Jira + Assets integrácia','Onboarding/offboarding dokumenty','Admin rozhranie a práva'];
 const right=['Ďalší krok','Auditné logy a monitoring','Rotácia tokenov a backup','Lepšie šablóny / vizuálny editor','Rozšírenie na ďalšie Jira projekty'];
 [[0.75,left,C.teal],[6.85,right,C.gold]].forEach(([x,a,accent])=>{rect(s,x,2.0,5.72,3.9,C.panel,{line:C.line,lineTransparency:0,shadow:true}); rect(s,x,2.0,5.72,0.13,accent,{shape:S.rect}); text(s,a[0],x+0.35,2.45,4.8,0.35,{fontSize:22,bold:true,color:accent}); bulletLines(s,a.slice(1),x+0.4,3.18,4.85,2.1,C.pale,13.5);});
}

// 10 conclusion
{
 const s=pptx.addSlide('MASTER');
 s.background={color:C.navy};
 s.addShape(S.arc,{x:-1.3,y:2.2,w:5.0,h:5.0,adjustPoint:0.25,line:{color:C.teal,transparency:20,width:2},rotate:140});
 s.addShape(S.arc,{x:9.4,y:-1.5,w:5.7,h:5.7,adjustPoint:0.25,line:{color:C.blue,transparency:15,width:2},rotate:320});
 text(s,'JiraBot premieňa\nJira z formulára na rozhovor.',1.1,1.55,8.8,1.15,{fontSize:35,bold:true});
 text(s,'Jedna platforma. Jeden kontext. Menej manuálnej práce.',1.12,3.05,7.3,0.35,{fontSize:17,color:C.pale});
 const final=[['Jira','pracovné tikety'],['Assets','zariadenia'],['AI','prirodzený jazyk'],['Docs','on/offboarding']];
 final.forEach((a,i)=>{const x=1.12+i*2.48; rect(s,x,4.3,2.14,1.0,C.panel,{line:C.line,lineTransparency:0}); text(s,a[0],x+0.18,4.53,1.72,0.24,{fontSize:15,bold:true,color:i===0?C.blue:i===1?C.teal:i===2?C.gold:C.coral,align:'center'}); text(s,a[1],x+0.18,4.86,1.72,0.2,{fontSize:10.4,color:C.muted,align:'center'});});
 text(s,'Ďakujem',1.12,6.25,3.0,0.35,{fontSize:20,bold:true});
 text(s,'Otázky?',10.25,6.25,2.0,0.35,{fontSize:20,color:C.teal,bold:true,align:'right'});
}

pptx.writeFile({ fileName: 'D:/download/jira-ai-ticket-bot/deliverables/JiraBot_prezentacia.pptx' });
