import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { videoAPI, alertsAPI } from "../services/api";
import axios from "axios";
import useSurveillanceStore from "../store/surveillanceStore";

const api = axios.create({ baseURL: "/api/v1" });

const INCIDENT_STYLE = {
  zone_breach:        { color: "text-red-400",    bg: "bg-red-900/20 border-red-800",      icon: "🚨", label: "Zone Breach" },
  loitering_detected: { color: "text-orange-400", bg: "bg-orange-900/20 border-orange-800", icon: "⚠️", label: "Loitering" },
  crowd_detected:     { color: "text-purple-400", bg: "bg-purple-900/20 border-purple-800", icon: "👥", label: "Crowd" },
  object_left_behind: { color: "text-yellow-400", bg: "bg-yellow-900/20 border-yellow-800", icon: "🎒", label: "Object Left" },
  suspect_identified: { color: "text-red-300",    bg: "bg-red-950/40 border-red-700",       icon: "🔴", label: "Suspect" },
  re_entry:           { color: "text-pink-400",   bg: "bg-pink-900/20 border-pink-800",     icon: "↩️", label: "Re-entry" },
};
const DEFAULT_STYLE = { color: "text-gray-400", bg: "bg-gray-800 border-gray-700", icon: "📌", label: "Event" };
const getStyle = t => INCIDENT_STYLE[t.replace(":ended","")] || DEFAULT_STYLE;

const SEVERITY_BADGE = {
  critical: "bg-red-700 text-white",
  high:     "bg-orange-700 text-white",
  medium:   "bg-yellow-700 text-black",
  low:      "bg-blue-800 text-white",
  info:     "bg-gray-700 text-gray-300",
};

export default function Dashboard() {
  const { feeds, setFeeds } = useSurveillanceStore();
  const [incidents, setIncidents]     = useState([]);
  const [stats, setStats]             = useState({ total: 0, critical: 0, high: 0, active_feeds: 0 });
  const navigate = useNavigate();

  const load = async () => {
    try {
      const [feedsRes, incRes] = await Promise.all([
        api.get("/video/"),
        api.get("/events/incidents?limit=100"),
      ]);
      setFeeds(feedsRes.data);
      const inc = incRes.data;
      setIncidents(inc);
      setStats({
        total:        inc.length,
        critical:     inc.filter(e => e.extra_data?.severity === "critical").length,
        high:         inc.filter(e => e.extra_data?.severity === "high").length,
        active_feeds: feedsRes.data.filter(f => f.status === "completed").length,
      });
    } catch {}
  };

  useEffect(() => { load(); const iv = setInterval(load, 5000); return () => clearInterval(iv); }, []);

  // Group incidents by type for summary
  const typeCounts = incidents.reduce((acc, e) => {
    const t = e.event_type.replace(":ended","");
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});

  const criticalIncidents = incidents.filter(e =>
    ["critical","high"].includes(e.extra_data?.severity)
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Surveillance Intelligence</h1>
        <span className="text-xs text-gray-500">Auto-refreshes every 5s</span>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4">
        <KPICard label="Security Incidents"  value={stats.total}       accent="blue" />
        <KPICard label="Critical Alerts"     value={stats.critical}    accent={stats.critical > 0 ? "red" : "none"} />
        <KPICard label="High Priority"       value={stats.high}        accent={stats.high > 0 ? "orange" : "none"} />
        <KPICard label="Completed Feeds"     value={stats.active_feeds} accent="green" />
      </div>

      {/* Incident type breakdown */}
      {Object.keys(typeCounts).length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {Object.entries(typeCounts).sort((a,b) => b[1]-a[1]).map(([type, count]) => {
            const s = getStyle(type);
            return (
              <div key={type} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs ${s.bg}`}>
                <span>{s.icon}</span>
                <span className={s.color}>{s.label}</span>
                <span className="text-gray-400 font-bold">×{count}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        {/* Critical + high incidents */}
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Priority Incidents
          </h2>
          <div className="space-y-2">
            {criticalIncidents.length === 0 && (
              <div className="bg-gray-800/50 rounded-lg p-4 text-center text-gray-500 text-sm">
                No high-priority incidents
              </div>
            )}
            {criticalIncidents.slice(0, 8).map((e, i) => {
              const s = getStyle(e.event_type);
              const sev = e.extra_data?.severity || "medium";
              return (
                <div key={i} className={`border rounded-lg px-3 py-2.5 ${s.bg}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span>{s.icon}</span>
                      <span className={`text-sm font-medium ${s.color}`}>{s.label}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded uppercase ${SEVERITY_BADGE[sev] || SEVERITY_BADGE.medium}`}>
                        {sev}
                      </span>
                    </div>
                    <button onClick={() => navigate(`/player/${e.feed_id}`)}
                      className="text-xs text-gray-400 hover:text-white transition">View →</button>
                  </div>
                  <p className="text-xs text-gray-400 mt-1 truncate">
                    {e.extra_data?.message || `Feed #${e.feed_id}`}
                  </p>
                  <div className="flex gap-3 text-xs text-gray-600 mt-0.5">
                    {e.extra_data?.zone      && <span>Zone: {e.extra_data.zone}</span>}
                    {e.extra_data?.track_id  && <span>Track #{e.extra_data.track_id}</span>}
                    {e.extra_data?.dwell_seconds && <span>{e.extra_data.dwell_seconds}s dwell</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Feed status */}
        <section>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Video Feeds
          </h2>
          <div className="space-y-1.5">
            {feeds.length === 0 && (
              <p className="text-gray-600 text-sm py-4 text-center">No feeds yet.</p>
            )}
            {feeds.map(f => {
              const feedIncidents = incidents.filter(e => e.feed_id === f.id);
              const feedCritical  = feedIncidents.filter(e => ["critical","high"].includes(e.extra_data?.severity)).length;
              return (
                <div key={f.id} className={`rounded-lg px-3 py-2.5 flex items-center justify-between border
                  ${feedCritical > 0 ? "bg-red-950/20 border-red-900" : "bg-gray-800 border-gray-700"}`}>
                  <div className="min-w-0">
                    <p className="text-sm truncate max-w-xs">{f.name}</p>
                    <p className="text-xs text-gray-500">
                      {feedIncidents.length} incidents
                      {feedCritical > 0 && <span className="text-red-400 ml-1">· {feedCritical} critical</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      f.status === "completed"  ? "bg-green-800 text-green-200" :
                      f.status === "processing" ? "bg-yellow-800 text-yellow-200" :
                      "bg-gray-700 text-gray-400"}`}>{f.status}</span>
                    {f.status === "completed" &&
                      <button onClick={() => navigate(`/player/${f.id}`)}
                        className="text-xs text-green-400 hover:text-green-300">View →</button>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function KPICard({ label, value, accent }) {
  const colors = {
    red:    "border-red-700 bg-red-950/30",
    orange: "border-orange-700 bg-orange-950/30",
    green:  "border-green-700 bg-green-950/30",
    blue:   "border-blue-700 bg-blue-950/30",
    none:   "border-gray-700 bg-gray-800",
  };
  return (
    <div className={`p-4 rounded-lg border ${colors[accent] || colors.none}`}>
      <p className="text-gray-400 text-xs uppercase tracking-wider">{label}</p>
      <p className="text-3xl font-bold mt-1">{value}</p>
    </div>
  );
}
