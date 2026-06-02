import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

const ZONE_TYPES = [
  { value: "restricted",     label: "Restricted Area",  color: "#ef4444" },
  { value: "monitoring",     label: "Monitoring Area",  color: "#eab308" },
  { value: "entry",          label: "Entry Zone",        color: "#22c55e" },
  { value: "exit",           label: "Exit Zone",         color: "#f97316" },
  { value: "staff_area",     label: "Staff Area",        color: "#3b82f6" },
  { value: "waiting_area",   label: "Waiting Area",      color: "#8b5cf6" },
  { value: "public_corridor",label: "Public Corridor",   color: "#6b7280" },
];
const TYPE_COLOR = Object.fromEntries(ZONE_TYPES.map(t => [t.value, t.color]));

const ZONE_POLICIES = {
  restricted:     { loitering:"Enabled (12s)", multiplier:"2.0x",  stationary:"❌ Not allowed", desc:"Aggressive — any presence flagged quickly" },
  monitoring:     { loitering:"Enabled (25s)", multiplier:"1.2x",  stationary:"❌ Not allowed", desc:"Moderate — watched area" },
  entry:          { loitering:"Enabled (40s)", multiplier:"0.8x",  stationary:"❌ Not allowed", desc:"Brief transit expected" },
  exit:           { loitering:"Enabled (40s)", multiplier:"0.8x",  stationary:"❌ Not allowed", desc:"Brief transit expected" },
  staff_area:     { loitering:"Disabled",      multiplier:"0.1x",  stationary:"✅ Allowed",     desc:"Staff presence normal — loitering suppressed" },
  waiting_area:   { loitering:"Disabled",      multiplier:"0.2x",  stationary:"✅ Allowed",     desc:"Standing expected — relaxed thresholds" },
  public_corridor:{ loitering:"Enabled (45s)", multiplier:"0.6x",  stationary:"❌ Not allowed", desc:"Normal transit expected" },
};

