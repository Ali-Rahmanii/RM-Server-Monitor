const el = (id) => document.getElementById(id);
const grid = el("server-grid");
const summaryBar = el("summary-bar");
const orNull = (v) => (v && v.trim() !== "" ? v : null);

async function api(path, options = {}) {
    const resp = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${resp.status}`);
    }
    if (resp.status === 204) return null;
    return resp.json();
}

function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function pctColor(v) {
    if (v == null) return "#64748b";
    if (v >= 90) return "#f87171";
    if (v >= 75) return "#fbbf24";
    return "#34d399";
}

function fmtBps(v) {
    if (v == null) return "-";
    const units = ["B/s", "KB/s", "MB/s", "GB/s"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(1)}${units[i]}`;
}

function fmtBytes(v) {
    if (v == null) return "-";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(1)}${units[i]}`;
}

Chart.defaults.color = "#94a3b8";
Chart.defaults.font.family = "Vazirmatn, sans-serif";

// ══════════════════════════════════════════════════════════════════
//  گیج‌های دایره‌ای کوچک (کارت هر سرور)
// ══════════════════════════════════════════════════════════════════

function makeGauge(canvas, value) {
    const v = value ?? 0;
    return new Chart(canvas, {
        type: "doughnut",
        data: {
            datasets: [{
                data: [v, 100 - v],
                backgroundColor: [pctColor(value), "rgba(255,255,255,0.07)"],
                borderWidth: 0,
            }],
        },
        options: {
            cutout: "72%",
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 400 },
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
        },
    });
}

function updateGauge(chart, value) {
    const v = value ?? 0;
    chart.data.datasets[0].data = [v, 100 - v];
    chart.data.datasets[0].backgroundColor[0] = pctColor(value);
    chart.update("none");
}

// ══════════════════════════════════════════════════════════════════
//  کارت‌های گرید — به‌روزرسانی درجا (بدون بازسازی کامل DOM) برای
//  جلوگیری از فلیکر و overhead ساخت/نابودی مکرر چارت‌ها
// ══════════════════════════════════════════════════════════════════

const cardInstances = new Map(); // id -> { el, gCpu, gRam, gDisk, server }

function buildCardSkeleton(server) {
    const wrap = document.createElement("div");
    wrap.className = "card";
    wrap.innerHTML = `
        <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2 min-w-0">
                <span class="dot-holder"></span>
                <span class="font-bold truncate name-text"></span>
            </div>
            <span class="text-[10px] text-slate-500 group-text"></span>
        </div>
        <div class="text-xs text-slate-400 mb-3 ip-text"></div>
        <div class="gauges-row grid grid-cols-3 gap-2 justify-items-center"></div>
        <div class="down-msg hidden text-xs text-red-400 mt-2"></div>
        <div class="net-text text-[11px] text-slate-400 mt-3 flex justify-between"></div>
        <div class="traffic-text text-[10px] text-slate-500 mt-1 hidden"></div>
    `;
    wrap.onclick = () => openDetail(cardInstances.get(server.id).server);
    return wrap;
}

function renderGaugesRow(container) {
    container.innerHTML = `
        <div class="text-center">
            <div class="gauge-wrap"><canvas></canvas><div class="gauge-value cpu-val"></div></div>
            <div class="text-[10px] text-slate-500 mt-1">CPU</div>
        </div>
        <div class="text-center">
            <div class="gauge-wrap"><canvas></canvas><div class="gauge-value ram-val"></div></div>
            <div class="text-[10px] text-slate-500 mt-1">RAM</div>
        </div>
        <div class="text-center">
            <div class="gauge-wrap"><canvas></canvas><div class="gauge-value disk-val"></div></div>
            <div class="text-[10px] text-slate-500 mt-1">دیسک</div>
        </div>
    `;
}

function upsertCard(server) {
    let inst = cardInstances.get(server.id);
    const latest = server.latest;
    const status = server.last_status || "unknown";

    if (!inst) {
        const cardEl = buildCardSkeleton(server);
        grid.appendChild(cardEl);
        const gaugesRow = cardEl.querySelector(".gauges-row");
        renderGaugesRow(gaugesRow);
        const canvases = gaugesRow.querySelectorAll("canvas");
        inst = {
            el: cardEl,
            gCpu: makeGauge(canvases[0], latest?.cpu_percent),
            gRam: makeGauge(canvases[1], latest?.ram_percent),
            gDisk: makeGauge(canvases[2], latest?.disk_percent),
            server,
        };
        cardInstances.set(server.id, inst);
    }

    inst.server = server;
    inst.el.classList.toggle("down", status === "down");
    inst.el.querySelector(".dot-holder").innerHTML = `<span class="dot ${status}"></span>`;
    inst.el.querySelector(".name-text").textContent = server.name;
    inst.el.querySelector(".group-text").textContent = server.group_name || "";
    inst.el.querySelector(".ip-text").textContent = `${server.ip}:${server.port}${latest?.ping_ms != null ? " · " + latest.ping_ms.toFixed(0) + "ms" : ""}`;

    const downMsg = inst.el.querySelector(".down-msg");
    const gaugesRow = inst.el.querySelector(".gauges-row");
    const netText = inst.el.querySelector(".net-text");
    const trafficText = inst.el.querySelector(".traffic-text");

    if (status === "down") {
        gaugesRow.classList.add("hidden");
        netText.classList.add("hidden");
        trafficText.classList.add("hidden");
        downMsg.classList.remove("hidden");
        downMsg.textContent = "🔴 قطع" + (latest?.error ? " — " + latest.error : "");
    } else {
        gaugesRow.classList.remove("hidden");
        netText.classList.remove("hidden");
        downMsg.classList.add("hidden");
        updateGauge(inst.gCpu, latest?.cpu_percent);
        updateGauge(inst.gRam, latest?.ram_percent);
        updateGauge(inst.gDisk, latest?.disk_percent);
        inst.el.querySelector(".cpu-val").textContent = latest?.cpu_percent != null ? latest.cpu_percent.toFixed(0) + "%" : "-";
        inst.el.querySelector(".ram-val").textContent = latest?.ram_percent != null ? latest.ram_percent.toFixed(0) + "%" : "-";
        inst.el.querySelector(".disk-val").textContent = latest?.disk_percent != null ? latest.disk_percent.toFixed(0) + "%" : "-";
        netText.innerHTML = `<span>⬆ ${fmtBps(latest?.net_sent_bps)}</span><span>⬇ ${fmtBps(latest?.net_recv_bps)}</span>`;
        if (latest?.traffic_rx_bytes != null) {
            trafficText.classList.remove("hidden");
            trafficText.textContent = `📡 کل ترافیک: ⬆ ${fmtBytes(latest.traffic_tx_bytes)} ⬇ ${fmtBytes(latest.traffic_rx_bytes)}`;
        } else {
            trafficText.classList.add("hidden");
        }
    }
}

let allServers = [];

async function refresh() {
    let servers;
    try {
        servers = await api("/api/servers");
    } catch (e) {
        grid.innerHTML = `<div class="empty-state col-span-full">خطا در دریافت اطلاعات: ${escapeHtml(e.message)}</div>`;
        return;
    }
    allServers = servers;

    if (!servers.length) {
        for (const inst of cardInstances.values()) { inst.gCpu.destroy(); inst.gRam.destroy(); inst.gDisk.destroy(); }
        cardInstances.clear();
        grid.innerHTML = `<div class="empty-state col-span-full">هیچ سروری ثبت نشده. با «استقرار خودکار» یا «افزودن دستی» شروع کن.</div>`;
        summaryBar.innerHTML = "";
        return;
    }
    if (grid.querySelector(".empty-state")) grid.innerHTML = "";

    const seenIds = new Set();
    servers.forEach((s) => { upsertCard(s); seenIds.add(s.id); });

    for (const [id, inst] of [...cardInstances.entries()]) {
        if (!seenIds.has(id)) {
            inst.gCpu.destroy(); inst.gRam.destroy(); inst.gDisk.destroy();
            inst.el.remove();
            cardInstances.delete(id);
        }
    }

    const up = servers.filter((s) => s.last_status === "up").length;
    const down = servers.filter((s) => s.last_status === "down").length;
    const avgCpu = servers.filter(s => s.latest?.cpu_percent != null).reduce((a, s, _, arr) => a + s.latest.cpu_percent / arr.length, 0);
    summaryBar.innerHTML = `
        <div class="summary-chip"><div class="text-[11px] text-slate-400">🟢 آنلاین</div><div class="text-xl font-bold text-emerald-400">${up}</div></div>
        <div class="summary-chip"><div class="text-[11px] text-slate-400">🔴 آفلاین</div><div class="text-xl font-bold text-red-400">${down}</div></div>
        <div class="summary-chip"><div class="text-[11px] text-slate-400">مجموع سرورها</div><div class="text-xl font-bold">${servers.length}</div></div>
        <div class="summary-chip"><div class="text-[11px] text-slate-400">میانگین CPU</div><div class="text-xl font-bold">${servers.length ? avgCpu.toFixed(0) + "%" : "-"}</div></div>
    `;

    if (detailOpenId != null) {
        const fresh = servers.find((s) => s.id === detailOpenId);
        if (fresh) syncDetailHeader(fresh);
    }
}

async function refreshInterval() {
    try {
        const { minutes } = await api("/api/settings/interval");
        el("interval-display").textContent = `فاصله چک خودکار: ${minutes} دقیقه`;
    } catch (e) { /* ignore */ }
}

// ══════════════════════════════════════════════════════════════════
//  مودال افزودن دستی
// ══════════════════════════════════════════════════════════════════

const modalOverlay = el("modal-overlay");
const serverForm = el("server-form");

function openAddModal() {
    el("modal-title").textContent = "افزودن سرور";
    serverForm.reset();
    el("f-id").value = "";
    el("f-port").value = 5100;
    el("f-token").required = true;
    modalOverlay.classList.remove("hidden");
}

function openEditModal(server) {
    el("modal-title").textContent = "ویرایش سرور";
    el("f-id").value = server.id;
    el("f-name").value = server.name;
    el("f-ip").value = server.ip;
    el("f-port").value = server.port;
    el("f-token").value = "";
    el("f-token").required = false;
    el("f-group").value = server.group_name || "";
    modalOverlay.classList.remove("hidden");
}

el("btn-add-server").onclick = openAddModal;
el("btn-cancel").onclick = () => modalOverlay.classList.add("hidden");

serverForm.onsubmit = async (ev) => {
    ev.preventDefault();
    const id = el("f-id").value;
    const payload = {
        name: el("f-name").value.trim(),
        ip: el("f-ip").value.trim(),
        port: parseInt(el("f-port").value, 10),
        group_name: el("f-group").value.trim(),
    };
    const token = el("f-token").value.trim();
    try {
        if (id) {
            if (token) payload.token = token;
            await api(`/api/servers/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
        } else {
            payload.token = token;
            await api("/api/servers", { method: "POST", body: JSON.stringify(payload) });
        }
        modalOverlay.classList.add("hidden");
        await refresh();
    } catch (e) {
        alert("خطا: " + e.message);
    }
};

