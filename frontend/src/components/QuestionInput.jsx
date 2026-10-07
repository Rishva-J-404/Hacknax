import React from 'react';
import { Search, ArrowRight, CornerDownLeft } from 'lucide-react';

export default function QuestionInput({
  question,
  setQuestion,
  onAnalyze,
  isLoading,
  hasData,
  suggestions: dynamicSuggestions,
}) {
  const defaultSuggestions = [
    { label: 'Total order amount', query: 'Total order amount' },
    { label: 'Average order value', query: 'What is the average order amount?' },
    { label: 'Multi-world spread check', query: 'Total order amount across repair worlds' },
    { label: 'Customer churn rate (Unanswerable)', query: 'What was customer churn rate in 2024?' },
  ];

  const rawSuggestions = dynamicSuggestions && dynamicSuggestions.length > 0
    ? dynamicSuggestions
    : defaultSuggestions;

  const suggestions = rawSuggestions.map((s) => {
    if (typeof s === 'string') {
      return { label: s, query: s };
    }
    return {
      label: s?.label || s?.query || '',
      query: s?.query || s?.label || '',
    };
  }).filter((s) => s.label.trim().length > 0);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !isLoading) {
      onAnalyze();
    }
  };

  return (
    <div className="command-input-container animate-fade-in">
      <div className="command-input-box">
        <Search size={18} color="var(--text-muted)" style={{ flexShrink: 0 }} />
        <input
          type="text"
          className="command-input-field"
          placeholder="Ask a question about your data (e.g. Total order amount)..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          aria-label="Analytical Question"
        />
        <button
          className="btn btn-primary"
          onClick={onAnalyze}
          disabled={isLoading || !hasData}
          style={{ padding: '8px 18px', gap: '8px' }}
        >
          <span>{isLoading ? 'Computing...' : 'ANALYZE & PROVE'}</span>
          {!isLoading && <ArrowRight size={14} />}
        </button>
      </div>

      <div className="pills-row">
        <span className="pills-label">Suggestions:</span>
        {suggestions.map((s, idx) => (
          <button
            key={idx}
            className="pill-item"
            onClick={() => setQuestion(s.query)}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
