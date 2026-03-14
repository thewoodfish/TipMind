"use client";
import { useEffect, useState, useRef } from "react";

interface TipEvent {
  id: number;
  video_id: string;
  creator_address: string;
  amount: number;
  token: string;
  tx_hash: string | null;
  reason: string | null;
  emotion_score: number | null;
  milestone_triggered: boolean;
  status: string;
  created_at: string;
}

interface LiveEvent {
  event: string;
  data: Record<string, unknown>;
}

export default function Dashboard() {
  const [tips, setTips] = useState<TipEvent[]>([]);
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetch("/api/v1/tips?limit=20")
      .then((r) => r.json())
      .then(setTips)
      .catch(console.error);
  }, []);

  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws`);
    wsRef.current = ws;
    setWsStatus("connecting");

    ws.onopen = () => setWsStatus("connected");
    ws.onclose = () => setWsStatus("disconnected");
    ws.onmessage = (e) => {
      const event: LiveEvent = JSON.parse(e.data);
      setLiveEvents((prev) => [event, ...prev].slice(0, 20));
      if (event.event === "tip.sent") {
        fetch("/api/v1/tips?limit=20")
          .then((r) => r.json())
          .then(setTips)
          .catch(console.error);
      }
    };

    const ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 30_000);
    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, []);

  const statusColor = { connecting: "yellow", connected: "green", disconnected: "red" }[wsStatus];

  return (
    <div className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold text-yellow-400">💡 TipMind Dashboard</h1>
          <span className={`text-sm text-${statusColor}-400 flex items-center gap-2`}>
            <span className={`w-2 h-2 rounded-full bg-${statusColor}-400`} />
            WS {wsStatus}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-8">
          {/* Recent Tips */}
          <div>
            <h2 className="text-xl font-semibold mb-4 text-gray-200">Recent Tips</h2>
            <div className="space-y-3">
              {tips.length === 0 && (
                <p className="text-gray-500 text-sm">No tips yet. Analyze a video to get started.</p>
              )}
              {tips.map((tip) => (
                <div key={tip.id} className="p-4 bg-gray-900 rounded-lg border border-gray-800">
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-sm font-mono text-gray-400 truncate w-48">{tip.video_id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      tip.status === "confirmed" ? "bg-green-900 text-green-300" :
                      tip.status === "failed" ? "bg-red-900 text-red-300" :
                      "bg-gray-700 text-gray-300"
                    }`}>{tip.status}</span>
                  </div>
                  <div className="text-yellow-400 font-semibold">
                    {tip.amount} {tip.token}
                    {tip.milestone_triggered && <span className="ml-2 text-xs text-purple-400">🏆 milestone</span>}
                  </div>
                  <p className="text-xs text-gray-400 mt-1">{tip.reason}</p>
                  {tip.emotion_score != null && (
                    <div className="mt-2 text-xs text-gray-500">
                      Emotion score: {(tip.emotion_score * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Live Events */}
          <div>
            <h2 className="text-xl font-semibold mb-4 text-gray-200">Live Events</h2>
            <div className="space-y-2">
              {liveEvents.length === 0 && (
                <p className="text-gray-500 text-sm">Waiting for events...</p>
              )}
              {liveEvents.map((evt, i) => (
                <div key={i} className="p-3 bg-gray-900 rounded-lg border border-gray-800 text-sm font-mono">
                  <span className="text-yellow-400">{evt.event}</span>
                  <span className="text-gray-400 ml-2">{JSON.stringify(evt.data)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
