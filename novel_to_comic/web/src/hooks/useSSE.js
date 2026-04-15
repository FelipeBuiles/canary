import { useEffect, useRef, useState, useCallback } from "react";
/**
 * Hook that connects to the SSE event stream for a project.
 * Returns accumulated events and a `connect` function to start listening.
 */
export function useSSE(project) {
    const [events, setEvents] = useState([]);
    const [connected, setConnected] = useState(false);
    const sourceRef = useRef(null);
    const disconnect = useCallback(() => {
        sourceRef.current?.close();
        sourceRef.current = null;
        setConnected(false);
    }, []);
    const connect = useCallback(() => {
        if (!project)
            return;
        disconnect();
        setEvents([]);
        const es = new EventSource(`/api/projects/${project}/events`);
        sourceRef.current = es;
        setConnected(true);
        es.onmessage = (e) => {
            const event = JSON.parse(e.data);
            setEvents((prev) => [...prev, event]);
            if (event.type === "stage_complete" ||
                event.type === "stage_fail" ||
                event.type === "pipeline_done") {
                es.close();
                setConnected(false);
            }
        };
        es.onerror = () => {
            es.close();
            setConnected(false);
        };
    }, [project, disconnect]);
    // Clean up on unmount
    useEffect(() => disconnect, [disconnect]);
    return { events, connected, connect, disconnect, clearEvents: () => setEvents([]) };
}
