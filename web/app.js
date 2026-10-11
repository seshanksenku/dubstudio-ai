const $ = id => document.getElementById(id);
let activeJob, timer, previewURL, config, polling = false;
const message = value => $('message').textContent = value;
async function api(path, options={}) {
  const response = await fetch('/api/'+path, options);
  if (!response.ok) {
    if(response.status===401){$('studio').hidden=true;$('loginPanel').hidden=false;}
    let body;try{body=await response.json()}catch{body={detail:'Server request failed'}}
    throw new Error(typeof body.detail==='string'?body.detail:'Check your input and try again');
  }
  return response.json();
}
async function initialize(){
  try {
    config=await api('config');
    $('studio').hidden=false;$('loginPanel').hidden=true;$('logout').hidden=false;
    $('target').replaceChildren();$('source').replaceChildren(new Option('Detect automatically','auto'));
    for(const [key,name] of Object.entries(config.languages)){$('target').add(new Option(name,key));$('source').add(new Option(name,key));}
    $('target').value='te';
    $('limits').textContent=`MP4, MOV, MKV, WebM · ${config.max_upload_mb} MB · ${config.max_video_seconds} seconds`;
    setReady(config.worker_ready);
    await history();
  }catch(error){if(!error.message.includes('Sign in'))message(error.message);}
}
function setReady(ready){$('submit').disabled=!ready;$('worker').textContent=ready?'GPU worker connected. Ready to process.':'GPU worker offline. Start it and download models to enable processing.';}
$('loginForm').onsubmit=async event=>{event.preventDefault();try{await api('login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:$('password').value})});$('password').value='';message('');await initialize();}catch(e){message(e.message);}};
$('logout').onclick=async()=>{await api('logout',{method:'POST'});location.reload()};
function preview(){const file=$('videoFile').files[0];if(!file)return;if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(file);$('original').src=previewURL;$('original').hidden=false;$('fileName').textContent=file.name;}
$('videoFile').onchange=preview;
for(const name of ['dragenter','dragover'])$('drop').addEventListener(name,event=>{event.preventDefault();$('drop').classList.add('drag')});
$('drop').addEventListener('dragleave',()=> $('drop').classList.remove('drag'));
$('drop').addEventListener('drop',event=>{event.preventDefault();$('drop').classList.remove('drag');const files=event.dataTransfer.files;if(files.length){const transfer=new DataTransfer();transfer.items.add(files[0]);$('videoFile').files=transfer.files;preview();}});
$('uploadForm').onsubmit=async event=>{
  event.preventDefault();const file=$('videoFile').files[0];if(!file)return;
  if(file.size>config.max_upload_mb*1024**2){message('Video exceeds upload size limit');return;}
  const data=new FormData();data.append('video',file);data.append('source',$('source').value);data.append('target',$('target').value);
  $('submit').disabled=true;message('Uploading video…');
  try {const row=await api('jobs',{method:'POST',body:data});message('Video uploaded. Processing continues if you close this page.');await select(row.id);await history();}catch(e){message(e.message);}finally{$('submit').disabled=!config.worker_ready;}
};
async function history(){
  const rows=await api('jobs');$('jobs').replaceChildren();
  if(!rows.length){$('jobs').textContent='No projects yet. Upload your first video.';return;}
  for(const row of rows){
    const div=document.createElement('div');div.className='job-row';
    const info=document.createElement('div');info.className='job-info';info.textContent='Project '+row.id.slice(0,8);
    const small=document.createElement('small');small.textContent=new Date(row.created*1000).toLocaleString()+' · '+row.status+' · '+row.stage;info.append(small);
    const view=document.createElement('button');view.textContent='Open';view.onclick=()=>select(row.id).catch(e=>message(e.message));div.append(info,view);
    if(['failed','completed'].includes(row.status)){const del=document.createElement('button');del.textContent='Delete';del.onclick=async()=>{try{await api('jobs/'+row.id,{method:'DELETE'});if(activeJob===row.id){activeJob=null;$('result').hidden=true;$('download').hidden=true;$('processing').hidden=true;$('transcript').hidden=true;$('empty').hidden=false;}await history();}catch(e){message(e.message)}};div.append(del);}
    $('jobs').append(div);
  }
}
async function select(id){
  activeJob=id;$('empty').hidden=true;$('result').hidden=true;$('download').hidden=true;$('transcript').hidden=true;$('processing').hidden=false;
  await renderJob(id);
}
async function renderJob(id){
  const row=await api('jobs/'+id);if(activeJob!==id)return;
  $('stage').textContent=row.stage;$('progress').value=row.progress;$('jobState').textContent=row.error||`Stage progress: ${row.progress}% · ${row.status}`;
  if(row.transcript){$('transcript').hidden=false;$('lines').replaceChildren();for(const line of row.transcript.segments){const p=document.createElement('p');p.textContent=`${line.start.toFixed(1)}s · ${line.translated}`;$('lines').append(p);}}
  if(row.status==='completed'){$('result').hidden=false;const url='/api/jobs/'+id+'/download';if(!$('result').getAttribute('src')?.endsWith(url))$('result').src=url;$('download').href=url;$('download').download='DubStudio-dubbed.mp4';$('download').hidden=false;}
}
$('refresh').onclick=()=>initialize();
initialize();
timer=setInterval(async()=>{if(polling||$('studio').hidden)return;polling=true;try{const next=await api('config');config=next;setReady(next.worker_ready);if(activeJob)await renderJob(activeJob);await history();}catch(e){message(e.message)}finally{polling=false}},5000);
