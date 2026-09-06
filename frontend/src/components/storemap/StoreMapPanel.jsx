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

function computeProjection(zones, mapWidth, mapHeight, padding = 40) {
  const allPoints = zones.flatMap(z => z.poligono || []);
  if (allPoints.length === 0) return null;

  const minX = Math.min(...allPoints.map(p => p[0]));
  const maxX = Math.max(...allPoints.map(p => p[0]));
  const minY = Math.min(...allPoints.map(p => p[1]));
  const maxY = Math.max(...allPoints.map(p => p[1]));

  const sourceWidth = maxX - minX || 1;
  const sourceHeight = maxY - minY || 1;

  const scaleX = (mapWidth - 2 * padding) / sourceWidth;
  const scaleY = (mapHeight - 2 * padding) / sourceHeight;
  const scale = Math.min(scaleX, scaleY);

  const offsetX = padding + (mapWidth - 2 * padding - sourceWidth * scale) / 2 - minX * scale;
  const offsetY = padding + (mapHeight - 2 * padding - sourceHeight * scale) / 2 - minY * scale;

  return {
    project: (x, y) => [x * scale + offsetX, y * scale + offsetY],
  };
}

function transformToTopDown(zones, projection) {
  if (!zones || zones.length === 0 || !projection) return [];

  return zones.map(zone => {
    const transformedPolygon = (zone.poligono || []).map(([x, y]) => projection.project(x, y));
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

// Busca el índice del frame de tracking.jsonl cuyo timestamp está más cerca
// del tiempo actual del video (búsqueda binaria porque los frames vienen
// ordenados por timestamp).
function findClosestFrameIndex(frames, timeMs) {
  if (!frames || frames.length === 0) return -1;
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].timestamp_ms < timeMs) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

const PERSON_COLORS = ['#f97316', '#38bdf8', '#a78bfa', '#f43f5e', '#22d3ee', '#facc15', '#4ade80', '#fb7185'];

function colorForPersonId(id) {
  return PERSON_COLORS[Math.abs(id) % PERSON_COLORS.length];
}

function footPoint(bbox, projection) {
  const [x1, , x2, y2] = bbox;
  return projection.project((x1 + x2) / 2, y2);
}

// Cuántos milisegundos de recorrido reciente se dibujan detrás de cada
// persona. 2.5s da una estela visible sin saturar el mapa cuando hay
// varias personas cruzándose.
const TRAIL_WINDOW_MS = 2500;

// Recolecta, por persona, sus posiciones en los frames previos al actual
// dentro de TRAIL_WINDOW_MS, para dibujarlas como una estela que se
// desvanece — así el mapa se ve como un replay del recorrido real y no
// como puntos que saltan de una posición a otra.
function buildTrails(frames, currentIndex, projection) {
  const trails = new Map();
  if (currentIndex < 0 || !projection) return trails;

  const endTime = frames[currentIndex].timestamp_ms;
  const startTime = endTime - TRAIL_WINDOW_MS;

  for (let i = currentIndex; i >= 0; i--) {
    const frame = frames[i];
    if (frame.timestamp_ms < startTime) break;
    for (const track of frame.tracks || []) {
      const [px, py] = footPoint(track.bbox, projection);
      if (!trails.has(track.person_id)) trails.set(track.person_id, []);
      trails.get(track.person_id).push({ x: px, y: py });
    }
  }
  for (const points of trails.values()) points.reverse();
  return trails;
}

function pointInPolygon(x, y, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const intersects = (yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

// Para cada zona, qué porcentaje del tiempo transcurrido llevaba al menos
// una persona dentro de su polígono, acumulado desde el inicio del video.
// Se calcula una vez sobre todo tracking.jsonl (barato: pocos cientos de
// miles de operaciones) para que, al reproducir, el % — y con él la
// intensidad del color — vaya subiendo en vivo en vez de mostrar solo el
// dato final, dejando ver en qué góndola se fue concentrando la gente.
function buildOccupancyTimeline(zones, frames) {
  const timeline = new Map();
  if (!frames || frames.length === 0) return timeline;

  for (const zone of zones) {
    const polygon = zone.poligono;
    if (!polygon || polygon.length < 3) continue;
    const pct = new Float32Array(frames.length);
    let occupiedFrames = 0;
    for (let i = 0; i < frames.length; i++) {
      const tracks = frames[i].tracks || [];
      const present = tracks.some(track => {
        const [x1, , x2, y2] = track.bbox;
        return pointInPolygon((x1 + x2) / 2, y2, polygon);
      });
      if (present) occupiedFrames++;
      pct[i] = (occupiedFrames / (i + 1)) * 100;
    }
    timeline.set(zone.zone_id, pct);
  }
  return timeline;
}

function polygonToPath(polygon) {
  if (!polygon || polygon.length < 3) return '';
  const [first, ...rest] = polygon;
  return `M ${first[0]} ${first[1]} ${rest.map(([x, y]) => `L ${x} ${y}`).join(' ')} Z`;
}

export function StoreMapPanel({ zonasData, conteoZonas, tracking, currentTimeSec = 0 }) {
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

  const projection = useMemo(() => {
    if (!mergedZones.length) return null;
    return computeProjection(mergedZones, mapSize.width, mapSize.height);
  }, [mergedZones, mapSize]);

  const transformedZones = useMemo(() => {
    if (!mergedZones.length || !projection) return [];
    return transformToTopDown(mergedZones, projection);
  }, [mergedZones, projection]);

  const hasData = transformedZones.length > 0;

  const hasTracking = Array.isArray(tracking) && tracking.length > 0;

  const currentFrameIndex = useMemo(() => {
    if (!hasTracking) return -1;
    return findClosestFrameIndex(tracking, currentTimeSec * 1000);
  }, [hasTracking, tracking, currentTimeSec]);

  const currentFrame = currentFrameIndex >= 0 ? tracking[currentFrameIndex] : null;

  const livePeople = useMemo(() => {
    if (!currentFrame || !projection) return [];
    // Punto de apoyo (centro-inferior del bbox): aproxima dónde pisa la
    // persona, no el centro del cuerpo, para que el punto caiga sobre el
    // piso del mapa en vez de flotar a la altura del torso.
    return (currentFrame.tracks || []).map(track => {
      const [px, py] = footPoint(track.bbox, projection);
      return { id: track.person_id, x: px, y: py };
    });
  }, [currentFrame, projection]);

  const trails = useMemo(() => {
    if (!hasTracking || !projection) return new Map();
    return buildTrails(tracking, currentFrameIndex, projection);
  }, [hasTracking, tracking, currentFrameIndex, projection]);

  const occupancyTimeline = useMemo(() => {
    if (!hasTracking || !mergedZones.length) return new Map();
    return buildOccupancyTimeline(mergedZones, tracking);
  }, [hasTracking, mergedZones, tracking]);

  // % de ocupación a mostrar para una zona: en vivo (creciendo con la
  // reproducción) si hay tracking, o el dato final del análisis si no.
  const occupancyFor = (zoneId, fallbackPct) => {
    if (!hasTracking || currentFrameIndex < 0) return fallbackPct || 0;
    const pctArray = occupancyTimeline.get(zoneId);
    return pctArray ? pctArray[currentFrameIndex] : 0;
  };

  const topZone = useMemo(() => {
    if (!hasTracking || currentFrameIndex < 0 || !transformedZones.length) return null;
    let best = null;
    for (const zone of transformedZones) {
      const pct = occupancyFor(zone.zone_id, zone.occupancyPct);
      if (pct > 0 && (!best || pct > best.pct)) best = { zone_id: zone.zone_id, pct };
    }
    return best;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasTracking, currentFrameIndex, transformedZones, occupancyTimeline]);

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
        <div className="flex items-center gap-2">
          {hasTracking && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--ink-muted)] px-2 py-1 rounded bg-[var(--background)]">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              En vivo con el video
            </span>
          )}
          <div className="flex gap-1 text-xs text-[var(--ink-muted)] px-2 py-1 rounded bg-[var(--background)]">
            <span>{gondolaCount} góndolas</span>
            <span>{pasilloCount} pasillos</span>
            <span>{cajaCount} cajas</span>
          </div>
        </div>
      </div>

      {topZone && (
        <p className="px-4 pt-3 text-xs text-[var(--ink-muted)]">
            <strong className="text-[var(--ink)]">{topZone.zone_id}</strong> es la zona con más tráfico hasta ahora ({topZone.pct.toFixed(0)}% del tiempo ocupada).
        </p>
      )}

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
            const livePct = occupancyFor(zone.zone_id, zone.occupancyPct);
            // Más tiempo ocupada la zona → color más intenso. El piso de
            // 0.12 mantiene visible el contorno de zonas vacías; el tope de
            // 0.9 evita que tape la etiqueta al llegar al 100%.
            const fillOpacity = Math.min(0.9, 0.12 + (livePct / 100) * 0.78);
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
                  fill={zone.color.border}
                  fillOpacity={isHovered || isSelected ? Math.max(0.6, fillOpacity) : fillOpacity}
                  stroke={isSelected ? 'var(--accent)' : zone.color.border}
                  strokeWidth={isSelected ? 3 : isHovered ? 2.5 : 1.5}
                  strokeDasharray={zone.type === 'pasillo' ? '6,4' : 'none'}
                  style={{ transition: 'fill-opacity 0.3s, stroke-width 0.15s' }}
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

          {Array.from(trails.entries()).map(([personId, points]) => {
            if (points.length < 2) return null;
            const color = colorForPersonId(personId);
            return (
              <g key={`trail-${personId}`} pointerEvents="none">
                <polyline
                  points={points.map(p => `${p.x},${p.y}`).join(' ')}
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                  strokeOpacity={0.3}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {points.map((p, i) => (
                  <circle
                    key={i}
                    cx={p.x}
                    cy={p.y}
                    r={2}
                    fill={color}
                    opacity={0.15 + 0.45 * (i / points.length)}
                  />
                ))}
              </g>
            );
          })}

          {livePeople.map(person => (
            <g key={person.id} pointerEvents="none">
              <circle
                cx={person.x}
                cy={person.y}
                r={9}
                fill={colorForPersonId(person.id)}
                stroke="var(--panel)"
                strokeWidth={2}
              />
              <text
                x={person.x}
                y={person.y - 13}
                textAnchor="middle"
                fontSize={10}
                fontWeight={700}
                fill="var(--ink)"
                stroke="var(--panel)"
                strokeWidth={3}
                paintOrder="stroke"
              >
                {person.id}
              </text>
            </g>
          ))}

          {hoveredZone && (
            <g pointerEvents="none">
              {transformedZones
                .filter(z => z.zone_id === hoveredZone)
                .map(zone => {
                  const [cx, cy] = zone.centroid;
                  const color = zone.color;
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
                        {occupancyFor(zone.zone_id, zone.occupancyPct).toFixed(1)}% ocupación
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
                      Visitas: {zone.visits} • Ocupación: {occupancyFor(zone.zone_id, zone.occupancyPct).toFixed(1)}% • Área: {Math.round(zone.area)}px²
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
        {hasTracking && (
          <span>Personas ahora: <strong className="text-[var(--ink)]">{livePeople.length}</strong></span>
        )}
        <span className="flex-1"></span>
        <span>{hasTracking ? 'Reproduce el video para ver el recorrido' : 'Click para detalles • Hover para info'}</span>
      </div>
    </div>
  );
}