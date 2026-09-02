const metrics = document.getElementById('metrics');
const statusBox = document.getElementById('status');
const escapeText = (value) => String(value ?? '--').replace(/[&<>"']/g, (ch) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
const metricDefinitions = [
  ['기온', 'air_temp', '°C', 1], ['상대습도', 'humidity', '%', 1], ['CO₂', 'co2', 'ppm', 0],
  ['EC', 'ec', 'dS/m', 3], ['pH', 'ph', '', 2], ['양액 온도', 'solution_temp', '°C', 1],
];
function valueText(value, digits, unit) { return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}${unit ? ` ${unit}` : ''}` : '--'; }
function timeText(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '--' : date.toLocaleString('ko-KR', { dateStyle:'medium', timeStyle:'medium' }); }
function render(data) {
  const online = data.pico_connected === true;
  const measured = data.data_source === 'measured';
  statusBox.className = `status ${online && measured ? 'ok' : 'warning'}`;
  statusBox.textContent = online && measured ? '학교 서버·Pico 실측 연결됨' : `현장 데이터 상태: ${data.data_quality || '확인 필요'}`;
  metrics.innerHTML = metricDefinitions.map(([label, key, unit, digits]) => `<article class="metric"><span>${label}</span><strong>${valueText(data.sensors?.[key], digits, unit)}</strong><small>${escapeText(data.sensor_recorded_at || '수집 시각 대기')}</small></article>`).join('');
  document.getElementById('growth-title').textContent = data.growth?.overall_status || '판단 대기';
  document.getElementById('growth-summary').textContent = data.growth?.summary || '공개용 분석 요약이 없습니다.';
  document.getElementById('growth-details').innerHTML = [
    ['생육 단계', data.growth?.stage || '--'], ['판단 근거', data.growth?.stage_reason || '--'], ['영양 상태', data.growth?.nutrition || '--'],
  ].map(([key, value]) => `<div><dt>${escapeText(key)}</dt><dd>${escapeText(value)}</dd></div>`).join('');
  document.getElementById('data-title').textContent = data.data_quality || '확인 필요';
  document.getElementById('data-details').textContent = `센서 기록: ${data.sensor_recorded_at || '--'} · 전송: ${timeText(data.synced_at)}`;
  const images = Array.isArray(data.images) ? data.images : [];
  document.getElementById('camera-time').textContent = images.length ? `최근 촬영 ${images.map((item) => item.captured_at).sort().at(-1)}` : '사진 대기';
  document.getElementById('photos').innerHTML = images.length ? images.map((image) => `<figure><img src="${encodeURI(image.url)}" alt="${escapeText(image.camera_id)} 최근 촬영" loading="lazy"><figcaption>${escapeText(image.camera_id)} · ${escapeText(image.captured_at)}</figcaption></figure>`).join('') : '<p class="empty">공개용 사진을 기다리고 있습니다.</p>';
  document.getElementById('refreshed').textContent = timeText(new Date());
}
async function refresh() {
  try {
    const response = await fetch('/api/overview', { cache:'no-store' });
    if (!response.ok) throw new Error('waiting');
    render(await response.json());
  } catch {
    statusBox.className = 'status waiting';
    statusBox.textContent = '학교 서버가 아직 공개용 데이터를 전송하지 않았습니다.';
  }
}
refresh();
setInterval(refresh, 30000);
