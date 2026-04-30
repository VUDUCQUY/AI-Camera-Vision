import { useState } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

// Overlay vẽ khung xanh cho Modal
function MiniOverlay({ boxes }) {
  if (!boxes || !boxes.length) return null;
  return (
    <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }} viewBox="0 0 1 1" preserveAspectRatio="none" fill="none">
      {boxes.map((box, i) => {
        const pts = box.points;
        const polyPts = pts.map(p => p.join(',')).join(' ');
        return (
          <polygon key={i} points={polyPts} fill="rgba(74, 222, 128, 0.1)" stroke="#4ade80" strokeWidth="0.005" />
        );
      })}
    </svg>
  );
}

export default function StepFinalize({ pallets, files, scanStore, onSynced, onNewScan }) {
  const [syncing, setSyncing] = useState(false);
  const [synced, setSynced] = useState(false);

  // State để hiện Modal ảnh
  const [evidence, setEvidence] = useState(null);

  const totalCartons = pallets.reduce((s, p) => s + (p.total_cartons || 0), 0);
  const totalProducts = new Set(pallets.map(p => p.product_code)).size;

  const handleFinalize = async () => {
    setSyncing(true);
    // ... Logic sync giữ nguyên ...
    setSynced(true);
    setSyncing(false);
  };

  const today = new Date().toISOString().slice(0, 10);

  return (
    <div style={{ flex: 1, position: 'relative' }}>

      {/* ── 🆕 MODAL HIỆN ẢNH KHI CLICK DÒNG ── */}
      {evidence && (
        <div className="evidence-modal" onClick={() => setEvidence(null)}>
          <div className="evidence-modal__content" onClick={e => e.stopPropagation()}>
            <div className="evidence-modal__header">
              <span>BẰNG CHỨNG QUÉT: {evidence.name}</span>
              <button onClick={() => setEvidence(null)}>✕</button>
            </div>
            <div className="evidence-modal__body">
              <img src={evidence.url} alt="evidence" style={{ width: '100%' }} />
              <MiniOverlay boxes={evidence.boxes} />
            </div>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="summary-cards">
        <div className="summary-card">
            <div className="summary-card__value" style={{ color: 'var(--green-100)' }}>{pallets.length}</div>
            <div className="summary-card__label">PALLETS</div>
        </div>
        <div className="summary-card">
            <div className="summary-card__value" style={{ color: 'var(--cyan)' }}>{totalCartons}</div>
            <div className="summary-card__label">CARTONS</div>
        </div>
        <div className="summary-card">
            <div className="summary-card__value" style={{ color: 'var(--yellow)' }}>{totalProducts}</div>
            <div className="summary-card__label">PRODUCTS</div>
        </div>
      </div>

      {/* Table */}
      <div className="finalize-table">
        <div className="finalize-table__header">
          <span>#</span><span>PALLET ID</span><span>PRODUCT</span><span>EXPIRY</span><span>QTY</span><span>STATUS</span>
        </div>

        <div style={{ maxHeight: '350px', overflowY: 'auto' }}>
          {pallets.map((p, i) => {
            const expired = p.min_expiry_date && p.min_expiry_date < today;
            return (
              <div
                key={i}
                className="finalize-table__row clickable-row"
                onClick={() => {
                    // Tìm dữ liệu trong store dựa trên tên file gốc p._src
                    const fileIdx = files.findIndex(f => f.name === p._src);
                    const storeData = scanStore[fileIdx];
                    if (storeData) {
                        setEvidence({
                            url: storeData.previewUrl,
                            boxes: storeData.boxes,
                            name: p._src
                        });
                    }
                }}
              >
                <span style={{ color: 'var(--green-muted)' }}>{i + 1}</span>
                <span style={{ fontSize: 10, color: 'var(--green-100)', fontWeight: 'bold' }}>{p.pallet_id}</span>
                <span>{p.product_code}</span>
                <span style={{ color: expired ? 'var(--red)' : 'inherit' }}>{p.min_expiry_date}</span>
                <span style={{ textAlign: 'center' }}>{p.total_cartons}</span>
                <span className={expired ? 'finalize-table__status--expired' : 'finalize-table__status--ok'}>
                  {expired ? '⚠ EXPIRED' : '✓ OK'}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ marginTop: '20px' }}>
        {synced ? (
          <div className="sync-success">
            <div className="sync-success__title">ĐỒNG BỘ THÀNH CÔNG</div>
            <button className="btn-new-scan" onClick={onNewScan}>＋ QUÉT MỚI</button>
          </div>
        ) : (
          <button className={`btn-sync ${syncing ? 'btn-sync--syncing' : 'btn-sync--active'}`} onClick={handleFinalize} disabled={syncing}>
            {syncing ? 'ĐANG ĐỒNG BỘ...' : '⬇ FINALIZE & SYNC TO SHEETS'}
          </button>
        )}
      </div>
    </div>
  );
}