import { useState, useRef } from 'react';
import ScanOverLay from './ScanOverLay';

export default function StepUpload({ onNext }) {
  const [files, setFiles] = useState([]);
  const [previews, setPreviews] = useState([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const addFiles = (newFiles) => {
    const arr = Array.from(newFiles).filter(f => f.type.startsWith('image/') || f.type.startsWith('video/'));
    if (!arr.length) return;
    setFiles(arr);
    setPreviews(arr.map(f => URL.createObjectURL(f)));
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    setFiles([]);
    setPreviews([]);
  };

  const zoneClass = [
    'upload-zone',
    dragging ? 'upload-zone--dragging' : '',
    files.length ? 'upload-zone--has-files' : '',
  ].filter(Boolean).join(' ');

  return (
    <div style={{ flex: 1 }}>
      <div
        className={zoneClass}
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onClick={() => !files.length && inputRef.current.click()}
      >
        <ScanOverLay active={dragging} />

        {!files.length ? (
          <div className="upload-zone__empty">
            <div className="upload-zone__icon">📦</div>
            <div className="upload-zone__title">DRAG AND DROP</div>
            <div className="upload-zone__subtitle">image or video files here, or click to browse</div>
          </div>
        ) : (
          <>
            {previews.map((url, i) => (
              <div key={i} className="upload-zone__preview">
                {files[i]?.type.startsWith('video/') ? (
                  <video src={url} className="upload-zone__preview-img" muted />
                ) : (
                  <img src={url} alt="" className="upload-zone__preview-img" />
                )}
                <div className="upload-zone__preview-label">{files[i]?.name}</div>
              </div>
            ))}
            <button className="btn-clear" onClick={handleClear}>✕ CLEAR</button>
          </>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*,video/*"
        hidden
        onChange={e => addFiles(e.target.files)}
      />

      <div className="upload-actions">
        <button
          className="btn-browse"
          onClick={() => inputRef.current.click()}
        >
          {files.length ? `CHANGE FILES (${files.length})` : 'BROWSE FILES'}
        </button>

        <button
          className={`btn-next ${files.length ? 'btn-next--enabled' : 'btn-next--disabled'}`}
          onClick={() => files.length && onNext(files)}
          disabled={!files.length}
        >
          NEXT: START SCAN →
        </button>
      </div>
    </div>
  );
}