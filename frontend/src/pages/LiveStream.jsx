import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

// ── Constants ──────────────────────────────────────────────────────────────
const RISK_STYLE = {
  critical:  { badge:"bg-red-700 text-white",    bar:"#ef4444", dot:"bg-red-400",    label:"CRITICAL",  ring:"border-red-700" },
  suspicious:{ badge:"bg-orange-700 text-white",  bar:"#f97316", dot:"bg-orange-400", label:"SUSPICIOUS", ring:"border-orange-700" },
  elevated:  { badge:"bg-yellow-700 text-black",  bar:"#eab308", dot:"bg-yellow-400", label:"ELEVATED",   ring:"border-yellow-700" },
  normal:    { badge:"bg-gray-700 text-gray-300", bar:"#4b5563", dot:"bg-gray-500",   label:"NORMAL",     ring:"border-gray-700" },
};
const rs = l => RISK_STYLE[l] || RISK_STYLE.normal;

const INCIDENT_META = {
  zone_breach:        { icon:"🚨", label:"Zone Breach",    color:"text-red-400",    sev:"critical" },
  loitering_detected: { icon:"⚠️", label:"Loitering",      color:"text-orange-400", sev:"high" },
  suspicious_behavior:{ icon:"🎯", label:"Suspicious",     color:"text-red-300",    sev:"critical" },
  crowd_detected:     { icon:"👥", label:"Crowd",          color:"text-purple-400", sev:"medium" },
  object_left_behind: { icon:"🎒", label:"Object Left",    color:"text-yellow-400", sev:"high" },
};
const im = t => INCIDENT_META[t] || { icon:"📌", label:t, color:"text-gray-400", sev:"low" };

const TREND = { escalating:"▲", cooling:"▼", stable:"■" };
const TREND_COLOR = { escalating:"text-red-400", cooling:"text-green-400", stable:"text-gray-400" };

// Incident lifecycle states
const INC_STATES = ["ACTIVE","ACKNOWLEDGED","INVESTIGATING","RESOLVED"];
const INC_STATE_COLOR = {
  ACTIVE:"bg-red-800 text-red-200", ACKNOWLEDGED:"bg-yellow-800 text-yellow-200",
  INVESTIGATING:"bg-blue-800 text-blue-200", RESOLVED:"bg-green-900 text-green-300",
};

