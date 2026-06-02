import { useEffect, useState } from "react";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

const INCIDENT_META = {
  zone_breach:        { icon:"🚨", label:"Zone Breach",   color:"text-red-400",    dot:"bg-red-400" },
  loitering_detected: { icon:"⚠️", label:"Loitering",     color:"text-orange-400", dot:"bg-orange-400" },
  crowd_detected:     { icon:"👥", label:"Crowd",         color:"text-purple-400", dot:"bg-purple-400" },
  object_left_behind: { icon:"🎒", label:"Object Left",   color:"text-yellow-400", dot:"bg-yellow-400" },
  suspect_identified: { icon:"🔴", label:"Suspect",       color:"text-red-300",    dot:"bg-red-300" },
  re_entry:           { icon:"↩️", label:"Re-entry",      color:"text-pink-400",   dot:"bg-pink-400" },
  suspicious_behavior:{ icon:"🎯", label:"Suspicious",     color:"text-red-300",    dot:"bg-red-300" },
};
const DEFAULT_META = { icon:"📌", label:"Event", color:"text-gray-400", dot:"bg-gray-400" };
const SEV_BADGE = {
  critical:"bg-red-700 text-white",
  high:"bg-orange-700 text-white",
  medium:"bg-yellow-700 text-black",
  low:"bg-blue-800 text-white",
  info:"bg-gray-700 text-gray-400",
};
function getMeta(t) { return INCIDENT_META[t.replace(":ended","")] || DEFAULT_META; }
function fmtTime(s) {
  if (!s) return "--:--";
  const m = Math.floor(s/60), sec = Math.floor(s%60);
  return `${m}:${sec.toString().padStart(2,"0")}`;
}

