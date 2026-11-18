import { useMemo, useState, useRef, useEffect } from 'react';
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

// La proyeccion se calcula sobre el FRAME COMPLETO cuando el backend informa
// su tamano. Ajustandola solo al recuadro de las zonas, cualquier persona que
// camine fuera de una zona cae fuera del viewBox y desaparece del mapa, que es
// justo lo contrario de lo que el mapa debe mostrar.
function computeProjection(zones, mapWidth, mapHeight, frame = null, padding = 16) {
  const allPoints = zones.flatMap(z => z.poligono || []);
  if (allPoints.length === 0) return null;

  const usarFrame = Number(frame?.width) > 0 && Number(frame?.height) > 0;

  const minX = usarFrame ? 0 : Math.min(...allPoints.map(p => p[0]));
  const maxX = usarFrame ? Number(frame.width) : Math.max(...allPoints.map(p => p[0]));
  const minY = usarFrame ? 0 : Math.min(...allPoints.map(p => p[1]));
  const maxY = usarFrame ? Number(frame.height) : Math.max(...allPoints.map(p => p[1]));

  const sourceWidth = maxX - minX || 1;
  const sourceHeight = maxY - minY || 1;

  const scaleX = (mapWidth - 2 * padding) / sourceWidth;
  const scaleY = (mapHeight - 2 * padding) / sourceHeight;
  const scale = Math.max(1e-3, Math.min(scaleX, scaleY));

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

const PERSON_COLORS = ['#f97316', '#38bdf8', '#a78bfa', '#f43f5e', '#22d3ee', '#facc15', '#4ade80', '#fb7185'];

function colorForPersonId(id) {
  const num = Number(id);
  if (Number.isFinite(num)) {
    return PERSON_COLORS[Math.abs(Math.trunc(num)) % PERSON_COLORS.length];
  }
  const str = String(id ?? '');
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) >>> 0;
  }
  return PERSON_COLORS[hash % PERSON_COLORS.length];
}

function trackPersonId(track) {
  const id = track?.person_id ?? track?.track_id;
  return id === undefined || id === null ? null : id;
}

function footPoint(bbox, projection) {
  const [x1, , x2, y2] = bbox;
  return projection.project((x1 + x2) / 2, y2);
}

const TRAIL_WINDOW_MS = 2500;

function buildTrails(frames, currentIndex, projection) {
  const trails = new Map();
  if (currentIndex < 0 || !projection) return trails;

  const endTime = frames[currentIndex].timestamp_ms;
  const startTime = endTime - TRAIL_WINDOW_MS;

  for (let i = currentIndex; i >= 0; i--) {
    const frame = frames[i];
    if (frame.timestamp_ms < startTime) break;
    for (const track of frame.tracks || []) {
      const pid = trackPersonId(track);
      if (pid === null || !Array.isArray(track.bbox) || track.bbox.length !== 4) continue;
      const [px, py] = footPoint(track.bbox, projection);
      if (!trails.has(pid)) trails.set(pid, []);
      trails.get(pid).push({ x: px, y: py });
    }
  }
  for (const points of trails.values()) points.reverse();
  return trails;
}

function findClosestFrameIndex(frames, timeMs) {
  if (!frames || frames.length === 0) return -1;
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].timestamp_ms < timeMs) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0) {
    const prevDiff = Math.abs(frames[lo - 1].timestamp_ms - timeMs);
    const currDiff = Math.abs(frames[lo].timestamp_ms - timeMs);
    if (prevDiff < currDiff) return lo - 1;
  }
  return lo;
}

function polygonToPath(polygon) {
  if (!polygon || polygon.length < 3) return '';
  const [first, ...rest] = polygon;
  return `M ${first[0]} ${first[1]} ${rest.map(([x, y]) => `L ${x} ${y}`).join(' ')} Z`;
}

