(function(){
  'use strict';
  const $ = (id) => document.getElementById(id);
  const q = (s, root=document) => [...root.querySelectorAll(s)];

  const style = document.createElement('style');
  style.id = 'pipslife-ui-refresh';
  style.textContent = `
    :root{--ui-bg:#03101b;--ui-panel:#071a2a;--ui-panel2:#081f31;--ui-line:#12344b;--ui-cyan:#28d9ff;--ui-green:#22ef93;--ui-purple:#6f6cff;--ui-muted:#91a7b8}
    html{scroll-behavior:smooth;scroll-padding-top:8px}
    body{background:linear-gradient(180deg,#020a13 0%,#03111d 42%,#020a12 100%);overflow-x:hidden}
    main{width:min(100%,1080px);padding:8px 10px 112px}
    .top{padding:3px 1px 8px;gap:8px;min-height:58px}
    .brand{gap:8px}.brandmark{width:36px;height:36px;border-radius:10px;box-shadow:none}.brandmark svg{width:26px;height:26px}
    .brand h1{font-size:22px;letter-spacing:-.7px}.brand h1 span{display:none}.brand p{font-size:9px;margin-top:3px;color:#9ab0c1}
    .connection{min-width:auto;padding:7px 9px;border-radius:10px;box-shadow:none}.connection strong{font-size:10px}.connection small{font-size:8px}.gear{font-size:19px}
    .topnav{display:none}
    .hero{grid-template-columns:minmax(150px,1fr) minmax(145px,1.15fr) minmax(110px,.7fr);gap:10px;margin:6px 0 7px;padding:10px 11px;border:1px solid #143750;border-radius:11px;box-shadow:none}
    .gold{width:54px;height:54px;border-radius:10px}.gold svg{width:40px}.asset{gap:9px}.asset h2{font-size:20px}.asset small{font-size:11px}.strategyTitle{font-size:16px;line-height:1.1}.pill{font-size:9px;padding:4px 7px;margin-bottom:4px}.powered{font-size:9px;margin-top:3px}.run{padding-left:9px;gap:7px}.run .bigdot{width:25px;height:25px;border-width:6px;box-shadow:none}.run strong{font-size:11px}.run small{font-size:8px}
    .grid3{grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.card{border:1px solid #103149;border-radius:10px;box-shadow:none;background:linear-gradient(145deg,rgba(7,25,40,.99),rgba(4,16,27,.99))}.pad{padding:10px}.title{font-size:13px;margin-bottom:7px}.title small{font-size:8px}.price{font-size:25px}.change{font-size:11px}.range{font-size:8px;margin-top:8px}.spark{height:42px;gap:2px}.spark i{width:4px}
    .dealer{font-size:8px}.meter{height:12px}.meter:after{height:20px;top:-4px}.dealerValue{font-size:12px;margin-top:6px}.dealerSub{font-size:8px}.sentiment{gap:7px}.ring{width:55px;height:55px}.ring:after{width:40px;height:40px}.sentiment strong{font-size:13px}.sentiment small{font-size:8px}
    .flowCard{margin-top:7px}.flowHead{padding:10px;gap:7px}.flowHead h3{font-size:15px}.flowHead p{font-size:9px;margin-top:3px}.actions{gap:5px}.entry,.aligned{padding:6px 8px;font-size:9px}
    .greeks{min-width:700px}.greeks th{font-size:8px;padding:8px 5px}.greeks td{font-size:9px;padding:7px 5px}.strike{font-size:11px}.metricState{font-size:8px;margin:2px 0 4px}.bar{height:4px}.confluence{font-size:11px}.statusbar{padding:7px 10px!important;font-size:8px!important}
    .lower{grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:7px}.chart{height:112px;gap:5px;padding:7px 5px 14px}.chartCol{gap:3px}.chartCol em{font-size:7px}.chartCol i{width:19px}.logic p{font-size:9px;line-height:1.4}.plan .side{font-size:12px}.plan dl{grid-template-columns:42px 1fr;gap:5px;margin-top:8px;font-size:9px}.confidence{margin-top:9px;padding:7px;font-size:9px}
    .realtime{margin-top:7px}.flowTable th,.flowTable td{padding:6px 6px;font-size:8px}
    .account,.updateCard{margin-top:7px}.accountGrid{gap:7px}.input{padding:9px;font-size:10px}.btn{padding:10px;font-size:10px}.notice{font-size:8px}.updateLine strong{font-size:11px}.updateState{font-size:8px}.updateBtn{padding:7px 9px;font-size:9px}
    .controls{display:none!important}
    .bottom{padding:5px 8px calc(5px + env(safe-area-inset-bottom));background:rgba(3,12,21,.97);border-top:1px solid #14334a;box-shadow:0 -8px 25px rgba(0,0,0,.2);grid-template-columns:repeat(5,1fr)}
    .bottom button{font-size:8px;padding:4px 2px}.bottom button span{font-size:17px;line-height:17px;margin-bottom:2px}.bottom button.active{background:rgba(80,92,255,.14);color:#8d95ff}
    #pipslifeActionDock{position:fixed;left:10px;right:10px;bottom:61px;z-index:30;display:grid;grid-template-columns:1.25fr 1.25fr .8fr;gap:6px;padding:6px;background:rgba(4,16,27,.97);border:1px solid #123750;border-radius:12px;box-shadow:0 7px 25px rgba(0,0,0,.35);backdrop-filter:blur(12px)}
    #pipslifeActionDock button{border:0;border-radius:9px;padding:9px 6px;color:#fff;font-size:10px;font-weight:850;min-height:34px}
    #pipslifeActionDock .startProxy{background:linear-gradient(135deg,#08c9f4,#087fc5)}
    #pipslifeActionDock .stopProxy{background:linear-gradient(135deg,#f34870,#b7193e)}
    #pipslifeActionDock .updateProxy{background:#0a293d;border:1px solid #167fad;color:#6adfff}
    #pipslifeStrategyBar{display:flex;align-items:center;gap:5px;margin:0 0 7px;padding:5px;background:#061522;border:1px solid #10334a;border-radius:9px}
    #pipslifeStrategyBar .label{font-size:8px;color:#7f99ac;margin-right:auto;text-transform:uppercase;letter-spacing:.7px}
    #pipslifeStrategyBar button{border:1px solid #173d57;background:#071c2c;color:#8fa6b8;border-radius:7px;padding:5px 10px;font-size:9px;font-weight:800}
    #pipslifeStrategyBar button.active{color:#fff;background:linear-gradient(135deg,#1647aa,#4739b5);border-color:#5b64ff}
    #pipslifePageHint{font-size:8px;color:#738da0;margin:0 1px 6px}
    @media(max-width:720px){
      main{padding:7px 8px 112px}.hero{grid-template-columns:1fr 1fr;align-items:center}.run{grid-column:1/-1;border-left:0;border-top:1px solid #12344b;padding:7px 0 0}.grid3{grid-template-columns:repeat(3,minmax(0,1fr))}.lower{grid-template-columns:1fr 1fr}.lower .plan{grid-column:1/-1}.chart{height:105px}
    }
    @media(max-width:430px){
      .top{min-height:51px}.brandmark{display:none}.brand h1{font-size:20px}.brand p{font-size:8px}.connection small{display:none}.connection{padding:6px 8px}.gear{font-size:17px}
      .hero{grid-template-columns:1fr 1fr;gap:7px;padding:8px}.asset h2{font-size:18px}.asset small{font-size:9px}.gold{width:44px;height:44px}.gold svg{width:32px}.strategyTitle{font-size:13px}.powered{font-size:8px}.run{padding-top:6px}
      .grid3{gap:5px}.pad{padding:8px}.title{font-size:11px}.price{font-size:20px}.change{font-size:9px}.range{font-size:7px}.spark{height:32px}.dealer{font-size:7px}.dealerValue{font-size:10px}.dealerSub{font-size:7px}.ring{width:44px;height:44px}.ring:after{width:32px;height:32px}.sentiment strong{font-size:10px}.sentiment small{font-size:7px}
      .flowHead h3{font-size:13px}.flowHead p{font-size:8px}.entry,.aligned{font-size:8px;padding:5px 6px}.greeks{min-width:660px}.greeks th{font-size:7px}.greeks td{font-size:8px}.lower{gap:5px}.logic p{font-size:8px}.plan dl{font-size:8px}.confidence{font-size:8px}
      #pipslifeActionDock{left:7px;right:7px;bottom:57px;gap:4px;padding:5px}#pipslifeActionDock button{font-size:9px;padding:8px 4px}
    }
  `;
  document.head.appendChild(style);

  const brandTitle = document.querySelector('.brand h1');
  if(brandTitle) brandTitle.innerHTML = 'Pips-life';
  const brandMotto = document.querySelector('.brand p');
  if(brandMotto) brandMotto.textContent = 'Life-changing pips';

  const topnav = document.querySelector('.topnav');
  if(topnav) topnav.setAttribute('aria-hidden','true');

  const hero = document.querySelector('.hero');
  if(hero && !$('pipslifeStrategyBar')){
    const bar=document.createElement('div'); bar.id='pipslifeStrategyBar';
    bar.innerHTML='<span class="label">Active strategy</span><button type="button" data-strategy="001" class="active">STRATEGY 001</button><button type="button" data-strategy="002">STRATEGY 002</button>';
    hero.parentNode.insertBefore(bar,hero);
    bar.querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>setStrategy(btn.dataset.strategy)));
  }

  if(hero && !$('pipslifePageHint')){
    const hint=document.createElement('div'); hint.id='pipslifePageHint'; hint.textContent='Home • Live trading dashboard';
    hero.parentNode.insertBefore(hint,hero);
  }

  function setStrategy(id){
    const num=String(id).padStart(3,'0');
    q('#pipslifeStrategyBar button').forEach(b=>b.classList.toggle('active',b.dataset.strategy===num));
    q('.pill').forEach(el=>el.textContent='Strategy '+num);
    q('.statusbar b').forEach(el=>el.textContent='Strategy '+num);
    const hint=$('pipslifePageHint');
    if(hint) hint.textContent='Strategy '+num+' selected • UI selection only';
    const title=document.querySelector('.strategyTitle');
    if(title) title.textContent=num==='002'?'Momentum / Flow Strategy':'Quantitative Options Flow';
    const logic=$('dealerLogic');
    if(logic && num==='002') logic.textContent='Strategy 002 selected. This screen now follows the selected strategy presentation; trading-engine behaviour remains unchanged.';
    if(logic && num==='001') logic.textContent='Waiting for live dealer-flow data. Once permitted FlashAlpha data is available, this panel will explain the positioning signal without changing the trading engine.';
    localStorage.setItem('pipslifeSelectedStrategy',num);
  }

  const selected=localStorage.getItem('pipslifeSelectedStrategy')||'001';
  setTimeout(()=>setStrategy(selected),0);

  if(!$('pipslifeActionDock')){
    const dock=document.createElement('div');dock.id='pipslifeActionDock';
    dock.innerHTML='<button class="startProxy">▶ START BOT</button><button class="stopProxy">■ STOP BOT</button><button class="updateProxy">↻ UPDATE</button>';
    document.body.appendChild(dock);
    dock.querySelector('.startProxy').onclick=()=>{const b=$('start');if(b)b.click();};
    dock.querySelector('.stopProxy').onclick=()=>{const b=$('stop');if(b)b.click();};
    dock.querySelector('.updateProxy').onclick=()=>{const b=$('updateButton');if(b)b.click();else if(window.AndroidBot?.checkForUpdate)window.AndroidBot.checkForUpdate();};
  }

  const targets={Home:'home',Bots:'bots',Markets:'markets',Update:'update',Account:'accountSection'};
  q('.bottom button').forEach(btn=>{
    const text=(btn.textContent||'').trim().split(/\s+/).pop();
    const target=targets[text]||btn.dataset.target;
    if(target) btn.dataset.target=target;
    btn.onclick=()=>{
      const el=$(btn.dataset.target); if(!el)return;
      el.scrollIntoView({behavior:'smooth',block:'start'});
      q('.bottom button').forEach(x=>x.classList.toggle('active',x===btn));
    };
  });

  q('#bots,#markets,#update,#accountSection').forEach(el=>{el.style.scrollMarginTop='8px';});

  setInterval(()=>{
    const p=$('price')?.textContent||'—';
    if($('planEntry')) $('planEntry').textContent=p;
    const stop=$('stop')?.textContent||'—';
    if($('planSL')) $('planSL').textContent=stop;
    const pos=$('position')?.textContent||'—';
    if($('planPositions')) $('planPositions').textContent=pos==='—'?'0 / 4':pos+'/4';
  },700);
})();
