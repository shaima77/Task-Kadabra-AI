import React from "react";

function val(item, key) {
  if (!key) return undefined;
  return item[key];
}

function asText(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(asText).filter(Boolean).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function isUrl(v) {
  return typeof v === "string" && /^https?:\/\//.test(v);
}

function Stars({ value }) {
  const n = Number(value);
  if (!isFinite(n) || n <= 0 || n > 5) return <span className="rating-num">{asText(value)}</span>;
  const full = Math.round(n);
  return (
    <span className="stars" title={`${n}`}>
      {"★★★★★".slice(0, full)}
      <span className="stars-empty">{"★★★★★".slice(full)}</span>
    </span>
  );
}

function Card({ item, d }) {
  const title = asText(val(item, d.title_field)) || "Untitled";
  const subtitle = asText(val(item, d.subtitle_field));
  const image = val(item, d.image_field);
  const link = val(item, d.link_field);
  const rating = val(item, d.rating_field);

  return (
    <article className="result-card">
      {isUrl(image) && (
        <div className="rc-img" style={{ backgroundImage: `url(${image})` }} />
      )}
      <div className="rc-body">
        <div className="rc-top">
          <h4 className="rc-title">{title}</h4>
          {d.rating_field && rating !== undefined && rating !== "" && (
            <span className="rc-rating"><Stars value={rating} /></span>
          )}
        </div>
        {subtitle && <div className="rc-sub">{subtitle}</div>}

        {d.badge_fields?.length > 0 && (
          <div className="rc-badges">
            {d.badge_fields.map((b) => {
              const v = val(item, b);
              if (v === undefined || v === "" || v === null) return null;
              return <span className="pill" key={b}>{asText(v)}</span>;
            })}
          </div>
        )}

        {d.detail_fields?.map((df) => {
          const v = val(item, df.key);
          const text = asText(v);
          if (!text) return null;
          return (
            <div className="rc-detail" key={df.key}>
              <span className="rc-dk">{df.label}</span>
              <span className="rc-dv">{text.length > 240 ? text.slice(0, 240) + "…" : text}</span>
            </div>
          );
        })}

        {isUrl(link) && (
          <a className="rc-link" href={link} target="_blank" rel="noreferrer">View original →</a>
        )}
      </div>
    </article>
  );
}

export default function Results({ result, loading, sourceName, onBack, onRestart }) {
  if (loading && !result) {
    return (
      <section className="card">
        <h2 className="section-title">Getting your data…</h2>
        <p className="muted">Running your request. This can take a moment.</p>
        <div className="skeleton-grid">
          {Array.from({ length: 6 }).map((_, i) => <div className="skeleton-card" key={i} />)}
        </div>
      </section>
    );
  }

  if (!result) return null;

  if (!result.ok || result.count === 0) {
    return (
      <section className="card">
        <h2 className="section-title">{result.count === 0 ? "No results this time" : "That didn't work"}</h2>
        <div className="banner warn">{result.message || "No results were returned."}</div>
        <div className="actions">
          <button className="btn ghost" onClick={onBack}>← Adjust and try again</button>
          <button className="btn primary" onClick={onRestart}>New search</button>
        </div>
      </section>
    );
  }

  const d = result.display || {};

  return (
    <section>
      <div className="results-head">
        <div>
          <h2 className="section-title">{result.count} results</h2>
          <p className="muted">{result.summary}</p>
        </div>
        <div className="actions">
          <button className="btn ghost" onClick={onBack}>← Adjust inputs</button>
          <button className="btn primary" onClick={onRestart}>New search</button>
        </div>
      </div>

      <div className="results-grid">
        {result.items.map((it, i) => <Card key={i} item={it} d={d} />)}
      </div>
    </section>
  );
}
