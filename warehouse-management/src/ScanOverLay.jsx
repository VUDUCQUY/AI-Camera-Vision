export default function ScanOverLay({ active }) {
  if (!active) return null;
  return (
    <div className="scan-overlay">
      <div className="scan-overlay__line" />
    </div>
  );
}