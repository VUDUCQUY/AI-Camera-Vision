import React from 'react';

const STEPS = ['UPLOAD', 'SCAN', 'FINALIZE'];

export default function Stepper({ step }) {
  return (
    <div className="stepper">
      {STEPS.map((label, i) => {
        const done = i < step;
        const active = i === step;

        return (
          <React.Fragment key={i}>
            <div className="stepper__step">
              <div className={`stepper__circle ${done ? 'stepper__circle--done' : active ? 'stepper__circle--active' : 'stepper__circle--idle'}`}>
                {done
                  ? <span className="stepper__circle-check">✓</span>
                  : <span className={active ? 'stepper__circle-num--active' : 'stepper__circle-num--idle'}>{i + 1}</span>
                }
              </div>
              <span className={`stepper__label ${active ? 'stepper__label--active' : done ? 'stepper__label--done' : 'stepper__label--idle'}`}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`stepper__connector ${done ? 'stepper__connector--done' : 'stepper__connector--idle'}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}