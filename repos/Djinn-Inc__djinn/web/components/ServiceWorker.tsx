"use client";

import { useEffect } from "react";

export default function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    navigator.serviceWorker.register("/sw.js").catch(() => {
      // SW registration failed — ignore silently (dev mode, unsupported browser, etc.)
    });

    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "SW_UPDATED") {
        // New service worker has activated. The tab is still running
        // whatever JS was loaded from the OLD bundle. Reload once so
        // the user picks up the fresh bundle (fixes stale-cache "0
        // validators" errors after deploys that change API paths).
        window.location.reload();
      }
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => {
      navigator.serviceWorker.removeEventListener("message", onMessage);
    };
  }, []);

  return null;
}
