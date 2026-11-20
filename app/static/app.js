const API='/api/v1';
const tokenKey='nbu_iot_access_token';
let token=sessionStorage.getItem(tokenKey);
let currentUser=null;
let overviewStreamController=null;
let overviewStreamGeneration=0;
let overviewOrganizations=[];
let overviewProjects=[];
let onlinePage={page:1,pageSize:25,search:'',organizationId:'',projectId:'',items:[],total:0,request:0,reloadTimer:null};
const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function setTheme(theme){if(!['light','dark'].includes(theme))theme='dark';document.documentElement.dataset.theme=theme;localStorage.setItem('nbu_iot_theme',theme);document.querySelectorAll('[data-theme-choice]').forEach(button=>{const selected=button.dataset.themeChoice===theme;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));});const color=document.querySelector('meta[name="theme-color"]');if(color)color.content=theme==='light'?'#f3f6fb':'#0b1220';}
function updateWorkspaceNavigation(){const profile=location.hash==='#profile';const users=location.hash==='#users';if(users&&currentUser&&!currentUser.is_platform_admin){location.hash='#overview';return;}const section=location.hash==='#organizations'?'organizations':'overview';document.querySelectorAll('.workspace-nav .nav-item').forEach(link=>{const active=!profile&&!users&&link.hash==='#'+section;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});$('#workspace-dashboard')?.classList.toggle('hidden',profile||users);$('#profile-page')?.classList.toggle('hidden',!profile);$('#admin-users-page')?.classList.toggle('hidden',!users);const title=document.querySelector('#section-title');if(title)title.textContent=profile?'ข้อมูลส่วนตัว':users?'จัดการผู้ใช้งาน':section==='organizations'?'องค์กรและโปรเจกต์':'ภาพรวม';if(profile&&typeof loadProfilePage==='function')loadProfilePage();if(users&&typeof loadAdminUsers==='function')loadAdminUsers();}
window.addEventListener('hashchange',updateWorkspaceNavigation);updateWorkspaceNavigation();
document.querySelectorAll('[data-theme-choice]').forEach(button=>button.addEventListener('click',()=>setTheme(button.dataset.themeChoice)));
setTheme(document.documentElement.dataset.theme||'dark');
async function api(path,options={}){
  const headers={'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})};
  const response=await fetch(API+path,{...options,headers:{...headers,...options.headers}});
  if(response.status===401){logout();throw new Error('เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่');}
  const data=response.status===204?null:await response.json().catch(()=>null);
  if(!response.ok)throw new Error(data?.detail||'เกิดข้อผิดพลาด กรุณาลองอีกครั้ง');
  return data;
}
function showError(el,message=''){el.textContent=message;}
function confirmApp(message,{title='ยืนยันการดำเนินการ',confirmLabel='ยืนยัน',danger=false}={}){const dialog=$('#app-confirm-dialog');$('#app-confirm-title').textContent=title;$('#app-confirm-message').textContent=message;const button=$('#app-confirm-submit');button.textContent=confirmLabel;button.classList.toggle('danger-confirm',danger);return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});}
function setMode(mode){$$('.tab').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));$('#name-field').classList.toggle('hidden',mode!=='register');$('#auth-submit').textContent=mode==='register'?'สร้างบัญชี':'เข้าสู่ระบบ';$('#auth-form [name="password"]').autocomplete=mode==='register'?'new-password':'current-password';const authMessage=$('#auth-error');showError(authMessage);authMessage.classList.remove('success');}
$$('.tab').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
$('#auth-form').addEventListener('submit',async e=>{e.preventDefault();const authForm=e.currentTarget;const form=new FormData(authForm);const mode=$('.tab.active').dataset.mode;const payload={email:form.get('email'),password:form.get('password')};if(mode==='register')payload.full_name=form.get('full_name');const button=$('#auth-submit');button.disabled=true;try{const result=await api(`/auth/${mode}`,{method:'POST',body:JSON.stringify(payload)});if(result.pending_approval){authForm.reset();authForm.elements.email.value=payload.email;setMode('login');$('#auth-error').classList.remove('success');$('#auth-notice-message').textContent=result.message;$('#auth-notice-dialog').showModal();return;}token=result.access_token;sessionStorage.setItem(tokenKey,token);await startApp();}catch(err){showError($('#auth-error'),err.message);}finally{button.disabled=false;}});
$('#auth-notice-close').addEventListener('click',()=>$('#auth-notice-dialog').close());
function logout(){overviewStreamGeneration++;if(overviewStreamController)overviewStreamController.abort();overviewStreamController=null;clearTimeout(onlinePage.reloadTimer);onlinePage.items=[];token=null;currentUser=null;sessionStorage.removeItem(tokenKey);$('#app-view').classList.add('hidden');$('#auth-view').classList.remove('hidden');}
$('#logout').addEventListener('click',logout);
async function startApp(){if(!token)return;try{currentUser=await api('/auth/me');$('#profile-name').textContent=currentUser.full_name;$('#profile-email').textContent=currentUser.email;$('#avatar').textContent=(currentUser.full_name||'N')[0].toUpperCase();$('#account-menu-name').textContent=currentUser.full_name;$('#account-menu-email').textContent=currentUser.email;$('#account-menu-avatar').textContent=(currentUser.full_name||'N')[0].toUpperCase();$('#admin-users-menu-item').classList.toggle('hidden',!currentUser.is_platform_admin);$('#auth-view').classList.add('hidden');$('#app-view').classList.remove('hidden');updateWorkspaceNavigation();await loadOrganizations();startOnlineDeviceStream();void loadOnlineDevicePage();}catch(e){if(token)showError($('#app-error'),e.message);}}
async function loadOrganizations(){
  showError($('#app-error'));
  const organizations=await api('/organizations');
  void loadTopicAclCount();
  overviewOrganizations=organizations;
  overviewProjects=[];
  let projectTotal=0;
  $('#org-count').textContent=organizations.length;
  const list=$('#org-list');list.innerHTML='';
  $('#empty-state').classList.toggle('hidden',organizations.length!==0);
  for(const org of organizations){
    const card=document.createElement('article');card.className='org-card';
    const canManageOrg=['owner','organization_admin'].includes(org.role);
    card.innerHTML=`<div class="org-card-head"><div class="org-name"><div class="org-logo">${escapeHtml(org.name[0]?.toUpperCase()||'O')}</div><div><h3>${escapeHtml(org.name)}</h3><small>/${escapeHtml(org.slug)}</small></div></div><div class="org-header-tools"><span class="role-badge">${escapeHtml(org.role)}</span>${canManageOrg?'<button type="button" class="org-edit-button" aria-label="แก้ไของค์กร" title="แก้ไของค์กร"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg></button><button type="button" class="org-delete-button" aria-label="ลบองค์กร" title="ลบองค์กร"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m5 4v6m4-6v6"/></svg></button>':''}</div></div><p class="org-desc">${escapeHtml(org.description||'')}</p><div class="org-meta"><span class="project-count">กำลังโหลด…</span><div class="org-actions"><button class="secondary add-project">＋ โปรเจกต์</button><button class="secondary members">สมาชิก</button></div></div><div class="project-list"></div>`;
    if(org.role==='viewer')card.querySelector('.add-project').classList.add('hidden');
    if(canManageOrg){
      card.querySelector('.org-edit-button').addEventListener('click',()=>openOrganizationEdit(org));
      card.querySelector('.org-delete-button').addEventListener('click',()=>deleteOrganization(org));
    }
    card.querySelector('.add-project').addEventListener('click',()=>openProject(org));
    card.querySelector('.members').addEventListener('click',()=>showMembers(org));list.append(card);
    try{
      const projects=await api(`/organizations/${org.id}/projects`);
      projectTotal+=projects.length;
      overviewProjects.push(...projects.map(project=>({id:project.id,name:project.name,slug:project.slug,organization_id:org.id,organization_name:org.name})));
      card.querySelector('.project-count').textContent=`${projects.length} โปรเจกต์`;
      card.querySelector('.project-list').innerHTML=projects.map(p=>`<div class="project-row" data-project-id="${p.id}" data-org-id="${org.id}" data-can-manage="${p.can_manage}"><i class="project-dot"></i><div><strong>${escapeHtml(p.name)}</strong><small>/${escapeHtml(p.slug)}</small></div>${p.can_manage?`<button type="button" class="secondary project-manage-button" data-manage-project="${p.id}">⚙ จัดการ</button>`:''}</div>`).join('');
      card.querySelectorAll('.project-manage-button').forEach(button=>button.addEventListener('click',()=>openProjectManagement(org,projects.find(project=>project.id===Number(button.dataset.manageProject)))));
    }catch(e){card.querySelector('.project-count').textContent='โหลดโปรเจกต์ไม่สำเร็จ';}
  }
  $('#project-count').textContent=projectTotal;
  renderOnlineFilterOptions(organizations);
}
function openOrganizationEdit(org){const form=$('#org-edit-form');form.reset();form.elements.organization_id.value=org.id;form.elements.original_slug.value=org.slug;form.elements.name.value=org.name;form.elements.slug.value=org.slug;form.elements.description.value=org.description||'';showError($('.form-error',form));openDialog('#org-edit-dialog');}
$('#org-edit-close').addEventListener('click',()=>$('#org-edit-dialog').close());$('#org-edit-cancel').addEventListener('click',()=>$('#org-edit-dialog').close());
$('#org-edit-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,fields=new FormData(form),orgId=fields.get('organization_id'),name=String(fields.get('name')||'').trim(),slug=String(fields.get('slug')||'').trim(),oldSlug=String(fields.get('original_slug')||'');if(slug!==oldSlug&&!(await confirmApp('การเปลี่ยนรหัสองค์กร (slug) จะเปลี่ยน Topic namespace ของทุกโปรเจ็กต์ในองค์กร และอัปเดต ACL ใน EMQX อุปกรณ์ที่เชื่อมต่อจะถูกตัดการเชื่อมต่อเพื่อรับ ACL ใหม่ แต่ firmware และระบบภายนอกต้องแก้ Topic ด้วยตนเอง\n\nTopic เดิม: '+oldSlug+'/{project}/{device}/...\nTopic ใหม่: '+slug+'/{project}/{device}/...',{title:'ยืนยันการเปลี่ยนรหัสองค์กร (slug)',confirmLabel:'เปลี่ยนรหัสองค์กร (slug)'})))return;const submit=form.querySelector('[type="submit"]');submit.disabled=true;try{await api('/organizations/'+orgId,{method:'PATCH',body:JSON.stringify({name,slug,description:String(fields.get('description')||'').trim()||null})});$('#org-edit-dialog').close();await loadOrganizations();}catch(error){showError($('.form-error',form),error.message);}finally{submit.disabled=false;}});
async function loadTopicAclCount(){const count=$('#topic-acl-count'),breakdown=$('#topic-acl-breakdown');try{const result=await api('/topics/count');count.textContent=Number(result.total||0).toLocaleString('th-TH');breakdown.textContent=`Publish ${Number(result.publish||0).toLocaleString('th-TH')} · Subscribe ${Number(result.subscribe||0).toLocaleString('th-TH')}`;}catch{count.textContent='—';breakdown.textContent='โหลดจำนวน Topic ไม่สำเร็จ';}}
function renderOnlineFilterOptions(organizations,preserveProject=true){
  const organizationSelect=$('#overview-filter-organization'),projectSelect=$('#overview-filter-project');
  const selectedOrganization=organizationSelect.value||onlinePage.organizationId;
  organizationSelect.innerHTML='<option value="">ทุกองค์กร</option>'+organizations.map(org=>`<option value="${org.id}">${escapeHtml(org.name)}</option>`).join('');
  onlinePage.organizationId=organizations.some(org=>String(org.id)===String(selectedOrganization))?String(selectedOrganization):'';
  organizationSelect.value=onlinePage.organizationId;
  const selectedProject=preserveProject?(projectSelect.value||onlinePage.projectId):'';
  const projects=overviewProjects.filter(project=>!onlinePage.organizationId||String(project.organization_id)===onlinePage.organizationId);
  projectSelect.innerHTML='<option value="">ทุกโปรเจกต์</option>'+projects.map(project=>`<option value="${project.id}">${escapeHtml(project.name)} · ${escapeHtml(project.organization_name)}</option>`).join('');
  onlinePage.projectId=projects.some(project=>String(project.id)===String(selectedProject))?String(selectedProject):'';
  projectSelect.value=onlinePage.projectId;
}
function renderOnlineDevices(){
  const {items,total,page,pageSize}=onlinePage;
  const start=total?(page-1)*pageSize+1:0,end=Math.min(page*pageSize,total),pages=Math.max(1,Math.ceil(total/pageSize));
  $('#overview-online-count').textContent=total?`แสดง ${start.toLocaleString()}–${end.toLocaleString()} จาก ${total.toLocaleString()} อุปกรณ์ออนไลน์`:((onlinePage.search||onlinePage.organizationId||onlinePage.projectId)?'ไม่พบอุปกรณ์ออนไลน์ที่ตรงกับตัวกรอง':'ขณะนี้ไม่มีอุปกรณ์ออนไลน์');
  $('#overview-online-list').innerHTML=items.length?items.map(device=>`<article class="online-device-card"><i class="online-device-dot"></i><div class="online-device-copy"><div class="online-device-title"><strong>${escapeHtml(device.name)}</strong>${Number(device.last_connection_port)>0?`<span class="online-device-port">พอร์ต ${Number(device.last_connection_port)}</span>`:''}</div><small>${escapeHtml(device.client_id)} · ${escapeHtml(device.organization_name)} / ${escapeHtml(device.project_name)}</small></div></article>`).join(''):'<div class="online-empty">'+((onlinePage.search||onlinePage.organizationId||onlinePage.projectId)?'ไม่พบอุปกรณ์ออนไลน์ที่ตรงกับตัวกรอง':'ขณะนี้ไม่มีอุปกรณ์ออนไลน์')+'</div>';
  $('#overview-online-page').textContent=`หน้า ${page.toLocaleString()} / ${pages.toLocaleString()}`;
  $('#overview-online-prev').disabled=page<=1;
  $('#overview-online-next').disabled=page>=pages;
}
async function loadOnlineDevicePage(){
  const request=++onlinePage.request,params=new URLSearchParams({page:String(onlinePage.page),page_size:String(onlinePage.pageSize)});
  if(onlinePage.search.trim())params.set('search',onlinePage.search.trim());
  if(onlinePage.organizationId)params.set('organization_id',onlinePage.organizationId);
  if(onlinePage.projectId)params.set('project_id',onlinePage.projectId);
  try{
    const result=await api('/devices/online?'+params.toString());
    if(request!==onlinePage.request)return;
    const lastPage=Math.max(1,Math.ceil(result.total/onlinePage.pageSize));
    if(onlinePage.page>lastPage){onlinePage.page=lastPage;return loadOnlineDevicePage();}
    onlinePage.items=result.items;onlinePage.total=result.total;renderOnlineDevices();
  }catch(error){if(request===onlinePage.request)showError($('#app-error'),error.message);}
}
function queueOnlineDeviceReload(delay=180){
  clearTimeout(onlinePage.reloadTimer);
  onlinePage.reloadTimer=setTimeout(()=>void loadOnlineDevicePage(),delay);
}
function applyOnlineDeviceEvent(eventName,data){
  if(eventName==='snapshot'){queueOnlineDeviceReload(0);return;}
  if(eventName==='device_status'&&data&&data.list_changed)queueOnlineDeviceReload();
}
function startOnlineDeviceStream(){
  if(overviewStreamController)overviewStreamController.abort();
  const generation=++overviewStreamGeneration;
  void runOnlineDeviceStream(generation);
}
async function runOnlineDeviceStream(generation){
  let retryMs=1000;
  const state=$('#overview-online-state');
  while(token&&generation===overviewStreamGeneration){
    const controller=new AbortController();overviewStreamController=controller;
    try{
      const response=await fetch(API+'/devices/online/events',{headers:{Authorization:`Bearer ${token}`},signal:controller.signal});
      if(response.status===401){logout();return;}
      if(!response.ok||!response.body)throw new Error('SSE connection failed');
      state.textContent='อัปเดตแบบเรียลไทม์';state.className='online-stream-state connected';retryMs=1000;
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      while(generation===overviewStreamGeneration){
        const {value,done}=await reader.read();if(done)break;
        buffer+=decoder.decode(value,{stream:true});let boundary;
        while((boundary=buffer.search(/\r?\n\r?\n/))!==-1){
          const block=buffer.slice(0,boundary),separator=buffer.slice(boundary).match(/^\r?\n\r?\n/)[0];buffer=buffer.slice(boundary+separator.length);
          let eventName='message';const lines=[];
          for(const line of block.split(/\r?\n/)){if(line.startsWith('event:'))eventName=line.slice(6).trim();else if(line.startsWith('data:'))lines.push(line.slice(5).trim());}
          if(lines.length){try{applyOnlineDeviceEvent(eventName,JSON.parse(lines.join('\n')));}catch{/* Ignore malformed SSE frames. */}}
        }
      }
      if(controller.signal.aborted||generation!==overviewStreamGeneration)return;
      throw new Error('SSE stream ended');
    }catch{
      if(controller.signal.aborted||generation!==overviewStreamGeneration)return;
      state.textContent='กำลังเชื่อมต่ออีกครั้ง…';state.className='online-stream-state reconnecting';
      await new Promise(resolve=>setTimeout(resolve,retryMs));retryMs=Math.min(retryMs*2,15000);
    }
  }
}
async function refreshOverview(){
  const button=$('#overview-refresh');
  if(button.disabled)return;
  button.disabled=true;button.textContent='กำลังรีเฟรช…';
  try{
    await loadOrganizations();
    await loadOnlineDevicePage();
    showError($('#app-error'));
  }catch(error){showError($('#app-error'),error.message);}
  finally{button.disabled=false;button.textContent='↻ รีเฟรช';}
}
async function deleteOrganization(org){const message='ลบองค์กร "'+org.name+'" พร้อมโปรเจกต์และสมาชิกทั้งหมดหรือไม่? การลบนี้ย้อนกลับไม่ได้';if(!await confirmApp(message,{title:'ลบองค์กร',confirmLabel:'ลบองค์กร',danger:true}))return;try{await api('/organizations/'+org.id,{method:'DELETE'});await loadOrganizations();}catch(err){showError($('#app-error'),err.message);}}
function openDialog(id){$(id).showModal();}$$('.close-dialog').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));$$('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d)d.close();}));
$('#overview-refresh').addEventListener('click',refreshOverview);
$('#overview-online-search').addEventListener('input',event=>{onlinePage.search=event.currentTarget.value;onlinePage.page=1;queueOnlineDeviceReload(250);});
$('#overview-filter-organization').addEventListener('change',event=>{onlinePage.organizationId=event.currentTarget.value;onlinePage.projectId='';onlinePage.page=1;renderOnlineFilterOptions(overviewOrganizations,false);queueOnlineDeviceReload(0);});
$('#overview-filter-project').addEventListener('change',event=>{onlinePage.projectId=event.currentTarget.value;onlinePage.page=1;queueOnlineDeviceReload(0);});
$('#overview-page-size').addEventListener('change',event=>{onlinePage.pageSize=Number(event.currentTarget.value);onlinePage.page=1;queueOnlineDeviceReload(0);});
$('#overview-online-prev').addEventListener('click',()=>{if(onlinePage.page>1){onlinePage.page--;void loadOnlineDevicePage();}});
$('#overview-online-next').addEventListener('click',()=>{onlinePage.page++;void loadOnlineDevicePage();});
$('#new-org').addEventListener('click',()=>openDialog('#org-dialog'));$('#empty-create').addEventListener('click',()=>openDialog('#org-dialog'));
$('#org-form').addEventListener('input',e=>{if(e.target.name==='name'){const slug=$('#org-form [name="slug"]');if(!slug.dataset.edited)slug.value=e.target.value.toLowerCase().trim().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');}});$('#org-form [name="slug"]').addEventListener('input',e=>{e.target.dataset.edited='1';});
$('#org-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget;const f=new FormData(form);try{await api('/organizations',{method:'POST',body:JSON.stringify({name:f.get('name'),slug:f.get('slug'),description:f.get('description')||null})});form.reset();$('#org-form [name="slug"]').dataset.edited='';$('#org-dialog').close();await loadOrganizations();}catch(err){showError($('.form-error',form),err.message);}});
function openProject(org){const form=$('#project-form');form.reset();form.elements.organization_id.value=org.id;$('#project-org-label').textContent=`ในองค์กร ${org.name}`;form.elements.slug.dataset.edited='';openDialog('#project-dialog');}
$('#project-form [name="name"]').addEventListener('input',e=>{const slug=$('#project-form [name="slug"]');if(!slug.dataset.edited)slug.value=e.target.value.toLowerCase().trim().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');});$('#project-form [name="slug"]').addEventListener('input',e=>e.target.dataset.edited='1');
$('#project-form').addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget;const f=new FormData(form),orgId=f.get('organization_id');try{await api(`/organizations/${orgId}/projects`,{method:'POST',body:JSON.stringify({name:f.get('name'),slug:f.get('slug'),description:f.get('description')||null})});$('#project-dialog').close();await loadOrganizations();}catch(err){showError($('.form-error',form),err.message);}});
function showMembers(org){openOrganizationMembers(org);}
startApp();
