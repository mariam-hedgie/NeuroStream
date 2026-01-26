const API_BASE = "http://127.0.0.1:5000"; // where backend lives

const statusEl = document.getElementById("status");
const samplesEl = document.getElementById("samples");
const channelsEl = document.getElementById("channels");
const tsEl = document.getElementById("ts");

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

let chart; // Chart.js instance

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
        x: { display: false },
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
    tsEl.textContent = data[data.length - 1].timestamp.toFixed(3);
  }

  // Initialize chart on first successful payload
  if (!chart) initChart(num_channels);

  // x-axis labels = sample index (simple + stable)
  const labels = data.map((_, i) => i);

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
  } catch (e) {
    statusEl.textContent = "error";
  }

  // Poll ~5 times/sec (smooth enough without stressing the backend)
  setTimeout(mainLoop, 200);
}

mainLoop();