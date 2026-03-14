"use client";
import { useState } from "react";

interface AnalyzeResult {
  video_id: string;
  tip_decision: { should_tip: boolean; amount: number; reason: string; confidence: number };
  emotion_result: { score: number; sentiment: string; key_emotions: string[]; reasoning: string };
  milestone_result: { milestone_triggered: boolean; new_milestones: unknown[]; total_bonus: number; reasoning: string };
  status: string;
  tx_hash: string | null;
}

export default function AnalyzePage() {
  const [form, setForm] = useState({
    id: crypto.randomUUID(),
    title: "",
    creator_address: "",
    url: "",
    description: "",
    view_count: 0,
    like_count: 0,
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch("/api/v1/videos/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen p-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold text-yellow-400 mb-8">Analyze Video</h1>

        <form onSubmit={handleSubmit} className="space-y-4 bg-gray-900 p-6 rounded-xl border border-gray-800">
          {[
            { label: "Video Title", key: "title", type: "text", required: true },
            { label: "Creator Wallet Address", key: "creator_address", type: "text", required: true },
            { label: "Video URL", key: "url", type: "url", required: true },
            { label: "Description", key: "description", type: "text", required: false },
            { label: "View Count", key: "view_count", type: "number", required: false },
            { label: "Like Count", key: "like_count", type: "number", required: false },
          ].map(({ label, key, type, required }) => (
            <div key={key}>
              <label className="block text-sm text-gray-400 mb-1">{label}</label>
              <input
                type={type}
                required={required}
                value={form[key as keyof typeof form]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: type === "number" ? Number(e.target.value) : e.target.value }))}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:border-yellow-400"
              />
            </div>
          ))}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-yellow-400 text-gray-950 font-semibold rounded-lg hover:bg-yellow-300 disabled:opacity-50 transition"
          >
            {loading ? "Analyzing with AI Swarm..." : "Analyze & Tip"}
          </button>
        </form>

        {error && (
          <div className="mt-4 p-4 bg-red-900/50 border border-red-700 rounded-lg text-red-300 text-sm">
            {error}
          </div>
        )}

        {result && (
          <div className="mt-6 space-y-4">
            <div className={`p-4 rounded-xl border ${result.tip_decision.should_tip ? "bg-green-900/30 border-green-700" : "bg-gray-900 border-gray-800"}`}>
              <h3 className="font-semibold text-lg mb-2">
                {result.tip_decision.should_tip ? "✅ Tip Sent!" : "⏭️ No Tip"}
              </h3>
              {result.tip_decision.should_tip && (
                <p className="text-2xl font-bold text-yellow-400 mb-1">{result.tip_decision.amount} USDT</p>
              )}
              <p className="text-sm text-gray-300">{result.tip_decision.reason}</p>
              {result.tx_hash && (
                <p className="text-xs font-mono text-gray-400 mt-2">tx: {result.tx_hash}</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-gray-900 rounded-lg border border-gray-800">
                <h4 className="font-medium text-blue-400 mb-2">🧠 Emotion</h4>
                <p className="text-2xl font-bold">{(result.emotion_result.score * 100).toFixed(0)}%</p>
                <p className="text-sm text-gray-400">{result.emotion_result.sentiment}</p>
                <p className="text-xs text-gray-500 mt-1">{result.emotion_result.key_emotions?.join(", ")}</p>
              </div>
              <div className="p-4 bg-gray-900 rounded-lg border border-gray-800">
                <h4 className="font-medium text-purple-400 mb-2">🏆 Milestones</h4>
                <p className="text-2xl font-bold">{result.milestone_result.milestone_triggered ? "Yes" : "No"}</p>
                {result.milestone_result.total_bonus > 0 && (
                  <p className="text-sm text-yellow-400">+{result.milestone_result.total_bonus} USDT bonus</p>
                )}
                <p className="text-xs text-gray-500 mt-1">{result.milestone_result.reasoning}</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
