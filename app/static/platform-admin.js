const adminUsersState={page:1,pageSize:50,search:'',total:0,request:0,timer:null};
const adminAuditState={page:1,pageSize:20,total:0,request:0};
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
function adminAuditActionLabel(action,details={}){if(action==='platform.registration.updated')return details.registration_enabled?'เปิดรับสมัครสมาชิก':'ปิดรับสมัครสมาชิก';if(action==='user.status.updated')return details.is_active?'เปิดใช้งานบัญชีผู้ใช้':'ระงับบัญชีผู้ใช้';if(action==='user.admin.updated')return details.is_platform_admin?'กำหนดผู้ดูแลระบบ':'ถอดสิทธิ์ผู้ดูแลระบบ';if(action==='user.auditor.updated')return details.is_platform_auditor?'กำหนดผู้ตรวจสอบระบบ':'ถอดสิทธิ์ผู้ตรวจสอบระบบ';if(action==='user.updated'){const fields={full_name:'ชื่อ',email:'อีเมล',password:'รหัสผ่าน'};const changed=(details.fields||[]).map(field=>fields[field]||field);return changed.length?`แก้ไขข้อมูลผู้ใช้ · ${changed.join('、')}`:'แก้ไขข้อมูลผู้ใช้';}return ({'user.created':'สร้างบัญชีผู้ใช้','user.sessions.revoked':'ออกจากระบบทุกอุปกรณ์','user.deleted':'ลบบัญชีผู้ใช้','device.acl.retry':'ซิงก์กฎ ACL อุปกรณ์ไปยัง EMQX'})[action]||action;}
function adminAuditTargetLabel(item){return item.target_label||({user:'บัญชีผู้ใช้',device:'อุปกรณ์',platform_settings:'การรับสมัครสมาชิก'})[item.target_type]||'รายการระบบ';}
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
