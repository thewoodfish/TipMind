import Link from "next/link";

export default function Home() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen gap-8 p-8">
      <div className="text-center">
        <h1 className="text-5xl font-bold text-yellow-400 mb-4">💡 TipMind</h1>
        <p className="text-xl text-gray-400 max-w-xl">
          AI-powered crypto tipping for video creators. Our swarm of agents
          analyzes emotion, milestones, and content quality to automatically
          reward the best creators.
        </p>
      </div>

      <div className="flex gap-4">
        <Link
          href="/dashboard"
          className="px-6 py-3 bg-yellow-400 text-gray-950 font-semibold rounded-lg hover:bg-yellow-300 transition"
        >
          Open Dashboard
        </Link>
        <Link
          href="/analyze"
          className="px-6 py-3 border border-yellow-400 text-yellow-400 font-semibold rounded-lg hover:bg-yellow-400/10 transition"
        >
          Analyze Video
        </Link>
      </div>

      <div className="grid grid-cols-3 gap-6 mt-8 max-w-3xl w-full">
        {[
          {
            icon: "🧠",
            title: "Emotion Agent",
            desc: "Analyzes video sentiment and emotional resonance",
          },
          {
            icon: "🏆",
            title: "Milestone Agent",
            desc: "Detects creator milestones worthy of celebration",
          },
          {
            icon: "💸",
            title: "Tip Agent",
            desc: "Makes the final tip decision and sends USDT via WDK",
          },
        ].map((card) => (
          <div
            key={card.title}
            className="p-6 bg-gray-900 rounded-xl border border-gray-800"
          >
            <div className="text-3xl mb-3">{card.icon}</div>
            <h3 className="font-semibold text-white mb-1">{card.title}</h3>
            <p className="text-sm text-gray-400">{card.desc}</p>
          </div>
        ))}
      </div>
    </main>
  );
}