export default function ZoneEditor() {
  const canvasRef = useRef(null);
  const imgRef    = useRef(null);

  const [feeds, setFeeds]               = useState([]);
  const [selectedFeed, setSelectedFeed] = useState(null);
  const [zones, setZones]               = useState([]);
  const [points, setPoints]             = useState([]);   // stored as fractions [0-1]
  const [zoneName, setZoneName]         = useState("");
  const [zoneType, setZoneType]         = useState("restricted");
  const [drawing, setDrawing]           = useState(false);
  const [frameUrl, setFrameUrl]         = useState(null);
  const [status, setStatus]             = useState("");
  // actual video resolution — fetched from /frame endpoint headers or img naturalWidth
  const videoSize = useRef({ w: 1920, h: 1080 });

  useEffect(() => {
    api.get("/video/").then(r => setFeeds(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedFeed) return;
    setFrameUrl(`/api/v1/video/${selectedFeed}/frame?t=${Date.now()}`);
    loadZones(selectedFeed);
    setPoints([]);
    setDrawing(false);
  }, [selectedFeed]);

  const loadZones = (feedId) => {
    api.get(`/zones/?feed_id=${feedId}`).then(r => setZones(r.data)).catch(() => {});
  };

  const handleImageLoad = (e) => {
    videoSize.current = { w: e.target.naturalWidth, h: e.target.naturalHeight };
    redraw();
  };

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const img    = imgRef.current;
    if (!canvas || !img || !img.complete) return;
    const ctx = canvas.getContext("2d");
    const W = img.clientWidth;
    const H = img.clientHeight;
    canvas.width  = W;
    canvas.height = H;
    ctx.clearRect(0, 0, W, H);

    // Draw saved zones (points stored as fractions)
    zones.forEach(z => {
      if (!z.points?.length) return;
      const color = z.color || TYPE_COLOR[z.zone_type] || "#ef4444";
      ctx.beginPath();
      z.points.forEach(([fx, fy], i) => {
        const px = fx * W, py = fy * H;
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fillStyle   = color + "33";
      ctx.strokeStyle = color;
      ctx.lineWidth   = 2;
      ctx.fill(); ctx.stroke();
      // Label
      const cx = z.points.reduce((s, p) => s + p[0], 0) / z.points.length * W;
      const cy = z.points.reduce((s, p) => s + p[1], 0) / z.points.length * H;
      ctx.fillStyle = color;
      ctx.font = "bold 12px system-ui";
      ctx.fillText(`${z.zone_name} [${z.zone_type}]`, cx - 40, cy);
    });

    // Draw in-progress polygon (points as fractions)
    if (points.length > 0) {
      const color = TYPE_COLOR[zoneType] || "#ef4444";
      ctx.beginPath();
      points.forEach(([fx, fy], i) => {
        const px = fx * W, py = fy * H;
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.setLineDash([6, 3]); ctx.stroke(); ctx.setLineDash([]);
      // Vertex dots
      points.forEach(([fx, fy]) => {
        ctx.beginPath();
        ctx.arc(fx * W, fy * H, 5, 0, Math.PI * 2);
        ctx.fillStyle = color; ctx.fill();
      });
      // Close hint
      if (points.length > 2) {
        ctx.beginPath();
        ctx.moveTo(points[points.length-1][0]*W, points[points.length-1][1]*H);
        ctx.lineTo(points[0][0]*W, points[0][1]*H);
        ctx.strokeStyle = color + "55"; ctx.lineWidth = 1;
        ctx.setLineDash([4,4]); ctx.stroke(); ctx.setLineDash([]);
      }
    }
  }, [zones, points, zoneType]);

  useEffect(() => { redraw(); }, [redraw]);

  const handleCanvasClick = useCallback((e) => {
    if (!drawing) return;
    const canvas = canvasRef.current;
    const rect   = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    // Store as fractions relative to canvas display size
    const fx = px / canvas.width;
    const fy = py / canvas.height;
    setPoints(prev => [...prev, [parseFloat(fx.toFixed(6)), parseFloat(fy.toFixed(6))]]);
  }, [drawing]);

  const handleSave = async () => {
    if (points.length < 3) return setStatus("Need at least 3 points.");
    if (!zoneName.trim())  return setStatus("Enter a zone name.");
    try {
      const color = TYPE_COLOR[zoneType];
      // Convert fractions → actual video pixel coords using naturalWidth/Height
      const vw = videoSize.current.w;
      const vh = videoSize.current.h;
      const pixelPoints = points.map(([fx, fy]) => [
        parseFloat((fx * vw).toFixed(1)),
        parseFloat((fy * vh).toFixed(1)),
      ]);
      await api.post("/zones/", {
        feed_id:   selectedFeed ? parseInt(selectedFeed) : null,
        zone_name: zoneName.trim(),
        zone_type: zoneType,
        points:    pixelPoints,
        color,
      });
      setPoints([]); setZoneName(""); setDrawing(false); setStatus("Zone saved.");
      loadZones(selectedFeed);
    } catch (e) {
      setStatus(`Failed: ${e.response?.data?.detail || e.message}`);
    }
  };

  const handleDelete = async (zoneId) => {
    await api.delete(`/zones/${zoneId}`); loadZones(selectedFeed);
  };

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Zone Configuration</h1>
        <p className="text-gray-400 text-sm mt-1">
          Select a feed, click "Start Drawing", then click on the frame to place polygon vertices.
        </p>
      </div>

      <div className="flex gap-3 items-center flex-wrap">
        <select value={selectedFeed || ""} onChange={e => setSelectedFeed(e.target.value || null)}
          className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm">
          <option value="">Select a video feed…</option>
          {feeds.map(f => <option key={f.id} value={f.id}>{f.name} (#{f.id})</option>)}
        </select>
        {selectedFeed && !drawing && (
          <button onClick={() => { setDrawing(true); setPoints([]); setStatus("Click on the frame to add vertices. Save when done."); }}
            className="bg-green-700 hover:bg-green-600 px-4 py-2 rounded text-sm font-medium">
            + Start Drawing
          </button>
        )}
        {drawing && (
          <>
            <button onClick={() => setPoints(p => p.slice(0, -1))}
              className="bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded text-sm">Undo</button>
            <button onClick={() => { setDrawing(false); setPoints([]); setStatus(""); }}
              className="bg-red-800 hover:bg-red-700 px-3 py-2 rounded text-sm">Cancel</button>
          </>
        )}
      </div>

      {drawing && (
        <div className="flex gap-3 items-end flex-wrap bg-gray-800 p-4 rounded-lg">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Zone Name</label>
            <input value={zoneName} onChange={e => setZoneName(e.target.value)} placeholder="e.g. Server Room"
              className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm w-44" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Zone Type</label>
            <select value={zoneType} onChange={e => setZoneType(e.target.value)}
              className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm">
              {ZONE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded" style={{ backgroundColor: TYPE_COLOR[zoneType] }} />
            <span className="text-xs text-gray-400">{points.length} points</span>
          </div>
          {ZONE_POLICIES[zoneType] && (
            <div className="col-span-full bg-gray-900/60 border border-gray-700 rounded px-3 py-2 text-xs space-y-1">
              <p className="text-gray-300 font-medium">{ZONE_POLICIES[zoneType].desc}</p>
              <div className="flex gap-4 text-gray-500">
                <span>Loitering: <span className="text-gray-300">{ZONE_POLICIES[zoneType].loitering}</span></span>
                <span>Risk: <span className="text-gray-300">{ZONE_POLICIES[zoneType].multiplier}</span></span>
                <span>Stationary: <span className="text-gray-300">{ZONE_POLICIES[zoneType].stationary}</span></span>
              </div>
            </div>
          )}
          <button onClick={handleSave} disabled={points.length < 3 || !zoneName.trim()}
            className="bg-green-700 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2 rounded text-sm font-medium">
            Save Zone
          </button>
          {status && <p className="text-xs text-gray-400">{status}</p>}
        </div>
      )}

      <div className="grid grid-cols-3 gap-5">
        <div className="col-span-2">
          {selectedFeed ? (
            <div className="relative rounded-xl overflow-hidden bg-black">
              <img ref={imgRef} src={frameUrl} alt="frame" className="w-full"
                onLoad={handleImageLoad} />
              <canvas ref={canvasRef} onClick={handleCanvasClick}
                className={`absolute inset-0 w-full h-full ${drawing ? "cursor-crosshair" : "cursor-default"}`} />
              {drawing && (
                <div className="absolute top-2 right-2 bg-green-800/80 text-green-200 text-xs px-3 py-1 rounded-full">
                  Drawing — {points.length} points
                </div>
              )}
            </div>
          ) : (
            <div className="bg-gray-800 rounded-xl aspect-video flex items-center justify-center text-gray-500 text-sm">
              Select a video feed to configure zones
            </div>
          )}
        </div>

        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Zones ({zones.length})</h2>
          {zones.length === 0 && <p className="text-gray-600 text-sm py-4">No zones yet.</p>}
          {zones.map(z => (
            <div key={z.id} className="bg-gray-800 rounded-lg p-3 flex items-start justify-between gap-2">
              <div className="flex items-start gap-2">
                <div className="w-3 h-3 rounded-sm mt-1 flex-shrink-0"
                  style={{ backgroundColor: z.color || TYPE_COLOR[z.zone_type] }} />
                <div>
                  <p className="text-sm font-medium">{z.zone_name}</p>
                  <p className="text-xs text-gray-500">{z.zone_type} · {z.points?.length} pts</p>
                </div>
              </div>
              <button onClick={() => handleDelete(z.id)}
                className="text-gray-600 hover:text-red-400 text-xs transition">✕</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
