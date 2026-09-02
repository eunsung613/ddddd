const $ = id => document.getElementById(id);
const titles = {overview:'통합 현황',analytics:'환경 분석',performance:'운영 성과 비교',control:'제어 및 승인',ai:'AI 생육 분석',automation:'자동화 센터',reports:'보고서',system:'시스템'};
let toastTimer;
let historyData = [];
let historyQuery = '/api/sensors/history?hours=24&max_points=1600';
let historyRangeLabel = '최근 24시간';
let telegramFinalApproval = false;

function escapeHtml(value){return String(value ?? '').replace(/[&<>'"]/g, char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));}
function toast(message){const el=$('toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),3200);}
function fmt(value,digits=1){return value===null||value===undefined?'--':Number(value).toFixed(digits);}
function numericSensorValue(value){return value===null||value===undefined||value===''?null:Number(value);}
function timeText(value){if(!value)return '기록 없음';const date=new Date(value);return Number.isNaN(date.getTime())?escapeHtml(value):date.toLocaleString('ko-KR');}
function statusTag(ok,labelOk='정상',labelBad='확인 필요'){return `<span class="status ${ok?'success':'wait'}">${ok?labelOk:labelBad}</span>`;}
function sourceClass(source){const value=String(source||'');return value.startsWith('simulation')?'simulation':value==='imported:excel'?'imported':'measured';}
function sourceLabel(source){const value=String(source||'');return value.startsWith('simulation')?'모의 데이터':value==='imported:excel'?'Excel 가져오기(참조)':'서버 실측';}

async function api(path,options={}){
  const response=await fetch(path,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  if(!response.ok){let detail=`HTTP ${response.status}`;try{const body=await response.json();detail=body.detail||detail;}catch{}throw new Error(detail);}
  const type=response.headers.get('content-type')||'';
  return type.includes('application/json')?response.json():response;
}

function addReportsNavigation(){
  const desktop=$('desktopNav');
  const control=desktop.querySelector('[data-page="control"]');
  control.insertAdjacentHTML('beforebegin','<button data-page="performance"><span class="ico"><svg class="icon"><use href="#i-chart"/></svg></span><span>운영 성과 비교</span></button>');
  const system=desktop.querySelector('[data-page="system"]');
  system.insertAdjacentHTML('beforebegin','<button data-page="reports"><span class="ico"><svg class="icon"><use href="#i-report"/></svg></span><span>생육 보고서</span></button>');
  const mobile=$('mobileNav');
  mobile.querySelector('[data-page="control"]').insertAdjacentHTML('beforebegin','<button data-page="performance">성과</button>');
  mobile.querySelector('[data-page="system"]').insertAdjacentHTML('beforebegin','<button data-page="reports">보고서</button>');
  mobile.style.gridTemplateColumns='repeat(8,1fr)';
  const performance=document.createElement('section');performance.className='page';performance.id='performance';
  $('control').before(performance);
  const reports=document.createElement('section');reports.className='page';reports.id='reports';
  $('system').before(reports);
}

function buildPages(){
  addReportsNavigation();
  $('overview').innerHTML=`
    <div class="page-head"><div><h1>통합 현황</h1><p>학교 서버가 수집한 실측값, 최근 사진, 승인 대기 항목을 한곳에서 확인합니다.</p></div><div class="actions"><button class="btn" id="refreshAll"><svg class="icon"><use href="#i-refresh"/></svg>새로고침</button><button class="btn primary" data-page-jump="control">승인 대기열</button></div></div>
    <div class="mode-banner" id="modeBanner"><div><strong>서버 상태 확인 중</strong><span>FastAPI와 Pico USB 정보를 불러오고 있습니다.</span></div><span class="tag" id="modeTag">WAIT</span></div>
    <article class="card hero score-hero" style="margin-bottom:14px"><div class="hero-score"><div class="score-ring" id="scoreRing"><span class="broc-emoji broc-confused score-mascot" id="scoreMascot"></span><strong id="scoreNumber">--</strong><small id="scoreMood">판정 대기</small></div><div class="score-heading"><span class="tag" id="overallTag">수집 대기</span><h2 id="overallTitle">센서 데이터를 기다리고 있습니다</h2></div></div><button class="score-details-toggle" id="scoreDetailsToggle" type="button" aria-expanded="false">점수 산정 근거 보기 <span>⌄</span></button><div class="score-breakdown" id="scoreBreakdown" hidden><div class="score-details" id="scoreDetails">점수 근거를 불러오는 중입니다.</div><div class="hero-metrics"><div class="hero-metric"><span>센서 최근 수신</span><b id="lastSensorAge">--</b></div><div class="hero-metric"><span>승인 대기</span><b id="pendingCount">0건</b></div><div class="hero-metric"><span>등록 카메라</span><b id="cameraCount">0대</b></div><div class="hero-metric"><span>분석 모델</span><b id="modelName">--</b></div></div></div><span id="dataSourceBadge" hidden>출처 확인 중</span><p id="overallText" hidden></p></article>
    <div class="grid kpis"><article class="card kpi temp"><div class="kpi-top"><span>기온</span><span class="kpi-icon"><svg class="icon"><use href="#i-thermometer"/></svg></span></div><div class="kpi-value" id="tempValue">--<small>°C</small></div><div class="data-note" id="tempFoot">수집 대기</div></article><article class="card kpi humid"><div class="kpi-top"><span>상대습도</span><span class="kpi-icon"><svg class="icon"><use href="#i-droplet"/></svg></span></div><div class="kpi-value" id="humidValue">--<small>%</small></div><div class="data-note" id="humidFoot">수집 대기</div></article><article class="card kpi co2"><div class="kpi-top"><span>CO₂</span><span class="kpi-icon"><svg class="icon"><use href="#i-cloud"/></svg></span></div><div class="kpi-value" id="co2Value">--<small>ppm</small></div><div class="data-note" id="co2Foot">수집 대기</div></article><article class="card kpi light"><div class="kpi-top"><span>데이터 상태</span><span class="kpi-icon"><svg class="icon"><use href="#i-database"/></svg></span></div><div class="kpi-value" id="dataQuality">--</div><div class="data-note" id="dataQualityFoot">SQLite 확인 중</div></article></div>
    <div class="grid three" style="margin-bottom:14px"><article class="card kpi humid"><div class="kpi-top"><span>EC · 양액 농도</span><span class="tag" id="pe350Status">WAIT</span></div><div class="kpi-value" id="ecValue">--<small>dS/m</small></div><div class="data-note" id="ecFoot">수집 대기</div></article><article class="card kpi co2"><div class="kpi-top"><span>pH · 산도</span><span class="kpi-icon"><svg class="icon"><use href="#i-droplet"/></svg></span></div><div class="kpi-value" id="phValue">--</div><div class="data-note" id="phFoot">수집 대기</div></article><article class="card kpi temp"><div class="kpi-top"><span>양액 온도</span><span class="kpi-icon"><svg class="icon"><use href="#i-thermometer"/></svg></span></div><div class="kpi-value" id="solutionTempValue">--<small>°C</small></div><div class="data-note" id="solutionTempFoot">PE350 보조값</div></article></div>
    <div class="grid split"><article class="card"><div class="card-pad card-head"><div><div class="eyebrow">LATEST CAPTURE</div><div class="card-title">브로콜리 최근 촬영 이미지</div><div class="card-sub" id="cameraMeta">카메라 설정 확인 중</div></div><button class="btn" id="captureNow">지금 촬영</button></div><div id="cameraPanel" class="empty-panel"><div><b>이미지 대기</b><span>성공한 촬영이 아직 없습니다.</span></div></div></article><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">PENDING APPROVAL</div><div class="card-title">최근 제안</div></div><button class="btn soft" data-page-jump="control">전체 보기</button></div><div id="overviewRecommendations" class="approval-list"><div class="list-empty">승인 대기 정보를 불러오는 중입니다.</div></div></article></div>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">24H ENVIRONMENT</div><div class="card-title">기온 · 습도 추이</div></div><div class="legend"><span style="--c:#1769e0">기온</span><span style="--c:#706bd8">습도</span></div></div><canvas class="chart" id="overviewChart"></canvas></article>`;

  $('analytics').innerHTML=`
    <div class="page-head"><div><h1>환경 분석</h1><p>센서 원본을 1시간 평균으로 정리한 단순 꺾은선 그래프입니다.</p></div><div class="actions history-file-actions"><button class="btn" id="historyExportExcel" type="button">Excel 저장</button><label class="btn soft" for="historyImportExcel">Excel 불러오기</label><input id="historyImportExcel" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden></div></div>
    <article class="card card-pad history-controls"><div class="history-control-row"><div class="segmented" id="historyRange"><button data-hours="1">1시간</button><button data-hours="6">6시간</button><button class="on" data-hours="24">24시간</button><button data-hours="168">7일</button><button data-hours="720">30일</button></div><span class="tag" id="historyRangeLabel">최근 24시간</span></div><form id="historyCustomRange" class="history-custom-range"><div class="field"><label>시작</label><input id="historyStart" type="datetime-local" required></div><div class="field"><label>종료</label><input id="historyEnd" type="datetime-local" required></div><button class="btn primary" type="submit">기간 조회</button></form></article>
    <div class="history-inspector" id="historyInspector">모든 값은 1시간 평균입니다. 그래프의 원형 점에 정확히 마우스를 올리면 측정 시각과 값이 표시됩니다. Excel 가져오기 데이터는 그래프·기록용이며 자동 제어에는 사용되지 않습니다.</div><div class="history-tooltip" id="historyTooltip" hidden></div>
    <div class="grid two history-chart-grid"><article class="card card-pad chart-panel"><div class="card-head"><div><div class="eyebrow">AIR TEMPERATURE</div><div class="card-title">온도</div></div><span class="chart-value" id="tempHistorySummary">--</span></div><canvas class="chart tall detailed-chart" id="temperatureHistoryChart"></canvas></article><article class="card card-pad chart-panel"><div class="card-head"><div><div class="eyebrow">RELATIVE HUMIDITY</div><div class="card-title">습도</div></div><span class="chart-value" id="humidityHistorySummary">--</span></div><canvas class="chart tall detailed-chart" id="humidityHistoryChart"></canvas></article><article class="card card-pad chart-panel"><div class="card-head"><div><div class="eyebrow">NUTRIENT EC</div><div class="card-title">EC</div></div><span class="chart-value" id="ecHistorySummary">--</span></div><canvas class="chart tall detailed-chart" id="ecHistoryChart"></canvas></article><article class="card card-pad chart-panel"><div class="card-head"><div><div class="eyebrow">NUTRIENT PH</div><div class="card-title">pH</div></div><span class="chart-value" id="phHistorySummary">--</span></div><canvas class="chart tall detailed-chart" id="phHistoryChart"></canvas></article></div>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">SAMPLES IN SELECTED RANGE</div><div class="card-title">선택 기간 측정값</div></div><span class="source-pill" id="historySource">출처 확인</span></div><div class="table-wrap"><table><thead><tr><th>시각</th><th>기온</th><th>습도</th><th>CO₂</th><th>EC</th><th>pH</th><th>출처</th></tr></thead><tbody id="historyTable"></tbody></table></div></article>`;

  $('performance').innerHTML=`
    <div class="page-head"><div><h1>1차 · 2차 재배 운영 성과 비교</h1><p>두 기간의 1시간 평균 온습도·양액 값을 같은 경과시간 축에 겹쳐, 관리 목표 유지율과 변동성을 비교합니다.</p></div><div class="actions"><button class="btn primary" id="performancePng" type="button">PPT용 PNG 저장</button></div></div>
    <article class="card card-pad performance-controls"><form id="performanceForm" class="performance-form"><div class="field"><label>1차 재배 시작</label><input id="performanceFirstStart" type="datetime-local" value="2026-08-19T00:00" required></div><div class="field"><label>1차 재배 종료</label><input id="performanceFirstEnd" type="datetime-local" value="2026-08-24T00:00" required></div><div class="field"><label>2차 재배 시작</label><input id="performanceSecondStart" type="datetime-local" value="2026-08-26T00:00" required></div><div class="field"><label>2차 재배 종료</label><input id="performanceSecondEnd" type="datetime-local" value="2026-08-31T00:00" required></div><button class="btn primary" type="submit">비교 갱신</button></form><p class="performance-note">기본값은 DB의 재배 전환 공백(8월 25일)을 기준으로 설정했습니다. 재배 구분 날짜가 다르면 위 날짜를 직접 수정하세요. 비교 결과는 환경 관리 성과이며 생육 차이의 단독 원인을 뜻하지는 않습니다.</p></article>
    <article class="card card-pad historical-ai-panel"><div class="card-head"><div><div class="eyebrow">HISTORICAL OPERATION AI</div><div class="card-title">1차 재배 운영 데이터 AI 분석</div><div class="card-sub">분석 프롬프트와 표·CSV·수기 정리 내용을 직접 작성해 발표용 요약과 관리 한계를 생성합니다. 이 기능은 분석만 수행하며 어떤 장치도 제어하지 않습니다.</div></div><span class="tag" id="historicalAiTag">OpenAI 확인 중</span></div><form id="historicalOperationForm" class="historical-operation-form"><div class="field"><label for="historicalOperationTitle">분석 제목</label><input id="historicalOperationTitle" value="1차 재배 운영 데이터" maxlength="100" required></div><div class="field historical-data-field"><label for="historicalOperationPrompt">AI 분석 프롬프트</label><textarea id="historicalOperationPrompt" rows="12" maxlength="12000" required>너는 수경재배 스마트팜의 환경데이터 분석가다. 아래 브로콜리 1차 재배 데이터를 분석해 재배 환경의 문제와 개선 필요점을 전문적으로 평가하라.&#10;&#10;기간별 온도·습도·CO₂·EC·pH 변화, 목표 범위 이탈, 평균·최소·최대·변동폭을 분석하라. 수기 양액 혼합 과정의 EC·pH 관리 위험과 pH 약 4.0 사례가 뿌리 활력·양분 흡수·생육 균일성에 미칠 수 있는 가능성을 설명하라. 2차 재배의 RS485 PE350 기반 자동화와 비교해 1차의 관리 한계를 정리하라.&#10;&#10;데이터만으로 병해충이나 생리장해를 확진하지 말고, 근거가 부족하면 판단 근거 부족이라고 명시하라. PPT에 쓸 수 있도록 한 줄 결론, 핵심 문제 3가지, 2차 재배 개선점, 수치 근거가 있는 발표 문장 3개를 작성하라.</textarea><small>이 프롬프트는 직접 고쳐서 보낼 수 있습니다. 서버는 결과 형식·안전 안내만 덧붙이며, 입력한 프롬프트와 데이터는 분석 이력에 함께 보관됩니다.</small></div><div class="field historical-data-field"><label for="historicalOperationData">운영 데이터</label><textarea id="historicalOperationData" rows="10" maxlength="60000" placeholder="예시:&#10;날짜, 기온, 습도, CO2, EC, pH, 작업기록&#10;2026-08-19, 23.2, 82.1, 540, 1.4, 6.1, 수동 양액 혼합&#10;..." required></textarea><small>원본 표를 CSV 형태로 붙여넣거나, 날짜별 값·작업기록을 자유롭게 정리해 입력하세요. 입력한 원문은 분석 이력과 함께 서버 SQLite에 보관됩니다.</small></div><div class="form-actions"><button class="btn primary" type="submit" id="historicalOperationSubmit">AI 분석 실행</button></div></form><div id="historicalOperationResults" class="historical-analysis-list"><div class="list-empty">저장된 1차 재배 운영 데이터 분석이 없습니다.</div></div></article>
    <div class="performance-callout" id="performanceCallout">두 기간의 실측 데이터를 불러오는 중입니다.</div>
    <div class="grid four performance-kpis" id="performanceKpis"></div>
    <div class="grid two performance-charts"><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">AIR TEMPERATURE · OVERLAY</div><div class="card-title">기온 겹쳐보기</div><div class="card-sub">목표 범위 16~24℃ · 시작 시점을 0시간으로 정렬</div></div><div class="legend"><span style="--c:#8c9ab0">1차</span><span style="--c:#1769e0">2차</span></div></div><canvas class="chart tall performance-chart" id="performanceTempChart"></canvas></article><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">RELATIVE HUMIDITY · OVERLAY</div><div class="card-title">습도 겹쳐보기</div><div class="card-sub">목표 범위 60~75% · 시작 시점을 0시간으로 정렬</div></div><div class="legend"><span style="--c:#8c9ab0">1차</span><span style="--c:#0a9b71">2차</span></div></div><canvas class="chart tall performance-chart" id="performanceHumidityChart"></canvas></article></div>
    <div class="mode-banner warning performance-simulation-note"><div><strong>EC·pH 비교의 데이터 구분</strong><span>1차는 PE350이 설치되기 전이라 작업기록을 바탕으로 재현한 모의값입니다. 2차만 RS485 PE350 실측이며, 이 두 그래프는 수동 혼합 위험을 설명하는 시각 자료이지 실측 비교 근거가 아닙니다.</span></div><span class="tag amber">1차 모의 · 2차 실측</span></div>
    <div class="grid two performance-charts"><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">EC · MANUAL MIXING RECONSTRUCTION</div><div class="card-title">EC 겹쳐보기</div><div class="card-sub">목표 범위 1.3~1.8 dS/m · 1차는 모의 재현</div></div><div class="legend"><span style="--c:#c27a00">1차 모의</span><span style="--c:#0a9b71">2차 PE350 실측</span></div></div><canvas class="chart tall performance-chart" id="performanceEcChart"></canvas></article><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">PH · MANUAL MIXING RECONSTRUCTION</div><div class="card-title">pH 겹쳐보기</div><div class="card-sub">목표 범위 5.8~6.3 · 1차는 pH 4.0 사례를 포함한 모의 재현</div></div><div class="legend"><span style="--c:#c27a00">1차 모의</span><span style="--c:#d93f4c">2차 PE350 실측</span></div></div><canvas class="chart tall performance-chart" id="performancePhChart"></canvas></article></div>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">PRESENTATION EVIDENCE</div><div class="card-title">PPT 삽입용 운영 성과 도표</div><div class="card-sub">위 비교와 같은 실측 근거를 PNG 파일로 저장할 수 있습니다.</div></div></div><canvas class="performance-export-canvas" id="performanceEvidenceCanvas"></canvas></article>`;

  $('control').innerHTML=`
    <div class="page-head"><div><h1>제어 및 승인</h1><p>모든 요청은 대기열에 먼저 기록됩니다. 승인 후에도 서버 안전 제한을 통과해야 합니다.</p></div><div class="actions"><span class="tag amber" id="controlMode">제어 상태 확인 중</span></div></div>
    <div class="mode-banner warning"><div><strong>실물 장치 안전 원칙</strong><span>AI는 설명과 제안만 작성합니다. 승인 없는 제어, 센서 지연 상태의 제어, 설정 시간을 넘긴 작동은 차단됩니다.</span></div></div>
    <article class="card card-pad" style="margin-bottom:14px"><div class="card-head"><div><div class="eyebrow">MANUAL REQUEST</div><div class="card-title">수동 제어 요청 만들기</div></div><span class="tag">바로 작동하지 않음</span></div><form id="manualRequestForm" class="request-form"><div class="field"><label>장치</label><select id="requestActuator"></select></div><div class="field"><label>상태</label><select id="requestState"><option value="on">ON</option><option value="off">OFF</option></select></div><div class="field"><label>작동 시간(초)</label><input id="requestDuration" type="number" min="0" value="5"></div><div class="field"><label>요청자</label><input id="operatorName" value="이은성"></div><div class="field wide"><label>사유</label><input id="requestReason" value="현장 확인 후 수동 시험"></div><button class="btn primary" type="submit">승인 요청</button></form></article>
    <article class="card card-pad" style="margin-bottom:14px"><div class="card-head"><div><div class="eyebrow">ACTUATORS</div><div class="card-title">장치 상태와 장치측 제한</div></div></div><div id="actuatorGrid" class="actuator-grid"></div></article>
    <article class="card card-pad"><div class="card-head"><div><div class="eyebrow">HUMAN IN THE LOOP</div><div class="card-title">승인 대기열</div></div><span class="tag" id="queueCount">0건</span></div><div id="approvalQueue" class="approval-list"></div></article>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">ACTUATOR AUDIT</div><div class="card-title">액추에이터 작동 기록</div><div class="card-sub">요청·승인·거절·안전 차단·Pico 전송·Pico 응답을 모두 보관합니다.</div></div><span class="tag" id="actuatorEventCount">0건</span></div><div class="table-wrap"><table><thead><tr><th>시각</th><th>장치</th><th>명령</th><th>결과</th><th>근거</th></tr></thead><tbody id="actuatorEventTable"></tbody></table></div></article>`;

  $('ai').innerHTML=`
    <div class="page-head"><div><h1>AI 생육 분석</h1><p>카메라 사진과 같은 시점의 센서값을 함께 분석하고, 관찰과 한계를 구분해 저장합니다.</p></div><div class="actions"><button class="btn primary" id="runAnalysis"><svg class="icon"><use href="#i-scan"/></svg>분석 실행</button></div></div>
    <div class="mode-banner"><div><strong id="aiModelTitle">모델 설정 확인 중</strong><span>AI 결과는 의사결정 지원 자료이며 병해충 확정진단이 아닙니다.</span></div><span class="tag" id="aiConfigured">WAIT</span></div>
    <div class="ai-layout"><article class="card"><div class="card-pad card-head"><div><div class="eyebrow">VISION EVIDENCE</div><div class="card-title">분석에 사용되는 최근 사진</div><div class="card-sub" id="aiCameraMeta">사진 없음</div></div></div><div id="aiImagePanel" class="empty-panel"><div><b>분석 이미지 없음</b><span>카메라 촬영을 먼저 실행하세요.</span></div></div></article><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">LATEST ANALYSIS</div><div class="card-title">최근 분석 결과</div></div><span class="tag" id="analysisStatus">기록 없음</span></div><div id="analysisPanel" class="list-empty">분석 실행 기록이 없습니다.</div></article></div>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">TRACEABILITY</div><div class="card-title">최근 분석 이력</div></div></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>생성 시각</th><th>모델</th><th>상태</th><th>확신도</th></tr></thead><tbody id="analysisHistory"></tbody></table></div></article>`;

  $('automation').innerHTML=`
    <div class="page-head"><div><h1>자동화 센터</h1><p>서버 노트북의 Python 스케줄러가 담당합니다. n8n 없이도 실행되며 필요하면 나중에 연동할 수 있습니다.</p></div><div class="actions"><button class="btn primary" id="runCaptureAnalysis"><svg class="icon"><use href="#i-play"/></svg>촬영·분석 지금 실행</button></div></div>
    <div class="grid workflow-stats"><article class="card kpi temp"><div class="kpi-top"><span>센서 수집</span><span class="kpi-icon">USB</span></div><div class="kpi-value">5<small>초</small></div><div class="data-note measured">Pico 통합 런타임</div></article><article class="card kpi light"><div class="kpi-top"><span>사진·AI 분석</span><span class="kpi-icon">AI</span></div><div class="kpi-value">12<small>시</small></div><div class="data-note">텔레그램 사진 브리핑</div></article><article class="card kpi humid"><div class="kpi-top"><span>일간 보고서</span><span class="kpi-icon">PDF</span></div><div class="kpi-value">20<small>시</small></div><div class="data-note">텔레그램 선택 전송</div></article><article class="card kpi co2"><div class="kpi-top"><span>제어 방식</span><span class="kpi-icon">OK</span></div><div class="kpi-value">승인</div><div class="data-note">텔레그램 사람 최종 결정</div></article></div>
    <article class="card card-pad" style="margin-bottom:14px"><div class="card-head"><div><div class="eyebrow">LED PHOTOPERIOD</div><div class="card-title">LED 광주기 설정</div><div class="card-sub">AI가 아닌 사용자가 지정한 서울시간 고정 스케줄입니다. 최대 16시간까지 설정할 수 있습니다.</div></div><span class="tag" id="ledScheduleTag">확인 중</span></div><form id="ledScheduleForm" class="settings-form led-schedule-form"><label class="check-field"><input type="checkbox" id="ledScheduleEnabled"><span><b>광주기 활성화</b><small>끄면 LED에 즉시 OFF 명령을 보냅니다.</small></span></label><div class="field"><label for="ledOnTime">켜는 시각</label><input type="time" id="ledOnTime" value="06:00" required></div><div class="field"><label for="ledOffTime">끄는 시각</label><input type="time" id="ledOffTime" value="22:00" required></div><button class="btn primary" type="submit">광주기 저장</button></form><div class="settings-status" id="ledScheduleStatus">설정을 불러오는 중입니다.</div></article>
    <article class="card card-pad"><div class="card-head"><div><div class="eyebrow">PIPELINE</div><div class="card-title">실제 운영 흐름</div></div><span class="tag green" id="automationTag">설정 확인</span></div><div class="pipeline"><div class="node trigger"><div class="node-icon">T</div><b>정기 실행</b><small>서버 스케줄러</small></div><div class="arrow">→</div><div class="node camera-node"><div class="node-icon">C</div><b>카메라 촬영</b><small>JPEG 원본 저장</small></div><div class="arrow">→</div><div class="node ai-node"><div class="node-icon">AI</div><b>영상·센서 분석</b><small>근거·한계 기록</small></div><div class="arrow">→</div><div class="node db-node"><div class="node-icon">DB</div><b>SQLite 저장</b><small>추적 가능한 기록</small></div><div class="arrow">→</div><div class="node notify-node"><div class="node-icon">H</div><b>사람 승인</b><small>안전검사 후 실행</small></div></div></article>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">EXECUTIONS</div><div class="card-title">최근 자동화 실행</div></div></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>실행 시각</th><th>작업</th><th>상태</th><th>상세</th></tr></thead><tbody id="workflowTable"></tbody></table></div></article>`;

  $('reports').innerHTML=`
    <div class="page-head"><div><h1>생육 보고서</h1><p>당일 센서 통계·최신 AI 관찰·액추에이터 감사 기록을 근거로 PDF를 생성합니다.</p></div><div class="actions"><label class="tag"><input type="checkbox" id="sendTelegram"> 텔레그램 전송</label><button class="btn primary" id="generateReport"><svg class="icon"><use href="#i-report"/></svg>오늘 보고서 생성</button></div></div>
    <div class="mode-banner"><div><strong>신뢰성 표시 원칙</strong><span>실측·모의·AI 관찰·누락을 구분하며, 모든 액추에이터 요청·승인·전송·응답 기록을 포함합니다.</span></div><span class="tag">PDF 감사 기록</span></div>
    <article class="card"><div class="card-pad card-head"><div><div class="eyebrow">REPORT ARCHIVE</div><div class="card-title">생성된 일간 보고서</div></div><span class="tag" id="reportCount">0건</span></div><div id="reportList"><div class="list-empty">보고서 기록을 불러오는 중입니다.</div></div></article>`;

  $('system').innerHTML=`
    <div class="page-head"><div><h1>시스템</h1><p>학교 서버 노트북에 필요한 연결과 비밀 설정의 준비 상태를 표시합니다.</p></div><div class="actions"><button class="btn" id="refreshHealth">상태 다시 확인</button></div></div>
    <div class="health-grid" id="healthGrid"></div>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">CROP CAMERAS</div><div class="card-title">Hikvision 카메라 3대 설정</div><div class="card-sub">각 카메라를 서로 다른 IP로 활성화한 뒤 JPEG 주소와 계정을 저장합니다. 비밀번호는 서버의 .env에만 저장됩니다.</div></div><span class="tag" id="cameraSettingsTag">확인 중</span></div><form id="cameraSettingsForm"><div class="camera-settings-grid">${[1,2,3].map(number=>`<div class="camera-setting-row"><div class="camera-setting-title"><b>CAM-${String(number).padStart(2,'0')}</b><span id="camera${number}Saved">미설정</span></div><div class="field"><label for="camera${number}Label">이름</label><input id="camera${number}Label" value="카메라 ${number}"></div><div class="field url"><label for="camera${number}Url">JPEG 스냅샷 주소</label><input id="camera${number}Url" placeholder="http://192.168.0.${59+number}/ISAPI/Streaming/channels/101/picture"></div><div class="field"><label for="camera${number}User">사용자</label><input id="camera${number}User" value="admin" autocomplete="username"></div><div class="field"><label for="camera${number}Password">비밀번호</label><input type="password" id="camera${number}Password" placeholder="변경할 때만 입력" autocomplete="new-password"></div></div>`).join('')}</div><div class="camera-settings-actions"><button class="btn primary" type="submit">카메라 설정 저장</button><button class="btn" type="button" id="testCameras">3대 지금 촬영</button></div></form><div class="settings-status" id="cameraSettingsStatus">카메라 설정을 불러오는 중입니다.</div></article>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">OPENAI API</div><div class="card-title">OpenAI API 설정</div><div class="card-sub">API 키는 서버의 .env에만 저장되며 화면으로 다시 표시되지 않습니다.</div></div><span class="tag" id="openaiSettingsTag">확인 중</span></div><form id="openaiSettingsForm" class="settings-form"><div class="field grow"><label for="openaiApiKey">API 키</label><input type="password" id="openaiApiKey" placeholder="변경할 때만 입력" autocomplete="new-password"></div><div class="field"><label for="openaiModelInput">모델</label><input id="openaiModelInput" value="gpt-5.6-sol" required></div><button class="btn primary" type="submit">서버에 저장</button><button class="btn" type="button" id="testOpenAI">연결 테스트</button></form><div class="settings-status" id="openaiSettingsStatus">설정을 불러오는 중입니다. 원격 접속에서는 로그인과 HTTPS가 필수입니다.</div></article>
    <article class="card card-pad" style="margin-top:14px"><div class="card-head"><div><div class="eyebrow">TELEGRAM APPROVAL</div><div class="card-title">텔레그램 정오 알림·최종 승인</div><div class="card-sub">매일 12:00(서울)에 사진·AI 관찰·실측값을 전송합니다. 승인 버튼은 지정한 Telegram 사용자만 누를 수 있고, Pico 안전검사를 통과해야 실행됩니다.</div></div><span class="tag" id="telegramSettingsTag">확인 중</span></div><form id="telegramSettingsForm" class="settings-form telegram-settings-form"><div class="field telegram-token"><label for="telegramBotToken">봇 토큰</label><input type="password" id="telegramBotToken" placeholder="변경할 때만 입력" autocomplete="new-password"></div><div class="field telegram-chat"><label for="telegramChatId">FFK 대상 채팅 ID</label><input id="telegramChatId" placeholder="FFK 그룹 ID 찾기로 자동 입력"></div><div class="field telegram-approvers"><label for="telegramApprovers">지정 승인자 Telegram 사용자 ID</label><textarea id="telegramApprovers" rows="3" placeholder="선택 사항 · 여러 명 입력 가능 · 쉼표 또는 줄바꿈 구분&#10;예: 123456789&#10;987654321"></textarea><small>아래의 ‘FFK 전체 구성원 승인’을 켜면 이 칸을 비워도 됩니다.</small></div><label class="check-field telegram-daily"><input type="checkbox" id="telegramDailyEnabled"><span><b>매일 12:00 사진·AI 상태 전송</b><small>서울시간 기준</small></span></label><label class="check-field telegram-approval"><input type="checkbox" id="telegramApprovalEnabled"><span><b>텔레그램 최종 승인 허용</b><small>승인자 ID 또는 FFK 구성원 검증 필요</small></span></label><label class="check-field telegram-group-members"><input type="checkbox" id="telegramAllowGroupMembers"><span><b>FFK 전체 구성원 승인 허용</b><small>봇을 FFK 그룹 관리자로 지정해야 합니다.</small></span></label><div class="telegram-actions"><button class="btn primary" type="submit">텔레그램 설정 저장</button><button class="btn" type="button" id="testTelegram">봇 연결 확인</button><button class="btn" type="button" id="discoverTelegramGroups">FFK 그룹 ID 찾기</button><button class="btn primary" type="button" id="sendTelegramBrief">🥦 브로콜리봇 지금 브리핑</button></div></form><div class="settings-status telegram-group-choices" id="telegramGroupChoices">FFK 그룹에 봇을 초대한 뒤 그룹에서 /start@봇이름 을 보내고, 그룹 ID 찾기를 누르세요.</div><div class="settings-status" id="telegramSettingsStatus">토큰은 서버의 .env에만 저장되고 다시 표시되지 않습니다.</div></article>
    <div class="grid two" style="margin-top:14px"><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">SERVER ROLE</div><div class="card-title">장비별 역할</div></div></div><div class="architecture"><div class="arch-box"><b>Pico 2 W</b><span>센서·릴레이·자동 OFF</span></div><div class="arch-arrow">→ USB →</div><div class="arch-box"><b>학교 서버 노트북</b><span>DB·카메라·AI·보고서·제어</span></div><div class="arch-arrow">→ HTTPS →</div><div class="arch-box"><b>PC·스마트폰</b><span>조회·승인·보고서</span></div></div></article><article class="card card-pad"><div class="card-head"><div><div class="eyebrow">SECURITY</div><div class="card-title">외부 접속 전 필수 조건</div></div></div><ul class="bullet-list"><li>대시보드 사용자명과 강한 비밀번호 설정</li><li>카메라 포트 직접 공개 금지, 서버만 카메라에 접근</li><li>HTTPS 터널 또는 VPN 사용</li><li>실제 제어 전 비상정지·최대 작동시간·현장 시험 완료</li></ul></article></div>`;
}

function bindNavigation(){
  document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>showPage(button.dataset.page)));
  document.addEventListener('click',event=>{const button=event.target.closest('[data-page-jump]');if(button)showPage(button.dataset.pageJump);});
}
function showPage(id){document.querySelectorAll('.page').forEach(page=>page.classList.toggle('on',page.id===id));document.querySelectorAll('[data-page]').forEach(button=>button.classList.toggle('on',button.dataset.page===id));$('crumbName').textContent=titles[id];if(id==='overview'||id==='analytics')requestAnimationFrame(drawCharts);if(id==='performance')requestAnimationFrame(drawPerformanceComparison);window.scrollTo({top:0,behavior:'smooth'});}

function applyLatest(data){
  const online=Boolean(data.pico_connected);
  const remote=data.mqtt_mode==='subscribe'||data.port==='MQTT';
  const temperatureHumidityOnline=Boolean(data.temperature_humidity_connected);
  const co2Online=Boolean(data.co2_connected);
  const pe350Online=Boolean(data.pe350_connected);
  const liveCount=[temperatureHumidityOnline,co2Online,pe350Online].filter(Boolean).length;
  const noSensors=online&&liveCount===0;
  const partial=online&&liveCount<3;
  const errors=data.sensor_errors||{};
  const airTemp=temperatureHumidityOnline?data.air_temp:null,humidity=temperatureHumidityOnline?data.humidity:null,co2=co2Online?data.co2:null,ec=pe350Online?data.ec:null,ph=pe350Online?data.ph:null,solutionTemp=pe350Online?data.solution_temp:null;
  $('sensorTopState').textContent=!online?(remote?'MQTT · WAITING':'PICO USB · OFFLINE'):data.simulation?'SIMULATION · LIVE':remote?(partial?'MQTT · PARTIAL':'MQTT · LIVE'):noSensors?'PICO USB · NO SENSOR':partial?'PICO USB · PARTIAL':'PICO USB · LIVE';
  $('sidebarSensorState').textContent=!online?'센서 연결 확인 필요':partial?`${liveCount}/3 센서군 실측 중`:'센서 수집 정상';
  $('sidebarSensorDetail').textContent=online?`${data.port} · ${fmt(data.age_seconds,1)}초 전`:(data.error||'데이터 없음');
  $('sensorBannerTitle').textContent=!online?(remote?'학교 MQTT 실측 데이터를 받지 못했습니다.':'Pico 통합 데이터를 받지 못했습니다.'):noSensors?(remote?'MQTT 메시지에 유효한 센서값이 없습니다.':'Pico는 연결됐지만 유효한 센서값이 없습니다.'):partial?'정상 센서의 부분 실측값을 수신하고 있습니다.':remote?'학교 MQTT 실측 데이터를 수신하고 있습니다.':'통합 센서 데이터를 수신하고 있습니다.';
  $('sensorBannerText').textContent=!online?(data.error||(remote?'학교 서버와 MQTT 설정을 확인하세요.':'USB와 실행 파일을 확인하세요.')):partial?(data.error||'일부 센서를 점검하세요.'):'RS485 온습도·CO₂·PE350 값이 SQLite에 자동 저장됩니다.';
  const source=sourceClass(data.source);const sourceText=data.source?sourceLabel(data.source):'실측 데이터 대기';
  $('dataSourceBadge').textContent=sourceText;$('tempFoot').className=`data-note ${source}`;$('humidFoot').className=`data-note ${source}`;$('co2Foot').className=`data-note ${source}`;$('ecFoot').className=`data-note ${source}`;$('phFoot').className=`data-note ${source}`;
  $('tempFoot').textContent=temperatureHumidityOnline?`${sourceText} · RS485 SHTC3`:`RS485 SHTC3 · ${errors.rs485_shtc3||'연결 대기'}`;$('humidFoot').textContent=temperatureHumidityOnline?`${sourceText} · RS485 SHTC3`:`RS485 SHTC3 · ${errors.rs485_shtc3||'연결 대기'}`;$('co2Foot').textContent=co2Online?`${sourceText} · RS485 KCD-HP100`:`RS485 KCD-HP100 · ${errors.rs485_co2||'연결 대기'}`;$('ecFoot').textContent=pe350Online?`${sourceText} · RS485 PE350`:`RS485 PE350 · ${errors.pe350||'연결 대기'}`;$('phFoot').textContent=pe350Online?`${sourceText} · RS485 PE350`:`RS485 PE350 · ${errors.pe350||'연결 대기'}`;
  $('tempValue').innerHTML=`${fmt(airTemp,1)}<small>°C</small>`;$('humidValue').innerHTML=`${fmt(humidity,1)}<small>%</small>`;$('co2Value').innerHTML=`${fmt(co2,0)}<small>ppm</small>`;$('ecValue').innerHTML=`${fmt(ec,3)}<small>dS/m</small>`;$('phValue').textContent=fmt(ph,2);$('solutionTempValue').innerHTML=`${fmt(solutionTemp,1)}<small>°C</small>`;
  $('pe350Status').textContent=pe350Online?'LIVE':'OFFLINE';$('pe350Status').className=`tag ${pe350Online?'green':'amber'}`;
  $('lastSensorAge').textContent=data.age_seconds===null?'--':`${fmt(data.age_seconds,1)}초`;$('dataQuality').textContent=online?`${liveCount}/3`:'OFF';$('dataQualityFoot').textContent=data.recorded_at?timeText(data.recorded_at):'기록 없음';
  const growth=data.growth_score||{},score=Number.isFinite(Number(growth.score))?Number(growth.score):null,scoreStatus=growth.status||'판단 불가';
  const scoreLevels={
    '매우 좋음':{emoji:'🥦✨',mascot:'broc-happy',color:'#0a9b71',track:'#dce9e4',tagBg:'#e8f8f2',tagColor:'#0a9b71',title:'생육 단계 관리 기준에 매우 잘 맞습니다.'},
    '좋음':{emoji:'😊',mascot:'broc-happy',color:'#46a56a',track:'#e0f0e5',tagBg:'#edf8ef',tagColor:'#358153',title:'전반적으로 좋은 상태입니다.'},
    '보통':{emoji:'🙂',mascot:'broc-ok',color:'#91a83f',track:'#edf1d9',tagBg:'#f2f5df',tagColor:'#738a2c',title:'전반적으로 보통입니다. 일부 추세만 계속 확인하세요.'},
    '관찰 필요':{emoji:'👀',mascot:'broc-confused',color:'#c79a27',track:'#f7edd1',tagBg:'#fff6df',tagColor:'#9a7418',title:'기준 근처 항목이 있어 추세 관찰이 필요합니다.'},
    '주의':{emoji:'😟',mascot:'broc-sick',color:'#dd7f20',track:'#f9e4cf',tagBg:'#fff0df',tagColor:'#b86416',title:'관리 기준 이탈 항목을 현장에서 확인하세요.'},
    '위험':{emoji:'🚨',mascot:'broc-sick',color:'#d93f4c',track:'#f0dfe1',tagBg:'#fff0f1',tagColor:'#d93f4c',title:'즉시 현장 점검이 필요한 상태입니다.'},
  };
  const level=scoreLevels[scoreStatus]||{emoji:'⚪',mascot:'broc-confused',color:'#aeb9c7',track:'#dce9e4',tagBg:'#f2f5f9',tagColor:'#7c899c',title:'센서 근거가 부족해 점수를 산출할 수 없습니다.'};
  $('scoreNumber').textContent=score===null?'--':score;$('scoreMood').textContent=score===null?'⚪ 판정 불가':`${level.emoji} ${scoreStatus}`;$('scoreMascot').className=`broc-emoji ${level.mascot} score-mascot`;$('scoreRing').style.background=score===null?'conic-gradient(#aeb9c7 0 100%,#dce9e4 100%)':`conic-gradient(${level.color} 0 ${score}%,${level.track} ${score}%)`;
  $('overallTag').textContent=scoreStatus;$('overallTag').className='tag';$('overallTag').style.background=level.tagBg;$('overallTag').style.color=level.tagColor;$('overallTitle').textContent=level.title;$('overallText').textContent=`${growth.name||'관리 환경 점수'} · ${growth.stage||'생육 단계 확인 필요'} 기준 · ${growth.source||'출처 확인 필요'} · AI 사진 관찰은 별도 표시`;
  const scoreDetails=$('scoreDetails');if(scoreDetails){const components=Array.isArray(growth.components)?growth.components:[];scoreDetails.innerHTML=components.map(item=>`<span><b>${escapeHtml(item.label)}</b><strong>${Number(item.points||0).toFixed(1)}<i>/ ${Number(item.out_of||0).toFixed(0)}</i></strong><small>${escapeHtml(item.detail||'근거 미입력')}</small></span>`).join('')||'점수 근거를 불러오는 중입니다.';}
}

function applyHealth(health){
  const simulation=health.simulation,remote=health.mqtt_mode==='subscribe',remoteLive=remote&&health.pico==='online';$('modeBanner').className=`mode-banner ${simulation||remote&&!remoteLive?'warning':''}`;$('modeBanner').innerHTML=`<div><strong>${simulation?'게이밍 노트북 모의 실행':remote?'외부망 MQTT 실측 조회':'학교 서버 실측 운영'}</strong><span>${simulation?'현재 값은 실측이 아니며 장치 출력도 발생하지 않습니다.':remote?(remoteLive?'학교 서버가 발행한 센서 실측값을 읽기 전용으로 표시합니다.':'MQTT 브로커 연결 상태와 학교 서버의 센서 발행을 확인하는 중입니다.'):'Pico USB·SQLite 기반 실측 모드이며 MQTT로 외부에 발행합니다.'}</span></div><span class="tag ${simulation||remote&&!remoteLive?'amber':'green'}">${simulation?'SIMULATION':remote?(remoteLive?'MQTT LIVE':'MQTT WAIT'):'MEASURED'}</span>`;
  $('cameraCount').textContent=`${health.camera_count}대`;$('modelName').textContent=health.configured_model;$('aiModelTitle').textContent=`설정 모델 · ${health.configured_model}`;$('aiConfigured').textContent=health.openai_configured?'API 연결 준비':'API 키 미설정';$('aiConfigured').className=`tag ${health.openai_configured?'green':'amber'}`;$('controlMode').textContent=health.control_enabled?'실물 제어 활성':remote?'외부 조회 · 제어 차단':'모의 실행 · 출력 차단';$('controlMode').className=`tag ${health.control_enabled?'red':'amber'}`;$('automationTag').textContent=health.automation_enabled?'스케줄 활성':'스케줄 중지';$('automationTag').className=`tag ${health.automation_enabled?'green':'amber'}`;const requestButton=document.querySelector('#manualRequestForm button[type="submit"]');if(requestButton){requestButton.disabled=remote;requestButton.textContent=remote?'외부 조회 모드':'승인 요청';}
  const services=[['FastAPI','online',health.server==='online'],['SQLite',health.database_path,health.database==='online'],['Pico 2 W',health.pico_error||health.pico,health.pico==='online'],['MQTT',`${health.mqtt_mode} · ${health.mqtt_error||'정상'}`,health.mqtt_mode==='off'||health.mqtt_connected],['OpenAI',health.configured_model,health.openai_configured],['카메라',`${health.camera_count}대 설정`,health.camera_count>0],['텔레그램',health.telegram_approvals_ready?(health.telegram_polling?'승인 수신 대기':'승인 수신 시작 중'):health.telegram_configured?'승인자 설정 필요':'토큰/채팅방 미설정',health.telegram_approvals_ready&&health.telegram_polling],['대시보드 로그인',health.dashboard_auth_configured?'설정됨':'미설정',health.dashboard_auth_configured],['실물 제어',health.control_enabled?'활성':'기본 차단',health.control_enabled],['EC/pH 펌프',health.chemical_control_enabled?'별도 활성':'별도 차단',health.chemical_control_enabled],['자동화',health.automation_enabled?'활성':'중지',health.automation_enabled]];
  $('healthGrid').innerHTML=services.map(([name,detail,ok])=>`<div class="health-item"><div><b>${escapeHtml(name)}</b><small>${escapeHtml(detail)}</small></div>${statusTag(ok,ok?'준비':'',ok?'':'미설정')}</div>`).join('');
}

function applyOpenAISettings(data){
  if(!$('openaiSettingsForm').matches(':focus-within'))$('openaiModelInput').value=data.model;
  $('openaiSettingsTag').textContent=data.configured?'키 저장됨':'키 미설정';
  $('openaiSettingsTag').className=`tag ${data.configured?'green':'amber'}`;
  $('openaiSettingsStatus').textContent=data.configured?`서버 환경변수에 저장됨 · 모델 ${data.model}`:'API 키를 입력한 뒤 서버에 저장하세요.';
}

function applyTelegramSettings(data){
  const form=$('telegramSettingsForm');if(!form)return;
  telegramFinalApproval=Boolean(data.approval_enabled);
  if(!form.matches(':focus-within')){$('telegramChatId').value='';$('telegramApprovers').value='';$('telegramDailyEnabled').checked=data.daily_enabled;$('telegramApprovalEnabled').checked=data.approval_enabled;$('telegramAllowGroupMembers').checked=data.allow_group_members;}
  const ready=data.approvals_ready&&data.polling;$('telegramSettingsTag').textContent=ready?'승인 수신 중':data.configured?'설정 확인':'미설정';$('telegramSettingsTag').className=`tag ${ready?'green':'amber'}`;
  const base=data.config_error||(!data.configured?'봇 토큰과 대상 채팅 ID를 서버에서 저장하세요.':data.approvals_ready?(data.polling?'정오 12:00 브리핑과 승인 버튼이 준비되었습니다.':'승인 수신기를 시작하는 중입니다.'):`봇/채팅 저장됨 · ${data.allow_group_members?'FFK 전체 구성원 승인 사용':'지정 승인자 '+data.approver_count+'명'} · 승인 기능은 설정 확인 필요`);
  $('telegramSettingsStatus').textContent=`${base}${data.last_error?` · 최근 오류: ${data.last_error}`:''}`;
  $('telegramBotToken').placeholder=data.bot_token_saved?'토큰 저장됨 · 변경할 때만 입력':'BotFather 토큰';$('telegramChatId').placeholder=data.chat_id_saved?'채팅 ID 저장됨 · 변경할 때만 입력':'예: -100... 또는 개인 채팅 ID';$('telegramApprovers').placeholder=data.approver_count?`${data.approver_count}명 저장됨 · 변경 시 전체 입력`:'쉼표로 구분한 승인자 숫자 ID';
}

function applyLedSchedule(data){
  if(!$('ledScheduleForm').matches(':focus-within')){
    $('ledScheduleEnabled').checked=data.enabled;
    $('ledOnTime').value=data.on_time;
    $('ledOffTime').value=data.off_time;
  }
  const ready=data.enabled&&data.hardware_enabled&&!data.last_error;
  $('ledScheduleTag').textContent=!data.enabled?'중지':ready?'활성':'확인 필요';
  $('ledScheduleTag').className=`tag ${ready?'green':'amber'}`;
  const state=`현재 ${String(data.current_state).toUpperCase()} · 목표 ${String(data.desired_state).toUpperCase()} · ${data.on_time}–${data.off_time} (${data.photoperiod_hours}시간)`;
  $('ledScheduleStatus').textContent=data.last_error?`${state} · ${data.last_error}`:state;
}

function applyCameras(data){
  const captures=data.captures||[],configured=data.configured||[];const latest=captures.find(item=>item.status==='success'&&item.path);$('cameraMeta').textContent=`${configured.length}대 설정 · ${latest?timeText(latest.captured_at):'성공 사진 없음'}`;$('aiCameraMeta').textContent=latest?`${latest.camera_id} · ${timeText(latest.captured_at)}`:'사진 없음';
  if(configured.length){
    $('cameraPanel').className='camera-gallery';
    $('cameraPanel').innerHTML=configured.map(camera=>{const capture=captures.find(item=>item.camera_id===camera.id);const ok=capture&&capture.status==='success'&&capture.path;return `<div class="camera-tile"><div class="camera-frame">${ok?`<img class="real-photo" src="/api/captures/${capture.id}?t=${Date.now()}" alt="${escapeHtml(camera.label)} 최근 촬영 이미지">`:`<div class="camera-placeholder"><b>${capture&&capture.status==='failed'?'촬영 실패':'촬영 대기'}</b><span>${escapeHtml(capture&&capture.error?capture.error:'지금 촬영을 눌러 확인하세요.')}</span></div>`}</div><div class="camera-caption"><div><b>${escapeHtml(camera.label)}</b><small>${escapeHtml(camera.id)} · ${capture?timeText(capture.captured_at):'기록 없음'}</small></div><span class="tag ${ok?'green':'amber'}">${ok?'정상':capture&&capture.status==='failed'?'오류':'대기'}</span></div></div>`;}).join('');
  }else{$('cameraPanel').className='empty-panel';$('cameraPanel').innerHTML='<div><b>카메라 미설정</b><span>시스템 페이지에서 카메라 3대를 설정하세요.</span></div>';}
  const aiHtml=latest?`<img class="real-photo" src="/api/captures/${latest.id}?t=${Date.now()}" alt="최근 브로콜리 촬영 이미지">`:'<div><b>이미지 대기</b><span>카메라를 설정한 뒤 지금 촬영을 실행하세요.</span></div>';
  $('aiImagePanel').className=latest?'':'empty-panel';$('aiImagePanel').innerHTML=aiHtml;
  applyCameraSettings(data);
}

function applyCameraSettings(data){
  const form=$('cameraSettingsForm');if(!form)return;const slots=data.slots||[];
  if(!form.matches(':focus-within'))slots.filter(item=>item.slot<=3).forEach(item=>{const n=item.slot;$(`camera${n}Label`).value=item.label;$(`camera${n}Url`).value=item.snapshot_url;$(`camera${n}User`).value=item.username||'admin';$(`camera${n}Password`).placeholder=item.password_saved?'비밀번호 저장됨 · 변경할 때만 입력':'비밀번호 입력';});
  slots.filter(item=>item.slot<=3).forEach(item=>{$(`camera${item.slot}Saved`).textContent=item.configured?'주소 저장됨':'미설정';});
  const count=(data.configured||[]).filter(item=>item.slot<=3).length;$('cameraSettingsTag').textContent=`${count}/3 설정`;$('cameraSettingsTag').className=`tag ${count===3?'green':'amber'}`;$('cameraSettingsStatus').textContent=count===3?'세 카메라 주소가 저장되었습니다. 지금 촬영으로 인증과 이미지 수신을 확인하세요.':'카메라별 활성화·고유 IP 설정 후 빈 주소를 입력하세요.';
}

function recommendationHtml(item,buttons=false){const action=item.actuator?`${item.actuator} · ${item.requested_state||'-'} · ${item.duration_seconds||0}초`:'현장 확인 제안';const decisionUi=buttons&&item.status==='pending'?(telegramFinalApproval?'<span class="tag amber">텔레그램 승인</span>':`<div class="approval-actions"><button class="btn danger" data-decision="reject" data-id="${item.id}">거절</button><button class="btn primary" data-decision="approve" data-id="${item.id}">승인</button></div>`):`<span class="tag ${item.status==='pending'?'amber':item.status==='rejected'?'red':'green'}">${escapeHtml(item.status)}</span>`;return `<div class="approval"><div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.rationale)}</p><small>${escapeHtml(item.source)} · ${escapeHtml(action)} · ${timeText(item.created_at)}</small></div>${decisionUi}</div>`;}
function applyRecommendations(items){const pending=items.filter(item=>item.status==='pending');$('pendingCount').textContent=`${pending.length}건`;$('queueCount').textContent=`${pending.length}건`;$('overviewRecommendations').innerHTML=pending.length?pending.slice(0,3).map(item=>recommendationHtml(item)).join(''):'<div class="list-empty">현재 승인 대기 항목이 없습니다.</div>';$('approvalQueue').innerHTML=items.length?items.map(item=>recommendationHtml(item,true)).join(''):'<div class="list-empty">제어 요청이나 AI 제안이 없습니다.</div>';}

function applyActuators(data){const manualItems=data.items.filter(item=>!(data.supply_continuous_enabled&&item.id==='supply'));$('requestActuator').innerHTML=manualItems.map(item=>`<option value="${item.id}">${escapeHtml(item.label)}</option>`).join('');$('actuatorGrid').innerHTML=data.items.map(item=>{const detail=data.supply_continuous_enabled&&item.id==='supply'?'24시간 고정 순환 · 수동 ON/OFF 불가':`최대 연속 작동 ${item.max_seconds}초${['ec','ph'].includes(item.id)&&!data.chemical_control_enabled?' · 화학 펌프 별도 차단':''}`;return `<div class="actuator-card"><div class="row"><h3>${escapeHtml(item.label)}</h3><span class="tag ${item.state==='on'?'red':'green'}">${escapeHtml(item.state.toUpperCase())}</span></div><p>${detail}</p></div>`;}).join('');}
function applyActuatorEvents(items){const labels={led:'LED',raw_water:'원수',supply:'양액 공급',mixing:'교반',ec:'A+B 양액펌프',ph:'pH 산성액펌프',fan:'환풍기'},results={requested:'요청',approved:'승인',rejected:'거절',blocked:'안전 차단',deferred:'보정 대기',sent:'Pico 전송',pico_ack:'Pico 확인',pico_timeout:'시간 종료',pico_error:'Pico 오류',failed:'전송 실패',simulated:'잠금·모의',session_started:'보정 시작',target_reached:'목표 도달',session_limit:'횟수 제한',session_blocked:'세션 중단',safety_stop:'안전 중단',safety_stopped:'안전 중단',superseded:'정책 교체'};$('actuatorEventCount').textContent=`${items.length}건`;$('actuatorEventTable').innerHTML=items.length?items.map(item=>{const command=`${String(item.requested_state||'-').toUpperCase()}${item.duration_seconds?` · ${item.duration_seconds}초`:''}`;return `<tr><td>${timeText(item.created_at)}</td><td>${escapeHtml(labels[item.actuator]||item.actuator)}</td><td>${escapeHtml(command)}</td><td>${escapeHtml(results[item.result]||item.result)}</td><td>${escapeHtml(item.source||'-')} · ${escapeHtml(item.note||'-')}</td></tr>`;}).join(''):'<tr><td colspan="5">아직 액추에이터 기록이 없습니다.</td></tr>';}

function applyAnalyses(items){const latest=items[0];if(!latest){$('analysisPanel').innerHTML='분석 실행 기록이 없습니다.';$('analysisHistory').innerHTML='<tr><td colspan="5">기록 없음</td></tr>';return;}const result=latest.result||{};$('analysisStatus').textContent=result.overall_status||latest.overall_status;$('analysisStatus').className=`tag ${(result.overall_status||latest.overall_status)==='정상'?'green':'amber'}`;$('analysisPanel').className='analysis-summary';$('analysisPanel').innerHTML=`<h3>${escapeHtml(result.summary||latest.summary)}</h3><p>확신도: ${escapeHtml(result.confidence||latest.confidence)} · 모델: ${escapeHtml(latest.model)}</p><ul class="bullet-list">${(result.observations||[]).map(value=>`<li>관찰 · ${escapeHtml(value)}</li>`).join('')}${(result.limitations||[]).map(value=>`<li>한계 · ${escapeHtml(value)}</li>`).join('')}</ul>`;$('analysisHistory').innerHTML=items.map(item=>`<tr><td>#${item.id}</td><td>${timeText(item.created_at)}</td><td class="mono">${escapeHtml(item.model)}</td><td>${escapeHtml(item.overall_status)}</td><td>${escapeHtml(item.confidence)}</td></tr>`).join('');}

function applyWorkflows(items){$('workflowTable').innerHTML=items.length?items.map(item=>`<tr><td>#${item.id}</td><td>${timeText(item.created_at)}</td><td>${escapeHtml(item.workflow)}</td><td>${statusTag(item.status==='success',item.status,item.status)}</td><td>${escapeHtml(item.detail||'-')}</td></tr>`).join(''):'<tr><td colspan="5">실행 기록 없음</td></tr>';}
function applyReports(items){$('reportCount').textContent=`${items.length}건`;$('reportList').innerHTML=items.length?items.map(item=>`<div class="report-row"><div><b>${escapeHtml(item.report_date)} 브로콜리 AI 일일 생육관찰 보고서</b><small>${timeText(item.created_at)} · ${escapeHtml(item.model)} · 텔레그램 ${escapeHtml(item.telegram_status||'미요청')}</small></div><a class="btn" href="/api/reports/${item.id}/download">PDF 열기</a></div>`).join(''):'<div class="list-empty">생성된 보고서가 없습니다.</div>';}

function drawChart(id,series){const canvas=$(id);if(!canvas||!canvas.offsetParent)return;const valid=series.map(item=>({...item,data:item.data.filter(value=>value!==null&&value!==undefined)})).filter(item=>item.data.length);const ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,width=canvas.clientWidth,height=canvas.clientHeight;canvas.width=width*ratio;canvas.height=height*ratio;ctx.scale(ratio,ratio);ctx.clearRect(0,0,width,height);ctx.strokeStyle='#e9edf3';for(let i=0;i<5;i++){const y=12+i*(height-30)/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}if(!valid.length){ctx.fillStyle='#8b96a7';ctx.font='11px sans-serif';ctx.fillText('표시할 데이터가 없습니다.',12,height/2);return;}const all=valid.flatMap(item=>item.data),min=Math.min(...all),max=Math.max(...all),range=max-min||1,count=Math.max(...valid.map(item=>item.data.length));valid.forEach(item=>{ctx.strokeStyle=item.color;ctx.lineWidth=2;ctx.beginPath();item.data.forEach((value,index)=>{const x=8+(count===1?0:index*(width-16)/(count-1)),y=12+(max-value)/range*(height-30);index?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();});}

function historyValues(key){return historyData.map(item=>numericSensorValue(item[key])).filter(Number.isFinite);}
function historySummary(key,digits,unit){const values=historyValues(key);if(!values.length)return '--';const last=values.at(-1),min=Math.min(...values),max=Math.max(...values);return `현재 ${last.toFixed(digits)}${unit} · ${min.toFixed(digits)}–${max.toFixed(digits)}`;}
function historyTimeText(value){const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
function showHistoryInspector(item){const target=$('historyInspector');if(!target||!item)return;target.innerHTML=`<b>${historyTimeText(item.recorded_at)}</b><span>온도 ${fmt(item.air_temp,1)}℃ · 습도 ${fmt(item.humidity,1)}% · EC ${fmt(item.ec,3)} · pH ${fmt(item.ph,2)}</span>`;}
function drawDetailedChart(id,key,color,label,unit,digits){const canvas=$(id);if(!canvas||!canvas.offsetParent)return;const points=historyData.map(item=>({item,value:Number(item[key]),time:new Date(item.recorded_at).getTime()})).filter(point=>Number.isFinite(point.value)&&Number.isFinite(point.time));const ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,width=canvas.clientWidth,height=canvas.clientHeight;canvas.width=width*ratio;canvas.height=height*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);const left=48,right=16,top=14,bottom=30,plotW=Math.max(1,width-left-right),plotH=Math.max(1,height-top-bottom);if(!points.length){ctx.fillStyle='#8b96a7';ctx.font='11px sans-serif';ctx.fillText('선택 기간에 표시할 데이터가 없습니다.',left,top+24);return;}const values=points.map(point=>point.value),times=points.map(point=>point.time);let min=Math.min(...values),max=Math.max(...values);const pad=(max-min||Math.max(Math.abs(max)*.05,1))*.12;min-=pad;max+=pad;const range=max-min||1,start=Math.min(...times),end=Math.max(...times),span=end-start||1;ctx.font='10px sans-serif';ctx.strokeStyle='#edf1f5';ctx.fillStyle='#8491a3';ctx.lineWidth=1;for(let step=0;step<5;step++){const y=top+plotH*step/4,value=max-range*step/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();ctx.fillText(`${value.toFixed(digits)}${unit}`,2,y+3);}ctx.strokeStyle=color;ctx.lineWidth=2;ctx.lineJoin='round';ctx.beginPath();points.forEach((point,index)=>{const x=left+(point.time-start)/span*plotW,y=top+(max-point.value)/range*plotH;index?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.fillStyle='#8491a3';ctx.fillText(historyTimeText(points[0].item.recorded_at),left,height-8);const endText=historyTimeText(points.at(-1).item.recorded_at);ctx.fillText(endText,Math.max(left,width-right-ctx.measureText(endText).width),height-8);canvas.onmousemove=event=>{const rect=canvas.getBoundingClientRect(),x=Math.min(width-right,Math.max(left,event.clientX-rect.left));const targetTime=start+(x-left)/plotW*span;let nearest=points[0];for(const point of points){if(Math.abs(point.time-targetTime)<Math.abs(nearest.time-targetTime))nearest=point;}showHistoryInspector(nearest.item);ctx.setLineDash([3,3]);ctx.strokeStyle='#738199';ctx.beginPath();const px=left+(nearest.time-start)/span*plotW;ctx.moveTo(px,top);ctx.lineTo(px,top+plotH);ctx.stroke();ctx.setLineDash([]);};canvas.onmouseleave=()=>{const inspector=$('historyInspector');if(inspector)inspector.textContent='그래프 위에 마우스를 올리면 해당 시각의 실측값이 표시됩니다.';};}
function chartPoints(key){return historyData.map(item=>({item,value:Number(item[key]),time:new Date(item.recorded_at).getTime()})).filter(point=>Number.isFinite(point.value)&&Number.isFinite(point.time));}
function exactHistoryTime(value){const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});}
function drawHourlyMarkers(id,key,color){const canvas=$(id),points=chartPoints(key);if(!canvas||!canvas.offsetParent||!points.length)return;const ctx=canvas.getContext('2d'),width=canvas.clientWidth,height=canvas.clientHeight,left=48,right=16,top=14,bottom=30,plotW=Math.max(1,width-left-right),plotH=Math.max(1,height-top-bottom),values=points.map(point=>point.value),times=points.map(point=>point.time);let min=Math.min(...values),max=Math.max(...values);const pad=(max-min||Math.max(Math.abs(max)*.05,1))*.12;min-=pad;max+=pad;const range=max-min||1,start=Math.min(...times),span=Math.max(1,Math.max(...times)-start);ctx.fillStyle='#fff';ctx.strokeStyle=color;ctx.lineWidth=1.5;points.forEach(point=>{const x=left+(point.time-start)/span*plotW,y=top+(max-point.value)/range*plotH;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill();ctx.stroke();});}
function bindHistoryTooltip(id,key,label,unit,digits){const canvas=$(id),tooltip=$('historyTooltip');if(!canvas||!tooltip)return;const points=chartPoints(key);canvas.onmousemove=event=>{if(!points.length)return;const rect=canvas.getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),targetTime=points[0].time+ratio*(points.at(-1).time-points[0].time),point=points.reduce((nearest,current)=>Math.abs(current.time-targetTime)<Math.abs(nearest.time-targetTime)?current:nearest);tooltip.innerHTML=`<b>${exactHistoryTime(point.item.recorded_at)}</b><span>${label} ${point.value.toFixed(digits)}${unit} · 1시간 평균</span>`;tooltip.hidden=false;tooltip.style.left=`${Math.min(window.innerWidth-190,event.clientX+14)}px`;tooltip.style.top=`${Math.max(8,event.clientY-54)}px`;showHistoryInspector(point.item);};canvas.onmouseleave=()=>{tooltip.hidden=true;};}
function drawCharts(){const temp=historyData.map(item=>item.air_temp),humidity=historyData.map(item=>item.humidity);drawChart('overviewChart',[{data:temp,color:'#1769e0'},{data:humidity,color:'#706bd8'}]);const specs=[['temperatureHistoryChart','air_temp','#1769e0','온도','℃',1],['humidityHistoryChart','humidity','#706bd8','습도','%',1],['ecHistoryChart','ec','#0a9b71','EC','',3],['phHistoryChart','ph','#d88417','pH','',2]];specs.forEach(([id,key,color,label,unit,digits])=>{drawDetailedChart(id,key,color,label,unit,digits);drawHourlyMarkers(id,key,color);bindHistoryTooltip(id,key,label,unit,digits);});}
function applyHistory(items){historyData=items;const source=$('historySource');if(source)source.textContent=items.length?sourceLabel(items.at(-1).source):'데이터 없음';const table=$('historyTable');if(table)table.innerHTML=items.length?items.slice(-100).reverse().map(item=>`<tr><td>${timeText(item.recorded_at)}</td><td>${fmt(item.air_temp,1)}℃</td><td>${fmt(item.humidity,1)}%</td><td>${fmt(item.co2,0)}</td><td>${fmt(item.ec,3)}</td><td>${fmt(item.ph,2)}</td><td><span class="source-pill ${sourceClass(item.source)}">${sourceLabel(item.source)}</span></td></tr>`).join(''):'<tr><td colspan="7">저장된 데이터 없음</td></tr>';const labels=[['tempHistorySummary','air_temp',1,'℃'],['humidityHistorySummary','humidity',1,'%'],['ecHistorySummary','ec',3,''],['phHistorySummary','ph',2,'']];labels.forEach(([id,key,digits,unit])=>{const el=$(id);if(el)el.textContent=historySummary(key,digits,unit);});const rangeLabel=$('historyRangeLabel');if(rangeLabel)rangeLabel.textContent=`${historyRangeLabel} · ${items.length.toLocaleString()}포인트`;requestAnimationFrame(drawCharts);}

async function refreshAll(){try{const [latest,health,cameras,recommendations,actuators,actuatorEvents,analyses,reports,workflows,history,openaiSettings,ledSchedule,telegramSettings]=await Promise.all([api('/api/sensors/latest'),api('/api/health'),api('/api/cameras'),api('/api/recommendations'),api('/api/actuators'),api('/api/actuator-events'),api('/api/analyses'),api('/api/reports'),api('/api/workflows'),api(historyQuery),api('/api/settings/openai'),api('/api/led-schedule'),api('/api/settings/telegram')]);applyLatest(latest);applyHealth(health);applyCameras(cameras);applyRecommendations(recommendations);applyActuators(actuators);applyActuatorEvents(actuatorEvents);applyAnalyses(analyses);applyReports(reports);applyWorkflows(workflows);applyHistory(history);applyOpenAISettings(openaiSettings);applyLedSchedule(ledSchedule);applyTelegramSettings(telegramSettings);}catch(error){$('sensorTopState').textContent='SERVER · OFFLINE';$('sidebarSensorState').textContent='서버 연결 실패';$('sidebarSensorDetail').textContent=error.message;$('sensorBannerTitle').textContent='FastAPI 서버 응답 오류';$('sensorBannerText').textContent=error.message;toast(`연결 실패: ${error.message}`);}}

async function withBusy(button,task){button.classList.add('busy');button.disabled=true;try{await task();}catch(error){toast(error.message);}finally{button.classList.remove('busy');button.disabled=false;}}
function bindActions(){
  const localDateTime=value=>{const pad=part=>String(part).padStart(2,'0');return `${value.getFullYear()}-${pad(value.getMonth()+1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;};
  const historyEnd=new Date(),historyStart=new Date(historyEnd.getTime()-24*60*60*1000);$('historyStart').value=localDateTime(historyStart);$('historyEnd').value=localDateTime(historyEnd);
  $('refreshAll').addEventListener('click',refreshAll);$('refreshHealth').addEventListener('click',refreshAll);
  $('scoreDetailsToggle').addEventListener('click',event=>{const panel=$('scoreBreakdown'),open=panel.hidden;panel.hidden=!open;event.currentTarget.setAttribute('aria-expanded',String(open));event.currentTarget.innerHTML=open?'점수 산정 근거 접기 <span>⌃</span>':'점수 산정 근거 보기 <span>⌄</span>';});
  $('captureNow').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{await api('/api/cameras/capture',{method:'POST'});toast('카메라 촬영 작업을 완료했습니다.');await refreshAll();}));
  $('runAnalysis').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{await api('/api/analysis/run',{method:'POST'});toast('분석 결과를 저장했습니다.');await refreshAll();}));
  $('runCaptureAnalysis').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{await api('/api/workflows/capture-analysis',{method:'POST'});toast('촬영·분석 워크플로를 완료했습니다.');await refreshAll();}));
  $('generateReport').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{const send=$('sendTelegram').checked;const result=await api(`/api/reports/generate?send_telegram=${send}`,{method:'POST'});toast(`보고서 #${result.id} 생성 완료 · 텔레그램 ${result.telegram_status}`);await refreshAll();}));
  $('manualRequestForm').addEventListener('submit',async event=>{event.preventDefault();const actuator=$('requestActuator').value,state=$('requestState').value,duration=state==='on'?Number($('requestDuration').value):0;try{await api(`/api/actuators/${actuator}/request`,{method:'POST',body:JSON.stringify({state,duration_seconds:duration,reason:$('requestReason').value,operator:$('operatorName').value})});toast('승인 대기열에 추가했습니다.');await refreshAll();}catch(error){toast(error.message);}});
  $('approvalQueue').addEventListener('click',async event=>{const button=event.target.closest('[data-decision]');if(!button)return;const operator=$('operatorName').value.trim()||'미입력';await withBusy(button,async()=>{const result=await api(`/api/recommendations/${button.dataset.id}/decision`,{method:'POST',body:JSON.stringify({decision:button.dataset.decision,operator,note:'대시보드에서 결정'})});toast(`처리 결과: ${result.status}`);await refreshAll();});});
  $('historyRange').addEventListener('click',async event=>{const button=event.target.closest('[data-hours]');if(!button)return;$('historyRange').querySelectorAll('button').forEach(item=>item.classList.toggle('on',item===button));historyQuery=`/api/sensors/history?hours=${button.dataset.hours}&max_points=1600`;historyRangeLabel=`최근 ${button.textContent}`;try{applyHistory(await api(historyQuery));}catch(error){toast(error.message);}});
  $('historyCustomRange').addEventListener('submit',async event=>{event.preventDefault();const start=$('historyStart').value,end=$('historyEnd').value;if(!start||!end){toast('시작과 종료 시각을 모두 입력하세요.');return;}historyQuery=`/api/sensors/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&max_points=1600`;historyRangeLabel=`${start.replace('T',' ')} ~ ${end.replace('T',' ')}`;$('historyRange').querySelectorAll('button').forEach(item=>item.classList.remove('on'));try{applyHistory(await api(historyQuery));}catch(error){toast(error.message);}});
  $('openaiSettingsForm').addEventListener('submit',event=>{event.preventDefault();const button=event.currentTarget.querySelector('[type="submit"]');withBusy(button,async()=>{const result=await api('/api/settings/openai',{method:'PUT',body:JSON.stringify({api_key:$('openaiApiKey').value||null,model:$('openaiModelInput').value.trim()})});$('openaiApiKey').value='';toast(`OpenAI 설정 저장 완료 · ${result.model}`);await refreshAll();});});
  $('cameraSettingsForm').addEventListener('submit',event=>{event.preventDefault();const button=event.currentTarget.querySelector('[type="submit"]');withBusy(button,async()=>{const cameras=[1,2,3].map(slot=>({slot,label:$(`camera${slot}Label`).value.trim(),snapshot_url:$(`camera${slot}Url`).value.trim(),username:$(`camera${slot}User`).value.trim(),password:$(`camera${slot}Password`).value||null}));await api('/api/settings/cameras',{method:'PUT',body:JSON.stringify({cameras})});[1,2,3].forEach(slot=>$(`camera${slot}Password`).value='');toast('카메라 3대 설정을 서버에 저장했습니다.');await refreshAll();});});
  $('testCameras').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{const results=await api('/api/cameras/capture',{method:'POST'});const success=results.filter(item=>item.status==='success').length;toast(`카메라 촬영 ${success}/${results.length}대 성공`);await refreshAll();}));
  $('testOpenAI').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{const result=await api('/api/settings/openai/test',{method:'POST'});toast(`OpenAI 연결 성공 · ${result.model}`);await refreshAll();}));
  $('telegramSettingsForm').addEventListener('submit',event=>{event.preventDefault();const button=event.currentTarget.querySelector('[type="submit"]');withBusy(button,async()=>{const result=await api('/api/settings/telegram',{method:'PUT',body:JSON.stringify({bot_token:$('telegramBotToken').value||null,chat_id:$('telegramChatId').value.trim()||null,approver_user_ids:$('telegramApprovers').value.trim()||null,daily_enabled:$('telegramDailyEnabled').checked,approval_enabled:$('telegramApprovalEnabled').checked,allow_group_members:$('telegramAllowGroupMembers').checked})});$('telegramBotToken').value='';$('telegramChatId').value='';$('telegramApprovers').value='';toast('텔레그램 설정을 서버에 저장했습니다.');applyTelegramSettings(result);await refreshAll();});});
  $('testTelegram').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{const result=await api('/api/settings/telegram/test',{method:'POST'});toast(result.webhook_active?'봇 연결됨 · 기존 webhook을 해제해야 승인 버튼을 받을 수 있습니다.':`봇 연결 성공 · @${result.bot_username||'bot'}`);await refreshAll();}));
  $('discoverTelegramGroups').addEventListener('click',event=>withBusy(event.currentTarget,async()=>{const result=await api('/api/settings/telegram/discover-chats',{method:'POST'}),choices=result.chats||[];const panel=$('telegramGroupChoices');if(!choices.length){panel.textContent='최근 그룹 업데이트를 찾지 못했습니다. FFK 그룹에서 /start@봇이름 을 보낸 뒤 다시 누르세요.';return;}panel.innerHTML=choices.map(chat=>`<button class="btn" type="button" data-telegram-chat-id="${escapeHtml(chat.id)}">${escapeHtml(chat.title)} · ${escapeHtml(chat.id)}</button>`).join(' ');toast(`그룹 ${choices.length}개를 찾았습니다. FFK를 선택하세요.`);}));
  $('telegramGroupChoices').addEventListener('click',event=>{const button=event.target.closest('[data-telegram-chat-id]');if(!button)return;$('telegramChatId').value=button.dataset.telegramChatId;toast('대상 채팅 ID에 입력했습니다. 텔레그램 설정 저장을 누르세요.');});
  $('sendTelegramBrief').addEventListener('click',event=>{if(!confirm('카메라 촬영과 AI 분석을 실행한 뒤 실제 텔레그램 채팅에 사진·상태를 전송합니다. 계속할까요?'))return;withBusy(event.currentTarget,async()=>{const result=await api('/api/workflows/telegram-daily-brief',{method:'POST'});toast(`텔레그램 브리핑 ${result.status}`);await refreshAll();});});
  $('ledScheduleForm').addEventListener('submit',event=>{event.preventDefault();const button=event.currentTarget.querySelector('[type="submit"]');withBusy(button,async()=>{const result=await api('/api/led-schedule',{method:'PUT',body:JSON.stringify({enabled:$('ledScheduleEnabled').checked,on_time:$('ledOnTime').value,off_time:$('ledOffTime').value})});toast(`LED 광주기 저장 완료 · ${result.result}`);applyLedSchedule(result);await refreshAll();});});
}

