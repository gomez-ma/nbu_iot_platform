function setProfileMessage(id,message,isError=false){const el=document.getElementById(id);el.textContent=message;el.classList.toggle('is-error',isError);}
function loadProfilePage(){if(!currentUser)return;const details=document.getElementById('profile-details-form');if(details.elements.full_name.value!==currentUser.full_name)details.elements.full_name.value=currentUser.full_name;document.getElementById('profile-account-email').value=currentUser.email;}
document.getElementById('profile-details-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const button=form.querySelector('button[type="submit"]');button.disabled=true;setProfileMessage('profile-details-message','กำลังบันทึก…');
  try{const updated=await api('/auth/me',{method:'PATCH',body:JSON.stringify({full_name:form.elements.full_name.value})});currentUser=updated;document.getElementById('profile-name').textContent=updated.full_name;document.getElementById('avatar').textContent=(updated.full_name||'N')[0].toUpperCase();document.getElementById('account-menu-name').textContent=updated.full_name;document.getElementById('account-menu-avatar').textContent=(updated.full_name||'N')[0].toUpperCase();form.elements.full_name.value=updated.full_name;setProfileMessage('profile-details-message','บันทึกข้อมูลแล้ว');}
  catch(error){setProfileMessage('profile-details-message',error.message,true);}finally{button.disabled=false;}
});
document.getElementById('profile-password-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const button=form.querySelector('button[type="submit"]');
  if(form.elements.new_password.value!==form.elements.confirm_password.value){setProfileMessage('profile-password-message','รหัสผ่านใหม่และการยืนยันไม่ตรงกัน',true);return;}
  button.disabled=true;setProfileMessage('profile-password-message','กำลังเปลี่ยนรหัสผ่าน…');
  try{await api('/auth/me/password',{method:'POST',body:JSON.stringify({current_password:form.elements.current_password.value,new_password:form.elements.new_password.value})});form.reset();setProfileMessage('profile-password-message','เปลี่ยนรหัสผ่านแล้ว');}
  catch(error){setProfileMessage('profile-password-message',error.message,true);}finally{button.disabled=false;}
});
if(location.hash==='#profile')loadProfilePage();
