import { useMemo, useState } from 'react';
import { MapPin, ShoppingCart, ArrowRightLeft, Info } from 'lucide-react';

const ZONE_COLORS = {
  gondola: { bg: 'rgba(34, 197, 94, 0.35)', border: 'rgb(34, 197, 94)', label: 'Góndola', icon: ShoppingCart },
  pasillo: { bg: 'rgba(107, 114, 128, 0.25)', border: 'rgb(107, 114, 128)', label: 'Pasillo', icon: ArrowRightLeft },
  caja: { bg: 'rgba(59, 130, 246, 0.35)', border: 'rgb(59, 130, 246)', label: 'Caja', icon: MapPin },
  default: { bg: 'rgba(234, 179, 8, 0.3)', border: 'rgb(234, 179, 8)', label: 'Zona', icon: Info },
};

function getZoneType(zone) {
  if (zone.es_gondola === true) return 'gondola';
  const id = (zone.zone_id || '').toLowerCase();
  if (id.includes('caja') || id.includes('checkout') || id.includes('pago')) return 'caja';
  if (id.includes('pasillo') || id.includes('aisle') || id.includes('corredor')) return 'pasillo';
  return 'default';
}

function polygonCentroid(polygon) {
  if (!polygon || polygon.length < 3) return [0, 0];
  let cx = 0, cy = 0;
  for (const [x, y] of polygon) { cx += x; cy += y; }
  return [cx / polygon.length, cy / polygon.length];
}

function polygonArea(polygon) {
  if (!polygon || polygon.length < 3) return 0;
  let area = 0;
  for (let i = 0; i < polygon.length; i++) {
    const [x1, y1] = polygon[i];
    const [x2, y2] = polygon[(i + 1) % polygon.length];
    area += x1 * y2 - x2 * y1;
  }
  return Math.abs(area) / 2;
}

function transformToTopDown(zones, videoWidth, videoHeight, mapWidth, mapHeight, padding = 40) {
  if (!zones || zones.length === 0) return [];

  const allPoints = zones.flatMap(z => z.poligono || []);
  if (allPoints.length === 0) return [];

  const minX = Math.min(...allPoints.map(p => p[0]));
  const maxX = Math.max(...allPoints.map(p => p[0]));
  const minY = Math.min(...allPoints.map(p => p[1]));
  const maxY = Math.max(...allPoints.map(p => p[1]));

  const sourceWidth = maxX - minX;
  const sourceHeight = maxY - minY;

  const scaleX = (mapWidth - 2 * padding) / sourceWidth;
  const scaleY = (mapHeight - 2 * padding) / sourceHeight;
  const scale = Math.min(scaleX, scaleY);

  const offsetX = padding + (mapWidth - 2 * padding - sourceWidth * scale) / 2 - minX * scale;
  const offsetY = padding + (mapHeight - 2 * padding - sourceHeight * scale) / 2 - minY * scale;

  return zones.map(zone => {
    const transformedPolygon = (zone.poligono || []).map(([x, y]) => [
      x * scale + offsetX,
      y * scale + offsetY,
    ]);
    const [cx, cy] = polygonCentroid(transformedPolygon);
    const area = polygonArea(transformedPolygon);
    const type = getZoneType(zone);
    const color = ZONE_COLORS[type];
    return {
      ...zone,
      polygon: transformedPolygon,
      centroid: [cx, cy],
      area,
      type,
      color,
      visits: zone.visitas_unicas || 0,
      occupancyPct: zone.pct_tiempo_ocupada || 0,
    };
  });
}

function polygonToPath(polygon) {
  if (!polygon || polygon.length < 3) return '';
  const [first, ...rest] = polygon;
  return `M ${first[0]} ${first[1]} ${rest.map(([x, y]) => `L ${x} ${y}`).join(' ')} Z`;
}

