import { useEffect, useState, useRef, useCallback } from "react";
import RiskIntelligencePanel from "../components/RiskIntelligencePanel";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

// ── Constants ──────────────────────────────────────────────────────────────
const INCIDENT_TYPES = new Set([
  "zone_breach","loitering_detected","crowd_detected",
  "object_left_behind","suspect_identified","re_entry","suspicious_behavior",
]);

const SEVERITY_ORDER = { critical:0, high:1, medium:2, low:3, info:4 };

const INCIDENT_META = {
  zone_breach:        { icon:"🚨", label:"Zone Breach",     color:"#ef4444", severity:"critical" },
  loitering_detected: { icon:"⚠️", label:"Loitering",       color:"#f97316", severity:"high" },
  crowd_detected:     { icon:"👥", label:"Crowd Anomaly",   color:"#a855f7", severity:"medium" },
  object_left_behind: { icon:"🎒", label:"Object Left",     color:"#eab308", severity:"high" },
  suspect_identified: { icon:"🔴", label:"Suspect",         color:"#dc2626", severity:"critical" },
  re_entry:           { icon:"↩️", label:"Re-entry",        color:"#ec4899", severity:"medium" },
  suspicious_behavior:{ icon:"🎯", label:"Suspicious",       color:"#dc2626", severity:"critical" },
};
const DEFAULT_META = { icon:"📌", label:"Event", color:"#6b7280", severity:"low" };

const SEV_BADGE = {
  critical:"bg-red-700 text-white",
  high:"bg-orange-700 text-white",
  medium:"bg-yellow-700 text-black",
  low:"bg-blue-800 text-white",
  info:"bg-gray-700 text-gray-300",
};

function getMeta(type) {
  return INCIDENT_META[type.replace(":ended","")] || DEFAULT_META;
}
function fmt(s) {
  if (s==null) return "--:--";
  const m=Math.floor(s/60), sec=Math.floor(s%60);
  return `${m}:${sec.toString().padStart(2,"0")}`;
}
function isIncident(e) { return INCIDENT_TYPES.has(e.event_type.replace(":ended","")); }

