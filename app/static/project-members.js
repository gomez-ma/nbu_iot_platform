const projectMembersApi = '/api/v1';
const projectMembersTokenKey = 'nbu_iot_access_token';
const projectMembersState = { organizationId: null, projectId: null, canManage: false, members: [] };
const pmQuery = (selector, root = document) => root.querySelector(selector);
const pmEscape = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const projectRoleLabels = { project_owner: 'เจ้าของโปรเจกต์', project_admin: 'ผู้ดูแลโปรเจกต์', project_member: 'สมาชิก', project_viewer: 'ผู้ดู' };

async function projectMembersRequest(path, options = {}) {
  const token = sessionStorage.getItem(projectMembersTokenKey);
  const response = await fetch(projectMembersApi + path, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(options.headers || {}) } });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.detail || 'ทำรายการไม่สำเร็จ');
  return data;
}

function showProjectMembersNotice(message, type = 'error') {
  const notice = pmQuery('#members-notice');
  notice.textContent = message;
  notice.className = 'members-notice ' + type;
}

function renderProjectMembers() {
  const body = pmQuery('#project-members-list');
  const form = pmQuery('#project-member-form');
  form.classList.toggle('hidden', !projectMembersState.canManage);
  const query = pmQuery('#project-member-search').value.trim().toLowerCase();
  const members = projectMembersState.members.filter((member) => !query || member.full_name.toLowerCase().includes(query) || member.email.toLowerCase().includes(query));
  pmQuery('#project-member-count').textContent = projectMembersState.members.length;
  if (!members.length) {
    body.innerHTML = projectMembersState.members.length ? '<tr><td colspan="3" class="members-empty">ไม่พบสมาชิกที่ค้นหา</td></tr>' : '<tr><td colspan="3" class="members-empty">ยังไม่มีสมาชิกในโปรเจกต์</td></tr>';
    return;
  }
  body.innerHTML = members.map((member) => {
    const isOwner = member.role === 'project_owner';
    const roleCell = '<span class="member-role-label">' + projectRoleLabels[member.role] + '</span>';
    const edit = projectMembersState.canManage && !isOwner ? '<button type="button" class="member-edit" data-edit-project-member="' + member.user_id + '">แก้ไข</button>' : '';
    const remove = projectMembersState.canManage && !isOwner ? '<button type="button" class="member-remove" data-remove-member="' + member.user_id + '">นำออก</button>' : '';
    return '<tr><td><div class="member-identity"><span class="member-avatar">' + pmEscape((member.full_name || member.email || '?').trim().charAt(0).toUpperCase()) + '</span><span><strong>' + pmEscape(member.full_name) + '</strong><small>' + pmEscape(member.email) + '</small></span></div></td><td>' + roleCell + '</td><td><div class="member-row-actions">' + edit + remove + '</div></td></tr>';
  }).join('');
}

async function refreshProjectMembers() {
  try {
    const result = await projectMembersRequest('/organizations/' + projectMembersState.organizationId + '/projects/' + projectMembersState.projectId + '/members');
    projectMembersState.members = result.members;
    projectMembersState.canManage = result.can_manage;
    renderProjectMembers();
  } catch (error) { showProjectMembersNotice(error.message); }
}

async function openProjectMembers(organizationId, projectId) {
  projectMembersState.organizationId = organizationId;
  projectMembersState.projectId = projectId;
  projectMembersState.members = [];
  projectMembersState.canManage = false;
  pmQuery('#project-member-search').value = '';
  pmQuery('#project-member-count').textContent = '0';
  pmQuery('#project-members-list').innerHTML = '<tr><td colspan="3" class="members-empty">กำลังโหลดรายชื่อ…</td></tr>';
  pmQuery('#members-notice').className = 'members-notice hidden';
  pmQuery('#members-project-title').textContent = 'สมาชิกโปรเจกต์';
  pmQuery('#members-project-subtitle').textContent = 'กำลังโหลด…';
  pmQuery('#project-members-dialog').showModal();
  try {
    const [organizations, projects] = await Promise.all([
      projectMembersRequest('/organizations'),
      projectMembersRequest('/organizations/' + organizationId + '/projects'),
    ]);
    const organization = organizations.find((item) => item.id === organizationId);
    const project = projects.find((item) => item.id === projectId);
    if (!organization || !project) throw new Error('ไม่พบองค์กรหรือโปรเจกต์นี้');
    pmQuery('#members-project-title').textContent = project.name;
    pmQuery('#members-project-subtitle').textContent = organization.name + ' / ' + project.slug;
    await refreshProjectMembers();
  } catch (error) { showProjectMembersNotice(error.message); }
}

pmQuery('#project-member-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  const fields = new FormData(form);
  submit.disabled = true;
  try {
    await projectMembersRequest('/organizations/' + projectMembersState.organizationId + '/projects/' + projectMembersState.projectId + '/members', { method: 'POST', body: JSON.stringify({ email: fields.get('email'), role: fields.get('role') }) });
    form.reset();
    showProjectMembersNotice('เพิ่มสมาชิกเข้าโปรเจกต์แล้ว', 'success');
    await refreshProjectMembers();
  } catch (error) { showProjectMembersNotice(error.message); }
  finally { submit.disabled = false; }
});

pmQuery('#project-members-list').addEventListener('click', async (event) => {
  const editButton = event.target.closest('[data-edit-project-member]');
  if (editButton) {
    const member = projectMembersState.members.find((item) => item.user_id === Number(editButton.dataset.editProjectMember));
    if (member) openMemberEditor('project', member, projectMembersState.organizationId, projectMembersState.projectId);
    return;
  }
  const button = event.target.closest('[data-remove-member]');
  if (!button) return;
  const member = projectMembersState.members.find((item) => item.user_id === Number(button.dataset.removeMember));
  if (!member || !await confirmApp('นำ ' + member.full_name + ' ออกจากโปรเจกต์นี้หรือไม่?',{title:'นำสมาชิกออกจากโปรเจกต์',confirmLabel:'นำออก',danger:true})) return;
  button.disabled = true;
  try {
    await projectMembersRequest('/organizations/' + projectMembersState.organizationId + '/projects/' + projectMembersState.projectId + '/members/' + member.user_id, { method: 'DELETE' });
    showProjectMembersNotice('นำสมาชิกออกจากโปรเจกต์แล้ว', 'success');
    await refreshProjectMembers();
  } catch (error) { showProjectMembersNotice(error.message); button.disabled = false; }
});

pmQuery('#members-close').addEventListener('click', () => pmQuery('#project-members-dialog').close());
pmQuery('#project-member-search').addEventListener('input', renderProjectMembers);

function attachProjectMemberButtons(root) {
  root.querySelectorAll('.project-row[data-project-id]:not([data-member-button])').forEach((row) => {
    row.dataset.memberButton = 'true';
    const button = document.createElement('button');
    button.className = 'secondary project-member-manager';
    button.type = 'button';
    button.textContent = 'สมาชิก';
    button.addEventListener('click', () => openProjectMembers(Number(row.dataset.orgId), Number(row.dataset.projectId)));
    row.append(button);
  });
}

const projectMemberOrgList = document.querySelector('#org-list');
if (projectMemberOrgList) {
  const projectMemberObserver = new MutationObserver(() => attachProjectMemberButtons(projectMemberOrgList));
  projectMemberObserver.observe(projectMemberOrgList, { childList: true, subtree: true });
  attachProjectMemberButtons(projectMemberOrgList);
}
