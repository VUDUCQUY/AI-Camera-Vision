export default function HistoryTable({ history, onClear }) {
  if (!history.length) return null;

  return (
    <div className="history-panel">
      <div className="history-panel__header">
        <span className="history-panel__title">📋 SYNC HISTORY</span>
        <button className="history-panel__clear-btn" onClick={onClear}>✕ CLEAR ALL</button>
      </div>

      <div className="history-table">
        <div className="history-table__header">
          <span>#</span>
          <span>TIME</span>
          <span>PALLETS</span>
          <span>CARTONS</span>
          <span>PRODUCTS</span>
          <span>FILES</span>
          <span>STATUS</span>
        </div>
        {history.map((entry, i) => (
          <div key={i} className="history-table__row">
            <span className="history-table__num">{history.length - i}</span>
            <span className="history-table__time">{entry.time}</span>
            <span style={{ color: 'var(--green-100)', textAlign: 'center' }}>{entry.pallets}</span>
            <span style={{ textAlign: 'center' }}>{entry.cartons}</span>
            <span style={{ textAlign: 'center' }}>{entry.products}</span>
            <span style={{ color: '#7aaa8a', textAlign: 'center' }}>{entry.files ?? '—'}</span>
            <span className={`history-table__status history-table__status--${entry.status}`}>
              {entry.status === 'ok' ? '✓ SYNCED' : '⚠ ERROR'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}