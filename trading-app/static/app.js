const $ = (s) => document.querySelector(s);
const api = async (path, opts = {}) => {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
};
const fmt = (n, d = 2) => (n == null || isNaN(n) ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const pnlCls = (n) => (n > 0 ? "pos" : n < 0 ? "neg" : "");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let types = {};
let editing = null;

async function loadTypes() {
  types = await api("/api/strategy-types");
  const sel = $("#type");
  const current = sel.value;
  sel.innerHTML = Object.entries(types).map(([k, t]) => `<option value="${esc(k)}">${esc(t.name)}</option>`).join("");
  if (current && types[current]) sel.value = current;
  renderParams();
}

function renderParams(values = {}) {
  const t = types[$("#type").value];
  if (!t) return;
  $("#type-desc").textContent = t.description;
  $("#params").innerHTML = t.params.map((p) => {
    const v = values[p.name] ?? p.default;
    const input = p.type === "bool"
      ? `<select data-param="${esc(p.name)}"><option value="true" ${v ? "selected" : ""}>yes</option><option value="false" ${!v ? "selected" : ""}>no</option></select>`
      : `<input data-param="${esc(p.name)}" type="${p.type === "str" ? "text" : "number"}" step="any" value="${esc(v)}">`;
    return `<label title="${esc(p.help)}">${esc(p.name)}${p.help ? ` <span class="muted">· ${esc(p.help)}</span>` : ""}${input}</label>`;
  }).join("");
}

function collectParams() {
  const out = {};
  document.querySelectorAll("[data-param]").forEach((el) => (out[el.dataset.param] = el.value));
  return out;
}

function resetForm() {
  editing = null;
  $("#form-title").textContent = "Add strategy";
  $("#submit").textContent = "Add strategy";
  $("#cancel-edit").hidden = true;
  $("#type").disabled = $("#symbol").disabled = false;
  $("#label").value = "";
  renderParams();
}

$("#type").addEventListener("change", () => renderParams());
$("#cancel-edit").addEventListener("click", resetForm);
$("#reload").addEventListener("click", async () => {
  const r = await api("/api/strategy-types/reload", { method: "POST" });
  await loadTypes();
  alert(r.errors.length ? "Loaded with errors:\n" + r.errors.join("\n") : `Loaded ${r.types.length} strategy types.`);
});

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    if (editing) {
      await api(`/api/strategies/${editing}`, { method: "PATCH", body: JSON.stringify({ params: collectParams(), interval_sec: +$("#interval").value, label: $("#label").value }) });
      resetForm();
    } else {
      await api("/api/strategies", { method: "POST", body: JSON.stringify({ type: $("#type").value, symbol: $("#symbol").value, params: collectParams(), interval_sec: +$("#interval").value, label: $("#label").value }) });
      $("#label").value = "";
    }
    refresh();
  } catch (err) { alert(err.message); }
});

let strategies = [];
async function action(id, act) {
  try {
    if (act === "edit") {
      const s = strategies.find((x) => x.id === id);
      editing = id;
      $("#type").value = s.type; $("#symbol").value = s.symbol; $("#interval").value = s.interval_sec; $("#label").value = s.label;
      $("#type").disabled = $("#symbol").disabled = true;
      renderParams(s.params);
      $("#form-title").textContent = `Edit ${s.label}`; $("#submit").textContent = "Save changes"; $("#cancel-edit").hidden = false;
      $("#add-form").scrollIntoView({ behavior: "smooth" });
      return;
    }
    if (act === "delete" && !confirm("Delete this strategy? Its open position is NOT closed automatically.")) return;
    if (act === "flatten" && !confirm("Close this strategy's position at market?")) return;
    await api(`/api/strategies/${id}${act === "delete" ? "" : "/" + act}`, { method: act === "delete" ? "DELETE" : "POST" });
    refresh();
  } catch (err) { alert(err.message); }
}
window.action = action;

