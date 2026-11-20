let managedProjectContext = null;
const projectManagementDialog = document.querySelector('#project-management-dialog');
const projectManagementForm = document.querySelector('#project-management-form');
const projectManagementNotice = document.querySelector('#manage-project-notice');

function showProjectManagementNotice(message, type = 'error') {
  projectManagementNotice.textContent = message;
  projectManagementNotice.className = 'members-notice ' + type;
}

function openProjectManagement(organization, project) {
  if (!project?.can_manage) return;
  managedProjectContext = { organization, project };
  projectManagementForm.elements.name.value = project.name;
  projectManagementForm.elements.slug.value = project.slug;
  projectManagementForm.elements.slug.dataset.edited = '';
  projectManagementForm.elements.description.value = project.description || '';
  projectManagementNotice.className = 'members-notice hidden';
  document.querySelector('#manage-project-org').textContent = organization.name + ' / ' + project.slug;
  projectManagementDialog.showModal();
}

projectManagementForm.elements.name.addEventListener('input', (event) => {
  const slug = projectManagementForm.elements.slug;
  if (slug.dataset.edited) return;
  slug.value = event.currentTarget.value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
});

projectManagementForm.elements.slug.addEventListener('input', (event) => {
  event.currentTarget.dataset.edited = '1';
});

projectManagementForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!managedProjectContext) return;
  const submit = projectManagementForm.querySelector('[type="submit"]');
  const fields = new FormData(projectManagementForm);
  submit.disabled = true;
  try {
    await api('/organizations/' + managedProjectContext.organization.id + '/projects/' + managedProjectContext.project.id, {
      method: 'PATCH',
      body: JSON.stringify({ name: fields.get('name'), slug: fields.get('slug'), description: fields.get('description') || null }),
    });
    projectManagementDialog.close();
    await loadOrganizations();
  } catch (error) {
    showProjectManagementNotice(error.message);
  } finally { submit.disabled = false; }
});

document.querySelector('#delete-project-button').addEventListener('click', async (event) => {
  if (!managedProjectContext) return;
  const { organization, project } = managedProjectContext;
  if (!await confirmApp('ลบโปรเจ็กต์ "' + project.name + '" พร้อมสมาชิก อุปกรณ์ MQTT credentials และ ACL ทั้งหมดหรือไม่? การลบนี้ย้อนกลับไม่ได้',{title:'ลบโปรเจ็กต์',confirmLabel:'ลบโปรเจ็กต์',danger:true})) return;
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api('/organizations/' + organization.id + '/projects/' + project.id, { method: 'DELETE' });
    projectManagementDialog.close();
    await loadOrganizations();
  } catch (error) {
    showProjectManagementNotice(error.message);
  } finally { button.disabled = false; }
});

document.querySelector('#manage-project-close').addEventListener('click', () => projectManagementDialog.close());