function tick(){$('clock').textContent=new Date().toLocaleTimeString('ko-KR',{hour12:false});}
buildPages();bindNavigation();bindActions();tick();setInterval(tick,1000);refreshAll();setInterval(refreshAll,5000);window.addEventListener('resize',()=>requestAnimationFrame(drawCharts));
const historyChartGeometry = new Map();

// The older chart handler selected a time anywhere on the canvas and painted a new guide line
// on every mouse move.  Keep hover tied to the rendered marker instead, so the tooltip is stable.
function drawDetailedChart(id,key,color,label,unit,digits){
  const canvas=$(id);if(!canvas||!canvas.offsetParent)return;
  const points=historyData.map(item=>({item,value:numericSensorValue(item[key]),time:new Date(item.recorded_at).getTime()})).filter(point=>Number.isFinite(point.value)&&Number.isFinite(point.time));
  const ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,width=canvas.clientWidth,height=canvas.clientHeight;
  canvas.width=width*ratio;canvas.height=height*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
  const left=48,right=16,top=14,bottom=30,plotW=Math.max(1,width-left-right),plotH=Math.max(1,height-top-bottom);
  if(!points.length){historyChartGeometry.set(id,[]);ctx.fillStyle='#8b96a7';ctx.font='11px sans-serif';ctx.fillText('선택 기간에 표시할 데이터가 없습니다.',left,top+24);return;}
  const values=points.map(point=>point.value),times=points.map(point=>point.time);let min=Math.min(...values),max=Math.max(...values);
  const pad=(max-min||Math.max(Math.abs(max)*.05,1))*.12;min-=pad;max+=pad;
  const range=max-min||1,start=Math.min(...times),end=Math.max(...times),span=end-start||1;
  ctx.font='10px sans-serif';ctx.strokeStyle='#edf1f5';ctx.fillStyle='#8491a3';ctx.lineWidth=1;
  for(let step=0;step<5;step++){const y=top+plotH*step/4,value=max-range*step/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();ctx.fillText(`${value.toFixed(digits)}${unit}`,2,y+3);}
  const rendered=points.map(point=>({...point,x:left+(point.time-start)/span*plotW,y:top+(max-point.value)/range*plotH}));
  ctx.strokeStyle=color;ctx.lineWidth=2;ctx.lineJoin='round';ctx.beginPath();rendered.forEach((point,index)=>index?ctx.lineTo(point.x,point.y):ctx.moveTo(point.x,point.y));ctx.stroke();
  ctx.fillStyle='#fff';ctx.strokeStyle=color;ctx.lineWidth=1.5;rendered.forEach(point=>{ctx.beginPath();ctx.arc(point.x,point.y,3,0,Math.PI*2);ctx.fill();ctx.stroke();});
  ctx.fillStyle='#8491a3';ctx.fillText(historyTimeText(points[0].item.recorded_at),left,height-8);const endText=historyTimeText(points.at(-1).item.recorded_at);ctx.fillText(endText,Math.max(left,width-right-ctx.measureText(endText).width),height-8);
  historyChartGeometry.set(id,rendered);
}