export default function EventTimeline() {
  const [events, setEvents]   = useState([]);
  const [filter, setFilter]   = useState("all");
  const [mode, setMode]       = useState("operator");
  const [feeds, setFeeds]     = useState([]);
  const [feedFilter, setFeedFilter] = useState("all");

  useEffect(() => {
    api.get("/video/").then(r => setFeeds(r.data)).catch(() => {});
    load();
  }, []);

  const load = () => {
    api.get("/events/?limit=500").then(r => setEvents(r.data)).catch(() => {});
  };

  const isIncident = e => Object.keys(INCIDENT_META).includes(e.event_type.replace(":ended",""));

  const baseEvents = mode === "operator" ? events.filter(isIncident) : events;
  const feedFiltered = feedFilter === "all" ? baseEvents : baseEvents.filter(e => String(e.feed_id) === feedFilter);
  const filtered = filter === "all" ? feedFiltered : feedFiltered.filter(e => e.event_type.replace(":ended","") === filter);

  const incidentTypes = [...new Set(events.filter(isIncident).map(e => e.event_type.replace(":ended","")))];

  // Group by severity for summary
  const bySev = filtered.reduce((acc, e) => {
    const s = e.extra_data?.severity || "low";
    acc[s] = (acc[s]||0)+1; return acc;
  }, {});

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Incident Timeline</h1>
          <p className="text-gray-500 text-sm">{filtered.length} events shown</p>
        </div>
        <div className="flex gap-2 items-center">
          {/* Feed filter */}
          <select value={feedFilter} onChange={e => setFeedFilter(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs">
            <option value="all">All Feeds</option>
            {feeds.map(f => <option key={f.id} value={String(f.id)}>{f.name} (#{f.id})</option>)}
          </select>
          {/* Mode toggle */}
          <div className="flex bg-gray-800 rounded-lg p-1 border border-gray-700">
            <button onClick={() => setMode("operator")}
              className={`px-3 py-1 rounded text-xs font-medium transition
                ${mode==="operator"?"bg-green-700 text-white":"text-gray-400 hover:text-white"}`}>
              Operator
            </button>
            <button onClick={() => setMode("developer")}
              className={`px-3 py-1 rounded text-xs font-medium transition
                ${mode==="developer"?"bg-blue-700 text-white":"text-gray-400 hover:text-white"}`}>
              Developer
            </button>
          </div>
        </div>
      </div>

      {/* Severity summary row */}
      {Object.keys(bySev).length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {["critical","high","medium","low","info"].filter(s => bySev[s]).map(s => (
            <div key={s} className={`px-3 py-1 rounded-full text-xs font-bold ${SEV_BADGE[s]}`}>
              {s.toUpperCase()} ×{bySev[s]}
            </div>
          ))}
        </div>
      )}

      {/* Type filter pills */}
      <div className="flex gap-2 flex-wrap">
        <button onClick={() => setFilter("all")}
          className={`px-3 py-1 rounded-full text-xs font-medium border transition
            ${filter==="all"?"bg-gray-600 border-gray-500":"bg-gray-800 border-gray-700"}`}>
          All ({feedFiltered.length})
        </button>
        {incidentTypes.map(t => {
          const m = getMeta(t);
          const cnt = feedFiltered.filter(e => e.event_type.replace(":ended","") === t).length;
          return (
            <button key={t} onClick={() => setFilter(t)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border transition
                ${filter===t?"border-gray-400":"bg-gray-800 border-gray-700 hover:border-gray-500"}`}>
              <span className={`w-2 h-2 rounded-full ${m.dot}`} />
              {m.label} ({cnt})
            </button>
          );
        })}
        {mode === "developer" && (
          <button onClick={() => setFilter("tracking")}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition
              ${filter==="tracking"?"bg-blue-800 border-blue-600":"bg-gray-800 border-gray-700"}`}>
            🔧 Tracking only
          </button>
        )}
      </div>

      {/* Timeline */}
      <div className="relative">
        <div className="absolute left-5 top-0 bottom-0 w-px bg-gray-800" />
        <div className="space-y-2">
          {filtered.length === 0 && (
            <div className="text-center py-12 text-gray-600">
              {mode==="operator" ? "No security incidents recorded." : "No events recorded."}
            </div>
          )}
          {filtered.map((e, i) => {
            const m = getMeta(e.event_type);
            const sev = e.extra_data?.severity ||
              (Object.keys(INCIDENT_META).includes(e.event_type.replace(":ended","")) ? "medium" : "info");
            const isHighPriority = ["critical","high"].includes(sev);
            return (
              <div key={i} className="flex gap-4 pl-12 relative">
                {/* Timeline dot */}
                <div className={`absolute left-4 top-3 w-3 h-3 rounded-full border-2 border-gray-900 ${m.dot}
                  ${isHighPriority ? "ring-2 ring-offset-1 ring-offset-gray-900" : ""}`}
                  style={isHighPriority ? { ringColor: m.dot.replace("bg-","") } : {}} />

                <div className={`flex-1 rounded-lg p-3 border transition
                  ${isHighPriority
                    ? "bg-gray-800 border-gray-700"
                    : "bg-gray-900/50 border-gray-800"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{m.icon}</span>
                      <span className={`font-semibold text-sm ${m.color}`}>{m.label}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded uppercase ${SEV_BADGE[sev]||SEV_BADGE.info}`}>
                        {sev}
                      </span>
                      {e.event_type.includes(":ended") && (
                        <span className="text-xs text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">ended</span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 flex-shrink-0">
                      {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : ""}
                    </span>
                  </div>

                  {e.extra_data?.message && (
                    <p className="text-xs text-gray-400 mt-1">{e.extra_data.message}</p>
                  )}

                  <div className="flex gap-3 mt-1 text-xs text-gray-600 flex-wrap">
                    <span>Feed #{e.feed_id}</span>
                    {e.video_timestamp_seconds != null && <span>@ {fmtTime(e.video_timestamp_seconds)}</span>}
                    {e.extra_data?.zone          && <span>· {e.extra_data.zone}</span>}
                    {e.extra_data?.track_id      && <span>· Track #{e.extra_data.track_id}</span>}
                    {e.extra_data?.dwell_seconds && <span>· {e.extra_data.dwell_seconds}s dwell</span>}
                    {e.extra_data?.count         && <span>· {e.extra_data.count} people</span>}
                    {mode === "developer" && e.extra_data?.state && (
                      <span className="text-purple-400">· [{e.extra_data.state}]</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