export function StoreMapPanel({ zonasData, conteoZonas, tracking, currentTimeSec = 0 }) {

  const svgWrapRef = useRef(null);
  const [mapSize, setMapSize] = useState({ width: 400, height: 250 });
  const tieneZonas = Boolean(zonasData?.zonas?.length);

  useEffect(() => {
    const el = svgWrapRef.current;
    if (!el) return undefined;
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        const w = Math.round(entry.contentRect.width) - 16;
        const h = Math.round(entry.contentRect.height) - 16;
        // Ignora mediciones en pestaña oculta (0x0) para no colapsar el SVG.
        if (w <= 64 || h <= 60) continue;
        setMapSize(prev => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
      }
    });
    resizeObserver.observe(el);
    return () => resizeObserver.disconnect();
  }, [tieneZonas]);

  const mergedZones = useMemo(() => {
    if (!zonasData?.zonas) return [];
    // El hook expone conteoZonas ya como arreglo; la respuesta cruda de la API
    // lo trae como { zonas: [...] }. Aceptar las dos formas evita que el mapa
    // se dibuje siempre con 0 visitas y opacidad minima.
    const lista = Array.isArray(conteoZonas) ? conteoZonas : (conteoZonas?.zonas || []);
    const conteoMap = new Map(lista.map(z => [z.zone_id, z]));
    return zonasData.zonas.map(zone => ({
      ...zone,
      ...conteoMap.get(zone.zone_id),
    }));
  }, [zonasData, conteoZonas]);

  const projection = useMemo(() => {
    if (!mergedZones.length) return null;
    return computeProjection(mergedZones, mapSize.width, mapSize.height, {
      width: zonasData?.frame_width,
      height: zonasData?.frame_height,
    });
  }, [mergedZones, mapSize, zonasData]);

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
    const out = [];
    for (const track of currentFrame.tracks || []) {
      const pid = trackPersonId(track);
      if (pid === null || !Array.isArray(track.bbox) || track.bbox.length !== 4) continue;
      const [px, py] = footPoint(track.bbox, projection);
      out.push({ id: pid, x: px, y: py });
    }
    return out;
  }, [currentFrame, projection]);

  const trails = useMemo(() => {
    if (!hasTracking || !projection) return new Map();
    return buildTrails(tracking, currentFrameIndex, projection);
  }, [hasTracking, tracking, currentFrameIndex, projection]);

  if (!hasData) {
    return (
      <div className="flex flex-col overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)]" style={{ height: '320px' }}>
        <div className="flex items-center justify-center h-full text-sm text-[var(--ink-muted)]">
          Sin datos de zonas disponibles
        </div>
      </div>
    );
  }

  const totalVisits = transformedZones.reduce((sum, z) => sum + (z.visits || 0), 0);

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-[var(--panel-border)] bg-[var(--panel)] relative" style={{ height: '320px' }}>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--panel-border)] px-3 py-1.5">
        <h3 className="text-sm font-medium">Mapa de tienda</h3>
        <div className="flex items-center gap-1.5 text-[12px] text-[var(--ink-muted)]">
          {hasTracking && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[var(--background)]">
              <span className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />
              En vivo{livePeople.length > 0 ? ` · ${livePeople.length} en cuadro` : ''}
            </span>
          )}
          <span>{transformedZones.length} zonas</span>
          <span>· {totalVisits} visitas</span>
        </div>
      </div>

      <div ref={svgWrapRef} className="relative flex-1 min-h-0 w-full overflow-hidden p-2" style={{ minHeight: '260px' }}>
        <svg
          viewBox={`0 0 ${mapSize.width} ${mapSize.height}`}
          preserveAspectRatio="xMidYMid meet"
          className="absolute inset-2 block"
          style={{ width: 'calc(100% - 16px)', height: 'calc(100% - 16px)' }}
        >
          <rect
            x="0" y="0"
            width={mapSize.width}
            height={mapSize.height}
            fill="var(--background)"
            rx="6"
          />

          {transformedZones.map(zone => {
            const path = polygonToPath(zone.polygon);
            const [cx, cy] = zone.centroid;
            const livePct = zone.occupancyPct;
            const fillOpacity = Math.min(0.9, 0.12 + (livePct / 100) * 0.78);
            return (
              <g key={zone.zone_id} style={{ cursor: 'pointer' }}>
                <path
                  d={path}
                  fill={zone.color.border}
                  fillOpacity={fillOpacity}
                  stroke={zone.color.border}
                  strokeWidth={1}
                  strokeDasharray={zone.type === 'pasillo' ? '4,3' : 'none'}
                />
                <text
                  x={cx}
                  y={cy + 3}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={Math.max(8, Math.min(11, Math.sqrt(zone.area) / 7))}
                  fill="var(--ink)"
                  fontWeight={500}
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
                  strokeWidth={1.5}
                  strokeOpacity={0.35}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {points.map((p, i) => (
                  <circle
                    key={i}
                    cx={p.x}
                    cy={p.y}
                    r={1.5}
                    fill={color}
                    opacity={0.15 + 0.5 * (i / points.length)}
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
                r={6}
                fill={colorForPersonId(person.id)}
                stroke="var(--panel)"
                strokeWidth={1.5}
              />
              <text
                x={person.x}
                y={person.y - 9}
                textAnchor="middle"
                fontSize={8}
                fontWeight={700}
                fill="var(--ink)"
                stroke="var(--panel)"
                strokeWidth={2}
                paintOrder="stroke"
              >
                {person.id}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}