function drawHourlyMarkers(){/* Markers are drawn together with the line so hover geometry stays exact. */}

function bindHistoryTooltip(id,key,label,unit,digits){
  const canvas=$(id),tooltip=$('historyTooltip');if(!canvas||!tooltip)return;
  const reset=()=>{tooltip.hidden=true;canvas.style.cursor='default';const inspector=$('historyInspector');if(inspector)inspector.textContent='모든 값은 1시간 평균입니다. 그래프의 원형 점에 정확히 마우스를 올리면 측정 시각과 값을 확인할 수 있습니다.';};
  canvas.onmousemove=event=>{
    const points=historyChartGeometry.get(id)||[],rect=canvas.getBoundingClientRect();if(!points.length||!rect.width){reset();return;}
    const mouseX=event.clientX-rect.left,mouseY=event.clientY-rect.top;
    const point=points.reduce((nearest,current)=>((current.x-mouseX)**2+(current.y-mouseY)**2)<((nearest.x-mouseX)**2+(nearest.y-mouseY)**2)?current:nearest);
    const distance=(point.x-mouseX)**2+(point.y-mouseY)**2;
    if(distance>100){reset();return;}
    canvas.style.cursor='pointer';tooltip.innerHTML=`<b>${exactHistoryTime(point.item.recorded_at)}</b><span>${label} ${point.value.toFixed(digits)}${unit} · 1시간 평균</span>`;tooltip.hidden=false;
    tooltip.style.left=`${Math.max(8,Math.min(window.innerWidth-205,rect.left+point.x+12))}px`;tooltip.style.top=`${Math.max(8,Math.min(window.innerHeight-68,rect.top+point.y-54))}px`;
    showHistoryInspector(point.item);
  };
  canvas.onmouseleave=reset;
}

