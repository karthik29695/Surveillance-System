import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import VideoUpload from "./pages/VideoUpload";
import VideoPlayer from "./pages/VideoPlayer";
import LiveStream from "./pages/LiveStream";
import EventTimeline from "./pages/EventTimeline";
import SuspectManager from "./pages/SuspectManager";
import ZoneEditor from "./pages/ZoneEditor";
import AlertBanner from "./components/AlertBanner";

const NAV = [
  { path: "/",         label: "Dashboard" },
  { path: "/upload",   label: "Upload Video" },
  { path: "/stream",   label: "Live Stream" },
  { path: "/timeline", label: "Event Timeline" },
  { path: "/zones",    label: "Zone Config" },
  { path: "/suspects", label: "Suspects" },
];

export default function App() {
  return (
    <BrowserRouter>
      <AlertBanner />
      <div className="min-h-screen bg-gray-950 text-white flex">
        <nav className="w-52 bg-gray-900 border-r border-gray-800 flex flex-col p-4">
          <div className="mb-8">
            <p className="text-xs text-gray-500 uppercase tracking-wider">AI Surveillance</p>
            <p className="text-green-400 font-bold text-lg">SurveillanceAI</p>
          </div>
          <div className="space-y-1">
            {NAV.map(({ path, label }) => (
              <NavLink key={path} to={path} end={path === "/"}
                className={({ isActive }) =>
                  `block px-3 py-2 rounded text-sm transition ${isActive ? "bg-green-900 text-green-300" : "text-gray-400 hover:text-white hover:bg-gray-800"}`
                }>
                {label}
              </NavLink>
            ))}
          </div>
        </nav>
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/"               element={<Dashboard />} />
            <Route path="/upload"         element={<VideoUpload />} />
            <Route path="/player/:feedId" element={<VideoPlayer />} />
            <Route path="/stream"         element={<LiveStream />} />
            <Route path="/timeline"       element={<EventTimeline />} />
            <Route path="/zones"          element={<ZoneEditor />} />
            <Route path="/suspects"       element={<SuspectManager />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
