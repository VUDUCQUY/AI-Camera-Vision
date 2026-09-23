import { useState, useEffect, useRef } from 'react';
import heic2any from 'heic2any';

// Production (npm run build): backend phục vụ luôn giao diện → gọi cùng origin ('').
// Dev (npm start): backend chạy riêng ở cổng 8000. Ghi đè bằng biến REACT_APP_API_BASE nếu cần.
const API_BASE = process.env.REACT_APP_API_BASE
  ?? (process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:8000' : '');

// ── Bounding box overlay: Thêm fill="none" để không bị che ảnh ──
function BoundingBoxOverlay({ boxes }) {
  if (!boxes || !boxes.length) return null;

  return (
    <svg
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', background: 'transparent' }}
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      fill="none"
    >
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="0.004" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {boxes.map((box, i) => {
        const pts = box.points;
        const polyPts = pts.map(p => p.join(',')).join(' ');
        const tlx = Math.min(...pts.map(p => p[0]));
        const tly = Math.min(...pts.map(p => p[1]));

        const label = box.label || `QR ${i + 1}`;
        const labelWidth = Math.max(0.12, label.length * 0.014 + 0.02);

        return (
          <g key={i} filter="url(#glow)">
            <polygon
              points={polyPts}
              fill="rgba(0, 255, 136, 0.05)"
              stroke="#00ff88"
              strokeWidth="0.004"
              strokeDasharray="0.016 0.008"
            >
              <animate attributeName="stroke-dashoffset" from="0" to="-0.048" dur="1.2s" repeatCount="indefinite" />
            </polygon>

            {/* Corner brackets */}
            {pts.map((p, ci) => {
              const prev = pts[(ci + pts.length - 1) % pts.length];
              const next = pts[(ci + 1) % pts.length];
              const armLen = 0.025;
              const dx1 = (prev[0] - p[0]), dy1 = (prev[1] - p[1]);
              const dx2 = (next[0] - p[0]), dy2 = (next[1] - p[1]);
              const len1 = Math.hypot(dx1, dy1) || 1;
              const len2 = Math.hypot(dx2, dy2) || 1;
              return (
                <g key={ci} stroke="#00ffcc" strokeWidth="0.007" fill="none">
                  <line x1={p[0]} y1={p[1]} x2={p[0] + (dx1 / len1) * armLen} y2={p[1] + (dy1 / len1) * armLen} />
                  <line x1={p[0]} y1={p[1]} x2={p[0] + (dx2 / len2) * armLen} y2={p[1] + (dy2 / len2) * armLen} />
                </g>
              );
            })}

            <rect x={tlx} y={tly - 0.038} width={labelWidth} height={0.035} fill="rgba(0, 26, 10, 0.8)" rx="0.004" stroke="#00ff8866" strokeWidth="0.002" />
            <text x={tlx + 0.005} y={tly - 0.012} fill="#00ff88" fontSize="0.022" fontFamily="monospace" fontWeight="bold">
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function StepScan({ files, saved, onNext }) {
  // Quay lại từ bước 3 (BACK) → dùng lại kết quả lượt quét trước thay vì bắt đầu trắng
  const restored = useRef(Object.keys(saved?.scanStore || {}).length > 0);

  const [scanning, setScanning]       = useState(false);
  const [progress, setProgress]       = useState(restored.current ? 100 : 0);
  const [results, setResults]         = useState(restored.current ? saved.results : []);
  const [codes, setCodes]             = useState(restored.current ? saved.codes : []); // mọi mã QR đọc được: [{ code, src }]
  const [done, setDone]               = useState(restored.current);

  // STATE MỚI ĐỂ LƯU KẾT QUẢ TỪNG FILE
  const [scanStore, setScanStore]     = useState(restored.current ? saved.scanStore : {}); // { index: { boxes, previewUrl, pallets } }
  const [viewIndex, setViewIndex]     = useState(0);  // Đang hiển thị ảnh nào
  const [streamKey, setStreamKey]     = useState(0);
  const uploads = useRef(new Map());  // File → Promise<tên file trên server | null>  // đổi mỗi lần quét → <img> mở lại kết nối stream (nếu server vừa khởi động lại)

  useEffect(() => {
    if (restored.current) return; // đã có kết quả, không tạo lại preview / upload lại video
    if (files.length) {
      const initialStore = {};
      files.forEach((file, i) => {
        const isHeic = file.name.toLowerCase().endsWith('.heic') || file.name.toLowerCase().endsWith('.heif');
        initialStore[i] = {
          previewUrl: isHeic ? null : URL.createObjectURL(file),
          isHeic: isHeic,
          boxes: [],
          pallets: []
        };

        // Chuyển đổi HEIC nếu cần
        if (isHeic) {
          heic2any({ blob: file, toType: 'image/jpeg', quality: 0.6 })
            .then(blob => {
              const url = URL.createObjectURL(Array.isArray(blob) ? blob[0] : blob);
              setScanStore(prev => ({
                ...prev,
                [i]: { ...prev[i], previewUrl: url }
              }));
            })
            .catch(e => {
              console.error("HEIC conversion error in StepScan:", e);
              setScanStore(prev => ({
                ...prev,
                [i]: { ...prev[i], previewUrl: URL.createObjectURL(file) }
              }));
            });
        }

        // Tự động upload video để có thể stream MJPEG ngay.
        // Mỗi file chỉ upload 1 lần (React dev chạy effect 2 lần → trước đây bị upload trùng).
        if (file.type.startsWith('video/') && !uploads.current.has(file)) {
          const formData = new FormData();
          formData.append('file', file);
          const upload = fetch(`${API_BASE}/upload-video`, { method: 'POST', body: formData })
            .then(res => res.json())
            .then(data => {
              if (data.status !== 'ok') return null;
              setScanStore(prev => ({
                ...prev,
                [i]: { ...prev[i], serverFilename: data.filename }
              }));
              return data.filename;
            })
            .catch(e => { console.error("Auto-upload error:", e); return null; });
          uploads.current.set(file, upload);
        }
      });
      setScanStore(initialStore);
      setViewIndex(0);
    }
  }, [files]);

  const startScan = async () => {
    setStreamKey(Date.now());
    setScanning(true);
    setResults([]);
    setCodes([]);
    setProgress(0);
    setDone(false);

    const allPallets = [];
    const allCodes = [];

    for (let i = 0; i < files.length; i++) {
      setViewIndex(i); // Nhảy view tới ảnh đang quét
      setProgress(Math.round((i / files.length) * 100));

      const formData = new FormData();
      // Video: đợi upload nền xong (nếu chưa xong) để quét ĐÚNG file mà màn hình đang stream
      const serverFilename = files[i].type.startsWith('video/')
        ? (scanStore[i]?.serverFilename || await uploads.current.get(files[i]))
        : null;
      if (serverFilename) {
        // Video đã có sẵn trên server (/upload-video) → chỉ gửi tên, không upload lại cả file
        formData.append('file', new Blob([]), files[i].name);
        formData.append('server_filename', serverFilename);
      } else {
        formData.append('file', files[i]);
      }

      // Nếu là video, lấy nhanh thumbnail để hiện lên luôn
      if (files[i].type.startsWith('video/')) {
        try {
          const thumbRes = await fetch(`${API_BASE}/get-thumbnail`, { method: 'POST', body: formData });
          const thumbData = await thumbRes.json();
          if (thumbData.status === 'ok') {
            setScanStore(prev => ({
              ...prev,
              [i]: { ...prev[i], previews: [`data:image/jpeg;base64,${thumbData.thumbnail}`], slideshowIndex: 0 }
            }));
          }
        } catch (e) { console.error("Thumb error:", e); }
      }

      try {
        const res  = await fetch(`${API_BASE}/process-image`, { method: 'POST', body: formData });
        const data = await res.json();

        if (data.status === 'ok') {
          const filePallets = data.pallets.map(p => ({ ...p, _src: files[i].name }));
          allPallets.push(...filePallets);
          allCodes.push(...(data.codes || []).map(code => ({ code, src: files[i].name })));
          setCodes([...allCodes]);

          // Cập nhật kho dữ liệu cho ảnh i
          setScanStore(prev => ({
            ...prev,
            [i]: {
              ...prev[i],
              boxes: data.boxes || [],
              evidence: data.evidence || {}, // video: frame mà từng mã được đọc ra
              pallets: filePallets,
              previews: data.previews ? data.previews.map(p => `data:image/jpeg;base64,${p}`) : [],
              slideshowIndex: 0
            }
          }));
        }
      } catch (e) {
        console.error(e);
      }
    }

    setProgress(100);
    setResults(allPallets);
    setScanning(false);
    setDone(true);
  };

  // Logic Slideshow tự động
  const previewsCount = scanStore[viewIndex]?.previews?.length || 0;
  useEffect(() => {
    let interval;
    if (done && previewsCount > 1) {
      interval = setInterval(() => {
        setScanStore(prev => {
          const current = prev[viewIndex];
          if (!current || !current.previews) return prev;
          return {
            ...prev,
            [viewIndex]: {
              ...current,
              slideshowIndex: (current.slideshowIndex + 1) % current.previews.length
            }
          };
        });
      }, 800);
    }
    return () => clearInterval(interval);
  }, [done, viewIndex, previewsCount]);

  // Lấy dữ liệu của ảnh đang được chọn để hiển thị
  const currentView = scanStore[viewIndex] || {};

  return (
    <div className="stepscan-layout">
      <div className="stepscan-left">
        <div className="scan-viewport">
          {currentView.previewUrl ? (
            <>
              {files[viewIndex]?.type.startsWith('video/') ? (
                // Chỉ hiện stream nếu server báo đã nhận file xong (để tránh lỗi 404/ảnh vỡ)
                currentView.serverFilename ? (
                  <div className="scan-viewport__frame">
                    {/* Frame AI từ server đã vẽ sẵn khung YOLO đúng vị trí → không phủ overlay
                        (overlay gộp box của nhiều frame khác nhau, camera di chuyển sẽ lệch) */}
                    <img
                      key={streamKey}
                      src={`${API_BASE}/video-stream/${currentView.serverFilename}?t=${streamKey}`}
                      alt="video stream"
                      className="scan-viewport__img"
                    />
                  </div>
                ) : (
                  <div className="scan-viewport__loading-video" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#000' }}>
                    <div className="spinner" style={{ border: '3px solid #333', borderTop: '3px solid #00ff88', borderRadius: '50%', width: '30px', height: '30px', animation: 'spin 1s linear infinite', marginRight: '10px' }} />
                    <span style={{ color: '#00ff88', lineHeight: 'normal', whiteSpace: 'nowrap' }}>PREPARING VIDEO STREAM...</span>
                  </div>
                )
              ) : (
                // Khung bọc vừa khít ảnh → toạ độ box (0..1) khớp đúng ảnh, không lệch sang phần nền đen
                <div className="scan-viewport__frame">
                  <img src={currentView.previewUrl} alt="scan" className="scan-viewport__img" />
                  <BoundingBoxOverlay boxes={currentView.boxes} />
                </div>
              )}

              {scanning && viewIndex === Math.floor((progress / 100) * files.length) && (
                <div className="scan-viewport__scanline-wrap" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                  {/* Tia laser quét qua quét lại cho ngầu */}
                  <div className="scan-viewport__scanline" style={{ height: '2px', background: 'linear-gradient(to right, transparent, #00ff88, transparent)', boxShadow: '0 0 15px #00ff88', position: 'absolute', width: '100%', top: '0', animation: 'scan 2s linear infinite' }} />
                  
                  {files[viewIndex]?.type.startsWith('video/') && (
                    <div className="scan-viewport__loading-video-mini" style={{ position: 'absolute', bottom: '20px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(0,0,0,0.6)', padding: '8px 20px', borderRadius: '30px', display: 'flex', alignItems: 'center', border: '1px solid #00ff8844', backdropFilter: 'blur(4px)' }}>
                      <div className="spinner-mini" style={{ border: '2px solid #333', borderTop: '2px solid #00ff88', borderRadius: '50%', width: '16px', height: '16px', animation: 'spin 1s linear infinite', marginRight: '10px' }} />
                      <span style={{ color: '#00ff88', fontSize: '12px', fontWeight: 'bold', letterSpacing: '1px', lineHeight: 'normal', whiteSpace: 'nowrap' }}>AI SCANNING VIDEO...</span>
                    </div>
                  )}
                </div>
              )}

              <div className="scan-viewport__badge">
                <span>{files[viewIndex]?.name}</span>
              </div>
            </>
          ) : (
            <div className="scan-viewport__placeholder">
              {currentView.isHeic ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div className="spinner" style={{ marginBottom: '10px' }}></div>
                  <span>PREPARING HEIC IMAGE...</span>
                </div>
              ) : "NO IMAGE LOADED"}
            </div>
          )}
        </div>

      </div>

      <div className="stepscan-right">
        <div className="scan-dots-row">
          {files.map((_, i) => (
            <div
              key={i}
              className={`scan-dot ${
                progress >= Math.round(((i + 1) / files.length) * 100) ? 'scan-dot--done' : ''
              } ${
                i === Math.floor((progress / 100) * files.length) && scanning ? 'scan-dot--active' : ''
              } ${
                viewIndex === i ? 'scan-dot--selected' : ''
              }`}
              onClick={() => (done || !scanning) && setViewIndex(i)}
              style={{ cursor: (done || !scanning) ? 'pointer' : 'default' }}
            />
          ))}
        </div>

        <div className="scan-complete-label">
          {done ? "Scan Complete" : scanning ? `Scanning... ${progress}%` : "Ready"}
        </div>

        <div className="stepscan-btns">
          {!done ? (
            <button className={`btn-scan-action ${scanning ? 'btn-scan-action--scanning' : 'btn-scan-action--primary'}`}
                    onClick={startScan} disabled={scanning}>
              {scanning ? '⟳ SCANNING...' : '▶ START SCAN'}
            </button>
          ) : (
            <>
              <button className="btn-scan-action btn-scan-action--secondary" onClick={startScan}>↺ RESCAN</button>
              <button className="btn-scan-action btn-scan-action--primary" onClick={() => onNext(results, scanStore, codes)}>FINALIZE</button>
            </>
          )}
        </div>
      </div>

      <div className="results-table stepscan-codes">
        <div className="results-table__header results-table__header--codes">
          <span>STT</span><span>QR CODE ({codes.length})</span><span>FILE</span>
        </div>

        {codes.length === 0 ? (
          <div className="results-table__empty">
            {scanning ? '⟳ PROCESSING...' : 'No QR decoded.'}
          </div>
        ) : codes.map((c, i) => (
          <div key={i} className="results-table__row results-table__row--codes">
            <span className="results-table__num">{i + 1}</span>
            <span className="results-table__code">{c.code}</span>
            <span className="results-table__src">{c.src}</span>
          </div>
        ))}
      </div>
    </div>
  );
}