function drawCharts(){
  const temp=historyData.map(item=>item.air_temp),humidity=historyData.map(item=>item.humidity);
  drawChart('overviewChart',[{data:temp,color:'#1769e0'},{data:humidity,color:'#706bd8'}]);
  [['temperatureHistoryChart','air_temp','#1769e0','온도','℃',1],['humidityHistoryChart','humidity','#706bd8','습도','%',1],['ecHistoryChart','ec','#0a9b71','EC','',3],['phHistoryChart','ph','#d88417','pH','',2]].forEach(([id,key,color,label,unit,digits])=>{drawDetailedChart(id,key,color,label,unit,digits);bindHistoryTooltip(id,key,label,unit,digits);});
}

function bindHistoryFileActions(){
  const exportButton=$('historyExportExcel'),importInput=$('historyImportExcel');if(!exportButton||!importInput)return;
  exportButton.addEventListener('click',()=>{window.location.assign(historyQuery.replace('/api/sensors/history','/api/sensors/export.xlsx'));});
  importInput.addEventListener('change',async()=>{const file=importInput.files&&importInput.files[0];if(!file)return;if(!file.name.toLowerCase().endsWith('.xlsx')){toast('대시보드에서 저장한 .xlsx 파일을 선택하세요.');importInput.value='';return;}try{const result=await api('/api/sensors/import.xlsx',{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:await file.arrayBuffer()});toast(`Excel ${result.rows_added.toLocaleString()}행을 참조 기록으로 불러왔습니다.`);await refreshAll();}catch(error){toast(error.message);}finally{importInput.value='';}});
}

