export const TOUR_STEPS = [
  {
    target: '[data-tour="welcome"]',
    title: 'Bienvenido a GondHawk',
    content: 'GondHawk transforma el video de una superficie comercial en métricas útiles para entender el comportamiento alrededor de las góndolas.',
  },
  {
    target: '[data-tour="upload-video"]',
    title: 'Carga tu video',
    content: 'Selecciona el video que quieres analizar. A partir de este archivo GondHawk genera las métricas de la sesión.',
  },
  {
    target: '[data-tour="analysis-options"]',
    title: 'Configura el análisis',
    content: 'Puedes detectar las zonas automáticamente y elegir cuántos frames analizar. Usar todos los frames ofrece la mejor precisión.',
  },
  {
    target: '[data-tour="start-analysis"]',
    title: 'Inicia el análisis',
    content: 'Cuando tengas un video seleccionado, usa este botón para comenzar el procesamiento. El tour no ejecutará esta acción por ti.',
  },
  {
    target: '[data-tour="metrics"]',
    title: 'Métricas principales',
    content: 'Aquí verás personas detectadas, permanencia media, tasa de interacción y tasa de rechazo del análisis actual.',
  },
  {
    target: '[data-tour="heatmap"]',
    title: 'Mapa de calor',
    content: 'El mapa de calor permite identificar visualmente las zonas con mayor y menor flujo alrededor de la superficie comercial.',
  },
  {
    target: '[data-tour="interactions"]',
    title: 'Embudo de interacción',
    content: 'Este embudo resume el recorrido físico: personas que pasan, se detienen, toman un producto, lo devuelven o generan una posible conversión.',
  },
  {
    target: '[data-tour="performance"]',
    title: 'Rendimiento por góndola',
    content: 'Compara el flujo, dwell time, interacción, rechazo y estado de cada góndola para detectar oportunidades de mejora.',
  },
  {
    target: '[data-tour="recommendations"]',
    title: 'Recomendaciones',
    content: 'Aquí aparecen recomendaciones generadas a partir de las métricas del análisis para apoyar decisiones de distribución y space management.',
  },
  {
    target: '[data-tour="history"]',
    title: 'Historial',
    content: 'Consulta análisis guardados anteriormente y vuelve a abrirlos cuando necesites revisar sus resultados.',
  },
  {
    target: '[data-tour="reports"]',
    title: 'Descarga tus reportes',
    content: 'Después de cargar un análisis podrás descargar sus resultados en PDF, Excel o Word. Si todavía no hay un análisis disponible, este paso se omite.',
  },
  {
    target: '[data-tour="privacy"]',
    title: 'Privacidad por diseño',
    content: 'GondHawk trabaja con procesamiento local, métricas anónimas y sin reconocimiento facial, de acuerdo con las garantías mostradas en esta sección.',
  },
  {
    target: null,
    title: '¡Listo!',
    content: 'Ya conoces las principales funciones de GondHawk. Ahora puedes explorar los resultados y analizar el comportamiento alrededor de las góndolas.',
  },
];
