console.log("main.js loaded"); // for debugging
console.log("chart exists?", typeof Chart);

const API_BASE = ""; // where backend lives
const SAMPLE_RATE_HERTZ = 256;

const statusEl = document.getElementById("status");
const samplesEl = document.getElementById("samples");
const channelsEl = document.getElementById("channels");
const tsEl = document.getElementById("ts");

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

const qualitySummaryEl = document.getElementById("qualitySummary");
const qualityBadgesEl = document.getElementById("qualityBadges");

let chart; // Chart.js instance
let lastQualityFetch = 0;

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

async function fetchQuality() {
    const res = await fetch(`${API_BASE}/quality`);
    if (!res.ok) throw new Error(`quality not ok: ${res.status}`);
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
      pill.style.border = "1px solid #ccc";
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
  const labels = data.map((_, i) => (i / SAMPLE_RATE_HERTZ).toFixed(2)); // seconds

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

async function mainLoop() {
  await fetchHealth();

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

  // Poll ~5 times/sec (smooth enough without stressing the backend)
  setTimeout(mainLoop, 200);
}

mainLoop();