import Stepper from './Stepper';

const STEP_TITLES = [
  'STEP 1 OF 3: SELECT DATA SOURCE',
  'STEP 2 OF 3: AI SCAN',
  'STEP 3 OF 3: COMPLETION & SYNC',
];

export default function Sidebar({ step, files, pallets, onBack }) {
  const totalCartons  = pallets.reduce((s, p) => s + (p.total_cartons || 0), 0);
  const totalProducts = new Set(pallets.map(p => p.product_code)).size;

  return (
    <div className="sidebar">
      <div className="sidebar__step-title">{STEP_TITLES[step]}</div>

      <Stepper step={step} />

      <div className="sidebar__info-panel">
        {step === 0 && (
          <>
            <div className="sidebar__info-title">INSTRUCTIONS</div>
            {[
              'Select one or multiple images',
              'Drag & drop supported',
              'JPG, PNG, WEBP formats',
              'Press NEXT to proceed',
            ].map((text, i) => (
              <div key={i} className="sidebar__info-item">
                <span className="sidebar__info-bullet">›</span>
                <span>{text}</span>
              </div>
            ))}
          </>
        )}

        {step === 1 && (
          <>
            <div className="sidebar__info-title">QUEUE</div>
            <div className="sidebar__queue-count">{files.length}</div>
            <div className="sidebar__queue-label">files queued</div>
            {files.map((f, i) => (
              <div key={i} className="sidebar__file-item">
                <span className="sidebar__file-arrow">▸</span>
                <span className="sidebar__file-name">{f.name}</span>
              </div>
            ))}
          </>
        )}

        {step === 2 && (
          <>
            <div className="sidebar__info-title">SUMMARY</div>
            {[
              ['Pallets',      pallets.length],
              ['Cartons',      totalCartons],
              ['Products',     totalProducts],
              ['Source files', files.length],
            ].map(([label, val], i) => (
              <div key={i} className="sidebar__summary-row">
                <span className="sidebar__summary-label">{label}</span>
                <span className="sidebar__summary-value">{val}</span>
              </div>
            ))}
          </>
        )}
      </div>

      {step > 0 && (
        <button className="btn-back" onClick={onBack}>← BACK</button>
      )}
    </div>
  );
}