bindHistoryFileActions();

let performanceComparison={first:[],second:[],firstNutrients:[],firstLabel:'1차 재배',secondLabel:'2차 재배'};

function performanceRangeLabel(start,end){return `${String(start||'').replace('T',' ')} ~ ${String(end||'').replace('T',' ')}`;}
function periodStats(rows,key,low,high){
  const values=rows.map(item=>numericSensorValue(item[key])).filter(Number.isFinite);
  if(!values.length)return {count:0};
  const mean=values.reduce((sum,value)=>sum+value,0)/values.length;
  const variance=values.reduce((sum,value)=>sum+(value-mean)**2,0)/values.length;
  const minimum=Math.min(...values),maximum=Math.max(...values);
  return {count:values.length,mean,minimum,maximum,range:maximum-minimum,stdev:Math.sqrt(variance),inBand:values.filter(value=>value>=low&&value<=high).length/values.length*100};
}
function pct(value){return Number.isFinite(value)?`${value.toFixed(0)}%`:'--';}
function changeText(first,second,unit='',digits=1){
  if(!Number.isFinite(first)||!Number.isFinite(second))return '비교 데이터 부족';
  const delta=second-first,sign=delta>0?'+':'';
  return `${sign}${delta.toFixed(digits)}${unit}`;
}
function performanceCard(label,first,second,unit,digits,goal){
  if(!first.count||!second.count)return `<article class="card performance-kpi"><span>${label}</span><b>데이터 부족</b><small>두 기간의 유효 실측값을 확인하세요.</small></article>`;
  const direction=second.inBand>=first.inBand?'improve':'watch';
  return `<article class="card performance-kpi ${direction}"><span>${label} 목표 범위 유지율</span><b>${pct(first.inBand)} <i>→</i> ${pct(second.inBand)}</b><small>1차 ${first.count}시간 · 2차 ${second.count}시간 · ${goal}</small></article>`;
}
function renderPerformanceSummary(){
  const firstTemp=periodStats(performanceComparison.first,'air_temp',16,24),secondTemp=periodStats(performanceComparison.second,'air_temp',16,24);
  const firstHumidity=periodStats(performanceComparison.first,'humidity',60,75),secondHumidity=periodStats(performanceComparison.second,'humidity',60,75);
  const kpis=$('performanceKpis');if(!kpis)return;
  kpis.innerHTML=[
    performanceCard('기온',firstTemp,secondTemp,'℃',1,'16~24℃'),
    performanceCard('습도',firstHumidity,secondHumidity,'%',1,'60~75%'),
    `<article class="card performance-kpi"><span>기온 변동폭</span><b>${firstTemp.count?firstTemp.range.toFixed(1):'--'}℃ <i>→</i> ${secondTemp.count?secondTemp.range.toFixed(1):'--'}℃</b><small>표준편차 ${firstTemp.stdev?.toFixed(2)??'--'} → ${secondTemp.stdev?.toFixed(2)??'--'} · 작을수록 안정적</small></article>`,
    `<article class="card performance-kpi"><span>습도 변동폭</span><b>${firstHumidity.count?firstHumidity.range.toFixed(1):'--'}% <i>→</i> ${secondHumidity.count?secondHumidity.range.toFixed(1):'--'}%</b><small>표준편차 ${firstHumidity.stdev?.toFixed(2)??'--'} → ${secondHumidity.stdev?.toFixed(2)??'--'} · 작을수록 안정적</small></article>`,
  ].join('');
  const callout=$('performanceCallout');if(callout){
    const temperatureChange=secondTemp.inBand-firstTemp.inBand,humidityChange=secondHumidity.inBand-firstHumidity.inBand;
    const items=[];
    if(Number.isFinite(temperatureChange))items.push(`기온 목표 범위 유지율 ${changeText(firstTemp.inBand,secondTemp.inBand,'%p',0)}`);
    if(Number.isFinite(humidityChange))items.push(`습도 목표 범위 유지율 ${changeText(firstHumidity.inBand,secondHumidity.inBand,'%p',0)}`);
    if(Number.isFinite(firstHumidity.range)&&Number.isFinite(secondHumidity.range))items.push(`습도 변동폭 ${changeText(firstHumidity.range,secondHumidity.range,'%p',1)}`);
    callout.innerHTML=`<b>실측 비교 요약</b><span>${items.join(' · ') || '비교할 유효 온습도 데이터가 부족합니다.'}</span><small>목표 범위 유지율은 각 기간의 1시간 평균 중 관리 범위 안에 있었던 비율입니다.</small>`;
  }
  return {firstTemp,secondTemp,firstHumidity,secondHumidity};
}
function comparisonSeries(rows,key){
  const firstTime=rows.length?new Date(rows[0].recorded_at).getTime():0;
  return rows.map(item=>({elapsed:(new Date(item.recorded_at).getTime()-firstTime)/3600000,value:numericSensorValue(item[key])})).filter(point=>Number.isFinite(point.elapsed)&&Number.isFinite(point.value));
}
function reconstructedFirstNutrients(rows){
  // 1차에는 PE350이 없었고 수기 원본도 소실됐다.  아래 값은 당시의
  // "수동 혼합 중 pH 4.0까지 하락" 기록을 설명하기 위한 복원·모의값이며,
  // SQLite 실측이나 자동제어 근거로 저장하거나 사용하지 않는다.
  return rows.map((item,index)=>({
    ...item,
    // EC was hand-mixed but generally stayed near the target; give it a
    // smooth 0.4 dS/m band, modestly wider than the second crop's PE350 trend.
    ec:Number((1.50+.12*Math.sin(index/8)+.06*Math.sin(index/3.1)).toFixed(3)),
    // pH follows a smooth manual-adjustment curve.  One broad nitric-acid
    // over-dose event is reconstructed around the middle (minimum pH 4.0),
    // rather than drawing repeated artificial spikes.
    ph:Number((index===27?4:Math.max(4,6.03+.16*Math.sin(index/8.5)+.08*Math.sin(index/3.8)-2.05*Math.exp(-(((index-27)/2.7)**2)))).toFixed(2)),
    source:'reconstructed:manual-mixing',
  }));
}
function performanceRows(phase,key){
  return phase==='first'&&(key==='ec'||key==='ph')?performanceComparison.firstNutrients:performanceComparison[phase];
}
function drawOverlayChart(canvasId,key,firstColor,secondColor,unit,digits,low,high){
  const canvas=$(canvasId);if(!canvas||!canvas.offsetParent)return;
  const first=comparisonSeries(performanceRows('first',key),key),second=comparisonSeries(performanceRows('second',key),key);
  const ctx=canvas.getContext('2d'),ratio=devicePixelRatio||1,width=canvas.clientWidth,height=canvas.clientHeight;
  canvas.width=width*ratio;canvas.height=height*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
  const left=48,right=16,top=14,bottom=30,plotW=Math.max(1,width-left-right),plotH=Math.max(1,height-top-bottom),all=[...first,...second];
  if(!all.length){ctx.fillStyle='#8b96a7';ctx.font='11px sans-serif';ctx.fillText('비교할 데이터가 없습니다.',left,top+24);return;}
  const values=all.map(point=>point.value);let min=Math.min(...values,low),max=Math.max(...values,high);const pad=(max-min||1)*.1;min-=pad;max+=pad;const range=max-min||1,maxElapsed=Math.max(...all.map(point=>point.elapsed),1);
  const y=value=>top+(max-value)/range*plotH,x=value=>left+value/maxElapsed*plotW;
  ctx.fillStyle='rgba(10,155,113,.08)';ctx.fillRect(left,y(high),plotW,y(low)-y(high));
  ctx.font='10px sans-serif';ctx.strokeStyle='#edf1f5';ctx.fillStyle='#8491a3';ctx.lineWidth=1;
  for(let step=0;step<5;step++){const py=top+plotH*step/4,value=max-range*step/4;ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(width-right,py);ctx.stroke();ctx.fillText(`${value.toFixed(digits)}${unit}`,2,py+3);}
  const draw=(points,color,dashed)=>{if(!points.length)return;ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dashed?[5,4]:[]);ctx.beginPath();points.forEach((point,index)=>index?ctx.lineTo(x(point.elapsed),y(point.value)):ctx.moveTo(x(point.elapsed),y(point.value)));ctx.stroke();ctx.setLineDash([]);points.forEach(point=>{ctx.fillStyle='#fff';ctx.strokeStyle=color;ctx.beginPath();ctx.arc(x(point.elapsed),y(point.value),2.5,0,Math.PI*2);ctx.fill();ctx.stroke();});};
  draw(first,firstColor,true);draw(second,secondColor,false);
  ctx.fillStyle='#8491a3';ctx.fillText('두 기간 시작',left,height-8);const end='경과 시간 (h)';ctx.fillText(end,width-right-ctx.measureText(end).width,height-8);
}
function drawPerformanceComparison(){
  renderPerformanceSummary();
  drawOverlayChart('performanceTempChart','air_temp','#8c9ab0','#1769e0','℃',1,16,24);
  drawOverlayChart('performanceHumidityChart','humidity','#8c9ab0','#0a9b71','%',1,60,75);
  drawOverlayChart('performanceEcChart','ec','#c27a00','#0a9b71','',3,1.3,1.8);
  drawOverlayChart('performancePhChart','ph','#c27a00','#d93f4c','',2,5.8,6.3);
  drawPresentationEvidence();
}
function drawPresentationEvidence(){
  const canvas=$('performanceEvidenceCanvas');if(!canvas)return;
  const width=1600,height=1670,ctx=canvas.getContext('2d');canvas.width=width;canvas.height=height;
  ctx.fillStyle='#ffffff';ctx.fillRect(0,0,width,height);ctx.fillStyle='#172033';ctx.font='700 42px sans-serif';ctx.fillText('1차 · 2차 재배 환경관리 성과 비교',74,78);ctx.fillStyle='#718096';ctx.font='24px sans-serif';ctx.fillText('SQLite 실측값 1시간 평균 · 두 기간은 시작 시점을 0시간으로 맞춰 비교',74,116);
  const stats=renderPerformanceSummary(),tiles=[['기온 목표 범위 유지율',stats.firstTemp,stats.secondTemp,'16~24℃'],['습도 목표 범위 유지율',stats.firstHumidity,stats.secondHumidity,'60~75%'],['기온 변동폭',stats.firstTemp,stats.secondTemp,'작을수록 안정적'],['습도 변동폭',stats.firstHumidity,stats.secondHumidity,'작을수록 안정적']];
  tiles.forEach((tile,index)=>{const x=74+index*380;ctx.fillStyle='#f5f8fc';ctx.fillRect(x,156,350,142);ctx.fillStyle='#62738a';ctx.font='600 20px sans-serif';ctx.fillText(tile[0],x+20,190);ctx.fillStyle='#173f6b';ctx.font='700 34px sans-serif';const value=index<2?`${pct(tile[1].inBand)} → ${pct(tile[2].inBand)}`:`${tile[1].range?.toFixed(1)??'--'} → ${tile[2].range?.toFixed(1)??'--'}${index===2?'℃':'%'} `;ctx.fillText(value,x+20,238);ctx.fillStyle='#7b8b9e';ctx.font='18px sans-serif';ctx.fillText(`1차 ${tile[1].count||0}h · 2차 ${tile[2].count||0}h · ${tile[3]}`,x+20,275);});
  function exportGraph(top,key,title,unit,digits,low,high,firstColor,secondColor,firstLegend='1차 실측',secondLegend='2차 실측'){const first=comparisonSeries(performanceRows('first',key),key),second=comparisonSeries(performanceRows('second',key),key),all=[...first,...second],left=94,right=70,chartW=1436,chartH=215;if(!all.length)return;const values=all.map(point=>point.value);let min=Math.min(...values,low),max=Math.max(...values,high),pad=(max-min||1)*.1;min-=pad;max+=pad;const range=max-min||1,maxElapsed=Math.max(...all.map(p=>p.elapsed),1),x=v=>left+v/maxElapsed*chartW,y=v=>top+(max-v)/range*chartH;ctx.fillStyle='#172033';ctx.font='700 25px sans-serif';ctx.fillText(title,74,top-20);ctx.fillStyle='rgba(10,155,113,.09)';ctx.fillRect(left,y(high),chartW,y(low)-y(high));ctx.strokeStyle='#e4eaf1';ctx.lineWidth=1;for(let step=0;step<5;step++){const py=top+chartH*step/4,val=max-range*step/4;ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(left+chartW,py);ctx.stroke();ctx.fillStyle='#7d8c9e';ctx.font='16px sans-serif';ctx.fillText(`${val.toFixed(digits)}${unit}`,15,py+5);}const draw=(points,color,dash)=>{ctx.strokeStyle=color;ctx.lineWidth=3;ctx.setLineDash(dash?[10,7]:[]);ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(x(p.elapsed),y(p.value)):ctx.moveTo(x(p.elapsed),y(p.value)));ctx.stroke();ctx.setLineDash([]);};draw(first,firstColor,true);draw(second,secondColor,false);ctx.fillStyle=firstColor;ctx.font='17px sans-serif';ctx.fillText(firstLegend,1090,top-20);ctx.fillStyle=secondColor;ctx.fillText(secondLegend,1325,top-20);}
  exportGraph(375,'air_temp','기온 비교','℃',1,16,24,'#8c9ab0','#1769e0');exportGraph(675,'humidity','습도 비교','%',1,60,75,'#8c9ab0','#0a9b71');
  exportGraph(975,'ec','EC 비교 · 1차 수기 작업기록 기반 복원값','',3,1.3,1.8,'#c27a00','#0a9b71','1차 복원·모의','2차 PE350 실측');exportGraph(1275,'ph','pH 비교 · 1차 수기 작업기록 기반 복원값','',2,5.8,6.3,'#c27a00','#d93f4c','1차 복원·모의','2차 PE350 실측');
  ctx.fillStyle='#718096';ctx.font='17px sans-serif';ctx.fillText('온습도: SQLite 실측 비교. EC·pH: 1차는 소실된 수기자료의 작업기록을 바탕으로 한 복원·모의값, 2차는 RS485 PE350 실측값입니다.',74,1585);ctx.fillText('목표 범위 유지율은 높을수록, 변동폭은 낮을수록 안정적인 환경 관리입니다. 본 도표는 생육 결과의 단독 인과를 주장하지 않습니다.',74,1620);
}
async function loadPerformanceComparison(){
  const firstStart=$('performanceFirstStart')?.value,firstEnd=$('performanceFirstEnd')?.value,secondStart=$('performanceSecondStart')?.value,secondEnd=$('performanceSecondEnd')?.value;
  if(!firstStart||!firstEnd||!secondStart||!secondEnd)return;
  if(new Date(firstEnd)<=new Date(firstStart)||new Date(secondEnd)<=new Date(secondStart)){toast('각 재배 기간의 종료 시각은 시작 시각보다 뒤여야 합니다.');return;}
  const query=(start,end)=>`/api/sensors/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&max_points=2500`;
  try{const [first,second]=await Promise.all([api(query(firstStart,firstEnd)),api(query(secondStart,secondEnd))]);performanceComparison={first,second,firstNutrients:reconstructedFirstNutrients(first),firstLabel:performanceRangeLabel(firstStart,firstEnd),secondLabel:performanceRangeLabel(secondStart,secondEnd)};drawPerformanceComparison();}catch(error){toast(`성과 비교를 불러오지 못했습니다: ${error.message}`);}
}
function bindPerformanceComparison(){
  const form=$('performanceForm'),save=$('performancePng');if(!form||!save)return;
  form.addEventListener('submit',event=>{event.preventDefault();loadPerformanceComparison();});
  save.addEventListener('click',()=>{drawPresentationEvidence();const canvas=$('performanceEvidenceCanvas'),link=document.createElement('a');link.href=canvas.toDataURL('image/png');link.download='broccoli_operation_comparison_1st_vs_2nd.png';link.click();toast('PPT 삽입용 PNG를 저장했습니다.');});
  loadPerformanceComparison();
}

