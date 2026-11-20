const memberEditState = { context: null, organizationId: null, projectId: null, member: null };
const memberEditRoles = {
  organization: [
    ['organization_admin', 'ผู้ดูแลองค์กร'],
    ['member', 'สมาชิก'],
    ['viewer', 'ผู้ดู'],
  ],
  project: [
    ['project_admin', 'ผู้ดูแลโปรเจ็กต์'],
    ['project_member', 'สมาชิก'],
    ['project_viewer', 'ผู้ดู'],
  ],
};

function openMemberEditor(context, member, organizationId, projectId = null) {
  if (!member || member.role === 'owner' || member.role === 'project_owner') return;
  memberEditState.context = context;
  memberEditState.organizationId = organizationId;
  memberEditState.projectId = projectId;
  memberEditState.member = member;
  const form = document.querySelector('#member-edit-form');
  form.elements.full_name.value = member.full_name;
  const canEditDisplayName = context === 'organization';
  document.querySelector('#member-edit-name-field').classList.toggle('hidden', !canEditDisplayName);
  form.elements.role.innerHTML = memberEditRoles[context].map(([role, label]) => '<option value="' + role + '">' + label + '</option>').join('');
  form.elements.role.value = member.role;
  document.querySelector('#member-edit-title').textContent = canEditDisplayName ? 'แก้ไขข้อมูลสมาชิก' : 'แก้ไขบทบาทสมาชิก';
  document.querySelector('#member-edit-description').textContent = canEditDisplayName ? 'แก้ไขชื่อที่แสดงและบทบาทของสมาชิก' : 'ปรับบทบาทของสมาชิกในโปรเจ็กต์นี้';
  document.querySelector('#member-edit-role-label').textContent = context === 'organization' ? 'บทบาทในองค์กร' : 'บทบาทในโปรเจ็กต์';
  document.querySelector('#member-edit-email').textContent = member.email;
  const notice = document.querySelector('#member-edit-notice');
  notice.textContent = '';
  notice.className = 'members-notice hidden';
  document.querySelector('#member-edit-dialog').showModal();
}

document.querySelector('#member-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  const notice = document.querySelector('#member-edit-notice');
  const route = memberEditState.context === 'organization'
    ? '/organizations/' + memberEditState.organizationId + '/members/' + memberEditState.member.user_id
    : '/organizations/' + memberEditState.organizationId + '/projects/' + memberEditState.projectId + '/members/' + memberEditState.member.user_id;
  submit.disabled = true;
  notice.textContent = '';
  notice.className = 'members-notice hidden';
  try {
    const update = { role: form.elements.role.value };
    if (memberEditState.context === 'organization') update.full_name = form.elements.full_name.value.trim();
    await api(route, { method: 'PATCH', body: JSON.stringify(update) });
    document.querySelector('#member-edit-dialog').close();
    if (memberEditState.context === 'organization') {
      showOrganizationMemberNotice('บันทึกข้อมูลสมาชิกแล้ว', 'success');
      await refreshOrganizationMembers();
      await loadOrganizations();
    } else {
      showProjectMembersNotice('บันทึกข้อมูลสมาชิกแล้ว', 'success');
      await refreshProjectMembers();
    }
  } catch (error) {
    notice.textContent = error.message;
    notice.className = 'members-notice error';
  } finally {
    submit.disabled = false;
  }
});

document.querySelector('#member-edit-close').addEventListener('click', () => document.querySelector('#member-edit-dialog').close());
document.querySelector('#member-edit-cancel').addEventListener('click', () => document.querySelector('#member-edit-dialog').close());
