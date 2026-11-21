import { useEffect, useState, useCallback, createContext, useContext } from "react";

const API = ""; // same origin as the server that serves this app

// ---------- data from the backend API ----------
export function useApi() {
  const [data, setData] = useState(null);
  const [check, setCheck] = useState(null);
  const [err, setErr] = useState(null);
  const refresh = useCallback(async () => {
    try {
      const [d, c] = await Promise.all([
        fetch(API + "/api/run", { cache: "no-store" }).then(r => r.json()),
        fetch(API + "/api/checks", { cache: "no-store" }).then(r => r.json()),
      ]);
      d.moves.forEach(m => { m.city = (d.stores.find(s => s.store_id === m.to_loc) || {}).city || ""; });
      if (!d.warehouse) d.warehouse = "WH-KOL";
      setData(d); setCheck(c);
    } catch (e) { setErr(String(e)); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return { data, check, err, refresh };
}

export async function postAction(user_id, move_id, to) {
  const r = await fetch(API + "/api/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id, move_id, to }) });
  if (!r.ok) throw new Error((await r.json()).detail || "action failed");
  return r.json();
}
export async function postBulk(user_id, move_ids, to) {
  const r = await fetch(API + "/api/action/bulk", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id, move_ids, to }) });
  return r.json();
}

// ---------- format ----------
export const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN");
export const inrShort = n => {
  n = Number(n || 0);
  if (n >= 1e7) return "₹" + (n / 1e7).toFixed(2) + "Cr";
  if (n >= 1e5) return "₹" + (n / 1e5).toFixed(2) + "L";
  if (n >= 1e3) return "₹" + (n / 1e3).toFixed(1) + "k";
  return "₹" + n;
};
export const KINDS = {
  WAREHOUSE_TO_STORE: ["Warehouse → Store", "w"],
  STORE_TO_STORE: ["Store → Store", "s"],
  MIN_DISPLAY: ["Min display", "m"],
  AGEING: ["Ageing", "a"],
  PULL_BACK: ["Pull back", "p"],
};
export const kindLabel = k => (KINDS[k] || [k, ""])[0];
export const kindTag = k => (KINDS[k] || [k, ""])[1];

export const LIFECYCLE = ["proposed", "approved", "picked", "dispatched", "received"];

// transitions a role may apply to a move in its current state (mirrors the server)
export function transitions(move, state, role, scopeStores, warehouse) {
  const out = [];
  const isHO = role === "merchandiser" || role === "super_admin";
  const inScope = loc => !scopeStores || scopeStores.has(loc);
  if (state === "proposed") {
    if (isHO) { out.push(["approved", "Approve"]); out.push(["rejected", "Reject"]); }
    else if (role === "area_manager" && (inScope(move.to_loc) || inScope(move.from_loc)))
      out.push([move.needs_approval ? "approved_pending_ho" : "approved", move.needs_approval ? "Approve · needs HO" : "Approve"]);
  }
  if (state === "approved_pending_ho" && isHO) out.push(["approved", "Sign off"]);
  if (state === "approved") {
    if (role === "warehouse" && move.from_loc === warehouse) out.push(["picked", "Mark picked"]);
    if (role === "store_manager" && move.from_loc !== warehouse && inScope(move.from_loc)) out.push(["dispatched", "Dispatch"]);
  }
  if (state === "picked" && role === "warehouse" && move.from_loc === warehouse) out.push(["dispatched", "Dispatch"]);
  if (state === "dispatched" && role === "store_manager" && inScope(move.to_loc)) out.push(["received", "Receive"]);
  return out;
}

// ---------- role / persona ----------
export const ROLES = [
  ["super_admin", "Super Admin"],
  ["merchandiser", "Merchandiser (HO)"],
  ["area_manager", "Area Manager"],
  ["store_manager", "Store Manager"],
  ["warehouse", "Warehouse"],
];
export const RoleCtx = createContext(null);
export const useRole = () => useContext(RoleCtx);
export function scopeFor(role, who, data) {
  if (!data) return null;
  if (role === "area_manager") { const a = (data.area_managers || []).find(x => x.area_manager_id === who); return a ? new Set(a.stores) : new Set(); }
  if (role === "store_manager") return who ? new Set([who]) : new Set();
  return null;
}
export function visibleMoves(data, role, scope) {
  if (!data) return [];
  if (role === "warehouse") return data.moves.filter(m => m.from_loc === data.warehouse);
  if (!scope) return data.moves;
  return data.moves.filter(m => scope.has(m.to_loc) || scope.has(m.from_loc));
}