// ── Main component ─────────────────────────────────────────────────────────
export default function VideoPlayer() {
  const { feedId }  = useParams();
  const navigate    = useNavigate();
  const videoRef    = useRef(null);

  const [feed, setFeed]         = useState(null);
  const [events, setEvents]     = useState([]);
  const [currentTime, setCT]    = useState(0);
  const [loading, setLoading]   = useState(true);
  const [mode, setMode]         = useState("operator");   // operator | developer
  const [filterType, setFilter] = useState("all");
  const [activeIncident, setActiveIncident] = useState(null);
  const [sidebarTab, setSidebarTab] = useState("incidents");

  useEffect(() => {
    Promise.all([
      api.get(`/video/${feedId}`),
      api.get(`/events/?feed_id=${feedId}&limit=500`),
    ]).then(([fr, er]) => {
      setFeed(fr.data);
      setEvents(er.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [feedId]);

  const onTimeUpdate = () => {
    if (!videoRef.current) return;
    const t = videoRef.current.currentTime;
    setCT(t);
    // Auto-highlight nearest incident
    const nearby = incidentEvents.find(e =>
      e.video_timestamp_seconds != null &&
      Math.abs(e.video_timestamp_seconds - t) < 1.5
    );
    setActiveIncident(nearby || null);
  };

  const seekTo = useCallback((s) => {
    if (videoRef.current) { videoRef.current.currentTime = s; videoRef.current.play(); }
  }, []);

  // Derived data
  const incidentEvents = events.filter(isIncident);
  const allVisibleEvents = mode === "operator" ? incidentEvents : events;

  const filteredEvents = filterType === "all"
    ? allVisibleEvents
    : allVisibleEvents.filter(e => e.event_type.replace(":ended","") === filterType);

  // Operator stats
  const peakOccupancy = events.reduce((max, e) => {
    const c = e.extra_data?.count; return c ? Math.max(max, c) : max;
  }, 0);
  const byType = incidentEvents.reduce((acc, e) => {
    const t = e.event_type.replace(":ended","");
    acc[t] = (acc[t]||0)+1; return acc;
  }, {});
  const criticalCount = incidentEvents.filter(e =>
    ["critical","high"].includes(e.extra_data?.severity || getMeta(e.event_type).severity)
  ).length;

  const incidentTypes = [...new Set(incidentEvents.map(e => e.event_type.replace(":ended","")))];

  if (loading) return (
    <div className="p-6 flex items-center gap-2 text-gray-400">
      <span className="animate-spin">⟳</span> Loading...
    </div>
  );

  return (
    <div className="p-5 space-y-4 max-w-screen-2xl">
      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <button onClick={() => navigate("/upload")}
            className="text-gray-500 hover:text-white text-xs mb-1 flex items-center gap-1">
            ← Back
          </button>
          <h1 className="text-lg font-bold truncate max-w-xl">{feed?.name}</h1>
        </div>
        <div className="flex items-center gap-2">
          {/* Mode toggle */}
          <div className="flex bg-gray-800 rounded-lg p-1 border border-gray-700">
            <button onClick={() => setMode("operator")}
              className={`px-3 py-1 rounded text-xs font-medium transition ${mode==="operator"?"bg-green-700 text-white":"text-gray-400 hover:text-white"}`}>
              Operator
            </button>
            <button onClick={() => setMode("developer")}
              className={`px-3 py-1 rounded text-xs font-medium transition ${mode==="developer"?"bg-blue-700 text-white":"text-gray-400 hover:text-white"}`}>
              Developer
            </button>
          </div>
          <a href={`/api/v1/video/${feedId}/download`} download
            className="flex items-center gap-1 bg-gray-700 hover:bg-gray-600 px-3 py-1.5 rounded text-xs font-medium">
            ⬇ Download
          </a>
        </div>
      </div>

      {/* ── Operator KPIs ── */}
      {mode === "operator" && (
        <div className="grid grid-cols-4 gap-3">
          <KPI label="Security Incidents" value={incidentEvents.length}
            accent={criticalCount>0?"red":"blue"} />
          <KPI label="Critical / High" value={criticalCount}
            accent={criticalCount>0?"orange":"none"} />
          <KPI label="Peak Occupancy"    value={peakOccupancy || "—"} accent="none" />
          <KPI label="Incident Types"    value={Object.keys(byType).length} accent="none" />
        </div>
      )}

      {/* ── Incident type filter pills ── */}
      {incidentTypes.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setFilter("all")}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition
              ${filterType==="all"?"bg-gray-600 border-gray-500":"bg-gray-800 border-gray-700 hover:border-gray-500"}`}>
            All {mode==="operator"?`(${incidentEvents.length})`:`(${events.length})`}
          </button>
          {incidentTypes.map(t => {
            const m = getMeta(t);
            const cnt = byType[t] || 0;
            return (
              <button key={t} onClick={() => setFilter(t)}
                className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border transition
                  ${filterType===t?"border-opacity-100 opacity-100":"border-gray-700 bg-gray-800 opacity-70 hover:opacity-100"}`}
                style={filterType===t?{borderColor:m.color,backgroundColor:m.color+"22"}:{}}>
                <span>{m.icon}</span>
                <span style={filterType===t?{color:m.color}:{}}>{m.label}</span>
                <span className="text-gray-400">×{cnt}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* ── Active incident flash banner ── */}
      {activeIncident && mode === "operator" && (
        <ActiveIncidentBanner event={activeIncident} onSeek={seekTo} />
      )}

      <div className="grid grid-cols-3 gap-5">
        {/* ── Video player ── */}
        <div className="col-span-2 space-y-3">
          <div className="bg-black rounded-xl overflow-hidden aspect-video relative">
            <video ref={videoRef} src={`/api/v1/video/${feedId}/download`}
              controls onTimeUpdate={onTimeUpdate} className="w-full h-full" />
            {/* Operator mode overlay badge */}
            <div className={`absolute top-2 left-2 px-2 py-1 rounded text-xs font-bold
              ${mode==="operator"?"bg-green-800/80 text-green-200":"bg-blue-800/80 text-blue-200"}`}>
              {mode==="operator"?"🛡 OPERATOR":"🔧 DEVELOPER"}
            </div>
          </div>

          {/* ── Incident timeline scrubber ── */}
          <IncidentScrubber
            events={mode==="operator"?incidentEvents:events}
            currentTime={currentTime}
            onSeek={seekTo}
            videoRef={videoRef}
          />

          {/* ── Developer mode: raw event log ── */}
          {mode === "developer" && (
            <DevEventLog events={events} currentTime={currentTime} />
          )}
        </div>

        {/* ── Sidebar ── */}
        <div className="space-y-3">
          {/* Tab switcher */}
          <div className="flex bg-gray-800 rounded-lg p-1 border border-gray-700">
            <button onClick={() => setSidebarTab("incidents")}
              className={`flex-1 py-1 rounded text-xs font-medium transition
                ${sidebarTab==="incidents"?"bg-green-700 text-white":"text-gray-400 hover:text-white"}`}>
              Incidents
            </button>
            <button onClick={() => setSidebarTab("risk")}
              className={`flex-1 py-1 rounded text-xs font-medium transition
                ${sidebarTab==="risk"?"bg-red-800 text-white":"text-gray-400 hover:text-white"}`}>
              🎯 Risk Intel
            </button>
          </div>

          {sidebarTab === "incidents" ? (
            mode === "operator" ? (
              <OperatorSidebar events={filteredEvents} currentTime={currentTime}
                onSeek={seekTo} byType={byType} />
            ) : (
              <DeveloperSidebar events={filteredEvents} currentTime={currentTime} onSeek={seekTo} />
            )
          ) : (
            <RiskIntelligencePanel feedId={feedId} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Active incident flash banner ──────────────────────────────────────────
function ActiveIncidentBanner({ event, onSeek }) {
  const m = getMeta(event.event_type);
  const sev = event.extra_data?.severity || m.severity;
  return (
    <div className="rounded-lg px-4 py-3 flex items-center justify-between border animate-pulse"
      style={{ borderColor: m.color, backgroundColor: m.color + "15" }}>
      <div className="flex items-center gap-3">
        <span className="text-2xl">{m.icon}</span>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm" style={{ color: m.color }}>{m.label}</span>
            <span className={`text-xs px-2 py-0.5 rounded uppercase font-bold ${SEV_BADGE[sev]||SEV_BADGE.medium}`}>
              {sev}
            </span>
          </div>
          <p className="text-xs text-gray-300 mt-0.5">
            {event.extra_data?.message || "Incident detected"}
          </p>
        </div>
      </div>
      <div className="text-xs text-gray-500 flex flex-col items-end gap-1">
        {event.extra_data?.zone      && <span>Zone: {event.extra_data.zone}</span>}
        {event.extra_data?.track_id  && <span>Track #{event.extra_data.track_id}</span>}
        {event.extra_data?.dwell_seconds && <span>{event.extra_data.dwell_seconds}s dwell</span>}
        <span>{fmt(event.video_timestamp_seconds)}</span>
      </div>
    </div>
  );
}

// ── Operator sidebar ──────────────────────────────────────────────────────
function OperatorSidebar({ events, currentTime, onSeek, byType }) {
  return (
    <div className="space-y-3">
      {/* Incident summary */}
      {Object.keys(byType).length > 0 && (
        <div className="bg-gray-800 rounded-lg p-3 space-y-2">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Incident Summary</p>
          {Object.entries(byType).sort((a,b)=>b[1]-a[1]).map(([type, cnt]) => {
            const m = getMeta(type);
            return (
              <div key={type} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <span>{m.icon}</span>
                  <span style={{ color: m.color }}>{m.label}</span>
                </div>
                <span className="font-bold text-white">×{cnt}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Incident feed */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Incidents ({events.length})
        </p>
        <div className="space-y-1.5 max-h-[480px] overflow-y-auto pr-1">
          {events.length === 0 && (
            <div className="text-center py-8 text-gray-600 text-sm">
              No security incidents detected.
            </div>
          )}
          {events.map((e, i) => {
            const m = getMeta(e.event_type);
            const sev = e.extra_data?.severity || m.severity;
            const isActive = e.video_timestamp_seconds != null &&
              Math.abs(e.video_timestamp_seconds - currentTime) < 1.5;
            const isHighPriority = ["critical","high"].includes(sev);
            return (
              <button key={i} onClick={() => onSeek(e.video_timestamp_seconds)}
                className={`w-full text-left px-3 py-2.5 rounded-lg border transition
                  ${isActive
                    ? "border-opacity-80"
                    : isHighPriority
                    ? "border-gray-700 hover:border-gray-500"
                    : "border-transparent bg-gray-800/60 hover:bg-gray-800"
                  }`}
                style={isActive ? { borderColor: m.color, backgroundColor: m.color+"18" } : {}}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="flex-shrink-0">{m.icon}</span>
                    <span className="text-sm font-medium truncate" style={{ color: m.color }}>
                      {m.label}
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${SEV_BADGE[sev]||SEV_BADGE.low}`}>
                      {sev}
                    </span>
                  </div>
                  <span className="text-xs text-gray-500 flex-shrink-0">
                    {fmt(e.video_timestamp_seconds)}
                  </span>
                </div>
                <div className="flex gap-2 text-xs text-gray-500 mt-0.5 ml-6 flex-wrap">
                  {e.extra_data?.zone           && <span>· {e.extra_data.zone}</span>}
                  {e.extra_data?.track_id       && <span>· Track #{e.extra_data.track_id}</span>}
                  {e.extra_data?.dwell_seconds  && <span>· {e.extra_data.dwell_seconds}s</span>}
                  {e.extra_data?.count          && <span>· {e.extra_data.count} people</span>}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Developer sidebar ─────────────────────────────────────────────────────
function DeveloperSidebar({ events, currentTime, onSeek }) {
  return (
    <div>
      <p className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2">
        Raw Event Log ({events.length})
      </p>
      <div className="space-y-1 max-h-[600px] overflow-y-auto pr-1 font-mono text-xs">
        {events.map((e, i) => {
          const isActive = e.video_timestamp_seconds != null &&
            Math.abs(e.video_timestamp_seconds - currentTime) < 1;
          const isIncidentType = INCIDENT_TYPES.has(e.event_type.replace(":ended",""));
          return (
            <button key={i} onClick={() => onSeek(e.video_timestamp_seconds)}
              className={`w-full text-left px-2 py-1.5 rounded border transition
                ${isActive ? "bg-blue-900/40 border-blue-600"
                : isIncidentType ? "bg-gray-800 border-gray-700"
                : "border-transparent bg-gray-900/40 hover:bg-gray-800"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className={isIncidentType ? "text-yellow-400" : "text-gray-500"}>
                  {e.event_type}
                </span>
                <span className="text-gray-600">{fmt(e.video_timestamp_seconds)}</span>
              </div>
              {e.extra_data?.track_id && (
                <span className="text-blue-400">track#{e.extra_data.track_id} </span>
              )}
              {e.extra_data?.state && (
                <span className="text-purple-400">[{e.extra_data.state}] </span>
              )}
              {e.extra_data?.severity && (
                <span className="text-gray-600">sev:{e.extra_data.severity}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Developer event log (below player) ───────────────────────────────────
function DevEventLog({ events, currentTime }) {
  const recent = events.filter(e =>
    e.video_timestamp_seconds != null &&
    Math.abs(e.video_timestamp_seconds - currentTime) < 3
  );
  if (!recent.length) return null;
  return (
    <div className="bg-gray-950 border border-gray-800 rounded-lg p-3 font-mono text-xs">
      <p className="text-blue-400 mb-2 font-bold">LIVE DEBUG  t={currentTime.toFixed(1)}s</p>
      <div className="space-y-0.5 max-h-24 overflow-y-auto">
        {recent.map((e,i) => (
          <div key={i} className="flex gap-3 text-gray-400">
            <span className="text-gray-600 w-12">{fmt(e.video_timestamp_seconds)}</span>
            <span className={INCIDENT_TYPES.has(e.event_type.replace(":ended",""))
              ? "text-yellow-400" : "text-gray-500"}>{e.event_type}</span>
            {e.extra_data?.track_id && <span className="text-blue-400">#{e.extra_data.track_id}</span>}
            {e.extra_data?.zone     && <span className="text-red-400">{e.extra_data.zone}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Incident timeline scrubber ────────────────────────────────────────────
function IncidentScrubber({ events, currentTime, onSeek, videoRef }) {
  const duration = videoRef.current?.duration || 0;
  if (!duration) return null;
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs text-gray-500">Incident timeline — click to jump</p>
        <p className="text-xs text-gray-600">{fmt(currentTime)} / {fmt(duration)}</p>
      </div>
      <div className="relative h-7 bg-gray-900 rounded cursor-pointer"
        onClick={e => {
          const r = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - r.left) / r.width) * duration);
        }}>
        {/* Playhead */}
        <div className="absolute top-0 bottom-0 w-0.5 bg-white/60 pointer-events-none"
          style={{ left:`${(currentTime/duration)*100}%` }} />
        {/* Event markers */}
        {events.map((e, i) => {
          if (e.video_timestamp_seconds == null) return null;
          const m = getMeta(e.event_type);
          const isActive = Math.abs(e.video_timestamp_seconds - currentTime) < 1.5;
          return (
            <div key={i}
              title={`${m.label} @ ${fmt(e.video_timestamp_seconds)}`}
              className={`absolute top-1 bottom-1 rounded-sm transition-all`}
              style={{
                left:            `${(e.video_timestamp_seconds/duration)*100}%`,
                width:           isActive ? "4px" : "3px",
                backgroundColor: m.color,
                opacity:         isActive ? 1 : 0.7,
                transform:       isActive ? "scaleY(1.3)" : "none",
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────
function KPI({ label, value, accent }) {
  const colors = {
    red:   "border-red-700 bg-red-950/30",
    orange:"border-orange-700 bg-orange-950/30",
    blue:  "border-blue-700 bg-blue-950/30",
    none:  "border-gray-700 bg-gray-800",
  };
  return (
    <div className={`p-3 rounded-lg border ${colors[accent]||colors.none}`}>
      <p className="text-gray-400 text-xs">{label}</p>
      <p className="text-2xl font-bold mt-0.5">{value}</p>
    </div>
  );
}
