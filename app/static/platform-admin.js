const adminUsersState={page:1,pageSize:50,search:'',total:0,request:0,timer:null};
const adminAuditState={page:1,pageSize:20,total:0,request:0};
const adminBillingState={accounts:[],plans:[],summary:{total:0,trial:0,active:0,inactive:0},page:1,pageSize:20,search:'',status:'all',total:0,pages:1,request:0,timer:null};
const billingPlanState={plans:[],request:0};
function adminRoleActionButton(item){
  const isAdmin=Boolean(item.is_platform_admin);const label=isAdmin?'ถอดสิทธิ์ผู้ดูแลระบบ':'กำหนดเป็นผู้ดูแลระบบ';
  const mark=isAdmin?'<path d="M9 12h6"/>':'<path d="M12 9v6m-3-3h6"/>';
  return `<button class="icon-button admin-user-admin" type="button" data-user-id="${item.id}" data-admin="${isAdmin}" data-name="${escapeHtml(item.full_name)}" title="${label}" aria-label="${label}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4.5 6v5.2c0 4.2 2.8 7.8 7.5 9.8 4.7-2 7.5-5.6 7.5-9.8V6L12 3Z"/>${mark}</svg></button>`;
}
function adminActionIcon(className,label,item,paths,extra=''){
  return `<button class="icon-button admin-action-icon ${className}" type="button" data-user-id="${item.id}" data-name="${escapeHtml(item.full_name)}" ${extra} title="${label}" aria-label="${label}"><svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg></button>`;
}
function adminUserActions(item){
  if(!currentUser?.is_platform_admin)return '<span class="admin-user-self">อ่านอย่างเดียว</span>';
  if(item.id===currentUser.id)return '<span class="admin-user-self">บัญชีของคุณ</span>';
  const edit=adminActionIcon('admin-user-edit','แก้ไข',item,'<path d="m15 5 4 4M4 20l4.5-1 10.8-10.8a2.1 2.1 0 0 0-3-3L5.5 16 4 20Z"/>',`data-email="${escapeHtml(item.email)}"`);
  const auditorAction=item.is_platform_admin?'':adminActionIcon('admin-user-auditor',item.is_platform_auditor?'ถอดผู้ตรวจสอบ':'กำหนดผู้ตรวจสอบ',item,item.is_platform_auditor?'<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><path d="m4 4 16 16"/>':'<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',`data-auditor="${item.is_platform_auditor}"`);
  const statusLabel=item.is_active?'ระงับบัญชี':'เปิดใช้งานบัญชี';
  const toggle=adminActionIcon(`admin-user-toggle ${item.is_active?'danger-icon':'success-icon'}`,statusLabel,item,item.is_active?'<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>':'<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',`data-active="${item.is_active}"`);
  const revoke=adminActionIcon('admin-user-revoke','ออกจากระบบทุกอุปกรณ์',item,'<path d="M10 17l5-5-5-5M15 12H3"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/>');
  const remove=adminActionIcon('admin-user-delete danger-icon','ลบผู้ใช้',item,'<path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m4 4v6m6-6v6"/>');
  return `${edit}${adminRoleActionButton(item)}${auditorAction}${toggle}${revoke}${remove}`;
}
async function loadAdminUsers(){
  if(!currentUser?.is_platform_admin&&!currentUser?.is_platform_auditor)return;
  const isPlatformAdmin=Boolean(currentUser.is_platform_admin);
  document.getElementById('admin-user-add').hidden=!isPlatformAdmin;
  const request=++adminUsersState.request;const offset=(adminUsersState.page-1)*adminUsersState.pageSize;
  const body=document.getElementById('admin-users-list');body.innerHTML='<tr><td colspan="4" class="members-empty">กำลังโหลด…</td></tr>';
  try{
    const params=new URLSearchParams({q:adminUsersState.search,limit:String(adminUsersState.pageSize),offset:String(offset)});
    const result=await api('/admin/users?'+params.toString());if(request!==adminUsersState.request)return;
    adminUsersState.total=result.total;document.getElementById('admin-users-count').textContent=result.total.toLocaleString('th-TH');
    const pages=Math.max(1,Math.ceil(result.total/adminUsersState.pageSize));document.getElementById('admin-users-page-label').textContent=`หน้า ${adminUsersState.page} / ${pages}`;
    document.getElementById('admin-users-prev').disabled=adminUsersState.page<=1;document.getElementById('admin-users-next').disabled=adminUsersState.page>=pages;
    if(!result.items.length){body.innerHTML='<tr><td colspan="4" class="members-empty">ไม่พบบัญชีผู้ใช้</td></tr>';return;}
    body.innerHTML=result.items.map(item=>{const role=item.is_platform_admin?'<span class="admin-user-role admin"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 2.8 3.6v3.6c0 3.1 1.9 5.8 5.2 7.3 3.3-1.5 5.2-4.2 5.2-7.3V3.6L8 1.5Z"/><path d="m5.8 7.7 1.5 1.5 3-3.1"/></svg><span>ผู้ดูแลระบบ</span></span>':item.is_platform_auditor?'<span class="admin-user-role auditor">ผู้ตรวจสอบ · อ่านอย่างเดียว</span>':'<span class="admin-user-role standard"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="5" r="2.5"/><path d="M3.5 13c.3-2.3 1.8-3.5 4.5-3.5s4.2 1.2 4.5 3.5"/></svg><span>ผู้ใช้</span></span>';return `<tr><td><strong>${escapeHtml(item.full_name)}</strong><small class="admin-user-email">${escapeHtml(item.email)}</small></td><td>${role}</td><td><span class="admin-user-status ${item.is_active?'active':'suspended'}">${item.is_active?'ใช้งาน':'ระงับ · รอตรวจสอบ/เปิดใช้งาน'}</span></td><td><div class="admin-user-actions">${adminUserActions(item)}</div></td></tr>`;}).join('');
  }catch(error){if(request!==adminUsersState.request)return;body.innerHTML=`<tr><td colspan="4" class="members-empty">${escapeHtml(error.message)}</td></tr>`;}
}
function loadPlatformAdmin(){
  if(!currentUser?.is_platform_admin&&!currentUser?.is_platform_auditor)return;
  const isPlatformAdmin=Boolean(currentUser.is_platform_admin);
  document.querySelector('.admin-controls-card').classList.toggle('hidden',!isPlatformAdmin);
  document.getElementById('admin-registration-enabled').disabled=!isPlatformAdmin;
  void loadPlatformOverview();void loadPlatformSettings();void loadAdminAuditLogs();
}
function loadPlatformBilling(){
  if(!currentUser?.is_platform_admin&&!currentUser?.is_platform_auditor)return;
  void loadAdminBillingAccounts();
}
function planLimit(value){return value===null||value===undefined?'ไม่จำกัด':Number(value).toLocaleString('th-TH');}
function renderBillingPlans(){
  const root=document.getElementById('billing-plan-list');if(!root)return;
  if(!billingPlanState.plans.length){root.innerHTML='<p class="muted">ยังไม่มีแพ็กเกจในรายการ</p>';return;}
  root.innerHTML=billingPlanState.plans.map(plan=>{
    const quotas=[['องค์กร',plan.max_organizations],['โปรเจ็กต์',plan.max_projects],['สมาชิก',plan.max_members],['อุปกรณ์',plan.max_devices],['Topic ACL',plan.max_topic_acls]].map(([label,value])=>`<span><small>${label}</small><strong>${planLimit(value)}</strong></span>`).join('');
    const duration=plan.duration_days?`${Number(plan.duration_days).toLocaleString('th-TH')} วัน`:'ไม่กำหนดวันหมดอายุ';
    const toggleLabel=plan.code==='trial'?'แพ็กเกจทดลองต้องเปิดใช้งาน':plan.is_active?'ปิดแพ็กเกจ':'เปิดแพ็กเกจ';
    return `<article class="billing-plan-card ${plan.is_active?'':'is-inactive'}"><div class="billing-plan-card-head"><div><div class="billing-plan-title"><h2>${escapeHtml(plan.name)}</h2><code>${escapeHtml(plan.code)}</code></div><p>${escapeHtml(plan.description||'ไม่มีรายละเอียด')}</p></div><div class="billing-plan-badges"><span class="billing-status ${plan.is_active?'active':'suspended'}">${plan.is_active?'เปิดใช้งาน':'ปิดใช้งาน'}</span>${plan.is_public?'<span class="billing-plan-pill">สาธารณะ</span>':''}</div></div><div class="billing-plan-meta"><span>ระยะเวลา <b>${duration}</b></span></div><div class="billing-plan-quotas">${quotas}</div><div class="billing-plan-card-actions"><button type="button" class="secondary billing-plan-edit" data-code="${escapeHtml(plan.code)}">✎ แก้ไข</button><button type="button" class="secondary billing-plan-toggle" data-code="${escapeHtml(plan.code)}" ${plan.code==='trial'?'disabled':''}>${toggleLabel}</button></div></article>`;
  }).join('');
}
async function loadPlatformPlanManagement(){
  if(!currentUser?.is_platform_admin)return;
  const root=document.getElementById('billing-plan-list');if(!root)return;
  const request=++billingPlanState.request;root.innerHTML='<p class="muted">กำลังโหลดแพ็กเกจ…</p>';
  try{const result=await api('/admin/billing/plans');if(request!==billingPlanState.request)return;billingPlanState.plans=result.plans||[];renderBillingPlans();}
  catch(error){if(request===billingPlanState.request)root.innerHTML=`<p class="error">${escapeHtml(error.message)}</p>`;}
}
function openBillingPlanDialog(plan=null){
  const dialog=document.getElementById('billing-plan-dialog'),form=document.getElementById('billing-plan-form');form.reset();form.dataset.code=plan?.code||'';
  document.getElementById('billing-plan-dialog-title').textContent=plan?'แก้ไขแพ็กเกจ':'เพิ่มแพ็กเกจ';document.getElementById('billing-plan-error').textContent='';
  const code=form.elements.code;code.value=plan?.code||'';code.disabled=Boolean(plan);form.elements.name.value=plan?.name||'';form.elements.description.value=plan?.description||'';form.elements.duration_days.value=plan?.duration_days??'';
  for(const key of ['max_organizations','max_projects','max_members','max_devices','max_topic_acls'])form.elements[key].value=plan?.[key]??'';
  form.elements.is_public.checked=Boolean(plan?.is_public);form.elements.is_active.checked=plan?Boolean(plan.is_active):true;form.elements.is_active.disabled=plan?.code==='trial';dialog.showModal();
}
function closeBillingPlanDialog(){document.getElementById('billing-plan-dialog').close();}
function billingPlanPayload(fields,includeCode,form){
  const payload={name:String(fields.get('name')||'').trim(),description:String(fields.get('description')||'').trim(),duration_days:fields.get('duration_days')?Number(fields.get('duration_days')):null,is_public:fields.get('is_public')==='on',is_active:form.elements.is_active.disabled?true:fields.get('is_active')==='on'};
  if(includeCode)payload.code=String(fields.get('code')||'').trim();
  for(const key of ['max_organizations','max_projects','max_members','max_devices','max_topic_acls'])payload[key]=fields.get(key)===''?null:Number(fields.get(key));
  return payload;
}
document.getElementById('billing-plan-add').addEventListener('click',()=>openBillingPlanDialog());
document.getElementById('billing-plan-close').addEventListener('click',closeBillingPlanDialog);
document.getElementById('billing-plan-cancel').addEventListener('click',closeBillingPlanDialog);
document.getElementById('billing-plan-list').addEventListener('click',async event=>{
  const edit=event.target.closest('.billing-plan-edit');if(edit){const plan=billingPlanState.plans.find(item=>item.code===edit.dataset.code);if(plan)openBillingPlanDialog(plan);return;}
  const toggle=event.target.closest('.billing-plan-toggle');if(!toggle)return;
  const plan=billingPlanState.plans.find(item=>item.code===toggle.dataset.code);if(!plan)return;
  toggle.disabled=true;try{await api(`/admin/billing/plans/${encodeURIComponent(plan.code)}`,{method:'PATCH',body:JSON.stringify({is_active:!plan.is_active})});await loadPlatformPlanManagement();void loadAdminBillingAccounts();void loadAdminAuditLogs();}
  catch(error){const notice=document.getElementById('billing-plans-notice');notice.textContent=error.message;notice.classList.remove('hidden');}finally{toggle.disabled=false;}
});
document.getElementById('billing-plan-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector('[type="submit"]'),error=document.getElementById('billing-plan-error');
  if(!form.reportValidity())return;button.disabled=true;error.textContent='';const creating=!form.dataset.code;const payload=billingPlanPayload(new FormData(form),creating,form);
  try{await api(creating?'/admin/billing/plans':`/admin/billing/plans/${encodeURIComponent(form.dataset.code)}`,{method:creating?'POST':'PATCH',body:JSON.stringify(payload)});closeBillingPlanDialog();await loadPlatformPlanManagement();void loadAdminBillingAccounts();void loadAdminAuditLogs();}
  catch(err){error.textContent=err.message;}finally{button.disabled=false;}
});
function formatBillingDate(value){return value?new Date(value).toLocaleDateString('th-TH',{dateStyle:'medium'}):'ไม่กำหนดวันหมดอายุ';}
function renderAdminBillingAccounts(){
  const root=document.getElementById('admin-billing-accounts');const canManage=Boolean(currentUser?.is_platform_admin);
  const accounts=adminBillingState.accounts;const tally=adminBillingState.summary;
  document.getElementById('billing-accounts-total').textContent=tally.total.toLocaleString('th-TH');document.getElementById('billing-accounts-trial').textContent=tally.trial.toLocaleString('th-TH');document.getElementById('billing-accounts-active').textContent=tally.active.toLocaleString('th-TH');document.getElementById('billing-accounts-inactive').textContent=tally.inactive.toLocaleString('th-TH');
  const first=adminBillingState.total?((adminBillingState.page-1)*adminBillingState.pageSize+1):0;const last=Math.min(adminBillingState.page*adminBillingState.pageSize,adminBillingState.total);
  document.getElementById('billing-accounts-result-count').textContent=`แสดง ${first.toLocaleString('th-TH')}–${last.toLocaleString('th-TH')} จาก ${adminBillingState.total.toLocaleString('th-TH')} บัญชี`;
  const pageLabel=document.getElementById('billing-accounts-page-label');pageLabel.textContent=`หน้า ${adminBillingState.page.toLocaleString('th-TH')}/${adminBillingState.pages.toLocaleString('th-TH')}`;
  document.getElementById('billing-accounts-prev').disabled=adminBillingState.page<=1;document.getElementById('billing-accounts-next').disabled=adminBillingState.page>=adminBillingState.pages;
  if(!accounts.length){root.innerHTML=adminBillingState.total===0&&adminBillingState.summary.total===0?'<div class="billing-account-empty"><strong>ยังไม่มีบัญชีลูกค้า</strong><p>เมื่อมีผู้ใช้สร้างองค์กร ระบบจะสร้างบัญชีลูกค้าและกำหนดแพ็กเกจทดลองให้อัตโนมัติ</p></div>':'<div class="billing-account-empty"><strong>ไม่พบบัญชีที่ตรงกับตัวกรอง</strong><p>ลองเปลี่ยนคำค้นหาหรือเลือกสถานะอื่น</p></div>';return;}
  const names={max_organizations:'องค์กร',max_projects:'โปรเจ็กต์',max_members:'สมาชิก',max_devices:'อุปกรณ์',max_topic_acls:'Topic ACL'};
  root.innerHTML=accounts.map(account=>{
    const sub=account.subscription;
    const planOptions=adminBillingState.plans.map(plan=>`<option value="${escapeHtml(plan.code)}">${escapeHtml(plan.name)}</option>`).join('');
    const usage=sub?Object.keys(names).map(key=>{const used=Number(sub.usage[key]||0),limit=sub.limits[key];return `<span>${names[key]} <b>${used.toLocaleString('th-TH')}/${limit===null?'∞':Number(limit).toLocaleString('th-TH')}</b></span>`;}).join(''):'';
    const statusLabels={trial:'ทดลองใช้',active:'ใช้งาน',grace:'หมดอายุ · ผ่อนผัน',expired:'หมดอายุ',suspended:'ระงับ',unassigned:'ยังไม่มีแพ็กเกจ'};const status=sub?.status||'unassigned';
    const overrides=sub?.quota_overrides||{};
    return `<article class="admin-billing-account"><div class="admin-billing-account-head"><div><strong>${escapeHtml(account.name)}</strong><small>${escapeHtml(account.owner_name)} · ${escapeHtml(account.owner_email)}</small></div><span class="billing-status ${escapeHtml(status)}">${escapeHtml(statusLabels[status])}</span></div><div class="admin-billing-current"><span>แพ็กเกจ <b>${escapeHtml(sub?.plan_name||'ยังไม่กำหนด')}</b></span><span>หมดอายุ <b>${formatBillingDate(sub?.ends_at)}</b></span>${usage||'<span>ยังไม่มีข้อมูลโควตา</span>'}</div>${canManage?`<div class="billing-support-actions"><button type="button" class="secondary billing-support-start" data-account-id="${account.id}" data-account-name="${escapeHtml(account.name)}" data-owner-email="${escapeHtml(account.owner_email)}">เข้าช่วยเหลือ</button></div><details class="billing-account-manage"><summary>${sub?'เปลี่ยนแพ็กเกจ':'กำหนดแพ็กเกจ'}</summary><form class="admin-billing-form" data-account-id="${account.id}"><p class="billing-plan-change-note">ช่องโควตาที่กรอกจะใช้กับบัญชีนี้ ช่องว่างจะใช้ค่าของแพ็กเกจ การบันทึกจะเริ่มระยะเวลาใหม่</p><label>แพ็กเกจ<select name="plan_code" required><option value="" selected disabled>เลือกแพ็กเกจ</option>${planOptions}</select></label><label>อายุแพ็กเกจ (วัน)<input name="duration_days" type="number" min="1" max="3650" placeholder="ตามแพ็กเกจ"></label><label>ช่วงผ่อนผัน (วัน)<input name="grace_days" type="number" min="0" max="90" value="30" required></label><div class="admin-billing-overrides"><small>โควตาเฉพาะบัญชี · เว้นว่างใช้ค่าของแพ็กเกจ · 0 = ไม่อนุญาต · ค่าไม่จำกัดใช้ null</small><div>${Object.entries(names).map(([key,label])=>`<label>${label}<input name="${key}" type="number" min="0" placeholder="ตามแพ็กเกจ" value="${overrides[key]===undefined||overrides[key]===null?'':Number(overrides[key])}"></label>`).join('')}</div></div><p class="billing-form-error error" role="alert"></p><button class="primary" type="submit">ยืนยันการกำหนดแพ็กเกจ</button></form></details>`:''}</article>`;
  }).join('');
}
async function loadAdminBillingAccounts(){
  const root=document.getElementById('admin-billing-accounts');if(!root)return;
  const request=++adminBillingState.request;root.innerHTML='<p class="muted">กำลังโหลดบัญชีลูกค้า…</p>';
  try{const params=new URLSearchParams({page:String(adminBillingState.page),page_size:String(adminBillingState.pageSize),status:adminBillingState.status});if(adminBillingState.search.trim())params.set('search',adminBillingState.search.trim());const result=await api('/admin/billing/accounts?'+params.toString());if(request!==adminBillingState.request)return;if(adminBillingState.page>(result.pages||1)){adminBillingState.page=result.pages||1;return loadAdminBillingAccounts();}adminBillingState.accounts=result.accounts||[];adminBillingState.plans=result.plans||[];adminBillingState.summary=result.summary||{total:result.total||0,trial:0,active:0,inactive:0};adminBillingState.total=result.total||0;adminBillingState.pages=result.pages||1;renderAdminBillingAccounts();}
  catch(error){if(request===adminBillingState.request)root.innerHTML=`<p class="error">${escapeHtml(error.message)}</p>`;}
}
async function loadPlatformOverview(){
  try{
    const data=await api('/admin/overview');
    document.getElementById('admin-total-users').textContent=Number(data.users).toLocaleString('th-TH');
    document.getElementById('admin-pending-users').textContent=`รอตรวจสอบ/ระงับ ${Number(data.inactive_users).toLocaleString('th-TH')}`;
    document.getElementById('admin-total-organizations').textContent=Number(data.organizations).toLocaleString('th-TH');
    document.getElementById('admin-total-projects').textContent=Number(data.projects).toLocaleString('th-TH');
    document.getElementById('admin-total-devices').textContent=Number(data.devices).toLocaleString('th-TH');
    document.getElementById('admin-online-devices').textContent=`ออนไลน์ ${Number(data.online_devices).toLocaleString('th-TH')}`;
    setAdminHealth('admin-db-health','ฐานข้อมูล',data.database_status);
    setAdminHealth('admin-emqx-health','EMQX',data.emqx_status);
  }catch(error){
    setAdminHealth('admin-db-health','ฐานข้อมูล','error');
    setAdminHealth('admin-emqx-health','EMQX','unknown');
  }
}
async function loadPlatformSettings(){
  try{const data=await api('/admin/settings');document.getElementById('admin-registration-enabled').checked=Boolean(data.registration_enabled);}catch(error){document.getElementById('admin-registration-enabled').disabled=true;}
}
async function loadAdminAuditLogs(){
  const body=document.getElementById('admin-audit-list');
  const request=++adminAuditState.request;
  const offset=(adminAuditState.page-1)*adminAuditState.pageSize;
  try{
    const params=new URLSearchParams({limit:String(adminAuditState.pageSize),offset:String(offset)});
    const result=await api('/admin/audit-logs?'+params.toString());
    if(request!==adminAuditState.request)return;
    adminAuditState.total=result.total;
    const pages=Math.max(1,Math.ceil(result.total/adminAuditState.pageSize));
    const first=result.total?offset+1:0;const last=Math.min(offset+result.items.length,result.total);
    document.getElementById('admin-audit-count').textContent=result.total?`แสดง ${first.toLocaleString('th-TH')}–${last.toLocaleString('th-TH')} จาก ${result.total.toLocaleString('th-TH')} รายการ`:'ยังไม่มีประวัติ';
    document.getElementById('admin-audit-page-label').textContent=`หน้า ${adminAuditState.page} / ${pages}`;
    document.getElementById('admin-audit-prev').disabled=adminAuditState.page<=1;
    document.getElementById('admin-audit-next').disabled=adminAuditState.page>=pages;
    body.innerHTML=result.items.length?result.items.map(item=>`<tr><td>${new Date(item.created_at).toLocaleString('th-TH',{dateStyle:'medium',timeStyle:'short'})}</td><td>${escapeHtml(item.actor_email)}</td><td>${escapeHtml(adminAuditActionLabel(item.action,item.details))}</td><td>${escapeHtml(adminAuditTargetLabel(item))}</td></tr>`).join(''):'<tr><td colspan="4" class="members-empty">ยังไม่มีประวัติ</td></tr>';
  }catch(error){if(request!==adminAuditState.request)return;document.getElementById('admin-audit-count').textContent='โหลดประวัติไม่สำเร็จ';body.innerHTML=`<tr><td colspan="4" class="members-empty">${escapeHtml(error.message)}</td></tr>`;}
}
function adminSupportRequestAction(details={}){
  const method=String(details.method||'').toUpperCase();
  const path=String(details.path||'').replace(/^\/api\/v1\/?/,'');
  if(method==='POST'&&path==='support/session/exit')return 'ออกจากโหมดช่วยเหลือ';
  if(method==='POST'&&/^devices\/\d+\/topics$/.test(path))return 'เพิ่มสิทธิ์ Topic ACL';
  if(method==='DELETE'&&/^devices\/\d+\/topics\/\d+$/.test(path))return 'ลบสิทธิ์ Topic ACL';
  if(method==='POST'&&/^devices\/\d+\/credentials\/rotate$/.test(path))return 'ออกข้อมูลรับรองอุปกรณ์ใหม่';
  const routes=[
    [/^auth\/me$/,'ข้อมูลบัญชี'],[/^billing\/usage$/,'แพ็กเกจและโควตา'],
    [/^organizations\/?$/,'องค์กร'],[/^organizations\/\d+$/,'ข้อมูลองค์กร'],
    [/^organizations\/\d+\/members$/,'สมาชิกองค์กร'],
    [/^organizations\/\d+\/projects$/,'โปรเจ็กต์'],
    [/^organizations\/\d+\/projects\/\d+$/,'โปรเจ็กต์'],
    [/^organizations\/\d+\/projects\/\d+\/members$/,'สมาชิกโปรเจ็กต์'],
    [/^organizations\/\d+\/projects\/\d+\/devices$/,'อุปกรณ์'],
    [/^devices\/online(?:\/events)?$/,'อุปกรณ์ออนไลน์'],
    [/^devices\/\d+$/,'อุปกรณ์'],[/^mqtt\/connection-info$/,'ข้อมูลเชื่อมต่อ MQTT'],
    [/^support\/session$/,'สถานะโหมดช่วยเหลือ'],
  ];
  const resource=routes.find(([pattern])=>pattern.test(path))?.[1]||'ข้อมูลลูกค้า';
  if(method==='GET')return `ดู${resource}`;
  if(method==='POST')return path==='organizations'?'สร้างองค์กร':/^organizations\/\d+\/projects$/.test(path)?'สร้างโปรเจ็กต์':/^organizations\/\d+\/members$/.test(path)||/^organizations\/\d+\/projects\/\d+\/members$/.test(path)?'เพิ่มสมาชิก':/^organizations\/\d+\/projects\/\d+\/devices$/.test(path)?'เพิ่มอุปกรณ์':`เพิ่ม${resource}`;
  if(method==='PATCH'||method==='PUT')return `แก้ไข${resource}`;
  if(method==='DELETE')return `ลบ${resource}`;
  return `ดำเนินการกับ${resource}`;
}
function adminAuditActionLabel(action,details={}){
  if(action==='support.session.started')return `เริ่มโหมดช่วยเหลือลูกค้า · ${details.target_email||'บัญชีลูกค้า'}`;
  if(action==='support.session.ended')return 'ออกจากโหมดช่วยเหลือลูกค้า';
  if(action==='support.request')return `ช่วยเหลือลูกค้า · ${adminSupportRequestAction(details)}`;
  if(action==='platform.registration.updated')return details.registration_enabled?'เปิดรับสมัครสมาชิก':'ปิดรับสมัครสมาชิก';
  if(action==='user.status.updated')return details.is_active?'เปิดใช้งานบัญชีผู้ใช้':'ระงับบัญชีผู้ใช้';
  if(action==='user.admin.updated')return details.is_platform_admin?'กำหนดผู้ดูแลระบบ':'ถอดสิทธิ์ผู้ดูแลระบบ';
  if(action==='user.auditor.updated')return details.is_platform_auditor?'กำหนดผู้ตรวจสอบระบบ':'ถอดสิทธิ์ผู้ตรวจสอบระบบ';
  if(action==='user.updated'){const fields={full_name:'ชื่อ',email:'อีเมล',password:'รหัสผ่าน'};const changed=(details.fields||[]).map(field=>fields[field]||'ข้อมูลอื่น');return changed.length?`แก้ไขข้อมูลผู้ใช้ · ${changed.join(' · ')}`:'แก้ไขข้อมูลผู้ใช้';}
  const labels={'user.created':'สร้างบัญชีผู้ใช้','user.sessions.revoked':'ออกจากระบบทุกอุปกรณ์','user.deleted':'ลบบัญชีผู้ใช้','device.acl.retry':'ซิงก์กฎ ACL อุปกรณ์ไปยัง EMQX','billing.subscription.updated':`กำหนดแพ็กเกจ ${details.plan_code||''}`,'billing.plan.created':`สร้างแพ็กเกจ ${details.name||details.code||''}`,'billing.plan.updated':`แก้ไขแพ็กเกจ ${details.code||''}`};
  return labels[action]||'ดำเนินการในระบบ';
}
function adminAuditTargetLabel(item){const labels={user:'บัญชีผู้ใช้',device:'อุปกรณ์',platform_settings:'การรับสมัครสมาชิก',billing_account:'บัญชีลูกค้า',billing_plan:'แพ็กเกจ'};return item.target_label&&item.target_label!==item.target_type?item.target_label:labels[item.target_type]||'รายการระบบ';}
function setAdminHealth(id,label,status){
  const element=document.getElementById(id);const healthy=status==='ok';
  element.className='admin-health '+(healthy?'healthy':'unhealthy');
  element.textContent=`${label}: ${healthy?'ปกติ':status==='unknown'?'ไม่ทราบ':'ขัดข้อง'}`;
}
let adminSearchTimer=null;let adminSearchRequest=0;
async function searchPlatformData(query){
  const target=document.getElementById('admin-global-search-results');const term=query.trim();
  if(term.length<2){target.innerHTML='<p class="muted">พิมพ์อย่างน้อย 2 ตัวอักษรเพื่อค้นหา</p>';return;}
  const request=++adminSearchRequest;target.innerHTML='<p class="muted">กำลังค้นหา…</p>';
  try{
    const result=await api('/admin/search?q='+encodeURIComponent(term));if(request!==adminSearchRequest)return;
    const groups=[
      ['ผู้ใช้',result.users,(item)=>`<strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.email)} · ${item.active?'ใช้งาน':'รอตรวจสอบ/ระงับ'}</small>`],
      ['องค์กร',result.organizations,(item)=>`<strong>${escapeHtml(item.name)}</strong><small>/${escapeHtml(item.slug)}</small>`],
      ['โปรเจ็กต์',result.projects,(item)=>`<strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.organization_name)} / ${escapeHtml(item.slug)}</small>`],
      ['อุปกรณ์',result.devices,(item)=>`<strong>${escapeHtml(item.name)} <span class="admin-search-status ${escapeHtml(item.status)}">${item.status==='online'?'ออนไลน์':'ออฟไลน์'}</span></strong><small>${escapeHtml(item.client_id)} · ${escapeHtml(item.organization_name)} / ${escapeHtml(item.project_name)}</small>${currentUser?.is_platform_admin?`<button class="secondary admin-device-acl-retry" type="button" data-device-id="${item.id}" data-device-name="${escapeHtml(item.name)}">ซิงก์ ACL จากระบบ</button>`:''}`],
    ];
    const html=groups.map(([label,items,render])=>items.length?`<section><h3>${label} <small>${items.length}</small></h3>${items.map(item=>`<article>${render(item)}</article>`).join('')}</section>`:'').join('');
    target.innerHTML=html||'<p class="muted">ไม่พบข้อมูลที่ตรงกับคำค้น</p>';
  }catch(error){if(request===adminSearchRequest)target.innerHTML=`<p class="error">${escapeHtml(error.message)}</p>`;}
}
document.getElementById('admin-global-search-input').addEventListener('input',event=>{clearTimeout(adminSearchTimer);adminSearchTimer=setTimeout(()=>void searchPlatformData(event.currentTarget.value),250);});
document.getElementById('admin-global-search-form').addEventListener('submit',event=>{event.preventDefault();clearTimeout(adminSearchTimer);void searchPlatformData(document.getElementById('admin-global-search-input').value);});
function startAclSyncCooldown(button,resultLabel){
  let seconds=10;button.disabled=true;button.textContent=`${resultLabel} · รอ ${seconds} วินาที`;
  const tick=()=>{seconds--;if(seconds<=0){button.textContent='ซิงก์ ACL จากระบบ';button.disabled=false;return;}button.textContent=`${resultLabel} · รอ ${seconds} วินาที`;setTimeout(tick,1000);};
  setTimeout(tick,1000);
}
document.getElementById('admin-global-search-results').addEventListener('click',async event=>{
  const button=event.target.closest('.admin-device-acl-retry');if(!button)return;
  if(!await confirmApp(`เขียนกฎ topic ACL จากฐานข้อมูลไปยัง EMQX สำหรับ “${button.dataset.deviceName}” หรือไม่?`,{title:'ซิงก์ ACL อุปกรณ์',confirmLabel:'ซิงก์ ACL'}))return;
  button.disabled=true;button.textContent='กำลังซิงก์…';
  try{await api(`/admin/devices/${button.dataset.deviceId}/retry-acl`,{method:'POST'});button.title='';void loadAdminAuditLogs();startAclSyncCooldown(button,'ซิงก์สำเร็จ');}
  catch(error){button.title=error.message;startAclSyncCooldown(button,'ซิงก์ไม่สำเร็จ');}
});
document.getElementById('admin-overview-refresh').addEventListener('click',()=>void loadPlatformOverview());
document.getElementById('admin-audit-refresh').addEventListener('click',()=>void loadAdminAuditLogs());
document.getElementById('billing-accounts-search').addEventListener('input',event=>{adminBillingState.search=event.currentTarget.value;adminBillingState.page=1;clearTimeout(adminBillingState.timer);adminBillingState.timer=setTimeout(()=>void loadAdminBillingAccounts(),250);});
document.getElementById('billing-accounts-status').addEventListener('change',event=>{adminBillingState.status=event.currentTarget.value;adminBillingState.page=1;void loadAdminBillingAccounts();});
document.getElementById('billing-accounts-page-size').addEventListener('change',event=>{adminBillingState.pageSize=Number(event.currentTarget.value)||20;adminBillingState.page=1;void loadAdminBillingAccounts();});
document.getElementById('billing-accounts-prev').addEventListener('click',()=>{if(adminBillingState.page>1){adminBillingState.page--;void loadAdminBillingAccounts();}});
document.getElementById('billing-accounts-next').addEventListener('click',()=>{if(adminBillingState.page<adminBillingState.pages){adminBillingState.page++;void loadAdminBillingAccounts();}});
document.getElementById('admin-billing-accounts').addEventListener('click',event=>{
  const button=event.target.closest('.billing-support-start');if(!button)return;
  if(!currentUser?.is_platform_admin)return;
  const form=document.getElementById('support-access-form');form.reset();form.dataset.accountId=button.dataset.accountId;
  document.getElementById('support-access-account').textContent=`${button.dataset.accountName} · ${button.dataset.ownerEmail}`;
  document.getElementById('support-access-error').textContent='';document.getElementById('support-access-dialog').showModal();
});
function closeSupportAccessDialog(){document.getElementById('support-access-dialog').close();}
document.getElementById('support-access-close').addEventListener('click',closeSupportAccessDialog);
document.getElementById('support-access-cancel').addEventListener('click',closeSupportAccessDialog);
document.getElementById('support-access-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector('[type="submit"]'),error=document.getElementById('support-access-error');
  if(!form.reportValidity())return;button.disabled=true;error.textContent='';
  try{
    const result=await api(`/admin/billing/accounts/${form.dataset.accountId}/support-session`,{method:'POST',body:JSON.stringify({reason:new FormData(form).get('reason')})});
    sessionStorage.setItem(supportAdminTokenKey,token);token=result.access_token;sessionStorage.setItem(tokenKey,token);form.reset();closeSupportAccessDialog();location.hash='#overview';await startApp();
  }catch(err){error.textContent=err.message;}
  finally{button.disabled=false;}
});
document.getElementById('admin-billing-accounts').addEventListener('submit',async event=>{
  const form=event.target.closest('.admin-billing-form');if(!form)return;event.preventDefault();
  const button=form.querySelector('[type="submit"]'),error=form.querySelector('.billing-form-error'),fields=new FormData(form);
  const payload={plan_code:String(fields.get('plan_code')||''),duration_days:fields.get('duration_days')?Number(fields.get('duration_days')):null,grace_days:Number(fields.get('grace_days')||0),quota_overrides:{}};
  for(const key of ['max_organizations','max_projects','max_members','max_devices','max_topic_acls']){const value=String(fields.get(key)||'').trim();if(value!=='')payload.quota_overrides[key]=Number(value);else if(payload.plan_code==='enterprise')payload.quota_overrides[key]=null;}
  const account=adminBillingState.accounts.find(item=>String(item.id)===form.dataset.accountId);const plan=adminBillingState.plans.find(item=>item.code===payload.plan_code);
  if(!plan){error.textContent='กรุณาเลือกแพ็กเกจ';return;}
  const duration=payload.duration_days??plan.duration_days;const durationText=duration?`${Number(duration).toLocaleString('th-TH')} วัน`:'ไม่กำหนดวันหมดอายุ';
  const quotaNames={max_organizations:'องค์กร',max_projects:'โปรเจ็กต์',max_members:'สมาชิก',max_devices:'อุปกรณ์',max_topic_acls:'Topic ACL'};const quotaPreview=Object.entries(quotaNames).map(([key,label])=>{const value=payload.quota_overrides[key]??plan[key];return `${label} ${value===null||value===undefined?'ไม่จำกัด':Number(value).toLocaleString('th-TH')}`;}).join(' · ');
  const from=account?.subscription?.plan_name||'ยังไม่มีแพ็กเกจ';const message=`บัญชี: ${account?.name||''}\nแพ็กเกจเดิม: ${from}\nแพ็กเกจใหม่: ${plan.name}\nระยะเวลา: ${durationText} · ผ่อนผัน ${payload.grace_days} วัน\nโควตาใหม่: ${quotaPreview}\n\nการยืนยันจะเริ่มระยะเวลาใหม่ และใช้โควตาตามค่าที่แสดงด้านบน ต้องการดำเนินการหรือไม่?`;
  if(!await confirmApp(message,{title:'ยืนยันการกำหนดแพ็กเกจ',confirmLabel:'ยืนยันการเปลี่ยนแพ็กเกจ'}))return;
  error.textContent='';button.disabled=true;
  try{await api(`/admin/billing/accounts/${form.dataset.accountId}/subscription`,{method:'PUT',body:JSON.stringify(payload)});void loadAdminBillingAccounts();void loadAdminAuditLogs();}
  catch(err){error.textContent=err.message;}
  finally{button.disabled=!currentUser?.is_platform_admin;}
});
document.getElementById('admin-audit-prev').addEventListener('click',()=>{if(adminAuditState.page>1){adminAuditState.page--;void loadAdminAuditLogs();}});
document.getElementById('admin-audit-next').addEventListener('click',()=>{if(adminAuditState.page*adminAuditState.pageSize<adminAuditState.total){adminAuditState.page++;void loadAdminAuditLogs();}});
document.getElementById('admin-audit-page-size').addEventListener('change',event=>{adminAuditState.pageSize=Number(event.currentTarget.value)||20;adminAuditState.page=1;void loadAdminAuditLogs();});
document.getElementById('admin-registration-enabled').addEventListener('change',async event=>{
  const checkbox=event.currentTarget;const next=checkbox.checked;
  if(!await confirmApp(`${next?'เปิด':'ปิด'}รับสมัครบัญชีใหม่?`,{title:'ตั้งค่าการรับสมัคร',confirmLabel:next?'เปิดรับสมัคร':'ปิดรับสมัคร',danger:!next})){checkbox.checked=!next;return;}
  checkbox.disabled=true;
  try{await api('/admin/settings',{method:'PATCH',body:JSON.stringify({registration_enabled:next})});void loadAdminAuditLogs();}
  catch(error){checkbox.checked=!next;}
  finally{checkbox.disabled=false;}
});
document.getElementById('admin-users-search').addEventListener('input',event=>{adminUsersState.search=event.currentTarget.value.trim();adminUsersState.page=1;clearTimeout(adminUsersState.timer);adminUsersState.timer=setTimeout(()=>void loadAdminUsers(),250);});
document.getElementById('admin-users-search-form').addEventListener('submit',event=>{event.preventDefault();clearTimeout(adminUsersState.timer);adminUsersState.search=document.getElementById('admin-users-search').value.trim();adminUsersState.page=1;void loadAdminUsers();});
document.getElementById('admin-users-prev').addEventListener('click',()=>{if(adminUsersState.page>1){adminUsersState.page--;void loadAdminUsers();}});
document.getElementById('admin-users-next').addEventListener('click',()=>{if(adminUsersState.page*adminUsersState.pageSize<adminUsersState.total){adminUsersState.page++;void loadAdminUsers();}});
document.getElementById('admin-users-list').addEventListener('click',async event=>{
  const editButton=event.target.closest('.admin-user-edit');if(editButton){openAdminUserDialog({id:editButton.dataset.userId,name:editButton.dataset.name,email:editButton.dataset.email});return;}
  const adminButton=event.target.closest('.admin-user-admin');if(adminButton){const promote=adminButton.dataset.admin!=='true';const label=adminButton.dataset.name;if(!await confirmApp(`${promote?'กำหนด':'ถอด'}สิทธิ์ผู้ดูแลระบบให้ “${label}”? ${promote?'ผู้ดูแลจะเข้าถึงข้อมูลและการตั้งค่าทั่วทั้งระบบได้':'ผู้ใช้จะสูญเสียสิทธิ์ดูแลระบบ'} Session เดิมของผู้ใช้จะถูกยุติ${promote&&adminButton.closest('tr')?.querySelector('.admin-user-status')?.classList.contains('suspended')?' และต้องเปิดใช้งานบัญชีก่อนจึงจะเข้าสู่ระบบได้':''}`,{title:'สิทธิ์ผู้ดูแลระบบ',confirmLabel:promote?'กำหนดผู้ดูแล':'ถอดสิทธิ์',danger:!promote}))return;adminButton.disabled=true;try{await api(`/admin/users/${adminButton.dataset.userId}/admin`,{method:'PATCH',body:JSON.stringify({is_platform_admin:promote})});void loadAdminUsers();void loadAdminAuditLogs();}catch(error){const notice=document.getElementById('admin-users-notice');notice.textContent=error.message;notice.classList.remove('hidden');}finally{adminButton.disabled=false;}return;}
  const auditorButton=event.target.closest('.admin-user-auditor');if(auditorButton){const enabled=auditorButton.dataset.auditor==='true';if(!await confirmApp(`${enabled?'ถอด':'กำหนด'}สิทธิ์ผู้ตรวจสอบระบบ? ผู้ตรวจสอบดูข้อมูลทั่วระบบได้แบบอ่านอย่างเดียวและ session เดิมจะถูกยุติ`,{title:'สิทธิ์ผู้ตรวจสอบระบบ',confirmLabel:enabled?'ถอดสิทธิ์':'กำหนดสิทธิ์',danger:enabled}))return;auditorButton.disabled=true;try{await api(`/admin/users/${auditorButton.dataset.userId}/auditor`,{method:'PATCH',body:JSON.stringify({is_platform_auditor:!enabled})});void loadAdminUsers();void loadAdminAuditLogs();}catch(error){const notice=document.getElementById('admin-users-notice');notice.textContent=error.message;notice.classList.remove('hidden');}finally{auditorButton.disabled=false;}return;}
  const revokeButton=event.target.closest('.admin-user-revoke');if(revokeButton){
    if(!await confirmApp(`ยุติ session ทั้งหมดของ “${revokeButton.dataset.name}” หรือไม่? ผู้ใช้ต้องเข้าสู่ระบบใหม่ทุกอุปกรณ์`,{title:'บังคับออกจากระบบ',confirmLabel:'ออกจากระบบ',danger:true}))return;
    revokeButton.disabled=true;try{await api(`/admin/users/${revokeButton.dataset.userId}/revoke-sessions`,{method:'POST'});void loadAdminAuditLogs();}catch(error){const notice=document.getElementById('admin-users-notice');notice.textContent=error.message;notice.classList.remove('hidden');}finally{revokeButton.disabled=false;}return;
  }
  const deleteButton=event.target.closest('.admin-user-delete');if(deleteButton){
    if(!await confirmApp(`ลบบัญชี “${deleteButton.dataset.name}” หรือไม่? สมาชิกภาพจะถูกลบ โปรเจกต์ที่สร้างไว้จะยังคงอยู่ และหากเป็นเจ้าขององค์กร ระบบจะโอนเจ้าของให้อีกสมาชิกหนึ่ง`,{title:'ลบบัญชีผู้ใช้',confirmLabel:'ลบบัญชี',danger:true}))return;
    deleteButton.disabled=true;
    try{await api(`/admin/users/${deleteButton.dataset.userId}`,{method:'DELETE'});void loadAdminUsers();void loadAdminAuditLogs();}
    catch(error){const notice=document.getElementById('admin-users-notice');notice.textContent=error.message;notice.classList.remove('hidden');}
    finally{deleteButton.disabled=false;}
    return;
  }
  const button=event.target.closest('.admin-user-toggle');if(!button)return;
  const isActive=button.dataset.active==='true';const action=isActive?'ระงับ':'เปิดใช้งาน';
  if(!await confirmApp(`${action}บัญชีนี้${isActive?'? ผู้ใช้จะไม่สามารถเข้าสู่ระบบได้':''}`,{title:action+'บัญชีผู้ใช้',confirmLabel:action,danger:isActive}))return;
  button.disabled=true;
  try{await api(`/admin/users/${button.dataset.userId}`,{method:'PATCH',body:JSON.stringify({is_active:!isActive})});void loadAdminUsers();void loadAdminAuditLogs();}
  catch(error){const notice=document.getElementById('admin-users-notice');notice.textContent=error.message;notice.classList.remove('hidden');}
  finally{button.disabled=false;}
});
function openAdminUserDialog(user=null){
  const form=document.getElementById('admin-user-form');form.reset();
  const editing=Boolean(user);form.elements.user_id.value=user?.id||'';form.elements.full_name.value=user?.name||'';form.elements.email.value=user?.email||'';
  form.elements.password.required=!editing;
  document.getElementById('admin-user-dialog-title').textContent=editing?'แก้ไขข้อมูลผู้ใช้':'เพิ่มผู้ใช้';
  document.getElementById('admin-user-dialog-help').textContent=editing?'แก้ไขชื่อหรืออีเมลบัญชี และกำหนดรหัสผ่านใหม่ได้โดยกรอกช่องรหัสผ่าน':'สร้างบัญชีผู้ใช้ใหม่ โดยตั้งรหัสผ่านเริ่มต้นให้ผู้ใช้';
  document.getElementById('admin-user-password-help').textContent=editing?'เว้นว่างหากไม่ต้องการเปลี่ยนรหัสผ่าน':'อย่างน้อย 10 ตัวอักษร ควรแจ้งผู้ใช้ผ่านช่องทางที่ปลอดภัย';
  document.getElementById('admin-user-submit').textContent=editing?'บันทึกการแก้ไข':'สร้างบัญชี';
  document.getElementById('admin-user-form-error').textContent='';
  document.getElementById('admin-user-dialog').showModal();
}
document.getElementById('admin-user-add').addEventListener('click',()=>openAdminUserDialog());
document.getElementById('admin-user-close').addEventListener('click',()=>document.getElementById('admin-user-dialog').close());
document.getElementById('admin-user-cancel').addEventListener('click',()=>document.getElementById('admin-user-dialog').close());
document.getElementById('admin-user-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const button=document.getElementById('admin-user-submit');
  const payload={full_name:form.elements.full_name.value,email:form.elements.email.value};
  if(form.elements.password.value)payload.password=form.elements.password.value;
  const id=form.elements.user_id.value;button.disabled=true;document.getElementById('admin-user-form-error').textContent='';
  try{await api(id?`/admin/users/${id}/details`:'/admin/users',{method:id?'PATCH':'POST',body:JSON.stringify(payload)});document.getElementById('admin-user-dialog').close();void loadAdminUsers();void loadAdminAuditLogs();}
  catch(error){document.getElementById('admin-user-form-error').textContent=error.message;}
  finally{button.disabled=false;}
});
if(location.hash==='#users'&&currentUser?.is_platform_admin)void loadAdminUsers();
