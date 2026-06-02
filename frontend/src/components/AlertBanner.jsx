import { useEffect, useState } from "react";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

const SEVERITY_STYLE = {
  critical: { bg: "bg-red-950 border-red-600",      icon: "🚨", text: "text-red-200",    badge: "bg-red-700 text-white" },
  high:     { bg: "bg-orange-950 border-orange-600", icon: "⚠️", text: "text-orange-200", badge: "bg-orange-700 text-white" },
  medium:   { bg: "bg-yellow-950 border-yellow-600", icon: "⚡", text: "text-yellow-200", badge: "bg-yellow-700 text-black" },
};

export default function AlertBanner() {
  const [incidents, setIncidents] = useState([]);
  const [dismissed, setDismissed] = useState(new Set());

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await api.get("/events/incidents?limit=20");
        // Only show critical and high in banner
        setIncidents(res.data.filter(e =>
          ["critical", "high"].includes(e.extra_data?.severity) &&
          !e.event_type.includes(":ended") &&
          e.extra_data?.visible !== false
        ));
      } catch {}
    };
    poll();
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, []);

  const visible = incidents.filter(e => !dismissed.has(e.id));
  if (!visible.length) return null;

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2 w-80">
      {visible.slice(0, 3).map(e => {
        const sev = e.extra_data?.severity || "high";
        const s   = SEVERITY_STYLE[sev] || SEVERITY_STYLE.high;
        const msg = e.extra_data?.message || e.event_type.replace(/_/g, " ");
        return (
          <div key={e.id}
            className={`border rounded-lg px-4 py-3 flex items-start gap-3 shadow-xl ${s.bg}`}>
            <span className="text-xl flex-shrink-0">{s.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs px-2 py-0.5 rounded font-bold uppercase ${s.badge}`}>{sev}</span>
                <span className={`text-xs font-semibold ${s.text}`}>
                  {e.event_type.replace(/_/g," ").toUpperCase()}
                </span>
              </div>
              <p className={`text-sm ${s.text} opacity-90`}>{msg}</p>
              <div className="flex gap-3 mt-1 text-xs opacity-50 text-gray-300">
                {e.extra_data?.zone     && <span>{e.extra_data.zone}</span>}
                {e.extra_data?.track_id && <span>Track #{e.extra_data.track_id}</span>}
                <span>{new Date(e.timestamp).toLocaleTimeString()}</span>
              </div>
            </div>
            <button onClick={() => setDismissed(s => new Set([...s, e.id]))}
              className="text-gray-400 hover:text-white text-xl leading-none flex-shrink-0">×</button>
          </div>
        );
      })}
      {visible.length > 3 && (
        <p className="text-xs text-gray-500 text-right">+{visible.length - 3} more</p>
      )}
    </div>
  );
}
