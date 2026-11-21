const deviceDiagnosticsState={page:1,pageSize:25,total:0,request:0,timer:null};
function formatDiagnosticTime(value){return value?new Date(value).toLocaleString('th-TH',{dateStyle:'medium',timeStyle:'short'}):'ยังไม่มีข้อมูล';}
function diagnosticStatusLabel(status){return status==='online'?'ออนไลน์':status==='offline'?'ออฟไลน์':'ตรวจไม่ได้';}
function updateDiagnosticFilters(data){
  const org=document.getElementById('device-diagnostics-organization');const orgValue=org.value;
  org.innerHTML='<option value="">ทุกองค์กร</option>'+data.organizations.map(item=>`<option value="${item.id}">${escapeHtml(item.name)}</option>`).join('');
  if(data.organizations.some(item=>String(item.id)===orgValue))org.value=orgValue;
  const project=document.getElementById('device-diagnostics-project');const projectValue=project.value;const orgId=org.value;
  const projects=orgId?data.projects.filter(item=>String(item.organization_id)===orgId):data.projects;
  project.innerHTML='<option value="">ทุกโปรเจกต์</option>'+projects.map(item=>`<option value="${item.id}">${escapeHtml(item.name)} · ${escapeHtml(item.organization_name)}</option>`).join('');
  if(projects.some(item=>String(item.id)===projectValue))project.value=projectValue;
}
async function loadDeviceDiagnostics(){
  if(!currentUser?.is_platform_admin&&!currentUser?.is_platform_auditor)return;
  const request=++deviceDiagnosticsState.request;const offset=(deviceDiagnosticsState.page-1)*deviceDiagnosticsState.pageSize;
  const params=new URLSearchParams({q:document.getElementById('device-diagnostics-search').value.trim(),status:document.getElementById('device-diagnostics-status').value,limit:String(deviceDiagnosticsState.pageSize),offset:String(offset)});
  const organization=document.getElementById('device-diagnostics-organization').value;const project=document.getElementById('device-diagnostics-project').value;
  if(organization)params.set('organization_id',organization);if(project)params.set('project_id',project);
  const body=document.getElementById('device-diagnostics-list');body.innerHTML='<tr><td colspan="6" class="members-empty">กำลังตรวจสอบอุปกรณ์…</td></tr>';
  try{
    const data=await api('/admin/device-diagnostics?'+params.toString());if(request!==deviceDiagnosticsState.request)return;
    deviceDiagnosticsState.total=data.total;updateDiagnosticFilters(data);
    const pages=Math.max(1,Math.ceil(data.total/deviceDiagnosticsState.pageSize));
    const first=data.total?offset+1:0;const last=Math.min(offset+data.items.length,data.total);
    document.getElementById('device-diagnostics-count').textContent=`แสดง ${first.toLocaleString('th-TH')}–${last.toLocaleString('th-TH')} จาก ${data.total.toLocaleString('th-TH')} อุปกรณ์`;
    document.getElementById('device-diagnostics-page-label').textContent=`หน้า ${deviceDiagnosticsState.page} / ${pages}`;
    document.getElementById('device-diagnostics-prev').disabled=deviceDiagnosticsState.page<=1;
    document.getElementById('device-diagnostics-next').disabled=deviceDiagnosticsState.page>=pages;
    const emqx=document.getElementById('device-diagnostics-emqx');emqx.className='admin-health '+(data.emqx_status==='ok'?'healthy':'unhealthy');emqx.textContent=`EMQX: ${data.emqx_status==='ok'?'เชื่อมต่อได้':'ตรวจสอบไม่ได้'}`;
    body.innerHTML=data.items.length?data.items.map(item=>{
      const broker=item.broker_status;const heartbeat=item.heartbeat_status;
      const mqtt=item.last_connection_port?`Port ${item.last_connection_port} · ${item.last_connection_tls===true?'ใช้ TLS':item.last_connection_tls===false?'ไม่ใช้ TLS':'ไม่ทราบ TLS'}`:'ยังไม่มีข้อมูล Port';
      const heartbeatLabel=heartbeat==='active'?'ปกติ':heartbeat==='stale'?'ขาดช่วง':'ยังไม่เคยได้รับ';
      const brokerLabel=!item.is_active?'ปิดใช้งาน':diagnosticStatusLabel(broker);
      const recorded=broker==='unknown'?`<small>ค่าล่าสุดในระบบ: ${diagnosticStatusLabel(item.recorded_broker_status)}</small>`:'';
      return `<tr><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.client_id)}</small></td><td><strong>${escapeHtml(item.organization_name)}</strong><small>${escapeHtml(item.project_name)}</small></td><td><span class="diagnostic-pill ${escapeHtml(broker)}">${escapeHtml(brokerLabel)}</span><small>${escapeHtml(mqtt)}</small>${recorded}</td><td><span class="diagnostic-pill heartbeat-${escapeHtml(heartbeat)}">${heartbeatLabel}</span><small>ล่าสุด: ${formatDiagnosticTime(item.last_heartbeat_at)}</small><small>เกณฑ์หมดเวลา ${Number(item.heartbeat_timeout_seconds)} วินาที</small></td><td>${formatDiagnosticTime(item.last_seen_at)}<small>เหตุการณ์ broker: ${formatDiagnosticTime(item.connection_event_at)}</small></td><td>${escapeHtml(item.diagnosis)}</td></tr>`;
    }).join(''):'<tr><td colspan="6" class="members-empty">ไม่พบอุปกรณ์ตามตัวกรอง</td></tr>';
  }catch(error){if(request!==deviceDiagnosticsState.request)return;document.getElementById('device-diagnostics-count').textContent='โหลดข้อมูลไม่สำเร็จ';body.innerHTML=`<tr><td colspan="6" class="members-empty">${escapeHtml(error.message)}</td></tr>`;}
}
function reloadDiagnosticPage(){deviceDiagnosticsState.page=1;void loadDeviceDiagnostics();}
document.getElementById('device-diagnostics-search').addEventListener('input',event=>{clearTimeout(deviceDiagnosticsState.timer);deviceDiagnosticsState.timer=setTimeout(reloadDiagnosticPage,250);});
document.getElementById('device-diagnostics-status').addEventListener('change',reloadDiagnosticPage);
document.getElementById('device-diagnostics-organization').addEventListener('change',()=>{document.getElementById('device-diagnostics-project').value='';reloadDiagnosticPage();});
document.getElementById('device-diagnostics-project').addEventListener('change',reloadDiagnosticPage);
document.getElementById('device-diagnostics-page-size').addEventListener('change',event=>{deviceDiagnosticsState.pageSize=Number(event.currentTarget.value)||25;deviceDiagnosticsState.page=1;void loadDeviceDiagnostics();});
document.getElementById('device-diagnostics-prev').addEventListener('click',()=>{if(deviceDiagnosticsState.page>1){deviceDiagnosticsState.page--;void loadDeviceDiagnostics();}});
document.getElementById('device-diagnostics-next').addEventListener('click',()=>{if(deviceDiagnosticsState.page*deviceDiagnosticsState.pageSize<deviceDiagnosticsState.total){deviceDiagnosticsState.page++;void loadDeviceDiagnostics();}});
document.getElementById('device-diagnostics-refresh').addEventListener('click',()=>void loadDeviceDiagnostics());