function renderStrategies() {
  $("#empty").hidden = strategies.length > 0;
  $("#strategies tbody").innerHTML = strategies.map((s) => {
    const pnl = s.realized_pnl + s.unrealized_pnl;
    const statusCls = s.status.startsWith("running") ? "status-running" : s.status === "error" ? "status-error" : "status-stopped";
    const ind = Object.entries(s.indicators || {}).map(([k, v]) => `${esc(k)}=${esc(v)}`).join(" ");
    return `<tr>
      <td><strong>${esc(s.label)}</strong>${s.label !== s.type_name ? `<br><span class="muted">${esc(s.type_name)}</span>` : ""}</td>
      <td>${esc(s.symbol)}</td>
      <td class="${statusCls}" title="${esc(s.error)}">${esc(s.status)}</td>
      <td>${fmt(s.last_price, 4)}</td>
      <td>${fmt(s.position, 6)}${s.position ? `<br><span class="muted">@ ${fmt(s.avg_price, 4)}</span>` : ""}</td>
      <td class="${pnlCls(pnl)}">${fmt(pnl)}</td>
      <td class="muted">${ind}</td>
      <td class="row-actions">
        ${s.enabled ? `<button class="small ghost" onclick="action('${s.id}','stop')">Stop</button>` : `<button class="small" onclick="action('${s.id}','start')">Start</button>`}
        <button class="small ghost" onclick="action('${s.id}','edit')">Edit</button>
        <button class="small ghost" onclick="action('${s.id}','flatten')">Flatten</button>
        <button class="small danger" onclick="action('${s.id}','delete')">Delete</button>
      </td></tr>`;
  }).join("");
}

async function refresh() {
  try {
    const [status, strats, orders, logs] = await Promise.all([api("/api/status"), api("/api/strategies"), api("/api/orders"), api("/api/logs?limit=150")]);
    $("#mode").textContent = status.mode.toUpperCase() + (status.mode === "paper" ? ` · ${status.market_data} prices` : " · Liquid");
    $("#mode").className = "badge " + status.mode;
    $("#halted").hidden = !status.halted;
    $("#warning").hidden = !status.warning; $("#warning").textContent = status.warning;
    strategies = strats; renderStrategies();
    $("#orders tbody").innerHTML = orders.slice(0, 100).map((o) => `<tr>
      <td>${new Date(o.created_at * 1000).toLocaleTimeString()}</td><td>${esc(o.strategy_label)}</td>
      <td class="${o.side === "buy" ? "pos" : "neg"}">${o.side}</td><td>${fmt(o.quantity, 6)}</td><td>${fmt(o.fill_price, 4)}</td>
      <td title="${esc(o.reason)}">${esc(o.status)}</td><td class="muted">${esc(o.note || o.reason)}</td></tr>`).join("");
    $("#logs").innerHTML = logs.map((l) => `<li class="${l.level}">${new Date(l.t * 1000).toLocaleTimeString()} ${esc(l.message)}</li>`).join("");
    const acct = await api("/api/account").catch((e) => ({ error: e.message }));
    $("#account").innerHTML = acct.error
      ? `<div class="card"><div class="k">Account</div><div class="neg">${esc(acct.error)}</div></div>`
      : acct.mode === "paper"
        ? [["Equity", fmt(acct.equity)], ["Cash", fmt(acct.cash)], ["P&L", `<span class="${pnlCls(acct.pnl)}">${fmt(acct.pnl)}</span>`], ["Open positions", acct.positions.filter((p) => p.quantity).length], ["Running strategies", strats.filter((s) => s.enabled).length]]
            .map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")
        : `<div class="card"><div class="k">Liquid account</div><pre>${esc(JSON.stringify(acct.balances, null, 1)).slice(0, 600)}</pre></div>`;
  } catch (err) { console.error(err); }
}

loadTypes().then(refresh);
setInterval(refresh, 2000);
