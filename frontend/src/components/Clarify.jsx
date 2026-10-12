import React, { useState } from "react";

export default function Clarify({ need, restated, questions, onSubmit, onBack }) {
  const [answers, setAnswers] = useState({});

  function setAnswer(q, value) {
    setAnswers((a) => ({ ...a, [q.question]: value }));
  }

  function submit(e) {
    e.preventDefault();
    // Only send answered questions — unanswered ones are genuinely optional.
    const filled = Object.fromEntries(
      Object.entries(answers).filter(([, v]) => v && String(v).trim())
    );
    onSubmit(filled);
  }

  return (
    <section className="card">
      <button className="link back" onClick={onBack}>← Back</button>
      <h2 className="section-title">A few quick questions</h2>
      <p className="muted">
        So we pick the right source for <strong>{restated || need}</strong>. Answer what's
        relevant — you can skip the rest.
      </p>

      <form onSubmit={submit} className="questions">
        {questions.map((q) => (
          <div className="question" key={q.id}>
            <label className="q-label">{q.question}</label>
            {q.help && <div className="q-help">{q.help}</div>}

            {q.kind === "choice" ? (
              <div className="options">
                {q.options.map((opt) => (
                  <button
                    type="button"
                    key={opt.value}
                    className={"chip " + (answers[q.question] === opt.value ? "selected" : "")}
                    onClick={() => setAnswer(q, opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            ) : (
              <input
                className="text-input"
                placeholder="Type your answer…"
                value={answers[q.question] || ""}
                onChange={(e) => setAnswer(q, e.target.value)}
              />
            )}
          </div>
        ))}

        <div className="actions">
          <button type="button" className="btn ghost" onClick={() => onSubmit({})}>
            Skip
          </button>
          <button className="btn primary">Find the best source →</button>
        </div>
      </form>
    </section>
  );
}
