import { useState } from 'react';


// Overlay vẽ khung cho Modal. `highlight` = mã đang chọn → khung đó sáng + nhấp nháy, các khung khác mờ đi
function MiniOverlay({ boxes, highlight }) {
  if (!boxes || !boxes.length) return null;
  return (
    <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }} viewBox="0 0 1 1" preserveAspectRatio="none" fill="none">
      {boxes.map((box, i) => {
        const polyPts = box.points.map(p => p.join(',')).join(' ');
        const active = highlight && box.code === highlight;
        if (!active) {
          return <polygon key={i} points={polyPts} fill="rgba(74, 222, 128, 0.05)" stroke="#4ade80" strokeOpacity={highlight ? 0.3 : 1} strokeWidth="0.004" />;
        }
        const xs = box.points.map(p => p[0]), ys = box.points.map(p => p[1]);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
        return (
          <g key={i}>
            <polygon points={polyPts} fill="rgba(255, 204, 0, 0.25)" stroke="#ffcc00" strokeWidth="0.008" />
            {/* Vòng "ping" lan toả quanh mã được chọn */}
            <circle cx={cx} cy={cy} r="0.02" stroke="#ffcc00" strokeWidth="0.004">
              <animate attributeName="r" from="0.02" to="0.09" dur="1.2s" repeatCount="indefinite" />
              <animate attributeName="stroke-opacity" from="1" to="0" dur="1.2s" repeatCount="indefinite" />
            </circle>
          </g>
        );
      })}
    </svg>
  );
}

export default function StepFinalize({ codes, files, scanStore, onNewScan }) {
  // Tạm thời chỉ xác nhận trên giao diện — CHƯA lưu / đồng bộ đi đâu (Google Sheets làm sau)
  const [confirmed, setConfirmed] = useState(false);

  // State để hiện Modal ảnh
  const [evidence, setEvidence] = useState(null);

  const totalFiles = new Set(codes.map(c => c.src)).size;

  return (
    <div style={{ flex: 1, position: 'relative' }}>

      {/* ── 🆕 MODAL HIỆN ẢNH KHI CLICK DÒNG ── */}
      {evidence && (
        <div className="evidence-modal" onClick={() => setEvidence(null)}>
          <div className="evidence-modal__content" onClick={e => e.stopPropagation()}>
            <div className="evidence-modal__header">
              <span>BẰNG CHỨNG QUÉT: {evidence.name}{evidence.code && <> — <span style={{ color: 'var(--yellow)' }}>{evidence.code}</span></>}</span>
              <button onClick={() => setEvidence(null)}>✕</button>
            </div>
            <div className="evidence-modal__body">
              <div className="scan-viewport__frame">
                <img src={evidence.url} alt="evidence" style={{ width: '100%', display: 'block' }} />
                <MiniOverlay boxes={evidence.boxes} highlight={evidence.code} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="summary-cards">
        <div className="summary-card">
            <div className="summary-card__value" style={{ color: 'var(--green-100)' }}>{codes.length}</div>
            <div className="summary-card__label">QR CODES</div>
        </div>
        <div className="summary-card">
            <div className="summary-card__value" style={{ color: 'var(--cyan)' }}>{totalFiles}</div>
            <div className="summary-card__label">FILES</div>
        </div>
      </div>

      {/* Bảng mã đã quét — click 1 dòng để xem ảnh bằng chứng */}
      <div className="finalize-table">
        <div className="finalize-table__header finalize-table__header--codes">
          <span>#</span><span>QR CODE</span><span>FILE</span>
        </div>

        <div style={{ maxHeight: '65vh', overflowY: 'auto' }}>
          {codes.length === 0 && (
            <div className="results-table__empty">Chưa đọc được mã QR nào.</div>
          )}
          {codes.map((c, i) => (
            <div
              key={i}
              className="finalize-table__row finalize-table__row--codes clickable-row"
              onClick={() => {
                const storeData = scanStore[files.findIndex(f => f.name === c.src)];
                if (!storeData) return;
                const frame = storeData.evidence?.[c.code]; // video: dùng đúng frame đọc ra mã này
                setEvidence(frame
                  ? { url: `data:image/jpeg;base64,${frame.image}`, boxes: [{ points: frame.points, code: c.code }], name: c.src, code: c.code }
                  : { url: storeData.previewUrl, boxes: storeData.boxes, name: c.src, code: c.code });
              }}
            >
              <span style={{ color: 'var(--green-muted)' }}>{i + 1}</span>
              <span style={{ color: 'var(--green-100)', fontWeight: 'bold', wordBreak: 'break-all' }}>{c.code}</span>
              <span className="results-table__src">{c.src}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: '20px' }}>
        {confirmed ? (
          <div className="sync-success">
            <div className="sync-success__title">ĐÃ XÁC NHẬN {codes.length} MÃ</div>
            <button className="btn-new-scan" onClick={onNewScan}>＋ QUÉT MỚI</button>
          </div>
        ) : (
          <button className="btn-sync btn-sync--active" onClick={() => setConfirmed(true)} disabled={codes.length === 0}>
            ✓ XÁC NHẬN
          </button>
        )}
      </div>
    </div>
  );
}