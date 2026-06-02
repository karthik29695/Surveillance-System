import { useState, useEffect } from "react";
import { facesAPI } from "../services/api";
export default function SuspectManager() {
  const [suspects, setSuspects] = useState([]);
  const [name, setName] = useState(""); const [notes, setNotes] = useState(""); const [image, setImage] = useState(null); const [status, setStatus] = useState("");
  useEffect(() => { facesAPI.listSuspects().then(r => setSuspects(r.data)).catch(() => {}); }, []);
  const handleAdd = async () => {
    if (!name || !image) return setStatus("Name and image required.");
    try {
      setStatus("Adding...");
      await facesAPI.addSuspect(name, notes, image);
      const res = await facesAPI.listSuspects();
      setSuspects(res.data); setName(""); setNotes(""); setImage(null); setStatus("Added successfully.");
    } catch (e) { setStatus(e.response?.data?.detail || "Failed."); }
  };
  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Suspect Database</h1>
      <div className="bg-gray-800 rounded-lg p-5 mb-6">
        <h2 className="text-lg font-semibold mb-4">Add New Profile</h2>
        <div className="grid grid-cols-2 gap-4">
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Full name" className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm" />
          <input type="file" accept="image/*" onChange={e => setImage(e.target.files[0])} className="bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm" />
          <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes (optional)" rows={2} className="col-span-2 bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm" />
        </div>
        <div className="flex items-center gap-4 mt-4">
          <button onClick={handleAdd} className="bg-green-600 hover:bg-green-700 px-4 py-2 rounded text-sm font-medium">Add Suspect</button>
          {status && <p className="text-sm text-gray-400">{status}</p>}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {suspects.map(s => (
          <div key={s.id} className="bg-gray-800 rounded-lg p-4 flex gap-4">
            <div className="w-12 h-12 bg-gray-700 rounded-full flex items-center justify-center text-lg font-bold text-gray-400">{s.name[0]}</div>
            <div>
              <p className="font-medium">{s.name}</p>
              {s.notes && <p className="text-xs text-gray-400 mt-1">{s.notes}</p>}
              <p className="text-xs text-gray-600 mt-1">Added {new Date(s.added_at).toLocaleDateString()}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
