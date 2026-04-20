console.log("main.js loaded"); // for debugging
console.log("chart exists?", typeof Chart);

const API_BASE = ""; // where backend lives
let sampleRateHertz = 256;

const statusEl = document.getElementById("status");
const samplesEl = document.getElementById("samples");
const channelsEl = document.getElementById("channels");
const tsEl = document.getElementById("ts");

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

const qualitySummaryEl = document.getElementById("qualitySummary");
const qualityBadgesEl = document.getElementById("qualityBadges");

// tabs
const tabQualityBtn = document.getElementById("tabQualityBtn");
const tabIncidentsBtn = document.getElementById("tabIncidentsBtn");
const tabQuality = document.getElementById("tabQuality");
const tabIncidents = document.getElementById("tabIncidents");

// events UI
const refreshEventsBtn = document.getElementById("refreshEventsBtn");
const clearEventsBtn = document.getElementById("clearEventsBtn");
const eventsSummaryEl = document.getElementById("eventsSummary");
const eventsTbodyEl = document.getElementById("eventsTbody");

let lastEventsFetch = 0;

let chart; // Chart.js instance
let lastQualityFetch = 0;
let configLoaded = false;

function setActiveTab(which) {
    const isQuality = which === "quality";
  
    if (tabQualityBtn) tabQualityBtn.classList.toggle("active", isQuality);
    if (tabIncidentsBtn) tabIncidentsBtn.classList.toggle("active", !isQuality);
  
    if (tabQuality) tabQuality.classList.toggle("active", isQuality);
    if (tabIncidents) tabIncidents.classList.toggle("active", !isQuality);
  }

if (tabQualityBtn && tabIncidentsBtn) {
tabQualityBtn.addEventListener("click", () => {
    setActiveTab("quality");
});

tabIncidentsBtn.addEventListener("click", () => {
    setActiveTab("incidents");
    fetchAndRenderEvents(); // load immediately on switch
});
}

async function fetchHealth() {
    // health check
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error("health not ok");
    statusEl.textContent = "connected";
  } catch (e) {
    statusEl.textContent = "disconnected";
  }
}

async function fetchLatest() {
  const res = await fetch(`${API_BASE}/latest`);
  if (!res.ok) throw new Error("latest not ok");
  return await res.json();
}

async function fetchConfig() {
  const res = await fetch(`${API_BASE}/config`);
  if (!res.ok) throw new Error("config not ok");
  return await res.json();
}

async function fetchQuality() {
    const res = await fetch(`${API_BASE}/quality`);
    if (!res.ok) throw new Error(`quality not ok: ${res.status}`);
    return await res.json();
  }

async function fetchEvents(limit = 100) {
    const res = await fetch(`${API_BASE}/events?limit=${limit}`);
    if (!res.ok) throw new Error(`events not ok: ${res.status}`);
    return await res.json(); // { events: [...] }
    }
  
async function clearEvents() {
    const res = await fetch(`${API_BASE}/events/clear`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
    });
    if (!res.ok) throw new Error(`clear failed: ${res.status}`);
    return await res.json();
    }
  
function renderQuality(q) {
    if (!qualitySummaryEl) return;

    qualitySummaryEl.textContent =
      `Overall: ${q.overall.status} (${q.overall.summary})`;
  
    if (!qualityBadgesEl) return;
    qualityBadgesEl.innerHTML = "";
  
    q.channels.forEach((ch) => {
      const pill = document.createElement("div");
      pill.style.padding = "6px 10px";
      pill.style.borderRadius = "999px";
      pill.style.border = "1px solid rgba(255,255,255,0.25)";
      pill.style.fontSize = "12px";
  
      pill.style.background =
        ch.status === "good" ? "#16a34a" :
        ch.status === "degraded" ? "#f59e0b" :
        "#dc2626";

        pill.style.color = "#ffffff";
        pill.style.fontWeight = "600";
        pill.style.boxShadow = "0 0 6px rgba(255,255,255,0.15)";
  
      pill.textContent =
        `Ch${ch.channel}: ${ch.status} | RMS ${ch.rms.toFixed(2)} | LN ${ch.line_noise_ratio.toFixed(2)}`;
  
      qualityBadgesEl.appendChild(pill);
    });
  }

function fmtTime(ts) {
    if (ts === null || ts === undefined) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  }
  
