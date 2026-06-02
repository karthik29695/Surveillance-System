import { useEffect, useState, useRef } from "react";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

const LEVEL_STYLE = {
  critical:  { bg:"bg-red-950/60 border-red-700",   badge:"bg-red-700 text-white",     bar:"bg-red-500",    text:"text-red-300" },
  suspicious:{ bg:"bg-orange-950/60 border-orange-700", badge:"bg-orange-700 text-white", bar:"bg-orange-500", text:"text-orange-300" },
  elevated:  { bg:"bg-yellow-950/60 border-yellow-700", badge:"bg-yellow-700 text-black", bar:"bg-yellow-400", text:"text-yellow-300" },
  normal:    { bg:"bg-gray-800 border-gray-700",    badge:"bg-gray-700 text-gray-300",  bar:"bg-gray-500",   text:"text-gray-400" },
};
const ls = (l) => LEVEL_STYLE[l] || LEVEL_STYLE.normal;

const TREND_STYLE = {
  escalating: { icon:"▲", cls:"text-red-400" },
  cooling:    { icon:"▼", cls:"text-green-400" },
  stable:     { icon:"■", cls:"text-gray-400" },
};

const CONTRIBUTOR_ICONS = {
  restricted_zone:"🚫", monitoring_zone:"👁", loitering:"⏱",
  re_entry:"↩️", erratic_movement:"↗️", crowd:"👥", decay:"📉",
};

