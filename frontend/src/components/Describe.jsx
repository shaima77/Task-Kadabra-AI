import React, { useState } from "react";

const EXAMPLES = [
  "Competitor ads running on Facebook right now",
  "Reviews of local coffee shops in Chicago",
  "Trending TikTok videos about skincare",
  "Contact details for marketing agencies in Berlin",
];

export default function Describe({ onSubmit, loading, error }) {
  const [text, setText] = useState("");

  function submit(e) {
    e.preventDefault();
    if (text.trim() && !loading) onSubmit(text.trim());
  }

  return (
    <section className="card hero">
      <h1 className="hero-title">What data are you looking for?</h1>
      <p className="hero-sub">
        Describe it in your own words. We'll find the best place to get it and set it up for you —
        no technical setup, no accounts.
      </p>

      <form onSubmit={submit}>
        <textarea
          className="need-input"
          autoFocus
          rows={3}
          placeholder="e.g. Recent customer reviews of coffee shops in Chicago"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
        />

        <div className="examples">
          <span className="examples-label">Try:</span>
          {EXAMPLES.map((ex) => (
            <button type="button" key={ex} className="chip ghost" onClick={() => setText(ex)}>
              {ex}
            </button>
          ))}
        </div>

        {error && <div className="banner error">{error}</div>}

        <button className="btn primary big" disabled={!text.trim() || loading}>
          {loading ? "Thinking…" : "Find my data →"}
        </button>
      </form>
    </section>
  );
}
