import React from 'react';
import { Sparkles, Shield } from 'lucide-react';

export default function AnalysisHero() {
  return (
    <section className="hero-wrapper animate-fade-in">
      <div className="hero-pill-tag">
        <Shield size={12} />
        <span>VERIFIED DATA ANALYSIS</span>
      </div>
      <h1 className="hero-heading">
        Ask your data a question.
      </h1>
      <p className="hero-desc">
        ProofLens audits your data, evaluates possible repairs,
        computes the answer, and produces executable proof.
      </p>
    </section>
  );
}