// ══════════════════════════════════════════════════════════════════
//  مودال استقرار خودکار SSH
// ══════════════════════════════════════════════════════════════════

const deployOverlay = el("deploy-overlay");
const deployForm = el("deploy-form");

el("btn-deploy-server").onclick = () => {
    deployForm.reset();
    el("d-ssh-port").value = 22;
    el("d-ssh-user").value = "root";
    el("deploy-status").classList.add("hidden");
    el("btn-deploy-submit").disabled = false;
    el("btn-deploy-submit").textContent = "شروع نصب";
    deployOverlay.classList.remove("hidden");
};
el("btn-deploy-cancel").onclick = () => deployOverlay.classList.add("hidden");

document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.onclick = () => {
        document.querySelectorAll(".auth-tab").forEach((t) => t.classList.remove("auth-tab-active"));
        tab.classList.add("auth-tab-active");
        const isKey = tab.dataset.auth === "key";
        el("auth-password-panel").classList.toggle("hidden", isKey);
        el("auth-key-panel").classList.toggle("hidden", !isKey);
    };
});

function setDeployStatus(kind, html) {
    const box = el("deploy-status");
    box.classList.remove("hidden");
    const styles = {
        info: "bg-indigo-500/10 border-indigo-500/30 text-indigo-200",
        success: "bg-emerald-500/10 border-emerald-500/30 text-emerald-200",
        error: "bg-red-500/10 border-red-500/30 text-red-200",
    };
    // pre-wrap چون پیام خطا ممکن است شامل خروجی چندخطی اسکریپت SSH باشد
    box.className = "text-xs rounded-lg p-3 border max-h-64 overflow-y-auto whitespace-pre-wrap font-mono " + styles[kind];
    box.innerHTML = html;
}

