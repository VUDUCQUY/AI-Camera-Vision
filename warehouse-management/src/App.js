import { useState } from 'react';
import './Warehouse.css';

import StepUpload    from './StepUpload';
import StepScan      from './StepScan';
import StepFinalize  from './StepFinalize';
import Sidebar       from './Sidebar';
import HistoryTable  from './HistoryTable';

export default function App() {
  const [step,    setStep]      = useState(0);
  const [files,   setFiles]     = useState([]);
  const [pallets, setPallets]   = useState([]);
  const [codes,   setCodes]     = useState([]); // mã QR đã quét: [{ code, src }]
  const [history, setHistory]   = useState([]);

  // 🆕 Kho lưu trữ dữ liệu quét (ảnh preview + boxes)
  const [scanStore, setScanStore] = useState({});

  const clearHistory = () => setHistory([]);

  // Hàm reset để quét đợt mới
  const resetAll = () => {
    setStep(0);
    setFiles([]);
    setPallets([]);
    setCodes([]);
    setScanStore({}); // Xóa sạch kho khi quét mới
  };

  return (
    <div className="app-root">
      <div className="app-window">
        <div className="title-bar">
          <span className="title-bar__text">AI CAMERA WAREHOUSE MANAGEMENT</span>
        </div>

        <div className="app-body">
          <div className="main-area">
            {/* BƯỚC 1: UPLOAD */}
            {step === 0 && (
              <StepUpload onNext={(f) => { setFiles(f); setPallets([]); setCodes([]); setScanStore({}); setStep(1); }} />
            )}

            {/* BƯỚC 2: SCAN - saved: khôi phục kết quả khi bấm BACK từ bước 3 */}
            {step === 1 && (
              <StepScan
                files={files}
                saved={{ results: pallets, scanStore, codes }}
                onNext={(r, finalStore, scannedCodes) => {
                  setPallets(r);
                  setCodes(scannedCodes || []);
                  if(finalStore) setScanStore(finalStore); // Lưu lại kho dữ liệu
                  setStep(2);
                }}
              />
            )}

            {/* BƯỚC 3: FINALIZE - Truyền files và scanStore vào để click hiện ảnh */}
            {step === 2 && (
              <StepFinalize
                codes={codes}
                files={files}
                scanStore={scanStore}
                onNewScan={resetAll}
              />
            )}

            <HistoryTable history={history} onClear={clearHistory} />
          </div>

          <Sidebar
            step={step}
            files={files}
            pallets={pallets}
            onBack={() => setStep(s => s - 1)}
          />
        </div>
      </div>
    </div>
  );
}