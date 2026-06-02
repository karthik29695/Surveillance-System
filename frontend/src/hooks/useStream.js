import { useEffect, useState } from "react";
import useSurveillanceStore from "../store/surveillanceStore";
export function useStream(feedId, source) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);
  const { connectStream, disconnectStream, activeStream } = useSurveillanceStore();
  useEffect(() => {
    if (!feedId || !source) return;
    const ws = connectStream(feedId, source);
    ws.onopen = () => setIsConnected(true);
    ws.onerror = () => setError("Connection failed");
    ws.onclose = () => setIsConnected(false);
    return () => disconnectStream();
  }, [feedId, source]);
  return { isConnected, error, activeStream };
}
