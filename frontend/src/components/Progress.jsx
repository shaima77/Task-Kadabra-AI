import React from "react";

// Live, human-readable progress during the search. No logs — just what's happening.
export default function Progress({ need, progress }) {
  return (
    <section className="card">
      <h2 className="section-title">Finding the best source…</h2>
      <p className="muted">Working on: <strong>{need}</strong></p>

      <ul className="progress-list">
        {progress.map((msg, i) => {
          const isLast = i === progress.length - 1;
          return (
            <li key={i} className={"progress-item " + (isLast ? "active" : "done")}>
              <span className="pdot">{isLast ? <span className="spinner" /> : "✓"}</span>
              <span>{msg}</span>
            </li>
          );
        })}
        {progress.length === 0 && (
          <li className="progress-item active">
            <span className="pdot"><span className="spinner" /></span>
            <span>Getting started…</span>
          </li>
        )}
      </ul>
    </section>
  );
}