export function StoreMapPanel({ zonasData, conteoZonas, videoWidth, videoHeight }) {
  const [hoveredZone, setHoveredZone] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [mapSize, setMapSize] = useState({ width: 600, height: 450 });

  const mergedZones = useMemo(() => {
    if (!zonasData?.zonas) return [];
    const conteoMap = new Map((conteoZonas?.zonas || []).map(z => [z.zone_id, z]));
    return zonasData.zonas.map(zone => ({
      ...zone,
      ...conteoMap.get(zone.zone_id),
    }));
  }, [zonasData, conteoZonas]);

  const transformedZones = useMemo(() => {
    if (!mergedZones.length) return [];
    return transformToTopDown(
      mergedZones,
      videoWidth || 768,
      videoHeight || 576,
      mapSize.width,
      mapSize.height
    );
  }, [mergedZones, videoWidth, videoHeight, mapSize]);

  const hasData = transformedZones.length > 0;

  if (!hasData) {
    return (
      <div className="overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]">
        <div className="flex min-h-72 items-center justify-center p-4 text-sm text-[var(--ink-muted)]">
          El mapa de la tienda se generará después del análisis con zonas detectadas.
        </div>
      </div>
    );
  }

  const totalVisits = transformedZones.reduce((sum, z) => sum + (z.visits || 0), 0);
  const gondolaCount = transformedZones.filter(z => z.type === 'gondola').length;
  const pasilloCount = transformedZones.filter(z => z.type === 'pasillo').length;
  const cajaCount = transformedZones.filter(z => z.type === 'caja').length;

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--panel-border)] px-4 py-3">
        <h3 className="text-sm font-medium">Mapa de tienda (vista cenital)</h3>
        <div className="flex gap-1 text-xs text-[var(--ink-muted)] px-2 py-1 rounded bg-[var(--background)]">
          <span>{gondolaCount} góndolas</span>
          <span>{pasilloCount} pasillos</span>
          <span>{cajaCount} cajas</span>
        </div>
      </div>

      <div className="relative p-4" onMouseMove={e => {
        const rect = e.currentTarget.getBoundingClientRect();
        setMapSize({ width: rect.width, height: rect.height });
      }}>
        <svg
          width="100%"
          height="100%"
          viewBox={`0 0 ${mapSize.width} ${mapSize.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="w-full h-full"
        >
          <rect
            x="0" y="0"
            width={mapSize.width}
            height={mapSize.height}
            fill="var(--background)"
            rx="8"
          />

          {transformedZones.map(zone => {
            const isHovered = hoveredZone === zone.zone_id;
            const isSelected = selectedZone === zone.zone_id;
            const path = polygonToPath(zone.polygon);
            const [cx, cy] = zone.centroid;
            return (
              <g
                key={zone.zone_id}
                onMouseEnter={() => setHoveredZone(zone.zone_id)}
                onMouseLeave={() => setHoveredZone(null)}
                onClick={() => setSelectedZone(s => s === zone.zone_id ? null : zone.zone_id)}
                style={{ cursor: 'pointer' }}
              >
                <path
                  d={path}
                  fill={zone.color.bg}
                  stroke={isSelected ? 'var(--accent)' : zone.color.border}
                  strokeWidth={isSelected ? 3 : isHovered ? 2.5 : 1.5}
                  strokeDasharray={zone.type === 'pasillo' ? '6,4' : 'none'}
                  opacity={isHovered || isSelected ? 1 : 0.85}
                  transition="stroke-width 0.15s, opacity 0.15s"
                />
                {isHovered || isSelected ? (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={Math.max(16, Math.min(28, Math.sqrt(zone.area) / 3))}
                    fill="var(--background)"
                    stroke="var(--accent)"
                    strokeWidth={2}
                  />
                ) : null}
                <text
                  x={cx}
                  y={cy + 4}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={Math.max(9, Math.min(12, Math.sqrt(zone.area) / 8))}
                  fill="var(--ink)"
                  fontWeight={isSelected ? 700 : 500}
                  pointerEvents="none"
                >
                  {zone.zone_id}
                </text>
              </g>
            );
          })}

          {hoveredZone && (
            <g pointerEvents="none">
              {transformedZones
                .filter(z => z.zone_id === hoveredZone)
                .map(zone => {
                  const [cx, cy] = zone.centroid;
                  const color = zone.color;
                  const Icon = color.icon;
                  return (
                    <g key={zone.zone_id} transform={`translate(${cx}, ${cy - 50})`}>
                      <rect
                        x="-70" y="-40"
                        width="140" height="70"
                        rx="6"
                        fill="var(--panel)"
                        stroke="var(--panel-border)"
                        strokeWidth="1"
                        filter="drop-shadow(0 4px 6px rgba(0,0,0,0.1))"
                      />
                      <text x="0" y="-18" textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--ink)">
                        {zone.zone_id}
                      </text>
                      <text x="0" y="-4" textAnchor="middle" fontSize="10" fill="var(--ink-muted)">
                        {color.label} • {zone.visits} visitas
                      </text>
                      <text x="0" y="10" textAnchor="middle" fontSize="10" fill="var(--ink)">
                        {zone.occupancyPct?.toFixed(1)}% ocupación
                      </text>
                    </g>
                  );
                })}
            </g>
          )}
        </svg>

        <div className="absolute bottom-4 left-4 right-4 flex flex-wrap justify-center gap-3 text-xs text-[var(--ink-muted)]">
          {Object.entries(ZONE_COLORS).map(([key, val]) => (
            <span key={key} className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-[var(--background)] border border-[var(--panel-border)]">
              <span
                className="w-3 h-3 rounded"
                style={{ backgroundColor: val.bg, border: `1px solid ${val.border}` }}
              />
              {val.label}
            </span>
          ))}
        </div>
      </div>

      {selectedZone && (
        <div className="border-t border-[var(--panel-border)] px-4 py-3 bg-[var(--background)]">
          {transformedZones
            .filter(z => z.zone_id === selectedZone)
            .map(zone => {
              const color = zone.color;
              const Icon = color.icon;
              return (
                <div key={zone.zone_id} className="flex items-center gap-3 text-sm">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: color.bg, border: `1px solid ${color.border}` }}
                  >
                    <Icon size={16} style={{ color: color.border }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{zone.zone_id} — {color.label}</p>
                    <p className="text-xs text-[var(--ink-muted)]">
                      Visitas: {zone.visits} • Ocupación: {zone.occupancyPct?.toFixed(1)}% • Área: {Math.round(zone.area)}px²
                    </p>
                  </div>
                  <button
                    onClick={() => setSelectedZone(null)}
                    className="text-[var(--ink-muted)] hover:text-[var(--ink)]"
                    aria-label="Cerrar detalle"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
        </div>
      )}

      <div className="border-t border-[var(--panel-border)] px-4 py-3 text-xs text-[var(--ink-muted)] flex flex-wrap gap-4">
        <span>Total visitas: <strong className="text-[var(--ink)]">{totalVisits}</strong></span>
        <span>Zonas detectadas: <strong className="text-[var(--ink)]">{transformedZones.length}</strong></span>
        <span className="flex-1"></span>
        <span>Click para detalles • Hover para info</span>
      </div>
    </div>
  );
}