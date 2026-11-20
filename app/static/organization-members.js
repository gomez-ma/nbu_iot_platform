const organizationMemberState = { organization: null, canManage: false, members: [] };
const omQuery = (selector, root = document) => root.querySelector(selector);
const omEscape = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const organizationRoleLabels = { owner: 'เจ้าขององค์กร', organization_admin: 'ผู้ดูแลองค์กร', member: 'สมาชิก', viewer: 'ผู้ดู' };

function showOrganizationMemberNotice(message, type = 'error') {
  const notice = omQuery('#organization-members-notice');
  notice.textContent = message;
  notice.className = 'members-notice ' + type;
}

function renderOrganizationMembers() {
  const tbody = omQuery('#organization-members-list');
  const form = omQuery('#organization-member-form');
  form.classList.toggle('hidden', !organizationMemberState.canManage);
  const query = omQuery('#organization-member-search').value.trim().toLowerCase();
  const members = organizationMemberState.members.filter((member) => !query || member.full_name.toLowerCase().includes(query) || member.email.toLowerCase().includes(query));
  omQuery('#organization-member-count').textContent = organizationMemberState.members.length;
  if (!members.length) {
    tbody.innerHTML = organizationMemberState.members.length ? '<tr><td colspan="3" class="members-empty">ไม่พบสมาชิกที่ค้นหา</td></tr>' : '<tr><td colspan="3" class="members-empty">ยังไม่มีสมาชิกในองค์กร</td></tr>';
    return;
  }
  tbody.innerHTML = members.map((member) => {
    const isOwner = member.role === 'owner';
    const roleCell = '<span class="member-role-label">' + organizationRoleLabels[member.role] + '</span>';
    const edit = organizationMemberState.canManage && !isOwner ? '<button type="button" class="member-edit" data-edit-organization-member="' + member.user_id + '">แก้ไข</button>' : '';
    const remove = organizationMemberState.canManage && !isOwner ? '<button type="button" class="member-remove" data-remove-organization-member="' + member.user_id + '">นำออก</button>' : '';
    return '<tr><td><div class="member-identity"><span class="member-avatar">' + omEscape((member.full_name || member.email || '?').trim().charAt(0).toUpperCase()) + '</span><span><strong>' + omEscape(member.full_name) + '</strong><small>' + omEscape(member.email) + '</small></span></div></td><td>' + roleCell + '</td><td><div class="member-row-actions">' + edit + remove + '</div></td></tr>';
  }).join('');
}

async function refreshOrganizationMembers() {
  try {
    organizationMemberState.members = await api('/organizations/' + organizationMemberState.organization.id + '/members');
    renderOrganizationMembers();
  } catch (error) { showOrganizationMemberNotice(error.message); }
}

async function openOrganizationMembers(organization) {
  organizationMemberState.organization = organization;
  organizationMemberState.canManage = ['owner', 'organization_admin'].includes(organization.role);
  organizationMemberState.members = [];
  omQuery('#organization-members-title').textContent = 'สมาชิกองค์กร';
  omQuery('#organization-members-subtitle').textContent = organization.name + ' / ' + organization.slug;
  omQuery('#organization-members-notice').className = 'members-notice hidden';
  omQuery('#organization-member-search').value = '';
  omQuery('#organization-members-dialog').showModal();
  await refreshOrganizationMembers();
}

omQuery('#organization-member-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  const fields = new FormData(form);
  submit.disabled = true;
  try {
    await api('/organizations/' + organizationMemberState.organization.id + '/members', { method: 'POST', body: JSON.stringify({ email: fields.get('email'), role: fields.get('role') }) });
    form.reset();
    showOrganizationMemberNotice('เพิ่มสมาชิกเข้าองค์กรแล้ว', 'success');
    await refreshOrganizationMembers();
  } catch (error) { showOrganizationMemberNotice(error.message); }
  finally { submit.disabled = false; }
});

omQuery('#organization-members-list').addEventListener('click', async (event) => {
  const editButton = event.target.closest('[data-edit-organization-member]');
  if (editButton) {
    const member = organizationMemberState.members.find((item) => item.user_id === Number(editButton.dataset.editOrganizationMember));
    if (member) openMemberEditor('organization', member, organizationMemberState.organization.id);
    return;
  }
  const button = event.target.closest('[data-remove-organization-member]');
  if (!button) return;
  const member = organizationMemberState.members.find((item) => item.user_id === Number(button.dataset.removeOrganizationMember));
  if (!member || !await confirmApp('นำ ' + member.full_name + ' ออกจากองค์กรหรือไม่? สิทธิ์ในทุกโปรเจ็กต์ขององค์กรนี้จะถูกนำออกด้วย',{title:'นำสมาชิกออกจากองค์กร',confirmLabel:'นำออก',danger:true})) return;
  button.disabled = true;
  try {
    await api('/organizations/' + organizationMemberState.organization.id + '/members/' + member.user_id, { method: 'DELETE' });
    showOrganizationMemberNotice('นำสมาชิกออกจากองค์กรแล้ว', 'success');
    await refreshOrganizationMembers();
    await loadOrganizations();
  } catch (error) { showOrganizationMemberNotice(error.message); button.disabled = false; }
});

omQuery('#organization-member-search').addEventListener('input', renderOrganizationMembers);
omQuery('#organization-members-close').addEventListener('click', () => omQuery('#organization-members-dialog').close());
