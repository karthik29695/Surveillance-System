import { useState, useCallback, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import { useNavigate } from "react-router-dom";
import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });

export default function VideoUpload() {
  const [uploads, setUploads]   = useState([]);
  const [feeds, setFeeds]       = useState([]);
  const [clearing, setClearing] = useState(false);
  const navigate = useNavigate();

  const loadFeeds = () => api.get("/video/").then(r => setFeeds(r.data)).catch(() => {});

  useEffect(() => { loadFeeds(); }, []);

  // Poll processing feeds
  useEffect(() => {
    const busy = feeds.filter(f => f.status === "processing" || f.status === "queued");
    if (!busy.length) return;
    const iv = setInterval(async () => {
      for (const f of busy) {
        try {
          const res = await api.get(`/video/${f.id}/annotated-status`);
          if (res.data.feed_status !== f.status) loadFeeds();
        } catch {}
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [feeds]);

  // Also poll uploads in progress
  useEffect(() => {
    const processing = uploads.filter(u => u.id && u.feedStatus !== "completed" && u.feedStatus !== "error");
    if (!processing.length) return;
    const iv = setInterval(async () => {
      for (const u of processing) {
        try {
          const res = await api.get(`/video/${u.id}/annotated-status`);
          const { feed_status, annotated_ready } = res.data;
          setUploads(prev => prev.map(p =>
            p.id === u.id ? { ...p, feedStatus: feed_status, annotatedReady: annotated_ready } : p
          ));
          if (feed_status === "completed") loadFeeds();
        } catch {}
      }
    }, 3000);
    return () => clearInterval(iv);
  }, [uploads]);

  const onDrop = useCallback(async (files) => {
    for (const file of files) {
      setUploads(prev => [...prev, { name: file.name, progress: 0, uploadStatus: "uploading", feedStatus: null, id: null, annotatedReady: false }]);
      try {
        const res = await api.post("/video/upload", (() => { const f = new FormData(); f.append("file", file); return f; })(), {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: e => {
            const p = Math.round((e.loaded * 100) / e.total);
            setUploads(prev => prev.map(u => u.name === file.name ? { ...u, progress: p } : u));
          },
        });
        setUploads(prev => prev.map(u =>
          u.name === file.name ? { ...u, uploadStatus: "processing", feedStatus: "queued", id: res.data.id } : u
        ));
        loadFeeds();
      } catch {
        setUploads(prev => prev.map(u => u.name === file.name ? { ...u, uploadStatus: "error" } : u));
      }
    }
  }, []);

  const handleReprocess = async (feedId) => {
    await api.post(`/video/${feedId}/reprocess`);
    loadFeeds();
  };

  const handleClearDB = async (clearZones = false) => {
    if (!window.confirm(clearZones ? "Delete ALL data including zones?" : "Delete all feeds and events? Zones are kept.")) return;
    setClearing(true);
    try {
      await api.delete(clearZones ? "/admin/clear-all" : "/admin/clear-db");
      setFeeds([]); setUploads([]);
    } finally { setClearing(false); }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop, accept: { "video/*": [".mp4", ".avi", ".mov", ".mkv"] }
  });

  const statusColor = (s) => ({
    completed:  "bg-green-800 text-green-200",
    processing: "bg-yellow-800 text-yellow-200",
    queued:     "bg-gray-700 text-gray-300",
    error:      "bg-red-800 text-red-200",
  }[s] || "bg-gray-700 text-gray-300");

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Video Management</h1>
          <p className="text-gray-400 text-sm mt-1">Upload new videos or reprocess existing feeds with updated zones.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => handleClearDB(false)} disabled={clearing}
            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm disabled:opacity-40">
            🗑 Clear Feeds
          </button>
          <button onClick={() => handleClearDB(true)} disabled={clearing}
            className="px-3 py-2 bg-red-900 hover:bg-red-800 rounded text-sm disabled:opacity-40">
            🗑 Clear All
          </button>
        </div>
      </div>

      {/* Drop zone */}
      <div {...getRootProps()} className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition
        ${isDragActive ? "border-green-400 bg-green-900/20" : "border-gray-600 hover:border-gray-400"}`}>
        <input {...getInputProps()} />
        <div className="text-3xl mb-2">🎬</div>
        <p className="text-gray-300 font-medium">{isDragActive ? "Drop here..." : "Drag & drop or click to upload"}</p>
        <p className="text-gray-500 text-xs mt-1">MP4, AVI, MOV, MKV</p>
      </div>

      {/* Upload progress */}
      {uploads.filter(u => u.uploadStatus === "uploading").map((u, i) => (
        <div key={i} className="bg-gray-800 rounded-lg p-4">
          <div className="flex justify-between mb-2 text-sm">
            <span className="truncate max-w-xs">{u.name}</span>
            <span className="text-blue-300">Uploading {u.progress}%</span>
          </div>
          <div className="h-1.5 bg-gray-700 rounded-full">
            <div className="h-full bg-blue-500 rounded-full transition-all" style={{ width: `${u.progress}%` }} />
          </div>
        </div>
      ))}

      {/* All feeds */}
      {feeds.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
            All Feeds ({feeds.length})
          </h2>
          <div className="space-y-2">
            {feeds.map(f => (
              <div key={f.id} className="bg-gray-800 rounded-lg p-4 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-gray-500 text-xs w-6 text-right flex-shrink-0">#{f.id}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{f.name}</p>
                    <p className="text-xs text-gray-500">{new Date(f.created_at).toLocaleString()}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className={`text-xs px-2 py-0.5 rounded ${statusColor(f.status)}`}>{f.status}</span>
                  {f.status === "completed" && (
                    <button onClick={() => navigate(`/player/${f.id}`)}
                      className="text-xs bg-green-800 hover:bg-green-700 px-3 py-1 rounded transition">
                      ▶ View
                    </button>
                  )}
                  <button onClick={() => handleReprocess(f.id)}
                    disabled={f.status === "processing" || f.status === "queued"}
                    title="Reprocess with current zones"
                    className="text-xs bg-blue-900 hover:bg-blue-800 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1 rounded transition">
                    ↺ Reprocess
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