deployForm.onsubmit = async (ev) => {
    ev.preventDefault();
    const usingKey = !el("auth-key-panel").classList.contains("hidden");
    const payload = {
        name: el("d-name").value.trim(),
        ip: el("d-ip").value.trim(),
        group_name: el("d-group").value.trim(),
        ssh_port: parseInt(el("d-ssh-port").value, 10),
        ssh_username: el("d-ssh-user").value.trim(),
        ssh_password: usingKey ? null : orNull(el("d-ssh-pass").value),
        ssh_private_key: usingKey ? orNull(el("d-ssh-key").value) : null,
        ssh_key_passphrase: usingKey ? orNull(el("d-ssh-key-pass").value) : null,
    };
    el("btn-deploy-submit").disabled = true;
    el("btn-deploy-submit").textContent = "در حال نصب...";
    setDeployStatus("info", "⏳ در حال اتصال SSH و اجرای اسکریپت نصب — ممکن است تا چند دقیقه طول بکشد (نصب پکیج‌های پایتون روی سرور هدف)...");
    try {
        await api("/api/deploy", { method: "POST", body: JSON.stringify(payload) });
        setDeployStatus("success", "✅ نصب و ثبت سرور با موفقیت انجام شد.");
        await refresh();
        setTimeout(() => deployOverlay.classList.add("hidden"), 1200);
    } catch (e) {
        setDeployStatus("error", "❌ " + escapeHtml(e.message));
    } finally {
        el("btn-deploy-submit").disabled = false;
        el("btn-deploy-submit").textContent = "شروع نصب";
    }
};