function renderEvents(events) {
    if (!eventsTbodyEl) return;
  
    if (!events || events.length === 0) {
      eventsTbodyEl.innerHTML = `<tr><td colspan="8" style="color:#a9b4d0;">No events yet.</td></tr>`;
      if (eventsSummaryEl) eventsSummaryEl.textContent = "0 events";
      return;
    }
  
    if (eventsSummaryEl) eventsSummaryEl.textContent = `${events.length} most recent events`;
  
    eventsTbodyEl.innerHTML = "";
    for (const ev of events) {
      const endTs = ev.end_ts;
      const dur = (ev.duration_s !== null && ev.duration_s !== undefined)
        ? Number(ev.duration_s).toFixed(2)
        : "—";
  
      const reasons = Array.isArray(ev.reasons) ? ev.reasons.join(", ") : (ev.reasons || "");
  
      const statusClass = ev.status || "degraded";
  
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${ev.id ?? ""}</td>
        <td>${ev.channel}</td>
        <td><span class="pill ${statusClass}">${ev.status}</span></td>
        <td>${fmtTime(ev.start_ts)}</td>
        <td>${endTs ? fmtTime(endTs) : "OPEN"}</td>
        <td>${dur}</td>
        <td>${ev.diagnosis || ""}</td>
        <td style="color:#a9b4d0;">${reasons}</td>
      `;
      eventsTbodyEl.appendChild(tr);
    }
  }
  
async function fetchAndRenderEvents() {
    try {
      const payload = await fetchEvents(100);
      renderEvents(payload.events);
    } catch (e) {
      if (eventsSummaryEl) eventsSummaryEl.textContent = `Events error: ${e.message}`;
    }
  }

function initChart(numChannels) {
  const ctx = document.getElementById("chart");

  const datasets = [];
  for (let ch = 0; ch < numChannels; ch++) {
    datasets.push({
      label: `ch${ch}`,
      data: [],
      borderWidth: 1,
      pointRadius: 0,
      tension: 0.1
    });
  }

  chart = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets },
    options: {
      responsive: true,
      animation: false,
      plugins: { legend: { display: true } },
      scales: {
        x: { display: true, 
            title: {display: true, text: "Time (s)"},
            ticks: {maxTicksLimit: 10}
         },
        y: { title: { display: true, text: "Amplitude (simulated)" } }
      }
    }
  });
}

function updateChart(payload) {
  const { num_channels, num_samples, data } = payload;

  channelsEl.textContent = num_channels;
  samplesEl.textContent = num_samples;

  if (data.length > 0) {
    const ts = data[data.length-1].timestamp;
    tsEl.textContent = `${ts.toFixed(3)} (${new Date(ts * 1000).toLocaleTimeString()})`;
  }

  // Initialize chart on first successful payload
  if (!chart) initChart(num_channels);

  // x-axis labels = sample index (simple + stable)
  const labels = data.map((_, i) => (i / sampleRateHertz).toFixed(2)); // seconds

  chart.data.labels = labels;

  for (let ch = 0; ch < num_channels; ch++) {
    chart.data.datasets[ch].data = data.map(d => d.channels[ch]);
  }

  chart.update();
}

async function control(action) {
  const res = await fetch(`${API_BASE}/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action })
  });

  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || "control failed");
  return payload;
}

startBtn.addEventListener("click", async () => {
  try {
    await control("start");
  } catch (e) {
    alert(e.message);
  }
});

stopBtn.addEventListener("click", async () => {
  try {
    await control("stop");
  } catch (e) {
    alert(e.message);
  }
});

if (refreshEventsBtn) {
    refreshEventsBtn.addEventListener("click", fetchAndRenderEvents);
  }
  

if (clearEventsBtn) {
clearEventsBtn.addEventListener("click", async () => {
    try {
    await clearEvents();
    await fetchAndRenderEvents();
    } catch (e) {
    alert(e.message);
    }
});
}

setActiveTab("quality");

async function mainLoop() {
  await fetchHealth();

  if (!configLoaded) {
    try {
      const cfg = await fetchConfig();
      if (cfg.sample_rate_hertz) {
        sampleRateHertz = cfg.sample_rate_hertz;
      }
      configLoaded = true;
    } catch (e) {
      console.error(e);
    }
  }

  try {
    const latest = await fetchLatest();
    updateChart(latest);
    statusEl.textContent = "streaming";

    // Fetch quality ~1x/sec (FFT is heavier than /latest)
    const now = Date.now();
    if (now - lastQualityFetch > 1000) {
      lastQualityFetch = now;
      try {
        const q = await fetchQuality();
        renderQuality(q);
      } catch (e) {
        console.error(e);
        if (qualitySummaryEl) qualitySummaryEl.textContent = `Quality error: ${e.message}`;
      }
    }


    } catch (e) {
        statusEl.textContent = "error";
    }

    // Poll events ~1x/sec (cheap)
    const now2 = Date.now();
    if (now2 - lastEventsFetch > 1000) {
    lastEventsFetch = now2;
    // only refresh if the incidents tab is visible, to reduce noise
    if (tabIncidents && tabIncidents.classList.contains("active")) {
        fetchAndRenderEvents();
    }
    }

  // Poll ~5 times/sec (smooth enough without stressing the backend)
  setTimeout(mainLoop, 200);
}

mainLoop();
