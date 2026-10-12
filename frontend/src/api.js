// Thin client for the backend. The browser only ever talks to /api — no keys here.

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

export function describe(need) {
  return postJSON("/api/describe", { need });
}

export function runSource(sessionId, values) {
  return postJSON("/api/run", { session_id: sessionId, values });
}

// Stream the recommendation phase. Parses Server-Sent Events from a POST response,
// calling onProgress for each human step and onResult with the final recommendation.
export async function recommend(sessionId, answers, { onProgress, onResult, onError }) {
  const res = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, answers }),
  });
  if (!res.ok || !res.body) {
    onError && onError(new Error(`Search failed (${res.status})`));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // Normalize CRLF -> LF: the server separates SSE frames with "\r\n\r\n".
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      let payload;
      try {
        payload = JSON.parse(data);
      } catch (_) {
        continue;
      }
      if (event === "progress") onProgress && onProgress(payload.message);
      else if (event === "result") onResult && onResult(payload);
      else if (event === "error") onError && onError(new Error(payload.message));
    }
  }
}