// ══════════════════════════════════════════════════════════════════
//  مودال جزئیات سرور — چارت‌های زنده + پرمصرف‌ترین‌ها
// ══════════════════════════════════════════════════════════════════

const detailOverlay = el("detail-overlay");
let detailOpenId = null;
let detailTimer = null;
const charts = { cpu: null, ram: null, disk: null, network: null };
const MAX_POINTS = 40;

el("btn-detail-close").onclick = () => closeDetail();

function closeDetail() {
    detailOverlay.classList.add("hidden");
    if (detailTimer) clearInterval(detailTimer);
    detailTimer = null;
    detailOpenId = null;
    Object.keys(charts).forEach((k) => { if (charts[k]) { charts[k].destroy(); charts[k] = null; } });
}

function syncDetailHeader(server) {
    const status = server.last_status || "unknown";
    el("detail-title").innerHTML = `<span class="dot ${status}" style="margin-inline-end:6px"></span>${escapeHtml(server.name)}`;
    el("detail-sub").textContent = `${server.ip}:${server.port}${server.group_name ? " · " + server.group_name : ""}`;
}

function chartPanel(key, title, canvasId) {
    return `
        <div class="glass-panel p-4" id="panel-${key}">
            <div class="flex items-center justify-between mb-2">
                <div class="text-sm font-semibold pulse-live">${title}</div>
                <button type="button" class="chart-toggle text-sm" data-chart="${key}" title="نمایش/مخفی">👁️</button>
            </div>
            <div class="chart-box" id="box-${key}"><canvas id="${canvasId}"></canvas></div>
        </div>
    `;
}

