import { create } from "zustand";
const useSurveillanceStore = create((set, get) => ({
  feeds: [], events: [], alerts: [], suspects: [],
  activeStream: null, wsConnection: null,
  setFeeds: (feeds) => set({ feeds }),
  setEvents: (events) => set({ events }),
  setAlerts: (alerts) => set({ alerts }),
  setSuspects: (suspects) => set({ suspects }),
  addEvent: (event) => set((s) => ({ events: [event, ...s.events].slice(0, 200) })),
  addAlert: (alert) => set((s) => ({ alerts: [alert, ...s.alerts] })),
  markAlertRead: (id) => set((s) => ({ alerts: s.alerts.map(a => a.id === id ? { ...a, is_read: true } : a) })),
  connectStream: (feedId, source) => {
    const ws = new WebSocket(`ws://localhost:8000/api/v1/stream/ws/${feedId}`);
    ws.onopen = () => ws.send(JSON.stringify({ source }));
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      set({ activeStream: data });
      if (data.events?.length) data.events.forEach(ev => get().addEvent(ev));
    };
    set({ wsConnection: ws });
    return ws;
  },
  disconnectStream: () => {
    const ws = get().wsConnection;
    if (ws) ws.close();
    set({ wsConnection: null, activeStream: null });
  },
}));
export default useSurveillanceStore;
