(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const isGitHubPages = location.hostname.endsWith('.github.io');
  const deployDefault = document.querySelector('meta[name=clipforge-backend]')?.content?.trim() || '';
  const storedEngine = (deployDefault.startsWith('https://') ? deployDefault : '') || localStorage.getItem('clipforge_engine_v2') || '';
  const savedProjectsKey = 'clipforge_public_projects_v1';
  const savedProjects = () => { try{return JSON.parse(localStorage.getItem(savedProjectsKey)||'{}');}catch(_){return {};} };
  const tokenFor = id => savedProjects()[`${state.apiBase}:${id}`] || '';
  const rememberProject = p => {if(!p.access_token)return;const all=savedProjects();all[`${state.apiBase}:${p.id}`]=p.access_token;localStorage.setItem(savedProjectsKey,JSON.stringify(all));};
  const forgetProject = id => {const all=savedProjects();delete all[`${state.apiBase}:${id}`];localStorage.setItem(savedProjectsKey,JSON.stringify(all));};
  const privateVideoPath = (id,url) => `${serverPath(url)}?token=${encodeURIComponent(tokenFor(id))}`;
  async function myProjects(){const ids=Object.keys(savedProjects()).filter(key=>key.startsWith(`${state.apiBase}:`)).map(k=>k.substring(state.apiBase.length+1));const projects=await Promise.all(ids.map(id=>api(`/api/projects/${id}`).catch(()=>null)));return projects.filter(Boolean).sort((a,b)=>b.created-a.created);}
  const state = {file:null, url:'', aspect:'9:16', project:null, polling:null, editing:null, capabilities:null, mode:'clip', apiBase:storedEngine};
  const serverPath = path => `${state.apiBase}${path}`;
  const mediaPath = path => state.apiBase && path?.startsWith('/') ? serverPath(path) : path;
  const serverError = () => isGitHubPages && !state.apiBase
    ? 'Video server not connected. Click Engine settings to connect your Python backend.'
    : 'ClipForge video server is offline. Start Python app.py or check Engine settings.';

  const escapeHTML = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seconds = (value) => {let s=Math.floor(Number(value)||0);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
  const formatDate = ts => new Date(ts * 1000).toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'});
  let toastTimer;
  function toast(message, error=false){const el=$('toast');el.textContent=message;el.className=`toast visible${error?' error':''}`;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visible'),5000);}
  async function api(path, options={}){
    let response;
    if (isGitHubPages && !state.apiBase) throw new Error(serverError());
    try {
      const match=path.match(/^\/api\/projects\/([a-z0-9]+)/);
      if(match){const token=tokenFor(match[1]);if(token){options={...options,headers:{...(options.headers||{}),'X-Project-Token':token}};}}
      response=await fetch(serverPath(path),options);
    } catch (_) {throw new Error(serverError());}
    let value;
    try {value=await response.json();}catch(_){throw new Error(`Server returned ${response.status}; check the backend URL.`);}
    if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:`Request failed (${response.status})`);
    return value;
  }
  async function loadCapabilities(){
    try {
      const r=await api('/api/health');state.capabilities=r;
      $('engineStatus').innerHTML=`<span class="live-circle" style="background:${r.ffmpeg?'#a4fa86':'#ff7777'}"></span> ${r.ffmpeg?'Engine connected':'FFmpeg is missing'}`;
      $('sideEngineLabel').textContent=r.ffmpeg?'Connected':'FFmpeg missing';
      $('urlHint').textContent=r.link_import?'YouTube import enabled for permitted public videos. Live or restricted links can fail.':'YouTube import is unavailable. Install yt-dlp on the server.';
      $('captionHint').textContent=r.automatic_captions?'Whisper available':'Install faster-whisper';
      $('captionsSwitch').disabled=!r.automatic_captions;
      if(!r.ffmpeg)toast('FFmpeg is required to process videos. See README.md for setup.',true);
    }catch(e){state.capabilities=null;$('engineStatus').innerHTML='<span class="live-circle" style="background:#ff7777"></span> Engine not connected';$('sideEngineLabel').textContent='Not connected';$('urlHint').textContent=isGitHubPages?'Connect a backend server in Engine settings to enable video clipping.':'Start ClipForge Python server to enable clipping.';}
  }
  function showSite(site){
    const studio=site==='studio'; const pricing=site==='pricing'; $('site').classList.toggle('hidden',studio||pricing);$('studio').classList.toggle('hidden',!studio);$('pricingPage').classList.toggle('hidden',!pricing);
    if(studio){window.scrollTo(0,0);showTab('create');loadCapabilities();refreshProjectCount();}
    else{window.scrollTo(0,0);}
  }
  function navigate(route){
    const target=['studio','pricing'].includes(route)?route:'home';
    history.pushState({},'',`${location.pathname}#${target}`);showSite(target);
  }
  document.querySelectorAll('[data-navigate]').forEach(el=>el.addEventListener('click',e=>{e.preventDefault();navigate(el.dataset.navigate);}));
  function showTab(tab){
    clearInterval(state.polling);
    const id={create:'createPanel',projects:'projectsPanel',results:'resultsPanel',guide:'guidePanel'};
    Object.values(id).forEach(v=>$(v).classList.add('hidden'));
    $(id[tab]||id.create).classList.remove('hidden');
    document.querySelectorAll('.sidebar-item').forEach(el=>el.classList.toggle('active',el.dataset.tab===tab||(tab==='results'&&el.dataset.tab==='projects')));
    $('breadcrumb').textContent={create:'Create clips',projects:'My projects',results:'Your highlights',guide:'Getting started'}[tab]||'Create clips';
    if(tab==='projects')loadProjects();
    window.scrollTo(0,0);
  }
  document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>showTab(button.dataset.tab)));
  $('mobileMenu').addEventListener('click',()=>document.querySelector('.nav-center').classList.toggle('mobile-open'));
  document.querySelector('.nav-center').querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>document.querySelector('.nav-center').classList.remove('mobile-open')));
  function pickFile(){ $('filePicker').click(); }
  function setFile(file){
    if(!file)return;
    if(!/\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name)){toast('Choose an MP4, MOV, MKV, WebM, AVI or M4V video.',true);return;}
    if(file.size>150*1024*1024){toast('Public beta limit is 150 MB per video.',true);return;}
    state.file=file;state.url='';$('studioUrl').value='';
    $('selectedFile').classList.remove('hidden');$('selectedFile').textContent=`✓ ${file.name} · ${(file.size/(1024*1024)).toFixed(1)} MB`;
    $('dropTitle').textContent='Video selected — ready to create';$('dropSubtitle').textContent='Click to choose a different file';
  }
  $('filePicker').addEventListener('change',e=>{if(e.target.files?.[0]){if($('studio').classList.contains('hidden'))navigate('studio');setFile(e.target.files[0]);}});
  $('heroUpload').addEventListener('click',pickFile);$('browseButton').addEventListener('click',e=>{e.stopPropagation();pickFile();});
  $('fileDrop').addEventListener('click',e=>{if(e.target.closest('button'))return;pickFile();});
  $('fileDrop').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();pickFile();}});
  $('fileDrop').addEventListener('dragover',e=>{e.preventDefault();$('fileDrop').classList.add('dragging');});
  $('fileDrop').addEventListener('dragleave',()=>$('fileDrop').classList.remove('dragging'));
  $('fileDrop').addEventListener('drop',e=>{e.preventDefault();$('fileDrop').classList.remove('dragging');setFile(e.dataTransfer.files?.[0]);});
  document.querySelectorAll('.ratio-option').forEach(button=>button.addEventListener('click',()=>{state.aspect=button.dataset.ratio;document.querySelectorAll('.ratio-option').forEach(b=>b.classList.toggle('active',b===button));}));
  document.querySelectorAll('.creator-tab').forEach(button=>button.addEventListener('click',()=>{state.mode=button.dataset.mode;document.querySelectorAll('.creator-tab').forEach(b=>b.classList.toggle('active',b===button));if(state.mode==='auto'){toast('Auto-edit uses audio-based highlight suggestions. AI B-roll and speech cleanup are not included.');}}));
  $('studioUrl').addEventListener('input',e=>{state.url=e.target.value.trim();if(state.url){state.file=null;$('selectedFile').classList.add('hidden');$('dropTitle').textContent='Drop your video here, or click to browse';$('dropSubtitle').textContent='MP4, MOV, MKV, WebM, AVI, M4V · Up to 150 MB';}});
  $('studioUrlButton').addEventListener('click',()=>{state.url=$('studioUrl').value.trim();if(!state.url){toast('Paste your video link into the field first.',true);return;}createClips();});
  $('heroSubmit').addEventListener('click',()=>{const value=$('heroUrl').value.trim();if(!value){toast('Paste a video link or use the upload button.',true);return;}navigate('studio');$('studioUrl').value=value;$('studioUrl').dispatchEvent(new Event('input'));});
  $('heroUrl').addEventListener('keydown',e=>{if(e.key==='Enter')$('heroSubmit').click();});
  $('generateButton').addEventListener('click',createClips);
  $('heroDemo').addEventListener('click',()=>{navigate('studio');tryDemo();});
  $('studioDemo').addEventListener('click',tryDemo);
  function getSettings(){return {count:Number($('countSelect').value),length:Number($('lengthSelect').value),aspect:state.aspect,captions:$('captionsSwitch').checked};}
  async function createClips(){
    if(!state.file&&!($('studioUrl').value.trim())){toast('Choose a video file or paste a video link to start.',true);return;}
    if(!state.capabilities?.ffmpeg){toast(serverError(),true);openEngineSettings();return;}
    const btn=$('generateButton');btn.disabled=true;btn.textContent='Uploading your video...';
    try{
      const settings=getSettings();let project;
      if(state.file){const form=new FormData();form.append('file',state.file);for(const [key,value] of Object.entries(settings))form.append(key,String(value));project=await api('/api/upload',{method:'POST',body:form});}
      else {const url=$('studioUrl').value.trim();project=await api('/api/from-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,...settings})});}
      rememberProject(project);state.file=null;$('filePicker').value='';state.project=project;showTab('results');renderProject(project);startPolling(project.id);
    }catch(e){toast(e.message,true);}finally{btn.disabled=false;btn.innerHTML='Generate my clips <span>↗</span>';}
  }
  async function tryDemo(){
    if(!state.capabilities?.ffmpeg){await loadCapabilities();if(!state.capabilities?.ffmpeg){toast('Start the video server to try the demo.',true);return;}}
    const settings=getSettings();toast('Setting up a sample project...');
    try{const project=await api(`/api/demo?count=${settings.count}&length=${Math.min(settings.length,15)}&aspect=${encodeURIComponent(settings.aspect)}`,{method:'POST'});rememberProject(project);state.project=project;showTab('results');renderProject(project);startPolling(project.id);}catch(e){toast(e.message,true);}
  }
  async function refreshProjectCount(){try{$('projectTotal').textContent=(await myProjects()).length;}catch(_){}}
  async function loadProjects(){
    const root=$('projectList');root.innerHTML='<div class="empty-state">Loading your projects...</div>';
    try{
      const projects=await myProjects();$('projectTotal').textContent=projects.length;
      if(!projects.length){root.innerHTML='<div class="empty-state"><div class="empty-icon">✧</div><h3>Your first project starts here.</h3><p>Upload a video or try the sample to see your clips appear here.</p><br><button class="btn btn-primary" id="emptyCreate">Create your first clips ↗</button></div>';$('emptyCreate').onclick=()=>showTab('create');return;}
      root.innerHTML=projects.map(project=>`<article class="project-card"><span class="project-date">${formatDate(project.created)}</span><h3 title="${escapeHTML(project.name)}">${escapeHTML(project.name)}</h3><div class="project-card-summary"><span class="project-status ${escapeHTML(project.status)}">${project.status==='done'?'✓ READY':escapeHTML(project.status).toUpperCase()}</span><span>${project.clips?.length||0} clips · ${seconds(project.duration)}</span></div><div class="project-actions"><button class="btn btn-light" data-open="${escapeHTML(project.id)}">${project.status==='done'?'View clips':'View progress'} →</button><button class="btn-delete" data-delete="${escapeHTML(project.id)}">Delete</button></div></article>`).join('');
      root.querySelectorAll('[data-open]').forEach(btn=>btn.onclick=()=>openProject(btn.dataset.open));
      root.querySelectorAll('[data-delete]').forEach(btn=>btn.onclick=()=>deleteProject(btn.dataset.delete));
    }catch(e){root.innerHTML=`<div class="empty-state">${escapeHTML(e.message)}</div>`;}
  }
  async function deleteProject(id){
    if(!confirm('Delete this project and its videos from the server? This cannot be undone.'))return;
    try{await api(`/api/projects/${id}`,{method:'DELETE'});forgetProject(id);toast('Project deleted.');loadProjects();}catch(e){toast(e.message,true);}
  }
  async function openProject(id){try{const project=await api(`/api/projects/${id}`);state.project=project;showTab('results');renderProject(project);if(!['done','error'].includes(project.status))startPolling(id);}catch(e){toast(e.message,true);}}
  function renderProject(project){
    state.project=project;
    $('resultsTitle').textContent=project.status==='done'?'Your video, reimagined.':project.status==='error'?'Something went wrong.':'Finding the good stuff.';
    $('resultsInfo').textContent=`${project.name} · ${seconds(project.duration)} · ${project.clips?.length||0} clips`;
    const inProgress=!['done','error'].includes(project.status);
    $('processingCard').classList.toggle('hidden',!inProgress);
    $('errorCard').classList.toggle('hidden',project.status!=='error');
    if(inProgress){$('processTitle').textContent=project.status==='importing'?'Importing your video...':project.status==='queued'?'Preparing your project...':'Finding your highlights...';$('processHint').textContent='Your connected video server is processing the clip. Keep it running.';$('progressBar').style.width=`${project.progress||0}%`;$('progressPercent').textContent=`${project.progress||0}%`;}
    if(project.status==='error'){$('errorCard').textContent=project.error||'Video processing failed.';}
    $('clipsGrid').innerHTML=(project.clips||[]).map((clip,i)=>`<article class="clip-card"><div class="clip-video-wrap"><video controls preload="metadata" playsinline src="${escapeHTML(privateVideoPath(project.id,clip.url))}"></video>${Number.isFinite(clip.moment_score)?`<span class="clip-score">✦ Moment score ${clip.moment_score}</span>`:''}</div><div class="clip-details"><h3>${escapeHTML(clip.name)}</h3><div class="clip-meta"><span>${seconds(clip.start)} – ${seconds(clip.end)}</span><span>${Math.round(clip.end-clip.start)} sec · MP4</span></div><div class="clip-actions"><button data-edit="${escapeHTML(clip.id)}">✎ Edit</button><a href="${escapeHTML(serverPath(`/api/projects/${project.id}/clips/${clip.id}/download?token=${encodeURIComponent(tokenFor(project.id))}`))}" download="clipforge-${escapeHTML(project.id)}-clip-${i+1}.mp4">↓ Download</a></div></div></article>`).join('');
    $('clipsGrid').querySelectorAll('[data-edit]').forEach(btn=>btn.onclick=()=>openEditor(btn.dataset.edit));
  }
  function startPolling(pid){
    clearInterval(state.polling);
    state.polling=setInterval(async()=>{try{const project=await api(`/api/projects/${pid}`);if(state.project?.id!==pid){clearInterval(state.polling);return;}renderProject(project);if(['done','error'].includes(project.status)){clearInterval(state.polling);refreshProjectCount();if(project.status==='done')toast('Your clips are ready to preview and download.');else toast(project.error||'Processing failed.',true);}}catch(e){clearInterval(state.polling);toast(e.message,true);}},1600);
  }
  $('backToProjects').addEventListener('click',()=>showTab('projects'));$('newProjectButton').addEventListener('click',()=>showTab('create'));
  function openEditor(id){
    const clip=state.project?.clips?.find(c=>c.id===id);if(!clip)return;
    state.editing=id;
    $('editorVideo').src=privateVideoPath(state.project.id,clip.url);$('editStart').value=clip.start;$('editEnd').value=clip.end;$('editEnd').max=state.project.duration;$('editStart').max=state.project.duration;
    $('editAspect').value=state.project.settings.aspect;$('editCaption').value='';$('editorBackdrop').classList.remove('hidden');
  }
  function closeEditor(){$('editorBackdrop').classList.add('hidden');$('editorVideo').pause();$('editorVideo').removeAttribute('src');$('editorVideo').load();}
  $('closeEditor').onclick=closeEditor;$('editorBackdrop').addEventListener('click',e=>{if(e.target===$('editorBackdrop'))closeEditor();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('editorBackdrop').classList.contains('hidden'))closeEditor();});
  $('saveEdit').addEventListener('click',async()=>{
    const btn=$('saveEdit');const start=Number($('editStart').value),end=Number($('editEnd').value);
    if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||start<0||end>state.project.duration+.2){toast('Enter valid start and end times within the original video.',true);return;}
    btn.disabled=true;btn.textContent='Rendering your changes...';
    try{await api(`/api/projects/${state.project.id}/clips/${state.editing}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start,end,aspect:$('editAspect').value,caption_text:$('editCaption').value})});const project=await api(`/api/projects/${state.project.id}`);renderProject(project);closeEditor();toast('Your updated clip is ready.');}catch(e){toast(e.message,true);}finally{btn.disabled=false;btn.innerHTML='Render updated clip ↗';}
  });
  function openEngineSettings(){
    $('engineUrl').value=state.apiBase || (isGitHubPages?'':'http://127.0.0.1:8000');
    $('engineTestStatus').textContent='Enter a server URL, then click Test connection.';
    $('engineBackdrop').classList.remove('hidden');
  }
  function closeEngineSettings(){$('engineBackdrop').classList.add('hidden');}
  function normalizedEngineUrl(){
    const val=$('engineUrl').value.trim().replace(/\/+$/,'');
    if(!val)throw new Error('Enter the video server URL, for example https://your-backend.example.');
    let parsed;
    try{parsed=new URL(val);}catch(e){throw new Error('Enter a full server URL beginning with https://.');}
    if(parsed.protocol!=='https:' && !(parsed.protocol==='http:'&&['localhost','127.0.0.1'].includes(parsed.hostname)))
      throw new Error('Use HTTPS for an online server, or HTTP only for localhost.');
    if(parsed.pathname!=='/' && parsed.pathname!=='') throw new Error('Enter the server base URL without /api or other paths.');
    if(parsed.username||parsed.password||parsed.search||parsed.hash)throw new Error('Enter only the server base URL.');
    return parsed.origin;
  }
  async function checkEngineUrl(save){
    const status=$('engineTestStatus'); status.textContent='Connecting...';
    try{
      const url=normalizedEngineUrl();
      const response=await fetch(`${url}/api/health`,{signal:AbortSignal.timeout(12000)});
      if(!response.ok)throw new Error('The server did not answer /api/health successfully.');
      const result=await response.json();
      if(typeof result.ffmpeg!=='boolean') throw new Error('This URL does not look like a ClipForge server.');
      if(!result.ffmpeg)throw new Error('Server responds but FFmpeg is missing. Install FFmpeg there.');
      status.textContent=`✓ Connected! FFmpeg: ready · YouTube import: ${result.link_import?'available':'install yt-dlp'}`;
      if(save){state.apiBase=url;localStorage.setItem('clipforge_engine_v2',url);state.capabilities=result;toast('Video engine connected successfully.');loadCapabilities();closeEngineSettings();}
    }catch(e){status.textContent=`Connection failed: ${e.message}`;}
  }
  $('connectEngine').addEventListener('click',openEngineSettings);
  $('connectEngineSide').addEventListener('click',openEngineSettings);
  $('closeEngine').addEventListener('click',closeEngineSettings);
  $('testEngine').addEventListener('click',()=>checkEngineUrl(false));
  $('saveEngine').addEventListener('click',()=>checkEngineUrl(true));
  $('engineBackdrop').addEventListener('click',e=>{if(e.target===$('engineBackdrop'))closeEngineSettings();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('engineBackdrop').classList.contains('hidden'))closeEngineSettings();});
  const updatePrices=(annual)=>{
    $('creatorPrice').textContent=annual?'50':'5';
    $('creatorUnit').textContent=annual?' / year*':' / month*';
    $('creatorBilling').textContent=annual?'Proposed annual plan · $50 paid once per year':'Proposed monthly plan · billed monthly';
    $('creatorDiscount').textContent=annual?'Regular annual total: $60 · you save $10 (17%)':'Switch to yearly to save $10 (17%)';
    $('cycleMonthly').classList.toggle('active',!annual);$('cycleAnnual').classList.toggle('active',annual);
    $('cycleMonthly').setAttribute('aria-pressed',String(!annual));$('cycleAnnual').setAttribute('aria-pressed',String(annual));
  };
  $('cycleMonthly').addEventListener('click',()=>updatePrices(false));
  $('cycleAnnual').addEventListener('click',()=>updatePrices(true));
  window.addEventListener('popstate',()=>showSite(location.hash==='#studio'?'studio':location.hash==='#pricing'?'pricing':'home'));
  showSite(location.hash==='#studio'?'studio':location.hash==='#pricing'?'pricing':'home');
})();
