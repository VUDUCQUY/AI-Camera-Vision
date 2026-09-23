import { useState, useRef } from 'react';
import ScanOverLay from './ScanOverLay';
import heic2any from 'heic2any';

export default function StepUpload({ onNext }) {
  const [items, setItems] = useState([]); // [{ file, preview, isHeic, loading }]
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const addFiles = async (newFiles) => {
    const rawFiles = Array.from(newFiles);
    const validFiles = rawFiles.filter(f => {
      const ext = f.name.toLowerCase().split('.').pop();
      const isHeicExt = ['heic', 'heif'].includes(ext);
      return f.type.startsWith('image/') || f.type.startsWith('video/') || isHeicExt;
    });

    if (!validFiles.length) return;

    // Tạo các entry mới
    const newItems = validFiles.map(file => {
      const ext = file.name.toLowerCase().split('.').pop();
      const isHeic = ['heic', 'heif'].includes(ext);
      return {
        file,
        preview: isHeic ? 'LOADING' : URL.createObjectURL(file),
        isHeic,
        loading: isHeic
      };
    });

    setItems(newItems);

    // Chuyển đổi HEIC không đồng bộ
    newItems.forEach(async (item, index) => {
      if (item.isHeic) {
        try {
          // Kiểm tra heic2any có tồn tại không (phòng hờ lỗi import)
          const converter = typeof heic2any === 'function' ? heic2any : (heic2any?.default || null);
          
          if (!converter) {
            throw new Error("heic2any not found");
          }

          const blob = await converter({
            blob: item.file,
            toType: 'image/jpeg',
            quality: 0.5
          });
          
          const convertedBlob = Array.isArray(blob) ? blob[0] : blob;
          const url = URL.createObjectURL(convertedBlob);
          
          setItems(prev => {
            const next = [...prev];
            if (next[index]) {
              next[index] = { ...next[index], preview: url, loading: false };
            }
            return next;
          });
        } catch (e) {
          console.error("HEIC error:", e);
          setItems(prev => {
            const next = [...prev];
            if (next[index]) {
              next[index] = { ...next[index], preview: URL.createObjectURL(item.file), loading: false };
            }
            return next;
          });
        }
      }
    });
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    // Revoke URLs to avoid memory leaks
    items.forEach(item => {
      if (item.preview && item.preview.startsWith('blob:')) {
        URL.revokeObjectURL(item.preview);
      }
    });
    setItems([]);
  };

  const zoneClass = [
    'upload-zone',
    dragging ? 'upload-zone--dragging' : '',
    items.length ? 'upload-zone--has-files' : '',
  ].filter(Boolean).join(' ');

  const handleNext = () => {
    if (!items.length) return;
    onNext(items.map(it => it.file));
  };

  return (
    <div style={{ flex: 1 }}>
      <div
        className={zoneClass}
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onClick={() => !items.length && inputRef.current.click()}
      >
        <ScanOverLay active={dragging} />

        {!items.length ? (
          <div className="upload-zone__empty">
            <div className="upload-zone__icon">📦</div>
            <div className="upload-zone__title">DRAG AND DROP</div>
            <div className="upload-zone__subtitle">image or video files here, or click to browse</div>
          </div>
        ) : (
          <>
            {items.map((item, i) => (
              <div key={i} className="upload-zone__preview">
                {item.preview === 'LOADING' ? (
                  <div className="upload-zone__preview-img upload-zone__preview-img--loading">
                    <div className="spinner"></div>
                    <span style={{ fontSize: '9px', marginTop: '4px' }}>CONVERTING...</span>
                  </div>
                ) : item.file?.type.startsWith('video/') ? (
                  <video src={item.preview} className="upload-zone__preview-img" muted />
                ) : (
                  <img src={item.preview} alt="" className="upload-zone__preview-img" />
                )}
                <div className="upload-zone__preview-label">{item.file?.name}</div>
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
        accept="image/*,video/*,.heic,.heif"
        hidden
        onChange={e => addFiles(e.target.files)}
      />

      <div className="upload-actions">
        <button
          className="btn-browse"
          onClick={() => inputRef.current.click()}
        >
          {items.length ? `CHANGE FILES (${items.length})` : 'BROWSE FILES'}
        </button>

        <button
          className={`btn-next ${items.length ? 'btn-next--enabled' : 'btn-next--disabled'}`}
          onClick={handleNext}
          disabled={!items.length}
        >
          NEXT: START SCAN →
        </button>
      </div>
    </div>
  );
}