function detailBodyTemplate() {
    return `
        <div id="traffic-total-banner" class="text-xs text-slate-400 mb-3 hidden"></div>
        <div class="grid sm:grid-cols-2 gap-4 mb-4">
            ${chartPanel("cpu", "CPU (٪)", "chart-cpu")}
            ${chartPanel("ram", "RAM (٪)", "chart-ram")}
            ${chartPanel("disk", "دیسک (٪)", "chart-disk")}
            ${chartPanel("network", "ترافیک شبکه (لحظه‌ای)", "chart-network")}
        </div>
        <div class="grid sm:grid-cols-2 gap-4 mb-4">
            <div class="glass-panel p-4">
                <div class="text-sm font-semibold mb-2">🔥 پرمصرف‌ترین‌های CPU</div>
                <div id="top-cpu-list" class="space-y-1"></div>
            </div>
            <div class="glass-panel p-4">
                <div class="text-sm font-semibold mb-2">🧠 پرمصرف‌ترین‌های RAM</div>
                <div id="top-ram-list" class="space-y-1"></div>
            </div>
        </div>
        <div id="ssh-uninstall-panel" class="glass-panel p-4 mb-4 hidden">
            <div class="text-sm font-semibold mb-2">اطلاعات SSH برای حذف از راه دور</div>
            <div class="grid grid-cols-2 gap-2">
                <label class="field"><span>پورت SSH</span><input id="u-ssh-port" type="number" value="22"></label>
                <label class="field"><span>کاربر SSH</span><input id="u-ssh-user" value="root"></label>
                <label class="field col-span-2"><span>رمز عبور SSH</span><input id="u-ssh-pass" type="password"></label>
            </div>
        </div>
        <div class="flex flex-wrap gap-2">
            <button id="btn-check-now" class="btn-glass text-sm">🔄 چک فوری</button>
            <button id="btn-edit" class="btn-glass text-sm">✎ ویرایش</button>
            <button id="btn-delete" class="btn-glass text-sm">🗑 حذف از دیتابیس</button>
            <button id="btn-remote-uninstall" class="btn-danger text-sm">🧨 حذف از راه دور (SSH)</button>
        </div>
    `;
}

function singleLineChart(canvasId, label, color, bg, yOpts) {
    return new Chart(document.getElementById(canvasId), {
        type: "line",
        data: { labels: [], datasets: [{ label, data: [], borderColor: color, backgroundColor: bg, tension: 0.35, fill: true, pointRadius: 0 }] },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: { y: Object.assign({ grid: { color: "rgba(255,255,255,0.06)" } }, yOpts), x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } } },
            plugins: { legend: { display: false } },
        },
    });
}

function buildLiveCharts() {
    charts.cpu = singleLineChart("chart-cpu", "CPU", "#818cf8", "rgba(129,140,248,0.15)", { min: 0, max: 100 });
    charts.ram = singleLineChart("chart-ram", "RAM", "#34d399", "rgba(52,211,153,0.1)", { min: 0, max: 100 });
    charts.disk = singleLineChart("chart-disk", "Disk", "#fbbf24", "rgba(251,191,36,0.08)", { min: 0, max: 100 });
    charts.network = new Chart(document.getElementById("chart-network"), {
        type: "line",
        data: {
            labels: [],
            datasets: [
                { label: "دریافت", data: [], borderColor: "#22d3ee", backgroundColor: "rgba(34,211,238,0.12)", tension: 0.35, fill: true, pointRadius: 0 },
                { label: "ارسال", data: [], borderColor: "#f472b6", backgroundColor: "rgba(244,114,182,0.1)", tension: 0.35, fill: true, pointRadius: 0 },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: { y: { min: 0, grid: { color: "rgba(255,255,255,0.06)" }, ticks: { callback: (v) => fmtBps(v) } }, x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } } },
            plugins: { legend: { position: "bottom", labels: { boxWidth: 10, padding: 10 } } },
        },
    });

    document.querySelectorAll(".chart-toggle").forEach((btn) => {
        btn.onclick = () => {
            const key = btn.dataset.chart;
            const box = document.getElementById(`box-${key}`);
            const hidden = box.classList.toggle("hidden");
            btn.textContent = hidden ? "🙈" : "👁️";
        };
    });
}

function pushPoint(chart, label, values) {
    chart.data.labels.push(label);
    chart.data.datasets.forEach((ds, i) => ds.data.push(values[i]));
    if (chart.data.labels.length > MAX_POINTS) {
        chart.data.labels.shift();
        chart.data.datasets.forEach((ds) => ds.data.shift());
    }
    chart.update("none");
}

function pushSingle(chart, label, value) {
    pushPoint(chart, label, [value]);
}