function historicalAnalysisMarkup(item){
  const result=item.result||{},issues=Array.isArray(result.key_issues)?result.key_issues:[],ppt=Array.isArray(result.ppt_statements)?result.ppt_statements:[],improvements=Array.isArray(result.second_crop_improvements)?result.second_crop_improvements:[];
  const issueList=issues.length?issues.slice(0,3).map(issue=>`<li><b>${escapeHtml(issue.title||'핵심 문제')}</b><br><span>근거: ${escapeHtml(issue.evidence||'판단 근거 부족')}</span><br><span>의미: ${escapeHtml(issue.meaning||'판단 근거 부족')}</span><br><span>확인: ${escapeHtml(issue.follow_up||'추가 확인 필요')}</span></li>`).join(''):'<li>핵심 문제 기록 없음</li>';
  const pptList=ppt.length?ppt.slice(0,3).map(value=>`<li>${escapeHtml(value)}</li>`).join(''):'<li>발표 문장 기록 없음</li>';
  const improvementList=improvements.length?improvements.slice(0,5).map(value=>`<li>${escapeHtml(value)}</li>`).join(''):'<li>개선점 기록 없음</li>';
  return `<article class="historical-analysis"><div class="historical-analysis-head"><div><span class="tag green">${escapeHtml(item.model||'OpenAI')}</span><b>${escapeHtml(item.title||'운영 데이터 분석')}</b><small>${timeText(item.created_at)}</small></div></div><h3>${escapeHtml(result.headline||'분석 요약 없음')}</h3><p>${escapeHtml(result.environment_summary||'환경 분석 요약이 없습니다.')}</p><div class="historical-analysis-meta"><span><b>데이터 품질</b>${escapeHtml(result.data_quality||'미기록')}</span><span><b>해석 제한</b>${escapeHtml(result.interpretation_limits||'미기록')}</span></div><div class="grid two historical-analysis-grid"><div><h4>핵심 문제</h4><ul>${issueList}</ul></div><div><h4>양액 관리 위험</h4><p>${escapeHtml(result.nutrient_management_risk||'미기록')}</p><h4>2차 재배 개선점</h4><ul>${improvementList}</ul></div></div><div class="historical-ppt"><h4>PPT용 발표 문장</h4><ul>${pptList}</ul></div></article>`;
}
function applyHistoricalOperationAnalyses(items,settings){
  const tag=$('historicalAiTag'),panel=$('historicalOperationResults');if(!tag||!panel)return;
  tag.textContent=settings?.configured?`OpenAI · ${settings.model}`:'API 키 필요';tag.className=`tag ${settings?.configured?'green':'amber'}`;
  panel.innerHTML=items?.length?items.map(historicalAnalysisMarkup).join(''):'<div class="list-empty">저장된 1차 재배 운영 데이터 분석이 없습니다.</div>';
}
async function loadHistoricalOperationAnalyses(){
  try{const [items,settings]=await Promise.all([api('/api/historical-operation-analyses'),api('/api/settings/openai')]);applyHistoricalOperationAnalyses(items,settings);}catch(error){const panel=$('historicalOperationResults');if(panel)panel.innerHTML=`<div class="list-empty">분석 이력을 불러오지 못했습니다: ${escapeHtml(error.message)}</div>`;}
}
function bindHistoricalOperationAnalysis(){
  const form=$('historicalOperationForm');if(!form)return;
  form.addEventListener('submit',event=>{event.preventDefault();const title=$('historicalOperationTitle').value.trim(),prompt=$('historicalOperationPrompt').value.trim(),data=$('historicalOperationData').value.trim(),button=$('historicalOperationSubmit');if(prompt.length<20){toast('AI 분석 프롬프트를 20자 이상 입력하세요.');return;}if(data.length<20){toast('분석할 운영 데이터를 20자 이상 입력하세요.');return;}if(!confirm('입력한 프롬프트와 운영 데이터를 OpenAI API로 보내 분석하고, 결과와 원문을 서버 SQLite에 저장합니다. 계속할까요?'))return;withBusy(button,async()=>{const result=await api('/api/historical-operation-analyses',{method:'POST',body:JSON.stringify({title,prompt,data})});toast(`AI 분석 #${result.id} 저장 완료 · ${result.model}`);await loadHistoricalOperationAnalyses();});});
  loadHistoricalOperationAnalyses();
}

bindPerformanceComparison();
bindHistoricalOperationAnalysis();
