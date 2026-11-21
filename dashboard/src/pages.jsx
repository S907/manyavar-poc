import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import { inr, inrShort, kindLabel, kindTag, KINDS, LIFECYCLE, transitions, visibleMoves, useRole } from "./lib.js";

const C = { w: "#2f6db4", s: "#6a3b8a", m: "#1f7a4d", a: "#b26a00", p: "#b3261e", accent: "#9d3a1e", line: "#e7e0d6" };
const Tile = ({ lab, val, sub, cls }) => (
  <div className={"tile " + (cls || "")}><div className="lab">{lab}</div><div className="val">{val}</div>{sub && <div className="sub">{sub}</div>}</div>
);
const Meter = ({ now, after }) => (
  <div className={"meter " + (after >= 99 ? "hot" : "")} title={`${now}% → ${after}%`}>
    <i style={{ width: Math.min(100, now) + "%" }} /><em style={{ width: Math.min(100, after) + "%" }} />
  </div>
);
const Steps = ({ state }) => {
  const idx = state === "rejected" ? -1 : LIFECYCLE.indexOf(state === "approved_pending_ho" ? "proposed" : state);
  return <div className="steps">{LIFECYCLE.map((s, i) => <div key={s} className={"step " + (i < idx ? "done" : i === idx ? "cur" : "")}>{s}</div>)}</div>;
};

