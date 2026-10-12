import React, { useState } from "react";
import * as api from "./api.js";
import Describe from "./components/Describe.jsx";
import Clarify from "./components/Clarify.jsx";
import Progress from "./components/Progress.jsx";
import Recommendation from "./components/Recommendation.jsx";
import Results from "./components/Results.jsx";

const STEPS = ["describe", "clarify", "searching", "recommend", "results"];

export default function App() {
  const [step, setStep] = useState("describe");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [session, setSession] = useState(null);
  const [need, setNeed] = useState("");
  const [restated, setRestated] = useState("");
  const [questions, setQuestions] = useState([]);
  const [progress, setProgress] = useState([]);
  const [recommendation, setRecommendation] = useState(null);
  const [runResult, setRunResult] = useState(null);

  async function handleDescribe(text) {
    setError(null);
    setLoading(true);
    try {
      const resp = await api.describe(text);
      setSession(resp.session_id);
      setNeed(resp.need);
      setRestated(resp.restated_need);
      setQuestions(resp.questions || []);
      setStep(resp.questions && resp.questions.length ? "clarify" : "searching");
      if (!resp.questions || !resp.questions.length) startSearch(resp.session_id, {});
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function startSearch(sessionId, answers) {
    setStep("searching");
    setProgress([]);
    setRecommendation(null);
    setError(null);
    api.recommend(sessionId, answers, {
      onProgress: (msg) => setProgress((p) => [...p, msg]),
      onResult: (rec) => {
        setRecommendation(rec);
        setStep("recommend");
      },
      onError: (e) => {
        setError(e.message);
        setStep("recommend");
      },
    });
  }

  function handleClarifySubmit(answers) {
    startSearch(session, answers);
  }

  async function handleRun(values) {
    setError(null);
    setLoading(true);
    setStep("results");
    setRunResult(null);
    try {
      const resp = await api.runSource(session, values);
      setRunResult(resp);
    } catch (e) {
      setError(e.message);
      setRunResult({ ok: false, count: 0, message: e.message, items: [], display: {} });
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setStep("describe");
    setSession(null);
    setNeed("");
    setRestated("");
    setQuestions([]);
    setProgress([]);
    setRecommendation(null);
    setRunResult(null);
    setError(null);
  }

  const activeIdx = STEPS.indexOf(step === "running" ? "results" : step);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand" onClick={reset} role="button" title="Start over">
          <span className="logo">◆</span> Data&nbsp;Finder
        </div>
        <div className="steps">
          {["Describe", "Refine", "Search", "Recommend", "Use"].map((label, i) => (
            <div key={label} className={"pip " + (i <= activeIdx ? "done" : "")}>
              <span className="dot" />
              {label}
            </div>
          ))}
        </div>
      </header>

      <main className="stage">
        {step === "describe" && (
          <Describe onSubmit={handleDescribe} loading={loading} error={error} />
        )}
        {step === "clarify" && (
          <Clarify
            need={need}
            restated={restated}
            questions={questions}
            onSubmit={handleClarifySubmit}
            onBack={() => setStep("describe")}
          />
        )}
        {step === "searching" && <Progress need={restated || need} progress={progress} />}
        {step === "recommend" && (
          <Recommendation
            recommendation={recommendation}
            error={error}
            onRun={handleRun}
            onRestart={reset}
          />
        )}
        {step === "results" && (
          <Results
            result={runResult}
            loading={loading}
            sourceName={recommendation?.name}
            onBack={() => setStep("recommend")}
            onRestart={reset}
          />
        )}
      </main>
    </div>
  );
}