function updateTrafficBanner(rx, tx, iface) {
    const banner = el("traffic-total-banner");
    if (rx == null || tx == null) {
        banner.classList.add("hidden");
        return;
    }
    banner.classList.remove("hidden");
    banner.innerHTML = `📡 کل ترافیک مصرفی${iface ? ` (${escapeHtml(iface)})` : ""}: ⬆ ${fmtBytes(tx)} &nbsp; ⬇ ${fmtBytes(rx)}`;
}

function renderProcList(containerId, procs, valueKey) {
    const container = document.getElementById(containerId);
    if (!procs || !procs.length) {
        container.innerHTML = `<div class="text-xs text-slate-500">داده‌ای نیست</div>`;
        return;
    }
    container.innerHTML = procs.map((p) => `
        <div class="proc-row">
            <span class="truncate">${escapeHtml(p.name)} <span class="text-slate-500">#${p.pid}</span></span>
            <span class="font-semibold" style="color:${pctColor(p[valueKey])}">${p[valueKey].toFixed(1)}%</span>
        </div>
    `).join("");
}

async function seedHistory(serverId) {
    try {
        const history = await api(`/api/servers/${serverId}/history?limit=${MAX_POINTS}`);
        let lastTraffic = null;
        history.forEach((row) => {
            if (row.status !== "up") return;
            const label = new Date(row.timestamp * 1000).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            pushSingle(charts.cpu, label, row.cpu_percent);
            pushSingle(charts.ram, label, row.ram_percent);
            pushSingle(charts.disk, label, row.disk_percent);
            pushPoint(charts.network, label, [row.net_recv_bps, row.net_sent_bps]);
            if (row.traffic_rx_bytes != null) lastTraffic = row;
        });
        if (lastTraffic) updateTrafficBanner(lastTraffic.traffic_rx_bytes, lastTraffic.traffic_tx_bytes, lastTraffic.traffic_iface);
    } catch (e) { /* بی‌اهمیت — چارت خالی شروع می‌شود */ }
}

async function liveTick(server) {
    try {
        const result = await api(`/api/servers/${server.id}/check`, { method: "POST" });
        const label = new Date(result.timestamp * 1000).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        if (result.ok) {
            pushSingle(charts.cpu, label, result.cpu_percent);
            pushSingle(charts.ram, label, result.ram_percent);
            pushSingle(charts.disk, label, result.disk_percent);
            pushPoint(charts.network, label, [result.net_recv_bps, result.net_sent_bps]);
            updateTrafficBanner(result.traffic_rx_bytes, result.traffic_tx_bytes, result.traffic_iface);
            const procs = result.raw?.processes;
            renderProcList("top-cpu-list", procs?.top_cpu, "cpu_percent");
            renderProcList("top-ram-list", procs?.top_ram, "ram_percent");
        }
        await refresh();
    } catch (e) { /* شبکه لحظه‌ای قطع شد — تیک بعدی دوباره امتحان می‌کند */ }
}