export default function LiveStream() {
  const [feeds, setFeeds]         = useState([]);
  const [selectedFeed, setFeed]   = useState("");
  const [source, setSource]       = useState("0");
  const [wsState, setWsState]     = useState("idle");
  const [statsData, setStats]     = useState(null);
  const [riskProfiles, setProfiles]= useState([]);
  const [incidents, setIncidents] = useState([]);   // {id, meta, state, ts}
  const [sidebarTab, setSidebarTab]= useState("risks");
  const [showProfiler, setShowProfiler] = useState(false);
  const wsRef    = useRef(null);
  const imgRef   = useRef(null);
  const frameRef = useRef(0);
  const incIdRef = useRef(0);

  useEffect(() => {
    api.get("/video/").then(r => setFeeds(r.data.filter(f=>f.status==="completed"))).catch(()=>{});
  }, []);

  const connect = useCallback(() => {
    if (!selectedFeed) return;
    setWsState("connecting");
    const ws = new WebSocket(`ws://localhost:8000/api/v1/stream/ws/${selectedFeed}`);
    ws.onopen = () => {
      ws.send(JSON.stringify({ source: source === "0" ? 0 : source }));
      setWsState("live");
    };
    ws.onmessage = e => {
      const d = JSON.parse(e.data);
      if (d.error) { setWsState("error"); return; }

      // Frame update — direct img src assignment (no state re-render)
      if (d.frame && imgRef.current) {
        imgRef.current.src = `data:image/jpeg;base64,${d.frame}`;
      }
      frameRef.current = d.frame_number;

      // Stats update (arrives ~1/sec)
      if (d.track_count !== undefined) {
        setStats(d);
        if (d.risk_profiles) setProfiles(d.risk_profiles.sort((a,b)=>b.score-a.score));
      }

      // New incidents
      if (d.incidents?.length) {
        setIncidents(prev => {
          const newIncs = d.incidents.map(inc => ({
            id: ++incIdRef.current,
            meta: inc,
            state: "ACTIVE",
            ts: new Date().toLocaleTimeString(),
          }));
          return [...newIncs, ...prev].slice(0, 30);
        });
      }
    };
    ws.onerror = () => setWsState("error");
    ws.onclose = () => { setWsState("idle"); setStats(null); };
    wsRef.current = ws;
  }, [selectedFeed, source]);

  const disconnect = useCallback(() => {
    wsRef.current?.close(); wsRef.current = null;
    setWsState("idle"); setStats(null); setProfiles([]);
  }, []);

  const advanceIncidentState = (id) => {
    setIncidents(prev => prev.map(inc => {
      if (inc.id !== id) return inc;
      const idx = INC_STATES.indexOf(inc.state);
      return { ...inc, state: INC_STATES[Math.min(idx+1, INC_STATES.length-1)] };
    }));
  };
  const resolveIncident = (id) => {
    setIncidents(prev => prev.map(inc =>
      inc.id === id ? {...inc, state:"RESOLVED"} : inc
    ));
  };

  const wsColor = {idle:"text-gray-500",connecting:"text-yellow-400",live:"text-green-400",error:"text-red-400"};
  const wsLabel = {idle:"Offline",connecting:"Connecting…",live:"● LIVE",error:"Connection Error"};

  const activeIncidents   = incidents.filter(i => i.state !== "RESOLVED");
  const criticalIncidents = activeIncidents.filter(i => ["critical","high"].includes(i.meta?.severity));

  return (
    <div className="p-5 space-y-4 max-w-screen-2xl">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Live Stream Intelligence</h1>
          <p className={`text-sm font-medium ${wsColor[wsState]}`}>{wsLabel[wsState]}</p>
        </div>
        <div className="flex gap-2 items-center flex-wrap">
          <select value={selectedFeed} onChange={e=>setFeed(e.target.value)}
            className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm">
            <option value="">Select feed for zones…</option>
            {feeds.map(f=><option key={f.id} value={f.id}>{f.name} (#{f.id})</option>)}
          </select>
          <input value={source} onChange={e=>setSource(e.target.value)}
            placeholder="0 = webcam | rtsp://..."
            className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm w-52"/>
          {wsState !== "live" ? (
            <button onClick={connect} disabled={!selectedFeed}
              className="bg-green-700 hover:bg-green-600 disabled:opacity-40 px-4 py-2 rounded text-sm font-medium">
              ▶ Start
            </button>
          ) : (
            <button onClick={disconnect}
              className="bg-red-700 hover:bg-red-600 px-4 py-2 rounded text-sm font-medium">
              ■ Stop
            </button>
          )}
          <button onClick={()=>setShowProfiler(v=>!v)}
            className={`px-3 py-2 rounded text-xs font-medium border transition
              ${showProfiler?"bg-blue-900 border-blue-700":"bg-gray-800 border-gray-700"}`}>
            🔧 Profiler
          </button>
        </div>
      </div>

      {/* KPI strip */}
      {statsData && (
        <div className="grid grid-cols-5 gap-3">
          <KPI label="Live Tracks"     value={statsData.track_count||0} />
          <KPI label="Peak Occupancy"  value={statsData.peak_occupancy||0} />
          <KPI label="Active Incidents" value={activeIncidents.length}
            accent={activeIncidents.length>0?"red":"none"} />
          <KPI label="Critical"        value={criticalIncidents.length}
            accent={criticalIncidents.length>0?"orange":"none"} />
          <KPI label="Uptime"          value={fmtUptime(statsData.uptime_seconds||0)} />
        </div>
      )}

      {/* Profiler panel */}
      {showProfiler && statsData?.profile_report && (
        <ProfilerPanel report={statsData.profile_report} />
      )}

      <div className="grid grid-cols-3 gap-5">
        {/* Live feed */}
        <div className="col-span-2 space-y-3">
          <div className="relative bg-black rounded-xl overflow-hidden aspect-video">
            <img ref={imgRef} alt="live" className="w-full h-full object-contain"
              style={{display: wsState==="live"?"block":"none"}} />
            {wsState !== "live" && (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-600 gap-3">
                <span className="text-5xl">📹</span>
                <p className="text-sm">Select a feed and source, then Start</p>
                {!selectedFeed && <p className="text-xs text-yellow-500">Select a feed to load its zones</p>}
              </div>
            )}
            {wsState === "connecting" && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/70">
                <div className="text-center"><div className="animate-spin text-4xl mb-2">⟳</div>
                  <p className="text-sm text-gray-300">Connecting…</p></div>
              </div>
            )}
            {wsState === "live" && (
              <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-black/60 px-2 py-1 rounded">
                <span className="animate-pulse w-2 h-2 rounded-full bg-red-500"/>
                <span className="text-xs font-bold text-white">LIVE</span>
              </div>
            )}
          </div>

          {/* Active incident management */}
          {activeIncidents.length > 0 && (
            <div className="bg-gray-800 rounded-lg p-3">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                Active Incidents ({activeIncidents.length})
              </p>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {activeIncidents.slice(0,8).map(inc => {
                  const m = im(inc.meta?.event_type||"");
                  return (
                    <div key={inc.id} className="flex items-center gap-2 text-sm">
                      <span>{m.icon}</span>
                      <span className={`font-medium flex-1 ${m.color}`}>{m.label}</span>
                      {inc.meta?.zone && <span className="text-gray-500 text-xs">{inc.meta.zone}</span>}
                      {inc.meta?.track_id && <span className="text-gray-600 text-xs">#{inc.meta.track_id}</span>}
                      <span className="text-gray-600 text-xs">{inc.ts}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${INC_STATE_COLOR[inc.state]}`}>
                        {inc.state}
                      </span>
                      {inc.state !== "RESOLVED" && (
                        <button onClick={()=>advanceIncidentState(inc.id)}
                          className="text-xs bg-gray-700 hover:bg-gray-600 px-2 py-0.5 rounded">
                          {inc.state==="ACTIVE"?"ACK":inc.state==="ACKNOWLEDGED"?"INVEST":"RESOLVE"}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-3">
          {/* Tab switcher */}
          <div className="flex bg-gray-800 rounded-lg p-1 border border-gray-700">
            {[["risks","🎯 Risk Profiles"],["stats","📊 Stats"]].map(([tab,label])=>(
              <button key={tab} onClick={()=>setSidebarTab(tab)}
                className={`flex-1 py-1 rounded text-xs font-medium transition
                  ${sidebarTab===tab?"bg-green-700 text-white":"text-gray-400 hover:text-white"}`}>
                {label}
              </button>
            ))}
          </div>

          {sidebarTab === "risks" && (
            <RiskSidebar profiles={riskProfiles} active={wsState==="live"} />
          )}
          {sidebarTab === "stats" && (
            <StatsSidebar statsData={statsData} active={wsState==="live"} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Risk Profiles Sidebar ─────────────────────────────────────────────────
function RiskSidebar({ profiles, active }) {
  if (!active) return <p className="text-gray-600 text-sm py-4 text-center">Stream not active</p>;
  if (!profiles.length) return <p className="text-gray-600 text-sm py-4 text-center">No elevated tracks</p>;
  return (
    <div className="space-y-2 max-h-[540px] overflow-y-auto pr-1">
      {profiles.map(p => {
        const s = rs(p.risk_level);
        return (
          <div key={p.track_id} className={`rounded-lg p-3 border bg-gray-800 ${s.ring}`}>
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${s.dot}`}/>
                <span className="text-sm font-medium">Track #{p.track_id}</span>
                <span className={`text-xs ${TREND_COLOR[p.trend]||"text-gray-400"}`}>
                  {TREND[p.trend]||"■"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${s.badge}`}>
                  {s.label}
                </span>
                <span className="text-lg font-bold" style={{color:p.color}}>{p.score}</span>
              </div>
            </div>
            <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700"
                style={{width:`${p.score}%`, backgroundColor:p.color}}/>
            </div>
            {p.signals?.length>0 && (
              <p className="text-xs text-gray-500 mt-1.5 truncate">{p.signals.slice(0,2).join(" · ")}</p>
            )}
            {p.zone && <p className="text-xs text-gray-600 mt-0.5">📍 {p.zone}</p>}
          </div>
        );
      })}
    </div>
  );
}

// ── Stats Sidebar ─────────────────────────────────────────────────────────
function StatsSidebar({ statsData, active }) {
  if (!active || !statsData) return <p className="text-gray-600 text-sm py-4 text-center">Stream not active</p>;
  const lat = statsData.latency || {};
  return (
    <div className="space-y-3">
      <div className="bg-gray-800 rounded-lg p-3 space-y-1.5">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Occupancy</p>
        <StatRow label="Current"  value={statsData.track_count} />
        <StatRow label="Peak"     value={statsData.peak_occupancy} />
        <StatRow label="Incidents" value={statsData.total_incidents} />
      </div>
      {lat.avg_frame_age_ms !== undefined && (
        <div className="bg-gray-800 rounded-lg p-3 space-y-1.5">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Latency</p>
          <StatRow label="Avg frame age"  value={`${lat.avg_frame_age_ms}ms`}
            accent={lat.avg_frame_age_ms > 100} />
          <StatRow label="Max frame age"  value={`${lat.max_frame_age_ms}ms`} />
          <StatRow label="Pacer jitter"   value={`${lat.pacer_jitter_ms}ms`}
            accent={lat.pacer_jitter_ms > 10} />
          <StatRow label="WS avg send"    value={`${lat.avg_ws_send_ms}ms`}
            accent={lat.avg_ws_send_ms > 30} />
          <StatRow label="WS max send"    value={`${lat.max_ws_send_ms}ms`} />
          {lat.ws_backlog_warns > 0 && (
            <StatRow label="WS backlog warns" value={lat.ws_backlog_warns} accent />
          )}
        </div>
      )}
      {lat.drop_rate_pct !== undefined && (
        <div className="bg-gray-800 rounded-lg p-3 space-y-1.5">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Frame Health</p>
          <StatRow label="Drop rate"    value={`${lat.drop_rate_pct}%`}
            accent={lat.drop_rate_pct > 5} />
          <StatRow label="Total dropped" value={lat.total_dropped} />
          <StatRow label="Max jitter"   value={`${lat.pacer_max_jitter}ms`} />
        </div>
      )}
    </div>
  );
}

// ── Profiler Panel ────────────────────────────────────────────────────────
function ProfilerPanel({ report }) {
  const entries = Object.entries(report).sort((a,b)=>b[1]-a[1]);
  const total   = entries.reduce((s,[,v])=>s+v, 0);
  const fps     = total > 0 ? (1000/total).toFixed(1) : "—";
  return (
    <div className="bg-gray-950 border border-blue-900 rounded-lg p-4 font-mono text-xs">
      <div className="flex items-center justify-between mb-3">
        <p className="text-blue-400 font-bold">🔧 PIPELINE PROFILER</p>
        <p className="text-gray-400">Total: {total.toFixed(1)}ms/frame  ~{fps} FPS</p>
      </div>
      <div className="space-y-1">
        {entries.map(([stage, ms]) => {
          const pct = (ms/Math.max(total,1))*100;
          const hot = pct > 30;
          return (
            <div key={stage} className="flex items-center gap-2">
              <span className={`w-28 truncate ${hot?"text-red-400":"text-gray-400"}`}>{stage}</span>
              <div className="flex-1 bg-gray-800 rounded-full h-2">
                <div className={`h-full rounded-full ${hot?"bg-red-500":"bg-blue-600"}`}
                  style={{width:`${pct}%`}}/>
              </div>
              <span className={`w-16 text-right tabular-nums ${hot?"text-red-300":"text-gray-300"}`}>
                {ms.toFixed(1)}ms
              </span>
              <span className="w-8 text-right text-gray-600">{pct.toFixed(0)}%</span>
            </div>
          );
        })}
      </div>
      <p className="text-gray-600 mt-2 text-xs">
        Red = bottleneck (&gt;30% of total). Refreshes every ~150 frames.
      </p>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────
function KPI({ label, value, accent }) {
  const c = {red:"border-red-700 bg-red-950/30",orange:"border-orange-700 bg-orange-950/30",none:"border-gray-700 bg-gray-800"};
  return (
    <div className={`p-3 rounded-lg border ${c[accent]||c.none}`}>
      <p className="text-gray-400 text-xs">{label}</p>
      <p className="text-2xl font-bold mt-0.5">{value}</p>
    </div>
  );
}
function StatRow({ label, value, accent }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={`font-medium ${accent ? "text-orange-400" : "text-gray-200"}`}>{value}</span>
    </div>
  );
}
function fmtUptime(s) {
  const m=Math.floor(s/60), sec=Math.floor(s%60);
  return `${m}:${sec.toString().padStart(2,"0")}`;
}
