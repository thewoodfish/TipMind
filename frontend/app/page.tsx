"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import useSWR from "swr";
import { motion, AnimatePresence } from "framer-motion";

// ─── Types ────────────────────────────────────────────────────────────────────

interface WalletInfo { balance: number; address: string; token: string; }
interface Swarm {
  swarm_id: string; creator_id: string; goal_description: string;
  trigger_event?: string; target_amount_usd: number; current_amount_usd: number;
  participant_count: number; status: string;
}
interface Transaction {
  id: number; tx_hash: string | null; creator_id: string; amount: number;
  token: string; trigger_type: string; status: string; created_at: string;
}
interface Metrics {
  today: { total_usd: number; tip_count: number };
  this_week: { total_usd: number; tip_count: number };
  top_creators: { creator_id: string; total_usd: number; tip_count: number }[];
  active_swarms_count: number;
}
interface FeedEvent {
  id: string; type: string; agent: string | null; message: string;
  amount: number | null; token: string | null; timestamp: string;
  metadata: Record<string, unknown>;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const FEED_COLORS: Record<string, string> = {
  WATCH_TIME_UPDATE: "#00c9ff", CHAT_MESSAGE: "#fbbf24",
  MILESTONE_REACHED: "#a855f7", SWARM_TRIGGERED: "#ef4444",
  AGENT_DECISION: "#00ff88", TIP_EXECUTED: "#00ff88",
};
const FEED_ICONS: Record<string, string> = {
  WATCH_TIME_UPDATE: "👁", CHAT_MESSAGE: "💬",
  MILESTONE_REACHED: "🏆", SWARM_TRIGGERED: "🌊",
  AGENT_DECISION: "🤖", TIP_EXECUTED: "💸",
};

const fetcher = (url: string) => fetch(url).then(r => r.json());

function truncate(s: string, n = 6) {
  if (!s || s.length <= n * 2 + 3) return s;
  return `${s.slice(0, n)}...${s.slice(-n)}`;
}
function timeAgo(ts: string) {
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} style={{ position: "relative", width: 48, height: 26, background: "none", border: "none", padding: 0, cursor: "pointer" }}>
      <span style={{ display: "block", width: 48, height: 26, borderRadius: 999, background: on ? "#00ff88" : "#1e2d4a", transition: "background .2s" }} />
      <span style={{ position: "absolute", top: 3, left: on ? 25 : 3, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left .2s" }} />
    </button>
  );
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: "#0f1629", border: "1px solid #1e2d4a", borderRadius: 12, padding: "1.25rem" }}>
      <p style={{ color: "#64748b", fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>{label}</p>
      <p style={{ fontSize: 26, fontWeight: 700, color: "#00ff88", lineHeight: 1 }}>{value}</p>
      {sub && <p style={{ color: "#64748b", fontSize: 11, marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

function SwarmCard({ swarm, onJoin, exploding }: { swarm: Swarm; onJoin: (id: string) => void; exploding: boolean }) {
  const pct = swarm.target_amount_usd > 0 ? Math.min(100, (swarm.current_amount_usd / swarm.target_amount_usd) * 100) : 0;
  return (
    <motion.div
      animate={exploding ? { scale: [1, 1.06, 1], opacity: [1, 0.6, 1] } : {}}
      transition={{ duration: 0.6 }}
      style={{ background: "#0a0e1a", border: `1px solid ${exploding ? "#00ff88" : "#1e2d4a"}`, borderRadius: 10, padding: "1rem", boxShadow: exploding ? "0 0 24px rgba(0,255,136,.35)" : "none" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <div>
          <p style={{ fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>{swarm.goal_description}</p>
          <p style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{swarm.participant_count} fans · {swarm.trigger_event || swarm.creator_id}</p>
        </div>
        <span style={{ background: "#1e2d4a", color: "#00c9ff", fontSize: 10, padding: "2px 8px", borderRadius: 999, alignSelf: "flex-start" }}>{swarm.status}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
        <span style={{ color: "#64748b" }}>Progress</span>
        <span style={{ color: "#00ff88" }}>${swarm.current_amount_usd.toFixed(2)} / ${swarm.target_amount_usd.toFixed(2)}</span>
      </div>
      <div style={{ background: "#1e2d4a", borderRadius: 999, height: 5, overflow: "hidden", marginBottom: 10 }}>
        <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.8 }}
          style={{ height: "100%", borderRadius: 999, background: "linear-gradient(90deg,#00ff88,#00c9ff)" }} />
      </div>
      <button onClick={() => onJoin(swarm.swarm_id)}
        style={{ width: "100%", padding: "6px 0", borderRadius: 7, border: "none", background: "linear-gradient(90deg,#00ff88,#00c9ff)", color: "#0a0e1a", fontWeight: 700, fontSize: 12, cursor: "pointer" }}>
        Join Swarm ($5)
      </button>
    </motion.div>
  );
}

function FeedEntry({ event }: { event: FeedEvent }) {
  const color = FEED_COLORS[event.type] || "#64748b";
  const icon  = FEED_ICONS[event.type] || "⚡";
  return (
    <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .25 }}
      style={{ display: "flex", gap: 10, padding: "9px 0", borderBottom: "1px solid #1e2d4a" }}>
      <div style={{ width: 30, height: 30, borderRadius: 7, flexShrink: 0, background: `${color}22`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13 }}>{icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontSize: 12, color: "#e2e8f0", marginBottom: 2, lineHeight: 1.4 }}>{event.message}</p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, color }}>{event.agent || event.type}</span>
          {event.amount != null && <span style={{ fontSize: 11, color: "#00ff88", fontWeight: 600 }}>${event.amount.toFixed(2)} {event.token || "USDT"}</span>}
          <span style={{ fontSize: 11, color: "#475569", marginLeft: "auto" }}>{timeAgo(event.timestamp)}</span>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [agentOn,    setAgentOn]    = useState(true);
  const [maxPerVideo, setMaxPerVideo] = useState(5);
  const [token,      setToken]      = useState("USDT");
  const [triggers,   setTriggers]   = useState({ watch: true, chat: true, milestones: true, swarms: true });
  const [feedEvents, setFeedEvents] = useState<FeedEvent[]>([]);
  const [exploding,  setExploding]  = useState<Set<string>>(new Set());

  const { data: status }    = useSWR("/api/status",       fetcher, { refreshInterval: 5000 });
  const { data: metrics }   = useSWR("/api/metrics",      fetcher, { refreshInterval: 5000 });
  const { data: swarmData } = useSWR("/api/swarms",       fetcher, { refreshInterval: 5000 });
  const { data: txData }    = useSWR("/api/transactions", fetcher, { refreshInterval: 5000 });

  const wallet: WalletInfo     = status?.wallet || { balance: 0, address: "", token: "USDT" };
  const m: Metrics             = metrics || { today: { total_usd: 0, tip_count: 0 }, this_week: { total_usd: 0, tip_count: 0 }, top_creators: [], active_swarms_count: 0 };
  const swarms: Swarm[]        = Array.isArray(swarmData) ? swarmData : [];
  const txs: Transaction[]     = txData?.items || [];
  const largestTip             = txs.reduce((mx, t) => Math.max(mx, t.amount || 0), 0);
  const uniqueCreators         = new Set(txs.map(t => t.creator_id)).size;

  // WebSocket
  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/feed");
    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as FeedEvent;
        if (!ev.type || ev.type === "PONG") return;
        const id = `${ev.type}-${Date.now()}-${Math.random()}`;
        setFeedEvents(prev => [{ ...ev, id }, ...prev].slice(0, 50));
        // Swarm explosion
        if (ev.type === "AGENT_DECISION" && ev.metadata?.event === "SWARM_RELEASED") {
          const sid = ev.metadata.swarm_id as string;
          if (sid) {
            setExploding(s => new Set([...s, sid]));
            setTimeout(() => setExploding(s => { const n = new Set(s); n.delete(sid); return n; }), 1500);
          }
        }
      } catch { /* noop */ }
    };
    return () => ws.close();
  }, []);

  const callDemo = useCallback(async (scenario: string) => {
    await fetch(`/api/demo/${scenario}`, { method: "POST" });
  }, []);

  const joinSwarm = useCallback(async (swarmId: string) => {
    await fetch(`/api/swarms/${swarmId}/join`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: "viewer_001", pledged_amount: 5 }),
    });
  }, []);

  // Card styles
  const card = { background: "#0f1629", border: "1px solid #1e2d4a", borderRadius: 12, padding: "1.25rem" };

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "0 16px 80px" }}>

      {/* Header */}
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 0", borderBottom: "1px solid #1e2d4a", marginBottom: 20 }}>
        <div>
          <span style={{ fontSize: 26, fontWeight: 800, background: "linear-gradient(90deg,#00ff88,#00c9ff)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>TipMind</span>
          <span style={{ color: "#64748b", fontSize: 13, marginLeft: 10 }}>Your Autonomous Fan Agent</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <div style={{ textAlign: "right" }}>
            <p style={{ color: "#64748b", fontSize: 10, letterSpacing: ".1em" }}>WALLET</p>
            <p style={{ color: "#94a3b8", fontSize: 12, fontFamily: "monospace" }}>{truncate(wallet.address || "0x0000000000000000")}</p>
            <p style={{ color: "#00ff88", fontWeight: 700, fontSize: 15 }}>{(wallet.balance || 0).toFixed(4)} USDT</p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span className={agentOn ? "pulse-green" : ""} style={{ width: 8, height: 8, borderRadius: "50%", background: agentOn ? "#00ff88" : "#475569" }} />
              <span style={{ fontSize: 11, color: agentOn ? "#00ff88" : "#475569", fontWeight: 700, letterSpacing: ".1em" }}>{agentOn ? "ACTIVE" : "PAUSED"}</span>
            </div>
            <Toggle on={agentOn} onToggle={() => setAgentOn(v => !v)} />
          </div>
        </div>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 20 }}>

        {/* Settings Sidebar */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={card}>
            <h3 style={{ fontWeight: 600, fontSize: 13, color: "#e2e8f0", marginBottom: 16 }}>⚙️ Agent Settings</h3>

            {/* Slider */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 6 }}>
                <span style={{ color: "#94a3b8" }}>Max per video</span>
                <span style={{ color: "#00ff88", fontWeight: 700 }}>${maxPerVideo.toFixed(2)}</span>
              </div>
              <input type="range" min={0} max={10} step={0.25} value={maxPerVideo}
                onChange={e => setMaxPerVideo(parseFloat(e.target.value))}
                style={{ width: "100%", accentColor: "#00ff88" }} />
            </div>

            {/* Token */}
            <div style={{ marginBottom: 16 }}>
              <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>Token</p>
              <div style={{ display: "flex", gap: 6 }}>
                {["USDT","XAUT","BTC"].map(t => (
                  <button key={t} onClick={() => setToken(t)} style={{ flex: 1, padding: "5px 0", borderRadius: 6, border: `1px solid ${token===t?"#00ff88":"#1e2d4a"}`, background: token===t?"rgba(0,255,136,.1)":"transparent", color: token===t?"#00ff88":"#64748b", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>{t}</button>
                ))}
              </div>
            </div>

            {/* Triggers */}
            <div>
              <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 10 }}>Triggers</p>
              {([["watch","👁 Watch Time"],["chat","💬 Chat Emotion"],["milestones","🏆 Milestones"],["swarms","🌊 Swarms"]] as [keyof typeof triggers, string][]).map(([k, label]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <span style={{ fontSize: 13, color: "#e2e8f0" }}>{label}</span>
                  <Toggle on={triggers[k]} onToggle={() => setTriggers(t => ({ ...t, [k]: !t[k] }))} />
                </div>
              ))}
            </div>
          </div>

          {/* Top Creators */}
          <div style={card}>
            <h3 style={{ fontWeight: 600, fontSize: 13, color: "#e2e8f0", marginBottom: 12 }}>🏅 Top Creators</h3>
            {m.top_creators.length === 0
              ? <p style={{ color: "#475569", fontSize: 12 }}>No tips yet</p>
              : m.top_creators.slice(0, 5).map((c, i) => (
                <div key={c.creator_id} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ color: "#475569", fontSize: 11, width: 16 }}>#{i+1}</span>
                  <span style={{ color: "#94a3b8", fontSize: 12, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{truncate(c.creator_id, 8)}</span>
                  <span style={{ color: "#00ff88", fontSize: 12, fontWeight: 600 }}>${c.total_usd}</span>
                </div>
              ))
            }
          </div>
        </div>

        {/* Main Content */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

          {/* Metrics */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
            <MetricCard label="Tipped Today"  value={`$${m.today.total_usd.toFixed(2)}`}   sub="USDT" />
            <MetricCard label="Tips Sent"     value={String(m.today.tip_count)}             sub="today" />
            <MetricCard label="Creators"      value={String(uniqueCreators)}                sub="supported" />
            <MetricCard label="Largest Tip"   value={`$${largestTip.toFixed(2)}`}          sub="single tip" />
          </div>

          {/* Swarms + Live Feed */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

            <div style={card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ fontWeight: 600, fontSize: 13, color: "#e2e8f0" }}>🌊 Active Swarms</h3>
                <span style={{ background: "#1e2d4a", color: "#00c9ff", fontSize: 10, padding: "2px 8px", borderRadius: 999 }}>{swarms.length} active</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 300, overflowY: "auto" }}>
                <AnimatePresence>
                  {swarms.length === 0
                    ? <p style={{ color: "#475569", fontSize: 12 }}>No active swarms. Use demo to seed one!</p>
                    : swarms.map(s => <SwarmCard key={s.swarm_id} swarm={s} onJoin={joinSwarm} exploding={exploding.has(s.swarm_id)} />)
                  }
                </AnimatePresence>
              </div>
            </div>

            <div style={card}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ fontWeight: 600, fontSize: 13, color: "#e2e8f0" }}>⚡ Live Feed</h3>
                <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#00ff88" }}>
                  <span className="pulse-green" style={{ width: 6, height: 6, borderRadius: "50%", background: "#00ff88" }} /> LIVE
                </span>
              </div>
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                <AnimatePresence>
                  {feedEvents.length === 0
                    ? <p style={{ color: "#475569", fontSize: 12 }}>Waiting for events…</p>
                    : feedEvents.map(ev => <FeedEntry key={ev.id} event={ev} />)
                  }
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* Transaction Table */}
          <div style={card}>
            <h3 style={{ fontWeight: 600, fontSize: 13, color: "#e2e8f0", marginBottom: 12 }}>📋 Recent Transactions</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "#64748b" }}>
                    {["Time","Creator","Amount","Token","Trigger","Tx Hash","Status"].map(h => (
                      <th key={h} style={{ padding: "6px 10px", borderBottom: "1px solid #1e2d4a", textAlign: "left", fontWeight: 500, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {txs.length === 0
                    ? <tr><td colSpan={7} style={{ padding: "16px 10px", color: "#475569", textAlign: "center" }}>No transactions yet</td></tr>
                    : txs.slice(0, 20).map(tx => (
                      <tr key={tx.id} style={{ borderBottom: "1px solid #1e2d4a" }}>
                        <td style={{ padding: "7px 10px", color: "#64748b" }}>{timeAgo(tx.created_at)}</td>
                        <td style={{ padding: "7px 10px", color: "#94a3b8", fontFamily: "monospace" }}>{truncate(tx.creator_id)}</td>
                        <td style={{ padding: "7px 10px", color: "#00ff88", fontWeight: 600 }}>${tx.amount?.toFixed(4)}</td>
                        <td style={{ padding: "7px 10px", color: "#00c9ff" }}>{tx.token}</td>
                        <td style={{ padding: "7px 10px", color: "#94a3b8", fontSize: 11 }}>{tx.trigger_type}</td>
                        <td style={{ padding: "7px 10px" }}>
                          {tx.tx_hash
                            ? <a href={`https://etherscan.io/tx/${tx.tx_hash}`} target="_blank" rel="noreferrer" style={{ color: "#00c9ff", fontFamily: "monospace", fontSize: 11 }}>{truncate(tx.tx_hash, 6)}</a>
                            : <span style={{ color: "#475569" }}>—</span>}
                        </td>
                        <td style={{ padding: "7px 10px" }}>
                          <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 999, background: tx.status==="confirmed"?"rgba(0,255,136,.1)":"rgba(100,116,139,.1)", color: tx.status==="confirmed"?"#00ff88":"#64748b" }}>{tx.status}</span>
                        </td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {/* Demo Control Bar (dev only) */}
      {process.env.NODE_ENV === "development" && (
        <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: "#0f1629", borderTop: "1px solid #1e2d4a", padding: "10px 24px", display: "flex", alignItems: "center", gap: 10, zIndex: 50 }}>
          <span style={{ color: "#64748b", fontSize: 11, fontWeight: 700, marginRight: 8 }}>🎮 DEMO</span>
          {([
            { label: "▶ Simulate Watch",  scenario: "watch",     color: "#00c9ff" },
            { label: "🔥 Inject Hype",    scenario: "hype",      color: "#fbbf24" },
            { label: "🏆 Fire Milestone", scenario: "milestone", color: "#a855f7" },
            { label: "🌊 Release Swarm",  scenario: "swarm",     color: "#ef4444" },
          ] as { label: string; scenario: string; color: string }[]).map(({ label, scenario, color }) => (
            <button key={scenario} onClick={() => callDemo(scenario)}
              style={{ padding: "7px 14px", borderRadius: 8, border: `1px solid ${color}`, background: `${color}18`, color, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              {label}
            </button>
          ))}
          <span style={{ marginLeft: "auto", color: "#475569", fontSize: 10 }}>ws://localhost:8000/ws/feed</span>
        </div>
      )}
    </div>
  );
}
