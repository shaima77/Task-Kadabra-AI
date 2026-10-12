import React from "react";
import UsageForm from "./UsageForm.jsx";

export default function Recommendation({ recommendation, error, onRun, onRestart }) {
  if (error && !recommendation) {
    return (
      <section className="card">
        <h2 className="section-title">Something went wrong</h2>
        <div className="banner error">{error}</div>
        <button className="btn ghost" onClick={onRestart}>Start over</button>
      </section>
    );
  }

  if (!recommendation) return null;

  if (!recommendation.found) {
    return (
      <section className="card">
        <h2 className="section-title">No strong match — yet</h2>
        <p className="muted">
          {recommendation.message ||
            "I couldn't find a source that clearly fits. Try describing the data differently."}
        </p>
        <button className="btn primary" onClick={onRestart}>Try another description</button>
      </section>
    );
  }

  const r = recommendation;

  return (
    <section className="rec-layout">
      <div className="card rec-card">
        <div className="rec-badge">Best match</div>
        <h2 className="rec-name">{r.name}</h2>
        {r.headline && <p className="rec-headline">{r.headline}</p>}

        {r.reasons?.length > 0 && (
          <>
            <h4 className="rec-h4">Why it fits</h4>
            <ul className="rec-reasons">
              {r.reasons.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </>
        )}

        {r.evidence?.length > 0 && (
          <>
            <h4 className="rec-h4">What we checked</h4>
            <div className="evidence">
              {r.evidence.map((x, i) => <span className="fact" key={i}>{x}</span>)}
            </div>
          </>
        )}

        {r.alternatives?.length > 0 && (
          <>
            <h4 className="rec-h4">Also considered</h4>
            <div className="alts">
              {r.alternatives.map((a, i) => (
                <div className="alt" key={i}>
                  <div className="alt-name">{a.name}</div>
                  <div className="alt-trade">{a.tradeoff}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="card form-card">
        {r.form ? (
          <UsageForm form={r.form} onRun={onRun} running={false} />
        ) : (
          <p className="muted">This source needs no setup — just run it.</p>
        )}
        <button className="link subtle" onClick={onRestart}>Start a different search</button>
      </div>
    </section>
  );
}
