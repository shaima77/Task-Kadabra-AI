import React, { useState } from "react";

function initialValues(fields) {
  const v = {};
  for (const f of fields) {
    if (f.default !== null && f.default !== undefined) v[f.id] = f.default;
    else if (f.kind === "tags" || f.kind === "multiselect") v[f.id] = [];
    else if (f.kind === "toggle") v[f.id] = false;
    else v[f.id] = "";
  }
  return v;
}

function TagsInput({ value, onChange, placeholder }) {
  const [draft, setDraft] = useState("");
  const tags = Array.isArray(value) ? value : [];
  function add() {
    const t = draft.trim();
    if (t && !tags.includes(t)) onChange([...tags, t]);
    setDraft("");
  }
  return (
    <div className="tags-input" onClick={(e) => e.currentTarget.querySelector("input")?.focus()}>
      {tags.map((t) => (
        <span className="tag" key={t}>
          {t}
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))}>×</button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={tags.length ? "" : placeholder || "Type and press Enter…"}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
          if (e.key === "Backspace" && !draft && tags.length) onChange(tags.slice(0, -1));
        }}
        onBlur={add}
      />
    </div>
  );
}

export default function UsageForm({ form, onRun, running }) {
  const [values, setValues] = useState(() => initialValues(form.fields));
  const set = (id, v) => setValues((s) => ({ ...s, [id]: v }));

  function submit(e) {
    e.preventDefault();
    if (!running) onRun(values);
  }

  return (
    <form className="usage-form" onSubmit={submit}>
      <div className="uf-head">
        <h3>{form.title}</h3>
        {form.subtitle && <p className="muted">{form.subtitle}</p>}
      </div>

      {form.fields.map((f) => (
        <div className="uf-field" key={f.id}>
          <label className="uf-label">
            {f.label}
            {f.required && <span className="req">*</span>}
          </label>
          {f.help && <div className="uf-help">{f.help}</div>}

          {f.kind === "textarea" && (
            <textarea rows={3} value={values[f.id] || ""} placeholder={f.placeholder || ""}
              onChange={(e) => set(f.id, e.target.value)} />
          )}

          {f.kind === "text" && (
            <input value={values[f.id] || ""} placeholder={f.placeholder || ""}
              onChange={(e) => set(f.id, e.target.value)} />
          )}

          {f.kind === "number" && (
            <input type="number" value={values[f.id] ?? ""} placeholder={f.placeholder || ""}
              onChange={(e) => set(f.id, e.target.value === "" ? "" : Number(e.target.value))} />
          )}

          {f.kind === "toggle" && (
            <button type="button" className={"switch " + (values[f.id] ? "on" : "")}
              onClick={() => set(f.id, !values[f.id])}>
              <span className="knob" />
              <span className="switch-label">{values[f.id] ? "Yes" : "No"}</span>
            </button>
          )}

          {f.kind === "select" && (
            <div className="options">
              {f.options.map((o) => (
                <button type="button" key={o.value}
                  className={"chip " + (values[f.id] === o.value ? "selected" : "")}
                  onClick={() => set(f.id, o.value)}>
                  {o.label}
                </button>
              ))}
            </div>
          )}

          {f.kind === "multiselect" && (
            <div className="options">
              {f.options.map((o) => {
                const arr = Array.isArray(values[f.id]) ? values[f.id] : [];
                const on = arr.includes(o.value);
                return (
                  <button type="button" key={o.value}
                    className={"chip " + (on ? "selected" : "")}
                    onClick={() => set(f.id, on ? arr.filter((x) => x !== o.value) : [...arr, o.value])}>
                    {o.label}
                  </button>
                );
              })}
            </div>
          )}

          {f.kind === "tags" && (
            <TagsInput value={values[f.id]} placeholder={f.placeholder}
              onChange={(v) => set(f.id, v)} />
          )}
        </div>
      ))}

      <button className="btn primary big" disabled={running}>
        {running ? "Getting your data…" : (form.run_button_label || "Get the data")}
      </button>
    </form>
  );
}