async function openDetail(server) {
    detailOpenId = server.id;
    syncDetailHeader(server);
    el("detail-body").innerHTML = detailBodyTemplate();
    buildLiveCharts();
    detailOverlay.classList.remove("hidden");

    await seedHistory(server.id);
    await liveTick(server);
    detailTimer = setInterval(() => liveTick(server), 3000);

    const sshPanel = el("ssh-uninstall-panel");
    if (!server.ssh_configured) sshPanel.classList.remove("hidden");

    el("btn-check-now").onclick = () => liveTick(server);
    el("btn-edit").onclick = () => { closeDetail(); openEditModal(server); };
    el("btn-delete").onclick = async () => {
        if (!confirm(`سرور «${server.name}» فقط از دیتابیس حذف شود؟ (ایجنت روی سرور هدف دست‌نخورده می‌ماند)`)) return;
        try {
            await api(`/api/servers/${server.id}`, { method: "DELETE" });
            closeDetail();
            await refresh();
        } catch (e) { alert("خطا: " + e.message); }
    };
    el("btn-remote-uninstall").onclick = async () => {
        if (!confirm(`اتصال SSH به سرور «${server.name}» برقرار شده و ایجنت کاملاً حذف می‌شود. ادامه می‌دهی؟`)) return;
        const btn = el("btn-remote-uninstall");
        btn.disabled = true;
        btn.textContent = "در حال حذف...";
        try {
            let body = null;
            if (!server.ssh_configured) {
                body = JSON.stringify({
                    ssh_port: parseInt(el("u-ssh-port").value, 10) || 22,
                    ssh_username: orNull(el("u-ssh-user").value),
                    ssh_password: orNull(el("u-ssh-pass").value),
                });
            }
            await api(`/api/servers/${server.id}/uninstall`, { method: "POST", body });
            closeDetail();
            await refresh();
        } catch (e) {
            alert("خطا: " + e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = "🧨 حذف از راه دور (SSH)";
        }
    };
}

// ══════════════════════════════════════════════════════════════════
//  اسکن فوری سراسری + شروع
// ══════════════════════════════════════════════════════════════════

el("btn-scan-now").onclick = async () => {
    const btn = el("btn-scan-now");
    btn.disabled = true;
    btn.textContent = "⏳ در حال اسکن...";
    try {
        await api("/api/scan-now", { method: "POST" });
        await refresh();
    } catch (e) {
        alert("خطا: " + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "⚡ اسکن فوری";
    }
};

// ══════════════════════════════════════════════════════════════════
//  مودال تنظیمات — فاصله‌ی چک + پشتیبان‌گیری/بازیابی
// ══════════════════════════════════════════════════════════════════

const settingsOverlay = el("settings-overlay");

function setStatusBox(elId, kind, text) {
    const box = el(elId);
    box.classList.remove("hidden");
    const styles = {
        info: "text-indigo-300", success: "text-emerald-400", error: "text-red-400",
    };
    box.className = "text-xs mt-2 " + styles[kind];
    box.textContent = text;
}

el("btn-settings").onclick = async () => {
    el("settings-interval-status").classList.add("hidden");
    el("settings-restore-status").classList.add("hidden");
    try {
        const { minutes } = await api("/api/settings/interval");
        el("s-interval").value = minutes;
    } catch (e) { /* پیش‌فرض خالی می‌ماند */ }
    settingsOverlay.classList.remove("hidden");
};
el("btn-settings-close").onclick = () => settingsOverlay.classList.add("hidden");

el("btn-save-interval").onclick = async () => {
    const minutes = parseInt(el("s-interval").value, 10);
    if (!minutes || minutes < 1) {
        setStatusBox("settings-interval-status", "error", "یک عدد معتبر (دقیقه) وارد کن.");
        return;
    }
    try {
        await api("/api/settings/interval", { method: "POST", body: JSON.stringify({ minutes }) });
        setStatusBox("settings-interval-status", "success", `✅ فاصله‌ی چک روی ${minutes} دقیقه تنظیم شد.`);
        await refreshInterval();
    } catch (e) {
        setStatusBox("settings-interval-status", "error", "خطا: " + e.message);
    }
};

el("btn-backup-now").onclick = () => {
    window.location.href = "/api/backup";
};

el("btn-restore-upload").onclick = async () => {
    const fileInput = el("s-restore-file");
    const file = fileInput.files[0];
    if (!file) {
        setStatusBox("settings-restore-status", "error", "اول یک فایل .db انتخاب کن.");
        return;
    }
    if (!confirm("دیتابیس فعلی با این فایل جایگزین می‌شود. مطمئنی؟")) return;

    const btn = el("btn-restore-upload");
    btn.disabled = true;
    btn.textContent = "⏳ در حال بازیابی...";
    try {
        const formData = new FormData();
        formData.append("file", file);
        const resp = await fetch("/api/restore", { method: "POST", body: formData });
        if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            throw new Error(body.detail || `HTTP ${resp.status}`);
        }
        setStatusBox("settings-restore-status", "success", "✅ دیتابیس بازیابی شد.");
        fileInput.value = "";
        await refresh();
    } catch (e) {
        setStatusBox("settings-restore-status", "error", "خطا: " + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "♻️ بازیابی از فایل";
    }
};

refresh();
refreshInterval();
setInterval(refresh, 2500);
setInterval(refreshInterval, 30000);
