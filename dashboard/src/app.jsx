import { useMemo, useState } from "react";
import { HashRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import { useApi, postAction, postBulk, RoleCtx, scopeFor, visibleMoves, transitions } from "./lib.js";
import { Overview, Transfers, Stores, Products, Approvals, Exceptions, Admin } from "./pages.jsx";

const NAV = [
  ["/", "Overview", "▤", null],
  ["/transfers", "Transfers", "⇄", "moves"],
  ["/approvals", "My queue", "✔", null],
  ["/stores", "Stores", "▦", null],
  ["/products", "Products", "◳", null],
  ["/exceptions", "Exceptions", "!", "exc"],
];

export default function App() {
  const { data, check, err, refresh } = useApi();
  const [userId, setUserId] = useState("MERCH");
  const [pending, setPending] = useState(() => new Set());
  const addPending = ids => setPending(p => new Set([...p, ...ids]));
  const removePending = ids => setPending(p => { const n = new Set(p); ids.forEach(id => n.delete(id)); return n; });

  if (err) return <div style={{ padding: 40 }}>Could not reach the server API at <code>/api/run</code>.<br />Start it: <code>python server/app.py</code><br /><br />{err}</div>;
  if (!data || !check) return <div className="loadscreen"><span className="spinner" /><div>Loading today's run…</div></div>;

  const users = data.users || [];
  const u = users.find(x => x.user_id === userId) || users[0];
  const role = u ? u.role : "merchandiser";
  const scope = u ? scopeFor(role, u.user_id, data) : null;

  const statusMap = Object.fromEntries(data.moves.map(m => [m.move_id, m.status || "proposed"]));
  const life = {
    stateOf: id => statusMap[id] || "proposed",
    audit: data.audit || [],
    pending,
    act: async (move, _role, to) => {
      addPending([move.move_id]);
      try { await postAction(userId, move.move_id, to); await refresh(); }
      catch (e) { alert(e.message); }
      finally { removePending([move.move_id]); }
    },
    bulk: async (ids, to) => {
      addPending(ids);
      try { await postBulk(userId, ids, to); await refresh(); }
      finally { removePending(ids); }
    },
  };

  const moves = visibleMoves(data, role, scope);
  const counts = { moves: moves.length, exc: (data.issues || []).length };

  const Shell = ({ children, title, sub }) => (
    <div className="layout">
      <aside className="side">
        <div className="brand"><span>Stock</span> Mover<small>Manyavar · merchandising control</small></div>
        <nav className="nav">
          <div className="sec">Operate</div>
          {NAV.map(([to, label, ic, badge]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => isActive ? "on" : ""}>
              <span className="ic">{ic}</span>{label}
              {badge === "moves" && <span className="tag">{counts.moves}</span>}
              {badge === "exc" && counts.exc > 0 && <span className="tag">{counts.exc}</span>}
            </NavLink>
          ))}
          {role === "super_admin" && <><div className="sec">Administer</div>
            <NavLink to="/admin" className={({ isActive }) => isActive ? "on" : ""}><span className="ic">⚙</span>Admin</NavLink></>}
        </nav>
        <div className="foot">Data as of {data.today}<br />{data.moves.length} moves · {data.window.days}-day window</div>
      </aside>
      <div>
        <header className="top">
          <div><h1>{title}</h1><div className="sub">{sub}</div></div>
          <div className="right">
            {pending.size > 0 && <span className="muted saving"><span className="spinner" />saving…</span>}
            <span className={"badge " + (check.all_passed ? "ok" : "bad")}>{check.all_passed ? "✓ rules pass" : "✗ rules fail"}</span>
            <div className="rolesel"><span className="muted">Signed in as</span>
              <select value={userId} onChange={e => setUserId(e.target.value)}>
                {users.map(x => <option key={x.user_id} value={x.user_id}>{x.name} · {x.role.replace(/_/g, " ")}</option>)}
              </select>
            </div>
          </div>
        </header>
        {children}
      </div>
    </div>
  );

  return (
    <RoleCtx.Provider value={{ role, scope, user: u }}>
      <HashRouter>
        <Routes>
          <Route path="/" element={<Shell title="Overview" sub={`Exception view · stock as of ${data.today}`}><Overview data={data} check={check} life={life} /></Shell>} />
          <Route path="/transfers" element={<Shell title="Transfers" sub="Review, approve and move stock"><Transfers data={data} life={life} /></Shell>} />
          <Route path="/approvals" element={<Shell title="My queue" sub="Moves waiting on your role"><Approvals data={data} life={life} /></Shell>} />
          <Route path="/stores" element={<Shell title="Stores" sub="Fill and flow, before and after"><Stores data={data} life={life} /></Shell>} />
          <Route path="/products" element={<Shell title="Products" sub="What is moving, by style"><Products data={data} /></Shell>} />
          <Route path="/exceptions" element={<Shell title="Exceptions" sub="Data issues, rule check, blocked moves"><Exceptions data={data} check={check} /></Shell>} />
          <Route path="/admin" element={<Shell title="Admin" sub="Users, roles and audit trail"><Admin data={data} life={life} users={users} /></Shell>} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </HashRouter>
    </RoleCtx.Provider>
  );
}