export default function RiskIntelligencePanel({ feedId }) {
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    if (!feedId) return;
    const load = async () => {
      try {
        const res = await api.get(`/video/${feedId}/risk-profiles`);
        setProfiles(res.data);
        if (res.data.length > 0 && !selected) setSelected(res.data[0].track_id);
      } catch {}
      setLoading(false);
    };
    load();
  }, [feedId]);

  const profile = profiles.find(p => p.track_id === selected);

  if (loading) return <div className="text-gray-500 text-sm p-4">Loading risk profiles...</div>;
  if (!profiles.length) return (
    <div className="text-center py-8 text-gray-600 text-sm">
      No suspicious tracks detected in this feed.
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Track selector */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Suspicious Tracks ({profiles.length})
        </p>
        <div className="space-y-1.5">
          {profiles.map(p => {
            const s = ls(p.risk_level);
            const t = TREND_STYLE[p.trend] || TREND_STYLE.stable;
            return (
              <button key={p.track_id} onClick={() => setSelected(p.track_id)}
                className={`w-full text-left px-3 py-2 rounded-lg border transition
                  ${selected===p.track_id ? s.bg : "bg-gray-800 border-gray-700 hover:border-gray-500"}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${s.badge}`}>
                      {p.risk_level.toUpperCase()}
                    </span>
                    <span className="text-sm font-medium">Track #{p.track_id}</span>
                    <span className={`text-xs ${t.cls}`}>{t.icon}</span>
                  </div>
                  <span className={`text-lg font-bold ${s.text}`}>{p.risk_score}</span>
                </div>
                {p.dominant_signals?.length > 0 && (
                  <p className="text-xs text-gray-500 mt-0.5 truncate">
                    {p.dominant_signals.slice(0,2).join(" · ")}
                  </p>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Detail panel */}
      {profile && <RiskDetail profile={profile} />}
    </div>
  );
}

function RiskDetail({ profile }) {
  const s = ls(profile.risk_level);
  const t = TREND_STYLE[profile.trend] || TREND_STYLE.stable;

  return (
    <div className={`rounded-xl border p-4 space-y-4 ${s.bg}`}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded font-bold ${s.badge}`}>
              {profile.risk_level.toUpperCase()}
            </span>
            <span className={`text-xs ${t.cls} font-bold`}>{t.icon} {profile.trend}</span>
          </div>
          <h3 className="text-lg font-bold mt-1">Track #{profile.track_id}</h3>
          {profile.summary && (
            <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{profile.summary}</p>
          )}
        </div>
        <div className="text-right flex-shrink-0">
          <p className={`text-3xl font-bold ${s.text}`}>{profile.risk_score}</p>
          <p className="text-xs text-gray-500">/ 100</p>
        </div>
      </div>

      {/* Score bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Risk Score</span>
          <span>Peak: {profile.risk_score}</span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all ${s.bar}`}
            style={{ width: `${profile.risk_score}%` }} />
        </div>
        <div className="flex justify-between text-xs text-gray-600 mt-0.5">
          <span>NORMAL</span><span>ELEVATED</span><span>SUSPICIOUS</span><span>CRITICAL</span>
        </div>
        {/* Threshold markers */}
        <div className="relative h-1 -mt-0.5">
          {[25,50,75].map(th => (
            <div key={th} className="absolute top-0 w-px h-2 bg-gray-600"
              style={{ left:`${th}%` }} />
          ))}
        </div>
      </div>

      {/* Contributors */}
      {profile.top_contributors?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Risk Contributors
          </p>
          <div className="space-y-1.5">
            {profile.top_contributors.map(([key, val], i) => {
              const isDecay = key === "decay";
              const icon = CONTRIBUTOR_ICONS[key] || "•";
              const label = key.replace(/_/g," ").replace(/\w/g,c=>c.toUpperCase());
              return (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="w-5 text-center">{icon}</span>
                  <span className="flex-1 text-gray-300">{label}</span>
                  <span className={`font-bold tabular-nums ${isDecay?"text-green-400":"text-red-300"}`}>
                    {isDecay?"−":"+"}
                    {Math.abs(val).toFixed(1)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Risk Timeline Chart */}
      {profile.timeline?.length > 1 && (
        <RiskTimeline timeline={profile.timeline} currentLevel={profile.risk_level} />
      )}

      {/* Escalation history */}
      {profile.escalation_history?.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Escalation History
          </p>
          <div className="space-y-1.5">
            {profile.escalation_history.map((e, i) => {
              const mins = Math.floor((e.video_ts||0)/60);
              const secs = Math.floor((e.video_ts||0)%60);
              const tsStr = `${mins}:${secs.toString().padStart(2,"0")}`;
              const up = (e.to||e.to_level||"") > (e.from||e.from_level||"");
              return (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <span className="text-gray-500 w-10 flex-shrink-0">{tsStr}</span>
                  <span className={up?"text-red-400":"text-green-400"}>{up?"↑":"↓"}</span>
                  <span className="text-gray-400 leading-relaxed">{e.trigger}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Operational metadata */}
      <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-700/50">
        {profile.current_zone && (
          <Meta label="Current Zone" value={profile.current_zone} />
        )}
        {profile.zone_dwell_secs > 0 && (
          <Meta label="Zone Dwell" value={`${profile.zone_dwell_secs}s`} />
        )}
        {profile.reentry_count > 0 && (
          <Meta label="Re-entries" value={profile.reentry_count} accent />
        )}
        {profile.incident_count > 0 && (
          <Meta label="Incidents" value={profile.incident_count} accent />
        )}
      </div>
    </div>
  );
}

function RiskTimeline({ timeline, currentLevel }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !timeline.length) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    const PAD = { l:8, r:8, t:8, b:16 };
    const chartW = W - PAD.l - PAD.r;
    const chartH = H - PAD.t - PAD.b;

    const maxScore = 100;
    const minTs = timeline[0].ts;
    const maxTs = timeline[timeline.length-1].ts;
    const tsRange = Math.max(maxTs - minTs, 1);

    const toX = ts => PAD.l + ((ts - minTs) / tsRange) * chartW;
    const toY = score => PAD.t + chartH - (score / maxScore) * chartH;

    // Threshold bands
    const bands = [
      { y: toY(75), color: "rgba(239,68,68,0.08)",   label:"CRIT" },
      { y: toY(50), color: "rgba(249,115,22,0.08)",  label:"SUSP" },
      { y: toY(25), color: "rgba(234,179,8,0.08)",   label:"ELEV" },
    ];
    bands.forEach((b, i) => {
      const nextY = i === 0 ? PAD.t : bands[i-1].y;
      ctx.fillStyle = b.color;
      ctx.fillRect(PAD.l, b.y, chartW, nextY - b.y);
      // Threshold line
      ctx.strokeStyle = "rgba(255,255,255,0.08)";
      ctx.setLineDash([3,3]);
      ctx.beginPath();
      ctx.moveTo(PAD.l, b.y); ctx.lineTo(PAD.l+chartW, b.y);
      ctx.stroke();
      ctx.setLineDash([]);
    });

    // Score line
    const LEVEL_COLORS = {
      normal:"#4b5563", elevated:"#eab308", suspicious:"#f97316", critical:"#ef4444"
    };

    ctx.lineWidth = 2;
    ctx.beginPath();
    timeline.forEach((p, i) => {
      const x = toX(p.ts), y = toY(p.score);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = LEVEL_COLORS[currentLevel] || "#ef4444";
    ctx.stroke();

    // Area fill
    ctx.beginPath();
    timeline.forEach((p, i) => {
      const x = toX(p.ts), y = toY(p.score);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(toX(timeline[timeline.length-1].ts), PAD.t+chartH);
    ctx.lineTo(toX(timeline[0].ts), PAD.t+chartH);
    ctx.closePath();
    ctx.fillStyle = (LEVEL_COLORS[currentLevel]||"#ef4444") + "22";
    ctx.fill();

    // Event markers
    timeline.forEach(p => {
      if (!p.marker) return;
      const x = toX(p.ts), y = toY(p.score);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI*2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
    });

    // Current score dot
    const last = timeline[timeline.length-1];
    ctx.beginPath();
    ctx.arc(toX(last.ts), toY(last.score), 5, 0, Math.PI*2);
    ctx.fillStyle = LEVEL_COLORS[currentLevel] || "#ef4444";
    ctx.fill();

  }, [timeline, currentLevel]);

  return (
    <div>
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Risk Timeline
      </p>
      <canvas ref={canvasRef} width={280} height={80}
        className="w-full rounded bg-gray-900/60 border border-gray-700/50" />
      <div className="flex justify-between text-xs text-gray-600 mt-1">
        <span>{timeline[0]?.ts?.toFixed(1)}s</span>
        <span>{timeline[timeline.length-1]?.ts?.toFixed(1)}s</span>
      </div>
    </div>
  );
}

function Meta({ label, value, accent }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-sm font-semibold ${accent ? "text-orange-400" : "text-gray-300"}`}>
        {value}
      </p>
    </div>
  );
}
