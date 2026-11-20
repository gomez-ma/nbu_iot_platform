const adminUsersState={page:1,pageSize:50,search:'',total:0,request:0,timer:null};
async function loadAdminUsers(){
  if(!currentUser?.is_platform_admin)return;
  const request=++adminUsersState.request;const offset=(adminUsersState.page-1)*adminUsersState.pageSize;
  const body=document.getElementById('admin-users-list');body.innerHTML='<tr><td colspan="4" class="members-empty">กำลังโหลด…</td></tr>';
  try{
    const params=new URLSearchParams({q:adminUsersState.search,limit:String(adminUsersState.pageSize),offset:String(offset)});
    const result=await api('/admin/users?'+params.toString());if(request!==adminUsersState.request)return;
    adminUsersState.total=result.total;document.getElementById('admin-users-count').textContent=result.total.toLocaleString('th-TH');
    const pages=Math.max(1,Math.ceil(result.total/adminUsersState.pageSize));document.getElementById('admin-users-page-label').textContent=`หน้า ${adminUsersState.page} / ${pages}`;
    document.getElementById('admin-users-prev').disabled=adminUsersState.page<=1;document.getElementById('admin-users-next').disabled=adminUsersState.page>=pages;
    if(!result.items.length){body.innerHTML='<tr><td colspan="4" class="members-empty">ไม่พบบัญชีผู้ใช้</td></tr>';return;}
    body.innerHTML=result.items.map(item=>`<tr><td><strong>${escapeHtml(item.full_name)}</strong><small class="admin-user-email">${escapeHtml(item.email)}</small></td><td>${item.is_platform_admin?'<span class="admin-user-role">ผู้ดูแลระบบ</span>':'ผู้ใช้'}</td><td><span class="admin-user-status ${item.is_active?'active':'suspended'}">${item.is_active?'ใช้งาน':'ระงับ · รอตรวจสอบ/เปิดใช้งาน'}</span></td><td><div class="admin-user-actions"><button class="secondary admin-user-edit" type="button" data-user-id="${item.id}" data-name="${escapeHtml(item.full_name)}" data-email="${escapeHtml(item.email)}">แก้ไข</button>${item.id===currentUser.id?'<span class="admin-user-self">บัญชีของคุณ</span>':`<button class="${item.is_active?'danger-button':'secondary'} admin-user-toggle" type="button" data-user-id="${item.id}" data-active="${item.is_active}">${item.is_active?'ระงับบัญชี':'ตรวจสอบแล้ว · เปิดใช้งาน'}</button><button class="danger-button admin-user-delete" type="button" data-user-id="${item.id}" data-name="${escapeHtml(item.full_name)}">ลบ</button>`}</div></td></tr>`).join('');
  }catch(error){if(request!==adminUsersState.request)return;body.innerHTML=`<tr><td colspan="4" class="members-empty">${escapeHtml(error.message)}</td></tr>`;}
}
document.getElementById('admin-users-search').addEventListener('input',event=>{adminUsersState.search=event.currentTarget.value.trim();adminUsersState.page=1;clearTimeout(adminUsersState.timer);adminUsersState.timer=setTimeout(()=>void loadAdminUsers(),250);});
document.getElementById('admin-users-prev').addEventListener('click',()=>{if(adminUsersState.page>1){adminUsersState.page--;void loadAdminUsers();}});
document.getElementById('admin-users-next').addEventListener('click',()=>{if(adminUsersState.page*adminUsersState.pageSize<adminUsersState.total){adminUsersState.page++;void loadAdminUsers();}});
document.getElementById('admin-users-list').addEventListener('click',async event=>{
  const editButton=event.target.closest('.admin-user-edit');if(editButton){openAdminUserDialog({id:editButton.dataset.userId,name:editButton.dataset.name,email:editButton.dataset.email});return;}
  const deleteButton=event.target.closest('.admin-user-delete');if(deleteButton){
    if(!await confirmApp(`ลบบัญชี “${deleteButton.dataset.name}” หรือไม่? สมาชิกภาพจะถูกลบ โปรเจกต์ที่สร้างไว้จะยังคงอยู่ และหากเป็นเจ้าขององค์กร ระบบจะโอนเจ้าของให้อีกสมาชิกหนึ่ง`,{title:'ลบบัญชีผู้ใช้',confirmLabel:'ลบบัญชี',danger:true}))return;
    deleteButton.disabled=true;
    try{await api(`/admin/users/${deleteButton.dataset.userId}`,{method:'DELETE'});void loadAdminUsers();}
    catch(error){const notice=document.getElementById('admin-users-notice');notice.textContent=error.message;notice.classList.remove('hidden');}
    finally{deleteButton.disabled=false;}
    return;
  }
  const button=event.target.closest('.admin-user-toggle');if(!button)return;
  const isActive=button.dataset.active==='true';const action=isActive?'ระงับ':'เปิดใช้งาน';
  if(!await confirmApp(`${action}บัญชีนี้${isActive?'? ผู้ใช้จะไม่สามารถเข้าสู่ระบบได้':''}`,{title:action+'บัญชีผู้ใช้',confirmLabel:action,danger:isActive}))return;
  button.disabled=true;
  try{await api(`/admin/users/${button.dataset.userId}`,{method:'PATCH',body:JSON.stringify({is_active:!isActive})});void loadAdminUsers();}
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
  try{await api(id?`/admin/users/${id}/details`:'/admin/users',{method:id?'PATCH':'POST',body:JSON.stringify(payload)});document.getElementById('admin-user-dialog').close();void loadAdminUsers();}
  catch(error){document.getElementById('admin-user-form-error').textContent=error.message;}
  finally{button.disabled=false;}
});
if(location.hash==='#users'&&currentUser?.is_platform_admin)void loadAdminUsers();