// ---------------- Overview ----------------
export function Overview({ data, check, life }) {
  const { role, scope } = useRole();
  const nav = useNavigate();
  const moves = visibleMoves(data, role, scope);
  const units = moves.reduce((a, m) => a + m.units, 0);
  const value = moves.reduce((a, m) => a + m.value_mrp, 0);
  const needApp = moves.filter(m => m.needs_approval).length;
  const byKind = Object.keys(KINDS).map(k => ({ name: kindLabel(k).replace("Warehouse → Store","WH → Store"), units: moves.filter(m => m.kind === k).reduce((a, m) => a + m.units, 0), c: C[kindTag(k)] })).filter(d => d.units);
  const byCity = useMemo(() => {
    const g = {}; moves.forEach(m => { const c = m.city || m.to_loc; g[c] = (g[c] || 0) + m.value_mrp; });
    return Object.entries(g).map(([name, v]) => ({ name, v })).sort((a, b) => b.v - a.v).slice(0, 8);
  }, [moves]);
  const pipe = LIFECYCLE.map(s => ({ s, n: moves.filter(m => life.stateOf(m.move_id) === s).length }));
  const rejected = moves.filter(m => life.stateOf(m.move_id) === "rejected").length;

  return (
    <div className="content">
      <div className="tiles">
        <Tile lab={<><span className="dot" style={{ background: C.accent }} /> Moves proposed</>} val={moves.length} sub={`${units.toLocaleString("en-IN")} units`} />
        <Tile lab="Value at MRP" val={inrShort(value)} sub="to reposition" />
        <Tile lab="Need HO approval" val={needApp} sub="over ₹1,00,000" cls={needApp ? "warnc" : ""} />
        <Tile lab="Data exceptions" val={(data.issues || []).length} sub="flagged, not acted on" cls={(data.issues || []).length ? "warnc" : ""} />
        <Tile lab="Stores receiving" val={`${data.stores.filter(s => s.units_in > 0).length}/${data.stores.length}`} sub="in this plan" />
        <Tile lab="Rule checks" val={check.all_passed ? `${check.results.length}/${check.results.length}` : "FAIL"} sub="independent audit" cls={check.all_passed ? "" : "alert"} />
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Priority actions <span className="count">exception-based, highest value first</span></h2>
          <p className="note">What a merchandiser should look at before approving. Same idea Oracle Retail and Anaplan call “exception-based”.</p>
          {(data.problems || []).length ? (data.problems || []).map((p, i) => (
            <div className="exc" key={i}>
              <span className={"sev " + p.severity}>{p.severity}</span>
              <div><b>{p.headline}</b><div className="d">{p.detail}</div></div>
              <button className="btn sm go" onClick={() => nav("/transfers")}>Review →</button>
            </div>
          )) : <div className="empty">No exceptions.</div>}
        </div>
        <div className="card">
          <h2>Transfer pipeline</h2>
          <p className="note">Where today’s moves stand in the workflow.</p>
          {pipe.map(x => (
            <div key={x.s} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line)" }}>
              <span className={"st " + x.s}>{x.s}</span>
              <div className="meter" style={{ flex: 1 }}><em style={{ width: (moves.length ? 100 * x.n / moves.length : 0) + "%" }} /></div>
              <b style={{ minWidth: 36, textAlign: "right" }}>{x.n}</b>
            </div>
          ))}
          {rejected > 0 && <div className="muted" style={{ marginTop: 8 }}>{rejected} rejected</div>}
        </div>
      </div>

      <div className="grid2b">
        <div className="card">
          <h2>Units to move by type</h2>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={byKind} margin={{ left: -18, top: 10 }}>
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-12} textAnchor="end" height={50} />
              <YAxis tick={{ fontSize: 11 }} /><Tooltip />
              <Bar dataKey="units" radius={[5, 5, 0, 0]}>{byKind.map((d, i) => <Cell key={i} fill={d.c} />)}<LabelList dataKey="units" position="top" style={{ fontSize: 11, fill: "#555" }} /></Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h2>Value moving by city</h2>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={byCity} layout="vertical" margin={{ left: 22, top: 6 }}>
              <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={inrShort} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={78} />
              <Tooltip formatter={v => inr(v)} />
              <Bar dataKey="v" fill={C.accent} radius={[0, 5, 5, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

// ---------------- Transfers ----------------
export function Transfers({ data, life }) {
  const { role, scope } = useRole();
  const [sp] = useSearchParams();
  const [kind, setKind] = useState("");
  const [store, setStore] = useState(sp.get("store") || "");
  const [stat, setStat] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(null);
  const base = visibleMoves(data, role, scope);
  const moves = base.filter(m =>
    (!kind || m.kind === kind) && (!store || m.to_loc === store || m.from_loc === store) &&
    (!stat || life.stateOf(m.move_id) === stat) &&
    (!q || (m.style_id + m.style_name + m.sizes + m.reason + m.from_loc + m.to_loc).toLowerCase().includes(q.toLowerCase()))
  );
  const approveAll = async () => {
    const appr = moves.filter(m => transitions(m, life.stateOf(m.move_id), role, scope, data.warehouse).some(t => t[0] === "approved")).map(m => m.move_id);
    const pend = moves.filter(m => transitions(m, life.stateOf(m.move_id), role, scope, data.warehouse).some(t => t[0] === "approved_pending_ho")).map(m => m.move_id);
    if (appr.length) await life.bulk(appr, "approved");
    if (pend.length) await life.bulk(pend, "approved_pending_ho");
  };
  const approvingAll = moves.some(m => life.pending.has(m.move_id));

  return (
    <div className="content">
      <div className="bar">
        <select value={kind} onChange={e => setKind(e.target.value)}><option value="">All types</option>{Object.keys(KINDS).map(k => <option key={k} value={k}>{kindLabel(k)}</option>)}</select>
        <select value={store} onChange={e => setStore(e.target.value)}><option value="">All stores</option>{data.stores.map(s => <option key={s.store_id}>{s.store_id}</option>)}</select>
        <select value={stat} onChange={e => setStat(e.target.value)}><option value="">All statuses</option>{["proposed","approved","approved_pending_ho","picked","dispatched","received","rejected"].map(s => <option key={s}>{s}</option>)}</select>
        <input className="grow" placeholder="Search style, size, reason…" value={q} onChange={e => setQ(e.target.value)} />
        {(role === "merchandiser" || role === "super_admin" || role === "area_manager") &&
          <button className="btn primary" disabled={approvingAll} onClick={approveAll}>{approvingAll && <span className="spinner" />}Approve all shown</button>}
      </div>
      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        <table className="tbl">
          <thead><tr><th>Move</th><th>Style & sizes</th><th className="n">Units</th><th className="n">Value</th><th className="n">Arrives</th><th>Status</th><th>Reason</th></tr></thead>
          <tbody>
            {moves.map(m => (
              <tr key={m.move_id} className={life.pending.has(m.move_id) ? "row-pending" : ""} onClick={() => setSel(m)}>
                <td><span className="route">{m.from_loc} → {m.to_loc}</span><br /><span className={"kpill " + kindTag(m.kind)}>{kindLabel(m.kind)}</span> <span className="muted">{m.move_id}</span></td>
                <td><b>{m.style_name}</b> <span className="muted">{m.style_id}</span><br /><span className="muted">{m.sizes}</span></td>
                <td className="n"><b>{m.units}</b></td>
                <td className="n">{inr(m.value_mrp)}{m.needs_approval && <><br /><span className="need">needs approval</span></>}</td>
                <td className="n">{m.arrives_on}<br /><span className="muted">{m.lead_days}d</span></td>
                <td><span className={"st " + life.stateOf(m.move_id)}>{life.stateOf(m.move_id).replace(/_/g, " ")}</span></td>
                <td className="muted" style={{ maxWidth: 360 }}>{m.reason}</td>
              </tr>
            ))}
            {!moves.length && <tr><td colSpan="7"><div className="empty">No transfers match.</div></td></tr>}
          </tbody>
        </table>
      </div>
      {sel && <Drawer m={sel} data={data} life={life} onClose={() => setSel(null)} />}
    </div>
  );
}

function Drawer({ m, data, life, onClose }) {
  const { role, scope } = useRole();
  const [closing, setClosing] = useState(false);
  const close = () => { setClosing(true); setTimeout(onClose, 160); };
  const state = life.stateOf(m.move_id);
  const acts = transitions(m, state, role, scope, data.warehouse);
  const fromS = data.stores.find(s => s.store_id === m.from_loc);
  const toS = data.stores.find(s => s.store_id === m.to_loc);
  const busy = life.pending.has(m.move_id);
  return (
    <>
      <div className={"scrim" + (closing ? " out" : "")} onClick={close} />
      <div className={"drawer" + (closing ? " out" : "")}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div><h3>{m.from_loc} → {m.to_loc}</h3><span className={"kpill " + (m.kind && m.kind[0])}>{kindLabel(m.kind)}</span> <span className="muted">{m.move_id}</span></div>
          <button className="btn sm" style={{ marginLeft: "auto" }} onClick={close}>Close</button>
        </div>
        <Steps state={state} />
        <div className="reasonbox">{m.reason}</div>
        <div className="kv"><span>Style</span><b>{m.style_name} ({m.style_id})</b></div>
        <div className="kv"><span>Sizes</span><b>{m.sizes}</b></div>
        <div className="kv"><span>Units</span><b>{m.units}</b></div>
        <div className="kv"><span>Value at MRP</span><b>{inr(m.value_mrp)}{m.needs_approval ? " · needs approval" : ""}</b></div>
        <div className="kv"><span>Dispatch / arrive</span><b>{m.dispatch_on} → {m.arrives_on} ({m.lead_days}d)</b></div>
        {toS && <div className="kv"><span>Destination fill</span><b>{toS.units_now} → {toS.units_after} / {toS.capacity} ({toS.fill_now}%→{toS.fill_after}%)</b></div>}
        {fromS && <div className="kv"><span>Source fill</span><b>{fromS.units_now} → {fromS.units_after} / {fromS.capacity}</b></div>}
        <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
          {acts.length ? acts.map(a => <button key={a[0]} disabled={busy} className={"btn " + (a[0] === "rejected" ? "" : "primary")} onClick={() => { life.act(m, role, a[0], a[1]); close(); }}>{busy && <span className="spinner" />}{a[1]}</button>)
            : <div className="muted">No action for your role at this stage.</div>}
        </div>
      </div>
    </>
  );
}

// ---------------- Stores ----------------
export function Stores({ data, life }) {
  const { role, scope } = useRole();
  const rows = data.stores.filter(s => !scope || scope.has(s.store_id));
  return (
    <div className="content">
      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        <table className="tbl">
          <thead><tr><th>Store</th><th>Tier</th><th className="n">Capacity</th><th className="n">Now</th><th className="n">In</th><th className="n">Out</th><th className="n">After</th><th style={{ width: 160 }}>Fill (now → after)</th><th>Manager</th></tr></thead>
          <tbody>
            {rows.map(s => (
              <tr key={s.store_id}>
                <td><b>{s.store_id}</b> <span className="muted">{s.city}{s.new_store ? " · new" : ""}</span></td>
                <td><span className="kpill">{s.tier}</span></td>
                <td className="n">{s.capacity}</td><td className="n">{s.units_now}</td>
                <td className="n" style={{ color: "var(--ok)" }}>+{s.units_in}</td>
                <td className="n" style={{ color: s.units_out ? "var(--bad)" : "" }}>−{s.units_out}</td>
                <td className="n"><b>{s.units_after}</b></td>
                <td><Meter now={s.fill_now} after={s.fill_after} /><span className="muted">{s.fill_now}% → {s.fill_after}%</span></td>
                <td className="muted">{s.area_manager_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------- Products ----------------
export function Products({ data }) {
  const g = {};
  data.moves.forEach(m => { const k = m.style_id; (g[k] = g[k] || { style_id: k, name: m.style_name, cat: m.category, units: 0, value: 0, to: new Set() }); g[k].units += m.units; g[k].value += m.value_mrp; g[k].to.add(m.to_loc); });
  const rows = Object.values(g).sort((a, b) => b.value - a.value);
  return (
    <div className="content">
      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        <table className="tbl">
          <thead><tr><th>Style</th><th>Category</th><th className="n">Units moving</th><th className="n">Value</th><th className="n">Destinations</th></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.style_id}><td><b>{r.name}</b> <span className="muted">{r.style_id}</span></td><td><span className="kpill">{r.cat}</span></td><td className="n"><b>{r.units}</b></td><td className="n">{inr(r.value)}</td><td className="n">{r.to.size}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------- Approvals (role queue) ----------------
export function Approvals({ data, life }) {
  const { role, scope } = useRole();
  const base = visibleMoves(data, role, scope);
  const queue = base.filter(m => transitions(m, life.stateOf(m.move_id), role, scope, data.warehouse).length);
  return (
    <div className="content">
      <div className="card">
        <h2>Your work queue <span className="count">{queue.length} moves need you</span></h2>
        <p className="note">Only moves you can act on, at their current stage.</p>
        {queue.length ? (
          <table className="tbl"><thead><tr><th>Move</th><th>Style</th><th className="n">Units</th><th className="n">Value</th><th>Status</th><th></th></tr></thead>
            <tbody>{queue.map(m => {
              const busy = life.pending.has(m.move_id);
              return (
              <tr key={m.move_id} className={busy ? "row-pending" : ""}>
                <td><span className="route">{m.from_loc} → {m.to_loc}</span> <span className="muted">{m.move_id}</span></td>
                <td>{m.style_name} <span className="muted">{m.style_id}</span></td>
                <td className="n">{m.units}</td><td className="n">{inr(m.value_mrp)}</td>
                <td><span className={"st " + life.stateOf(m.move_id)}>{life.stateOf(m.move_id).replace(/_/g," ")}</span></td>
                <td className="n">{transitions(m, life.stateOf(m.move_id), role, scope, data.warehouse).map(a => <button key={a[0]} disabled={busy} className={"btn sm " + (a[0] === "rejected" ? "" : "primary")} style={{ marginLeft: 6 }} onClick={() => life.act(m, role, a[0], a[1])}>{busy && <span className="spinner" />}{a[1]}</button>)}</td>
              </tr>
            );})}</tbody>
          </table>
        ) : <div className="empty">Nothing in your queue right now.</div>}
      </div>
    </div>
  );
}

// ---------------- Exceptions / data quality ----------------
export function Exceptions({ data, check }) {
  return (
    <div className="content">
      <div className="grid2b">
        <div className="card">
          <h2>Data issues <span className="count">{(data.issues || []).length}</span></h2>
          <p className="note">Flagged and kept out of every move until a human checks.</p>
          {(data.issues || []).map((i, k) => <div className="exc" key={k}><span className="sev data">{i.kind}</span><div><b>{i.where}</b><div className="d">{i.detail}</div></div></div>)}
        </div>
        <div className="card">
          <h2>Rule check <span className="count">{check.all_passed ? "all pass" : "FAIL"}</span></h2>
          <p className="note">Re-checked from raw data by a separate program.</p>
          {check.results.map((r, k) => <div className="exc" key={k}><span className="sev" style={{ background: r.passed ? "var(--okbg)" : "var(--badbg)", color: r.passed ? "var(--ok)" : "var(--bad)" }}>{r.passed ? "pass" : "fail"}</span><div><b>{r.rule}</b><div className="d">{r.checked} checked · {r.violations} broken{r.note ? " · " + r.note : ""}</div></div></div>)}
        </div>
      </div>
      <div className="card">
        <h2>Moves blocked by a rule <span className="count">{(data.blocked || []).length} kinds</span></h2>
        {(data.blocked || []).map((b, k) => <div className="exc" key={k}><span className="sev stock">{b.units}u</span><div><b>{b.rule}</b><div className="d">{b.cases} cases · {(b.examples || []).slice(0, 2).join(" · ")}</div></div></div>)}
      </div>
    </div>
  );
}

// ---------------- Admin ----------------
export function Admin({ data, life, users, setUsers }) {
  return (
    <div className="content">
      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        <table className="tbl">
          <thead><tr><th>User</th><th>Role</th><th>Scope</th><th>Status</th></tr></thead>
          <tbody>{users.map(u => (
            <tr key={u.user_id}><td><b>{u.name}</b> <span className="muted">{u.email}</span></td><td><span className="kpill">{u.role.replace(/_/g," ")}</span></td>
              <td className="muted">{u.scope.type === "all" ? "everything" : u.scope.type === "warehouse" ? "warehouse" : (u.scope.stores || []).join(", ")}</td>
              <td><span className="st approved">active</span></td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="card">
        <h2>Audit log <span className="count">{life.audit.length} actions</span></h2>
        {life.audit.length ? life.audit.slice(0, 120).map((a, k) => (
          <div className="audrow" key={k}><span className="muted">{new Date(a.at).toLocaleString()}</span><span className="kpill">{a.role.replace(/_/g," ")}</span><span className={"st " + a.action}>{a.action.replace(/_/g," ")}</span><span>{a.move_id}</span><span className="muted">{a.detail}</span></div>
        )) : <div className="empty">No actions yet. Approve or move something and it appears here.</div>}
      </div>
    </div>
  );
}
