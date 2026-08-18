import { useCallback, useEffect, useState } from "react";

import {
  digikeyAuthorizationUrl,
  disconnectDigiKey,
  getDigiKeyStatus,
} from "../../api/client";
import type { DigiKeyConnectionStatus } from "../../api/types";
import "./ActivityPanel.css";

export function DigiKeyConnection() {
  const [status, setStatus] = useState<DigiKeyConnectionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getDigiKeyStatus());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  async function disconnect() {
    await disconnectDigiKey();
    await refresh();
  }

  return (
    <section className="activity-block">
      <div className="activity-block-header">
        <h3>DigiKey Ordering</h3>
        <span className={`badge ${status?.connected ? "badge-ok" : "badge-neutral"}`}>
          {status?.connected ? "Connected" : "Not connected"}
        </span>
      </div>
      <p className="small">Sandbox only. Login and payment credentials stay with DigiKey.</p>
      {error && <p className="issue-error small">{error}</p>}
      <div className="product-links">
        {!status?.connected ? (
          <a href={digikeyAuthorizationUrl()} target="_blank" rel="noreferrer">
            Connect DigiKey
          </a>
        ) : (
          <button type="button" className="link-button" onClick={() => void disconnect()}>
            Disconnect
          </button>
        )}
        <button type="button" className="link-button" onClick={() => void refresh()}>
          Refresh status
        </button>
      </div>
    </section>
  );
}
